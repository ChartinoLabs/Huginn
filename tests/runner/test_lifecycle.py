"""Tests for basic runner lifecycle: pass, fail, error, and cleanup."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from huginn.cli import app

from .conftest import (
    _FakeRuntimeBroker,
    first_test_case,
    load_report,
    stage_runner_fixture,
)


def test_run_executes_single_test_case_and_writes_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI run executes one test and writes a JSON report."""
    stage_runner_fixture(tmp_path, "passed")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "--mode",
            "testing",
            "--testbed",
            str(tmp_path / "testbed.yaml"),
            "--plan",
            str(tmp_path / "test_plan.yaml"),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    report_data = load_report(tmp_path)
    assert report_data["summary"]["status"] == "passed"
    assert report_data["summary"]["passed"] == 1


def test_run_returns_non_zero_for_failed_test_case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI run returns exit code 1 when a test fails."""
    stage_runner_fixture(tmp_path, "failed")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "--mode",
            "testing",
            "--testbed",
            str(tmp_path / "testbed.yaml"),
            "--plan",
            str(tmp_path / "test_plan.yaml"),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 1
    report_data = load_report(tmp_path)
    assert report_data["summary"]["status"] == "failed"
    assert report_data["summary"]["failed"] == 1


def test_cleanup_runs_when_test_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cleanup is executed even when test raises an exception."""
    stage_runner_fixture(tmp_path, "errored")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "--mode",
            "testing",
            "--testbed",
            str(tmp_path / "testbed.yaml"),
            "--plan",
            str(tmp_path / "test_plan.yaml"),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 1
    assert (tmp_path / "cleanup.marker").exists()
    assert _FakeRuntimeBroker.disconnect_invocations == 1
    report_data = load_report(tmp_path)
    assert report_data["summary"]["status"] == "errored"
    assert report_data["summary"]["errored"] == 1
    errored_case = first_test_case(report_data)
    assert errored_case["error_traceback"] is not None
    assert "Traceback (most recent call last)" in errored_case["error_traceback"]

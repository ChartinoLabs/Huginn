"""Integration tests for the first end-to-end runner slice."""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from huginn.cli import app


def test_run_executes_single_test_case_and_writes_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI run executes one test and writes a JSON report."""
    _stage_runner_fixture(tmp_path, "passed")
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
    report_data = _load_report(tmp_path)
    assert report_data["summary"]["status"] == "passed"
    assert report_data["summary"]["passed"] == 1


def test_run_returns_non_zero_for_failed_test_case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI run returns exit code 1 when a test fails."""
    _stage_runner_fixture(tmp_path, "failed")
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
    report_data = _load_report(tmp_path)
    assert report_data["summary"]["status"] == "failed"
    assert report_data["summary"]["failed"] == 1


def test_cleanup_runs_when_test_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cleanup is executed even when test raises an exception."""
    _stage_runner_fixture(tmp_path, "errored")
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
    report_data = _load_report(tmp_path)
    assert report_data["summary"]["status"] == "errored"
    assert report_data["summary"]["errored"] == 1


def _stage_runner_fixture(tmp_path: Path, fixture_name: str) -> None:
    """Copy a fixture scenario into the temp execution directory."""
    fixture_root = Path(__file__).resolve().parent / "fixtures" / "first_slice_runner"
    source = fixture_root / fixture_name
    for source_path in source.rglob("*"):
        if source_path.is_dir():
            continue
        destination = tmp_path / source_path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)


def _load_report(tmp_path: Path) -> dict[str, Any]:
    """Load the generated run report from the default reports directory."""
    report_path = tmp_path / "reports" / "run.json"
    return json.loads(report_path.read_text(encoding="utf-8"))

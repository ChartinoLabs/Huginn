"""Tests for device target resolution, selectors, and hierarchical intersection."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from huginn.cli import app

from .conftest import first_test_case, load_report, stage_runner_fixture


def test_run_honors_test_case_device_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runner resolves test-case targets and executes only matching devices."""
    stage_runner_fixture(tmp_path, "targeted")
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
    checks = first_test_case(report_data)["checks"]
    assert len(checks) == 1
    assert checks[0]["message"] == "ok:leaf-01"


def test_run_errors_when_test_target_device_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown test-case target devices are reported as execution errors."""
    stage_runner_fixture(tmp_path, "unknown_target")
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
    test_case = first_test_case(report_data)
    assert test_case["status"] == "errored"
    assert test_case["error_code"] == "validation_error"
    assert "Unknown target device 'leaf-42'" in test_case["error"]


def test_run_applies_group_and_os_target_selectors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Group and OS selectors filter target set with AND semantics."""
    stage_runner_fixture(tmp_path, "target_selectors")
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
    checks = first_test_case(report_data)["checks"]
    assert len(checks) == 1
    assert checks[0]["message"] == "selected:leaf-02"


def test_run_skips_test_case_when_no_targets_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No matched targets marks test as skipped instead of errored."""
    stage_runner_fixture(tmp_path, "target_no_match")
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
    assert not (tmp_path / "unexpected.execution").exists()
    report_data = load_report(tmp_path)
    test_case = first_test_case(report_data)
    assert test_case["status"] == "skipped"
    assert test_case["error_code"] is None
    assert "No devices matched target selectors" in test_case["error"]


def test_run_applies_phase_group_test_target_intersection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase/group/test-case targets are intersected deterministically."""
    stage_runner_fixture(tmp_path, "hierarchical_targets")
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
    checks = first_test_case(report_data)["checks"]
    assert len(checks) == 1
    assert checks[0]["message"] == "selected:leaf-02"


def test_run_skips_when_hierarchical_target_intersection_is_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty target set after phase/group/test intersections is skipped."""
    stage_runner_fixture(tmp_path, "hierarchical_no_match")
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
    assert not (tmp_path / "hierarchy.unexpected").exists()
    report_data = load_report(tmp_path)
    test_case = first_test_case(report_data)
    assert test_case["status"] == "skipped"

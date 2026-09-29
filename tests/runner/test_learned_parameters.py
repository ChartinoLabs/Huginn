"""Tests for testing mode loading the parameters that learning mode saved."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from huginn.cli import app

from .conftest import first_test_case, load_report, stage_runner_fixture


def test_run_testing_mode_loads_learned_parameters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Testing mode loads previously learned parameters and validates state."""
    stage_runner_fixture(tmp_path, "learning_testing_parameters")
    monkeypatch.chdir(tmp_path)

    parameters_dir = tmp_path / "parameters"
    parameters_dir.mkdir(parents=True, exist_ok=True)
    (parameters_dir / "1.0.0.json").write_text(
        json.dumps({"target_count": 1, "target_names": ["leaf-01"]}),
        encoding="utf-8",
    )

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
    assert checks[0]["message"] == "parameters matched"


def test_run_testing_mode_errors_when_parameters_are_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Testing mode surfaces missing learned parameter files as execution errors."""
    stage_runner_fixture(tmp_path, "learning_testing_parameters")
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
    assert "No learned parameters found" in test_case["error"]

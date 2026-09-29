"""Tests for the scenario, phase and group context given to running jobs."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from huginn.cli import app

from .conftest import first_test_case, load_report, stage_runner_fixture


def test_run_populates_scenario_phase_group_on_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Context.scenario, .phase, and .test_case_group are exposed to test jobs."""
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
    test_case = first_test_case(report_data)
    messages = [check["message"] for check in test_case["checks"]]
    joined = " ".join(messages)
    assert "scenario=scenario-1" in joined
    assert "phase=phase-1" in joined
    assert "group=group-1" in joined
    assert "test_id=1.0.0" in joined

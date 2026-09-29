"""Tests for the console output of `huginn run`."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from huginn.cli import app

from .conftest import stage_runner_fixture


def test_run_output_announces_scenario_and_phase_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI output announces scenario and qualified phase start messages."""
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
    assert "Executing scenarios and phases" in result.stdout
    assert "Execution order:" in result.stdout
    assert "Scenario: scenario-1" in result.stdout
    assert "Phase: phase-1" in result.stdout
    assert "Starting scenario: scenario-1" in result.stdout
    assert "  Starting phase: phase-1" in result.stdout

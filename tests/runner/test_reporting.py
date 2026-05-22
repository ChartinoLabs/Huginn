"""Tests for reporting: command recording, CLI output, context, and phase dependencies."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from huginn.cli import app
from huginn.enums import BrokerType

from .conftest import (
    _FakeRuntimeBroker,
    first_test_case,
    load_report,
    stage_runner_fixture,
)


def test_run_records_command_executions_in_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Command execution details are persisted with each executed test case."""
    stage_runner_fixture(tmp_path, "command_recording")
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
    command_execution = test_case["command_executions"][0]
    assert command_execution["device"] == "leaf-01"
    assert command_execution["command"] == "show version"
    assert command_execution["output"] == "ok:leaf-01"
    assert command_execution["parsed"] == {"vendor": "cisco"}


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


def test_phase_with_failed_dependency_is_marked_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Downstream phases are blocked when dependency phase fails."""
    stage_runner_fixture(tmp_path, "phase_dependency_blocked")
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
    assert not (tmp_path / "phase2.executed").exists()

    report_data = load_report(tmp_path)
    assert report_data["summary"]["failed"] == 1
    assert report_data["summary"]["blocked"] == 1

    phase_1 = report_data["scenarios"][0]["phases"][0]
    phase_2 = report_data["scenarios"][0]["phases"][1]
    assert phase_1["status"] == "failed"
    assert phase_2["status"] == "blocked"

    blocked_case = phase_2["test_case_groups"][0]["test_cases"][0]
    assert blocked_case["status"] == "blocked"


def test_runner_plans_brokers_from_job_declarations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runner uses job-declared broker requirements from validation planning."""
    stage_runner_fixture(tmp_path, "job_declared_netconf")
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
    assert _FakeRuntimeBroker.last_required_brokers == {BrokerType.NETCONF}
    report_data = load_report(tmp_path)
    checks = first_test_case(report_data)["checks"]
    assert checks[0]["message"] == "get:leaf-01:/interfaces"


def test_runner_disconnects_once_per_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runner tears down runtime broker once after all test cases."""
    stage_runner_fixture(tmp_path, "connection_reuse")
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
    assert _FakeRuntimeBroker.connect_invocations == 1
    assert _FakeRuntimeBroker.disconnect_invocations == 1

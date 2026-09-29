"""Tests for the run report: recorded commands and plan descriptions in run.json."""

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from huginn.cli import app

from .conftest import (
    first_test_case,
    load_report,
    phases_by_name as _phases_by_name,
    run_outcome_plan as _run,
    stage_outcome_plan as _stage_plan,
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


def test_run_json_carries_descriptions_for_run_and_blocked_phases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plan descriptions reach run.json for executed and blocked phases."""
    _stage_plan(
        tmp_path,
        {
            "first": {"test": "failed-1"},
            "dependent": {"test": "passed-2", "depends_on": ["first"]},
        },
    )
    plan_path = tmp_path / "test_plan.yaml"
    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    scenario = plan["scenarios"]["scenario-1"]
    scenario["description"] = "Scenario text"
    for name in ("first", "dependent"):
        scenario["phases"][name]["description"] = f"{name} phase"
        plan["test_case_groups"][f"{name}-group"]["description"] = f"{name} group"
    plan_path.write_text(yaml.safe_dump(plan), encoding="utf-8")

    assert _run(tmp_path, monkeypatch) == 1

    assert load_report(tmp_path)["scenarios"][0]["description"] == "Scenario text"
    phases = _phases_by_name(tmp_path)
    assert phases["dependent"]["status"] == "blocked"
    for name in ("first", "dependent"):
        assert phases[name]["description"] == f"{name} phase"
        assert phases[name]["test_case_groups"][0]["description"] == f"{name} group"

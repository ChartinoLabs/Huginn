"""Tests for `huginn relearn` execution scoping."""

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from huginn.cli import app

from .conftest import load_report, stage_runner_fixture

_TESTING_RUN_DIR = "2020-Jan-01-00-00-00-testing"


def _write_testing_run(tmp_path: Path, failures: set[tuple[str, str, str]]) -> None:
    """Write a testing run.json where only ``failures`` contexts failed."""
    scenarios: list[dict[str, Any]] = []
    for scenario_id in ("S1", "S2"):
        phases: list[dict[str, Any]] = []
        for phase_id in ("P1", "P2"):
            test_cases = [
                {
                    "test_id": test_id,
                    "title": test_id,
                    "status": (
                        "failed"
                        if (scenario_id, phase_id, test_id) in failures
                        else "passed"
                    ),
                    "result_path": f"test-cases/{test_id}/result.json",
                }
                for test_id in ("TA", "TB")
            ]
            phases.append(
                {
                    "id": phase_id,
                    "status": "failed",
                    "test_case_groups": [
                        {"id": "checks", "status": "failed", "test_cases": test_cases}
                    ],
                }
            )
        scenarios.append({"id": scenario_id, "status": "failed", "phases": phases})

    run_json = tmp_path / "results" / _TESTING_RUN_DIR / "run.json"
    run_json.parent.mkdir(parents=True)
    run_json.write_text(
        json.dumps({"mode": "testing", "scenarios": scenarios}), encoding="utf-8"
    )


def _invoke_relearn(tmp_path: Path, *extra_args: str) -> Result:
    """Run `huginn relearn` against the staged fixture."""
    return CliRunner().invoke(
        app,
        [
            "relearn",
            "--testbed",
            str(tmp_path / "testbed.yaml"),
            "--plan",
            str(tmp_path / "test_plan.yaml"),
            *extra_args,
        ],
        catch_exceptions=False,
    )


def _executed_contexts(tmp_path: Path) -> set[tuple[str, str, str]]:
    """Return (scenario, phase, test_id) tuples from the relearn run report."""
    report = load_report(tmp_path)
    assert report["mode"] == "learning"
    return {
        (scenario["id"], phase["id"], test_case["test_id"])
        for scenario in report["scenarios"]
        for phase in scenario["phases"]
        for group in phase["test_case_groups"]
        for test_case in group["test_cases"]
    }


@pytest.fixture
def staged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Stage the relearn fixture and chdir into it."""
    stage_runner_fixture(tmp_path, "relearn_exact_scope")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_relearn_runs_only_exact_failed_contexts(staged: Path) -> None:
    """Relearn does not expand failures into the scenario x phase cross-product."""
    _write_testing_run(staged, {("S1", "P1", "TA"), ("S2", "P2", "TB")})

    result = _invoke_relearn(staged)

    assert result.exit_code == 0, result.stdout
    assert "Re-learning 2 failed test context(s)" in result.stdout
    assert "S1/P1/TA" in result.stdout
    assert "S2/P2/TB" in result.stdout
    assert _executed_contexts(staged) == {("S1", "P1", "TA"), ("S2", "P2", "TB")}
    assert load_report(staged)["summary"]["total"] == 2


def test_relearn_runs_test_id_in_every_failed_context(staged: Path) -> None:
    """A test ID that failed in two contexts is re-learned in both."""
    _write_testing_run(staged, {("S1", "P1", "TA"), ("S2", "P2", "TA")})

    result = _invoke_relearn(staged)

    assert result.exit_code == 0, result.stdout
    assert "Re-learning 2 failed test context(s)" in result.stdout
    assert _executed_contexts(staged) == {("S1", "P1", "TA"), ("S2", "P2", "TA")}


def test_relearn_composes_exact_contexts_with_user_filters(staged: Path) -> None:
    """User --scenario/--phase options narrow the exact failed contexts."""
    _write_testing_run(
        staged,
        {("S1", "P1", "TA"), ("S1", "P2", "TB"), ("S2", "P2", "TB")},
    )

    result = _invoke_relearn(staged, "--scenario", "S1", "--phase", "P2")

    assert result.exit_code == 0, result.stdout
    assert "Re-learning 1 failed test context(s)" in result.stdout
    assert _executed_contexts(staged) == {("S1", "P2", "TB")}

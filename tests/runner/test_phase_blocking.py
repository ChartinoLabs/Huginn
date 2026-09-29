"""Tests for phase blocking and the run exit code."""

from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from huginn.cli import _summary_has_failures, app
from huginn.models import RunSummary

from .conftest import load_report, stage_runner_fixture

JOB = "jobs/test_verify_outcome.py"


def _stage_plan(tmp_path: Path, phases: dict[str, dict[str, Any]]) -> None:
    """Stage the fixture with one single-test group per phase.

    ``phases`` maps each phase name to its test ID and optional
    ``depends_on``. The test ID prefix sets the test's outcome.
    """
    stage_runner_fixture(tmp_path, "phase_blocking")
    plan = {
        "test_cases": {
            spec["test"]: {"title": spec["test"], "job": JOB}
            for spec in phases.values()
        },
        "test_case_groups": {
            f"{name}-group": {"tests": [spec["test"]]} for name, spec in phases.items()
        },
        "scenarios": {
            "scenario-1": {
                "phases": {
                    name: {
                        "test_case_groups": [f"{name}-group"],
                        "depends_on": spec.get("depends_on", []),
                    }
                    for name, spec in phases.items()
                }
            }
        },
    }
    (tmp_path / "test_plan.yaml").write_text(yaml.safe_dump(plan), encoding="utf-8")


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> int:
    """Run the staged plan in testing mode and return the exit code."""
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
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
    return result.exit_code


def _phases_by_name(tmp_path: Path) -> dict[str, dict[str, Any]]:
    """Return the report's phases for the only scenario, keyed by phase ID."""
    report = load_report(tmp_path)
    return {phase["id"]: phase for phase in report["scenarios"][0]["phases"]}


def _only_case(phase: dict[str, Any]) -> dict[str, Any]:
    """Return the single test case in a single-group phase."""
    return phase["test_case_groups"][0]["test_cases"][0]


@pytest.mark.parametrize(
    ("failing_status", "outcome"),
    [
        ("failed", "failed"),
        ("errored", "errored"),
        ("lost_applicability", "lost applicability"),
    ],
)
def test_failed_phase_does_not_block_independent_phase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failing_status: str,
    outcome: str,
) -> None:
    """A phase that does not depend on a failed phase still runs."""
    _stage_plan(
        tmp_path,
        {
            "first": {"test": f"{failing_status}-1"},
            "independent": {"test": "passed-2"},
            "dependent": {"test": "passed-3", "depends_on": ["first"]},
        },
    )

    assert _run(tmp_path, monkeypatch) == 1

    phases = _phases_by_name(tmp_path)
    assert phases["first"]["status"] == failing_status
    assert phases["independent"]["status"] == "passed"
    assert phases["dependent"]["status"] == "blocked"
    assert (tmp_path / "executed" / "passed-2").exists()
    assert not (tmp_path / "executed" / "passed-3").exists()
    assert _only_case(phases["dependent"])["error"] == (
        f"Blocked because phase 'first' {outcome}"
    )


def test_blocking_is_transitive_and_names_the_failed_phase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A blocked phase blocks its own dependents, citing the original failure."""
    _stage_plan(
        tmp_path,
        {
            "a": {"test": "failed-1"},
            "b": {"test": "passed-2", "depends_on": ["a"]},
            "c": {"test": "passed-3", "depends_on": ["b"]},
            "d": {"test": "passed-4"},
            "e": {"test": "passed-5", "depends_on": ["d"]},
        },
    )

    assert _run(tmp_path, monkeypatch) == 1

    phases = _phases_by_name(tmp_path)
    assert [phases[name]["status"] for name in "abcde"] == [
        "failed",
        "blocked",
        "blocked",
        "passed",
        "passed",
    ]
    for name in ("b", "c"):
        assert _only_case(phases[name])["error"] == "Blocked because phase 'a' failed"
    assert not (tmp_path / "executed" / "passed-2").exists()
    assert not (tmp_path / "executed" / "passed-3").exists()


@pytest.mark.parametrize("status", ["not_applicable", "skipped"])
def test_not_applicable_or_skipped_phase_does_not_block(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    """Dependents of a NOT_APPLICABLE or SKIPPED phase still run."""
    _stage_plan(
        tmp_path,
        {
            "first": {"test": f"{status}-1"},
            "second": {"test": "passed-2", "depends_on": ["first"]},
        },
    )

    assert _run(tmp_path, monkeypatch) == 0

    phases = _phases_by_name(tmp_path)
    assert phases["first"]["status"] == status
    assert phases["second"]["status"] == "passed"


@pytest.mark.parametrize(
    ("tests", "expected_exit_code"),
    [
        (["passed-1"], 0),
        (["not_applicable-1"], 0),
        (["skipped-1"], 0),
        (["not_applicable-1", "skipped-2"], 0),
        (["passed-1", "not_applicable-2", "skipped-3"], 0),
        (["passed-1", "failed-2"], 1),
        (["passed-1", "errored-2"], 1),
        (["not_applicable-1", "failed-2"], 1),
        (["passed-1", "lost_applicability-2"], 1),
        (["not_applicable-1", "lost_applicability-2"], 1),
    ],
    ids=[
        "passed",
        "not-applicable",
        "skipped",
        "not-applicable-and-skipped",
        "passed-mixed",
        "failed",
        "errored",
        "not-applicable-and-failed",
        "lost-applicability",
        "not-applicable-and-lost-applicability",
    ],
)
def test_run_exit_code_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tests: list[str],
    expected_exit_code: int,
) -> None:
    """Only failed, errored, lost or blocked test cases make the run exit 1."""
    _stage_plan(
        tmp_path,
        {f"phase-{index}": {"test": test} for index, test in enumerate(tests)},
    )

    assert _run(tmp_path, monkeypatch) == expected_exit_code


@pytest.mark.parametrize(
    ("counts", "expected"),
    [
        ({"passed": 1}, False),
        ({"not_applicable": 1, "skipped": 1}, False),
        ({"failed": 1}, True),
        ({"errored": 1}, True),
        ({"blocked": 1}, True),
        ({"lost_applicability": 1}, True),
    ],
    ids=[
        "passed",
        "not-applicable-and-skipped",
        "failed",
        "errored",
        "blocked",
        "lost-applicability",
    ],
)
def test_summary_has_failures_counts_blocked(
    counts: dict[str, int],
    expected: bool,
) -> None:
    """Failed, errored, lost and blocked counts each fail a run on their own."""
    fields = dict.fromkeys(
        (
            "passed",
            "failed",
            "errored",
            "not_applicable",
            "lost_applicability",
            "skipped",
            "blocked",
        ),
        0,
    )
    fields.update(counts)
    summary = RunSummary(status="passed", total=sum(counts.values()), **fields)

    assert _summary_has_failures(summary) is expected


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

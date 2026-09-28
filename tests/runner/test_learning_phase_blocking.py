"""Tests for phases that block their dependents because of learning mode."""

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner, Result

from huginn.cli import _summary_has_failures, app
from huginn.models import RunSummary

from .conftest import load_report, stage_runner_fixture

LEARN = "jobs/test_learn_state.py"
CHANGE = "jobs/test_apply_change.py"
NOT_LEARNED = "Blocked because phase '{}' was not run in learning mode"


def _stage_plan(tmp_path: Path, phases: dict[str, dict[str, Any]]) -> None:
    """Stage the fixture with one group per phase.

    ``phases`` maps each phase name to its ``tests`` (test ID to job path),
    optional ``depends_on`` and optional group ``target``.
    """
    stage_runner_fixture(tmp_path, "learning_phase_blocking")
    groups: dict[str, Any] = {}
    for name, spec in phases.items():
        group: dict[str, Any] = {"tests": list(spec["tests"])}
        if "target" in spec:
            group["target"] = spec["target"]
        groups[f"{name}-group"] = group
    plan = {
        "test_cases": {
            test_id: {"title": test_id, "job": job}
            for spec in phases.values()
            for test_id, job in spec["tests"].items()
        },
        "test_case_groups": groups,
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


def _change_plan() -> dict[str, dict[str, Any]]:
    """Return a pre-change, change and post-change phase chain."""
    return {
        "pre": {"tests": {"pre-1": LEARN}},
        "shut": {"tests": {"shut-1": CHANGE}, "depends_on": ["pre"]},
        "post": {"tests": {"post-1": LEARN}, "depends_on": ["shut"]},
    }


def _invoke(tmp_path: Path, *args: str) -> Result:
    """Invoke the CLI against the staged plan and testbed."""
    return CliRunner().invoke(
        app,
        [
            *args,
            "--testbed",
            str(tmp_path / "testbed.yaml"),
            "--plan",
            str(tmp_path / "test_plan.yaml"),
        ],
        catch_exceptions=False,
    )


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str) -> Result:
    """Run the staged plan in the given mode."""
    monkeypatch.chdir(tmp_path)
    return _invoke(tmp_path, "run", "--mode", mode)


def _phases_by_name(tmp_path: Path) -> dict[str, dict[str, Any]]:
    """Return the report's phases for the only scenario, keyed by phase ID."""
    report = load_report(tmp_path)
    return {phase["id"]: phase for phase in report["scenarios"][0]["phases"]}


def _cases(phase: dict[str, Any]) -> list[dict[str, Any]]:
    """Return every test case in a phase."""
    return [case for group in phase["test_case_groups"] for case in group["test_cases"]]


def test_learning_mode_blocks_phases_after_a_skipped_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A phase after a change that learning mode skipped is blocked, not learned."""
    _stage_plan(tmp_path, _change_plan())

    result = _run(tmp_path, monkeypatch, "learning")

    assert result.exit_code == 0, result.stdout
    phases = _phases_by_name(tmp_path)
    assert [phases[name]["status"] for name in ("pre", "shut", "post")] == [
        "passed",
        "skipped",
        "blocked",
    ]
    shut_case = _cases(phases["shut"])[0]
    assert shut_case["skip_kind"] == "learning_mode_unsupported"
    post_case = _cases(phases["post"])[0]
    assert post_case["error"] == NOT_LEARNED.format("shut")
    assert post_case["block_kind"] == "dependency_not_learned"
    assert (tmp_path / "parameters" / "pre-1.json").exists()
    assert not (tmp_path / "parameters" / "post-1.json").exists()
    assert not (tmp_path / "executed" / "post-1").exists()
    summary = load_report(tmp_path)["summary"]
    assert summary["blocked"] == 1
    assert summary["learning_mode_blocked"] == 1
    assert "blocked because a phase" in (result.stdout)


def test_testing_mode_runs_the_change_and_its_dependents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In testing mode the change phase runs, and so does the phase after it."""
    _stage_plan(tmp_path, _change_plan())
    parameters = tmp_path / "parameters"
    parameters.mkdir()
    for test_id in ("pre-1", "post-1"):
        (parameters / f"{test_id}.json").write_text(
            json.dumps({"state": "ok"}), encoding="utf-8"
        )

    result = _run(tmp_path, monkeypatch, "testing")

    assert result.exit_code == 0, result.stdout
    phases = _phases_by_name(tmp_path)
    assert [phases[name]["status"] for name in ("pre", "shut", "post")] == [
        "passed",
        "passed",
        "passed",
    ]
    for test_id in ("pre-1", "shut-1", "post-1"):
        assert (tmp_path / "executed" / test_id).exists()


def test_learning_mode_block_is_transitive_and_spares_independent_phases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Blocking passes down the chain, and a phase off the chain still learns."""
    plan = _change_plan()
    plan["after-post"] = {"tests": {"after-1": LEARN}, "depends_on": ["post"]}
    plan["other"] = {"tests": {"other-1": LEARN}, "depends_on": ["pre"]}
    _stage_plan(tmp_path, plan)

    assert _run(tmp_path, monkeypatch, "learning").exit_code == 0

    phases = _phases_by_name(tmp_path)
    assert phases["after-post"]["status"] == "blocked"
    assert _cases(phases["after-post"])[0]["error"] == NOT_LEARNED.format("shut")
    assert phases["other"]["status"] == "passed"
    assert (tmp_path / "parameters" / "other-1.json").exists()


def test_learning_mode_blocks_when_any_test_in_the_phase_was_not_learned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A phase mixing learned and learning-skipped tests still blocks."""
    _stage_plan(
        tmp_path,
        {
            "shut": {"tests": {"verify-1": LEARN, "shut-1": CHANGE}},
            "post": {"tests": {"post-1": LEARN}, "depends_on": ["shut"]},
        },
    )

    assert _run(tmp_path, monkeypatch, "learning").exit_code == 0

    phases = _phases_by_name(tmp_path)
    assert phases["shut"]["status"] == "passed"
    assert phases["post"]["status"] == "blocked"
    assert _cases(phases["post"])[0]["error"] == NOT_LEARNED.format("shut")


def test_learning_mode_skip_for_unmatched_targets_does_not_block(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A learning test skipped because no device matched does not block."""
    _stage_plan(
        tmp_path,
        {
            "pre": {"tests": {"pre-1": LEARN}, "target": {"os": ["iosxe"]}},
            "post": {"tests": {"post-1": LEARN}, "depends_on": ["pre"]},
        },
    )

    assert _run(tmp_path, monkeypatch, "learning").exit_code == 0

    phases = _phases_by_name(tmp_path)
    assert phases["pre"]["status"] == "skipped"
    assert _cases(phases["pre"])[0]["skip_kind"] == "no_matching_targets"
    assert phases["post"]["status"] == "passed"


def test_learning_mode_failure_takes_precedence_over_a_learning_block(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A phase blocked by both a failure and a skipped change fails the run."""
    _stage_plan(
        tmp_path,
        {
            "shut": {"tests": {"shut-1": CHANGE}},
            "broken": {"tests": {"errored-1": LEARN}},
            "post": {"tests": {"post-1": LEARN}, "depends_on": ["shut", "broken"]},
        },
    )

    assert _run(tmp_path, monkeypatch, "learning").exit_code == 1

    post_case = _cases(_phases_by_name(tmp_path)["post"])[0]
    assert post_case["error"] == "Blocked because phase 'broken' errored"
    assert post_case["block_kind"] == "dependency_failed"


def _write_testing_run(tmp_path: Path, failures: dict[str, str]) -> None:
    """Write a testing run.json of the change plan where ``failures`` failed.

    ``failures`` maps phase ID to the test ID that failed in it.
    """
    phases = [
        {
            "id": phase_id,
            "status": "failed" if phase_id in failures else "passed",
            "test_case_groups": [
                {
                    "id": f"{phase_id}-group",
                    "status": "failed" if phase_id in failures else "passed",
                    "test_cases": [
                        {
                            "test_id": test_id,
                            "title": test_id,
                            "status": (
                                "failed" if failures.get(phase_id) else "passed"
                            ),
                        }
                    ],
                }
            ],
        }
        for phase_id, test_id in (
            ("pre", "pre-1"),
            ("shut", "shut-1"),
            ("post", "post-1"),
        )
    ]
    run_json = tmp_path / "results" / "2020-Jan-01-00-00-00-testing" / "run.json"
    run_json.parent.mkdir(parents=True)
    run_json.write_text(
        json.dumps(
            {
                "mode": "testing",
                "scenarios": [
                    {"id": "scenario-1", "status": "failed", "phases": phases}
                ],
            }
        ),
        encoding="utf-8",
    )


def test_relearn_of_a_post_change_failure_runs_without_the_change_phase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Relearn drops the unfailed change phase, so the post-change test learns."""
    _stage_plan(tmp_path, _change_plan())
    monkeypatch.chdir(tmp_path)
    _write_testing_run(tmp_path, {"post": "post-1"})

    result = _invoke(tmp_path, "relearn")

    assert result.exit_code == 0, result.stdout
    assert (tmp_path / "parameters" / "post-1.json").exists()
    assert not (tmp_path / "executed" / "shut-1").exists()


def test_relearn_blocks_a_post_change_failure_behind_a_relearned_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the change phase is re-learned too, its dependents are blocked."""
    _stage_plan(tmp_path, _change_plan())
    monkeypatch.chdir(tmp_path)
    _write_testing_run(tmp_path, {"shut": "shut-1", "post": "post-1"})

    result = _invoke(tmp_path, "relearn")

    assert result.exit_code == 0, result.stdout
    post_case = _cases(_phases_by_name(tmp_path)["post"])[0]
    assert post_case["status"] == "blocked"
    assert post_case["error"] == NOT_LEARNED.format("shut")
    assert not (tmp_path / "parameters" / "post-1.json").exists()
    assert "blocked because a phase" in (result.stdout)


@pytest.mark.parametrize(
    ("blocked", "learning_mode_blocked", "expected"),
    [(2, 2, False), (2, 1, True), (1, 0, True)],
    ids=["learning-only", "mixed", "failure-only"],
)
def test_summary_has_failures_ignores_learning_mode_blocks(
    blocked: int,
    learning_mode_blocked: int,
    expected: bool,
) -> None:
    """Only blocked test cases not caused by learning mode fail the run."""
    summary = RunSummary(
        status="passed",
        total=blocked,
        passed=0,
        failed=0,
        errored=0,
        not_applicable=0,
        skipped=0,
        blocked=blocked,
        learning_mode_blocked=learning_mode_blocked,
    )

    assert _summary_has_failures(summary) is expected

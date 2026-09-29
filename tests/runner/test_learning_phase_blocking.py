"""Tests for phases that block their dependents because of learning mode."""

import json
from pathlib import Path

import pytest
from typer.testing import Result

from .conftest import (
    CHANGE_JOB as CHANGE,
    LEARN_STATE_JOB as LEARN,
    NOT_LEARNED,
    change_plan as _change_plan,
    invoke_cli as _invoke,
    load_report,
    phase_cases as _cases,
    phases_by_name as _phases_by_name,
    stage_learning_plan as _stage_plan,
)


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str) -> Result:
    """Run the staged plan in the given mode."""
    monkeypatch.chdir(tmp_path)
    return _invoke(tmp_path, "run", "--mode", mode)


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

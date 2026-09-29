"""Tests for phases blocked because a phase they depend on failed."""

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from huginn.cli import app

from .conftest import (
    load_report,
    phases_by_name as _phases_by_name,
    run_outcome_plan as _run,
    stage_outcome_plan as _stage_plan,
    stage_runner_fixture,
)


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
    assert blocked_case["error"] == "Blocked because phase 'phase-1' failed"

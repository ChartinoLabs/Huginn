"""Tests for the run exit code and the summary check that decides it."""

from pathlib import Path

import pytest

from huginn.cli import _summary_has_failures
from huginn.models import RunSummary

from .conftest import run_outcome_plan as _run, stage_outcome_plan as _stage_plan


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

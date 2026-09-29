"""Tests for `huginn relearn` when a re-learned change phase blocks its dependents."""

import json
from pathlib import Path

import pytest

from .conftest import (
    NOT_LEARNED,
    change_plan as _change_plan,
    invoke_cli as _invoke,
    phase_cases as _cases,
    phases_by_name as _phases_by_name,
    stage_learning_plan as _stage_plan,
)


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

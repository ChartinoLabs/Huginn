"""Tests that planning loads each distinct job once, however often it is used."""

from pathlib import Path

import pytest

import huginn.models as models
from huginn import runner, validation
from huginn.enums import ExecutionMode
from huginn.jobs import load_test_case_class
from huginn.validation import ValidationIssue

_FIXTURE_ROOT = (
    Path(__file__).resolve().parent.parent / "fixtures" / "runner" / "job_import_error"
)
_PASSING_JOB = "jobs/test_verify_import_error_sibling.py"
_BROKEN_JOB = "jobs/broken_import.py"


def _plan_with_jobs(jobs: dict[str, str]) -> models.TestPlan:
    """Build a plan whose test cases map each test ID to a job."""
    return models.TestPlan(
        scenarios={},
        test_case_groups={},
        test_cases={
            test_id: models.TestCaseDefinition(test_id=test_id, title=test_id, job=job)
            for test_id, job in jobs.items()
        },
    )


def _count_job_loads(monkeypatch: pytest.MonkeyPatch, module: object) -> list[str]:
    """Record every job the given module asks the loader for."""
    loaded: list[str] = []

    def _recording_loader(job: str, project_root: Path) -> type:
        loaded.append(job)
        return load_test_case_class(job=job, project_root=project_root)

    monkeypatch.setattr(module, "load_test_case_class", _recording_loader)
    return loaded


_DUPLICATED_JOBS = {
    "1.0.0": _PASSING_JOB,
    "2.0.0": _PASSING_JOB,
    "3.0.0": _PASSING_JOB,
    "4.0.0": _BROKEN_JOB,
    "5.0.0": _BROKEN_JOB,
}


def test_run_planning_loads_each_job_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test cases that share a job share one load and one plan."""
    loaded = _count_job_loads(monkeypatch, runner)

    planned = runner._plan_executions(
        mode=ExecutionMode.TESTING,
        test_plan=_plan_with_jobs(_DUPLICATED_JOBS),
        project_root=_FIXTURE_ROOT,
        output=None,
    )

    assert sorted(loaded) == [_BROKEN_JOB, _PASSING_JOB]
    assert set(planned) == set(_DUPLICATED_JOBS)
    assert planned["1.0.0"] is planned["2.0.0"] is planned["3.0.0"]
    assert planned["1.0.0"].planning_error is None
    assert planned["4.0.0"] is planned["5.0.0"]
    assert "Error importing job file" in (planned["4.0.0"].planning_error or "")


def test_validation_loads_each_job_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Validation loads a shared job once and still reports each test case."""
    loaded = _count_job_loads(monkeypatch, validation)
    errors: list[ValidationIssue] = []

    required = validation._collect_required_brokers(
        test_plan=_plan_with_jobs(_DUPLICATED_JOBS),
        project_root=_FIXTURE_ROOT,
        errors=errors,
        output=None,
    )

    assert sorted(loaded) == [_BROKEN_JOB, _PASSING_JOB]
    assert set(required) == set(_DUPLICATED_JOBS)
    assert sorted(error.message.split(":")[0] for error in errors) == [
        "4.0.0",
        "5.0.0",
    ]

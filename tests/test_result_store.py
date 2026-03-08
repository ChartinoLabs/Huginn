"""Unit tests for canonical JSON result writing."""

import json
from pathlib import Path
from typing import TYPE_CHECKING

from huginn.enums import ExecutionMode
from huginn.models import (
    CheckResult,
    ExecutedPhase,
    ExecutedTestCase,
    ExecutedTestCaseGroup,
    MetadataSection,
    RunSummary,
)
from huginn.result_store import write_run_result, write_validation_result
from huginn.validation import ValidationResult

if TYPE_CHECKING:
    from huginn.models import RunResult


def test_write_validation_result_writes_timestamped_json(tmp_path: Path) -> None:
    """Validation writes canonical JSON under a timestamped results directory."""
    result = ValidationResult(
        valid=True,
        phase_order=["phase-1"],
        required_brokers=["ssh"],
        test_cases=[],
        warnings=[],
        errors=[],
    )

    result_path = write_validation_result(
        result=result,
        results_dir=tmp_path / "results",
    )

    assert result_path.name == "validate.json"
    assert result_path.parent.parent == tmp_path / "results"
    assert result_path.parent.name.endswith("-validate")
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["valid"] is True


def test_write_run_result_writes_summary_and_test_case_json(tmp_path: Path) -> None:
    """Run writes a summary file plus one JSON result per test case."""
    result = _build_run_result_with_test_case()

    run_files = write_run_result(
        result=result,
        results_dir=tmp_path / "results",
        mode=ExecutionMode.TESTING,
    )

    result_path = run_files.run_json_path
    assert result_path.name == "run.json"
    assert result_path.parent.parent == tmp_path / "results"
    assert result_path.parent.name.endswith("-testing")
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["mode"] == "testing"
    assert payload["summary"]["status"] == "passed"
    test_case = payload["phases"][0]["test_case_groups"][0]["test_cases"][0]
    assert test_case["test_id"] == "test-1"
    assert test_case["result_path"] == "test-cases/test-1/result.json"
    assert "checks" not in test_case

    test_case_payload = json.loads(
        (result_path.parent / test_case["result_path"]).read_text(encoding="utf-8")
    )
    assert test_case_payload["checks"][0]["message"] == "all good"
    assert test_case_payload["metadata_sections"][0]["heading"] == "Description"


def _build_run_result_with_test_case() -> "RunResult":
    """Build a run result that includes one executed test case."""
    from huginn.models import RunResult

    return RunResult(
        summary=RunSummary(
            status="passed",
            total=1,
            passed=1,
            failed=0,
            errored=0,
            not_applicable=0,
            skipped=0,
            blocked=0,
        ),
        phases=[
            ExecutedPhase(
                name="phase-1",
                status="passed",
                test_case_groups=[
                    ExecutedTestCaseGroup(
                        name="group-1",
                        status="passed",
                        test_cases=[
                            ExecutedTestCase(
                                test_id="test-1",
                                title="Test 1",
                                status="passed",
                                metadata_sections=[
                                    MetadataSection(
                                        heading="Description",
                                        content="Test the happy path.",
                                    )
                                ],
                                checks=[
                                    CheckResult(
                                        status="passed",
                                        message="all good",
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )
        ],
    )

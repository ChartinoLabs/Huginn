"""Unit tests for standard HTML reporting."""

from pathlib import Path
from typing import TYPE_CHECKING

from huginn.models import (
    CheckResult,
    CommandExecution,
    ExecutedPhase,
    ExecutedTestCase,
    ExecutedTestCaseGroup,
    MetadataSection,
    RunSummary,
)
from huginn.reporting.html import write_standard_html_report

if TYPE_CHECKING:
    from huginn.models import RunResult


def test_write_standard_html_report_writes_dashboard_and_detail_pages(
    tmp_path: Path,
) -> None:
    """HTML reporting writes a dashboard and one detail page per test case."""
    result = _build_run_result()

    dashboard_path = write_standard_html_report(
        result=result,
        reports_dir=tmp_path / "reports",
        results_run_dir=tmp_path / "results" / "2026-Mar-07-12-00-00-testing",
        test_case_result_paths={
            "test-1": "test-cases/test-1/result.json",
            "test-2": "test-cases/test-2/result.json",
        },
    )

    assert dashboard_path == (
        tmp_path / "reports" / "2026-Mar-07-12-00-00-testing" / "html" / "index.html"
    )
    dashboard = dashboard_path.read_text(encoding="utf-8")
    assert "Run Dashboard" in dashboard
    assert "Phase 1" in dashboard
    assert "show version" in dashboard
    assert "View Details" in dashboard

    detail_page = (
        tmp_path
        / "reports"
        / "2026-Mar-07-12-00-00-testing"
        / "html"
        / "test-cases"
        / "test-1.html"
    )
    detail = detail_page.read_text(encoding="utf-8")
    assert "Description" in detail
    assert "Verify version output" in detail
    assert "Parsed Output" in detail
    assert "version" in detail
    assert "17.9" in detail


def _build_run_result() -> "RunResult":
    """Build a run result with enough detail for HTML rendering."""
    from huginn.models import RunResult

    return RunResult(
        summary=RunSummary(
            status="failed",
            total=2,
            passed=1,
            failed=1,
            errored=0,
            not_applicable=0,
            skipped=0,
            blocked=0,
        ),
        phases=[
            ExecutedPhase(
                name="Phase 1",
                status="failed",
                test_case_groups=[
                    ExecutedTestCaseGroup(
                        name="Group A",
                        status="failed",
                        test_cases=[
                            ExecutedTestCase(
                                test_id="test-1",
                                title="Version Check",
                                status="passed",
                                metadata_sections=[
                                    MetadataSection(
                                        heading="Description",
                                        content="Verify version output",
                                    ),
                                    MetadataSection(
                                        heading="Procedure",
                                        content="Run show version and compare fields.",
                                    ),
                                ],
                                checks=[
                                    CheckResult(
                                        status="info",
                                        message="Collected version details",
                                    ),
                                    CheckResult(
                                        status="passed",
                                        message="Version matched expected release",
                                    ),
                                ],
                                command_executions=[
                                    CommandExecution(
                                        device="leaf-1",
                                        command="show version",
                                        output="Version 17.9",
                                        parsed={"version": "17.9"},
                                        elapsed_ms=12.5,
                                        cached=False,
                                    )
                                ],
                            ),
                            ExecutedTestCase(
                                test_id="test-2",
                                title="Interface Health",
                                status="failed",
                                checks=[
                                    CheckResult(
                                        status="failed",
                                        message="Interface Eth1 is down",
                                    )
                                ],
                                command_executions=[
                                    CommandExecution(
                                        device="leaf-1",
                                        command="show interface status",
                                        output="Eth1 down",
                                        parsed=None,
                                    )
                                ],
                            ),
                        ],
                    )
                ],
            )
        ],
    )

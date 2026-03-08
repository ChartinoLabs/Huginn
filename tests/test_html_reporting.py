"""Unit tests for standard HTML reporting."""

from pathlib import Path
from typing import TYPE_CHECKING

from huginn.models import (
    CheckResult,
    CommandExecution,
    ExecutedPhase,
    ExecutedScenario,
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
            "Scenario 1::Phase 1::Group A::test-1": "test-cases/test-1/result.json",
            "Scenario 1::Phase 1::Group A::test-2": "test-cases/test-2/result.json",
        },
    )

    assert dashboard_path == (
        tmp_path / "reports" / "2026-Mar-07-12-00-00-testing" / "html" / "index.html"
    )
    latest_link = tmp_path / "reports" / "latest"
    assert latest_link.is_symlink()
    assert latest_link.resolve() == dashboard_path.parent.resolve()
    dashboard = dashboard_path.read_text(encoding="utf-8")
    assert "Test Results Summary" in dashboard
    assert "Scenario 1" in dashboard
    assert "Phase 1" in dashboard
    assert "Group A" in dashboard
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
    assert "Verify <strong>version</strong> output" in detail
    assert "<ul>" in detail
    assert "Parsed Output" in detail
    assert "Show Parsed Output" in detail
    assert "version" in detail
    assert "17.9" in detail
    assert "12.50 ms" in detail


def test_write_standard_html_report_updates_latest_symlink(tmp_path: Path) -> None:
    """Later reports repoint reports/latest to the newest HTML output."""
    result = _build_run_result()

    first_dashboard = write_standard_html_report(
        result=result,
        reports_dir=tmp_path / "reports",
        results_run_dir=tmp_path / "results" / "2026-Mar-07-12-00-00-testing",
        test_case_result_paths={
            "Scenario 1::Phase 1::Group A::test-1": "test-cases/test-1/result.json",
            "Scenario 1::Phase 1::Group A::test-2": "test-cases/test-2/result.json",
        },
    )
    second_dashboard = write_standard_html_report(
        result=result,
        reports_dir=tmp_path / "reports",
        results_run_dir=tmp_path / "results" / "2026-Mar-07-12-05-00-testing",
        test_case_result_paths={
            "Scenario 1::Phase 1::Group A::test-1": "test-cases/test-1/result.json",
            "Scenario 1::Phase 1::Group A::test-2": "test-cases/test-2/result.json",
        },
    )

    latest_link = tmp_path / "reports" / "latest"
    assert first_dashboard.parent != second_dashboard.parent
    assert latest_link.is_symlink()
    assert latest_link.resolve() == second_dashboard.parent.resolve()


def test_write_standard_html_report_handles_duplicate_test_ids_across_scenarios(
    tmp_path: Path,
) -> None:
    """Detail pages remain distinct when scenarios reuse the same test id."""
    from huginn.models import RunResult

    result = RunResult(
        summary=RunSummary(
            status="passed",
            total=2,
            passed=2,
            failed=0,
            errored=0,
            not_applicable=0,
            skipped=0,
            blocked=0,
        ),
        scenarios=[
            ExecutedScenario(
                name="Scenario 1",
                status="passed",
                phases=[
                    ExecutedPhase(
                        name="steady-state",
                        status="passed",
                        test_case_groups=[
                            ExecutedTestCaseGroup(
                                name="Group A",
                                status="passed",
                                test_cases=[
                                    ExecutedTestCase(
                                        scenario="Scenario 1",
                                        phase="steady-state",
                                        group="Group A",
                                        test_id="test-1",
                                        title="Scenario 1 test",
                                        status="passed",
                                        checks=[
                                            CheckResult(
                                                status="passed",
                                                message="scenario-1 result",
                                            )
                                        ],
                                    )
                                ],
                            )
                        ],
                    )
                ],
            ),
            ExecutedScenario(
                name="Scenario 2",
                status="passed",
                phases=[
                    ExecutedPhase(
                        name="steady-state",
                        status="passed",
                        test_case_groups=[
                            ExecutedTestCaseGroup(
                                name="Group A",
                                status="passed",
                                test_cases=[
                                    ExecutedTestCase(
                                        scenario="Scenario 2",
                                        phase="steady-state",
                                        group="Group A",
                                        test_id="test-1",
                                        title="Scenario 2 test",
                                        status="passed",
                                        checks=[
                                            CheckResult(
                                                status="passed",
                                                message="scenario-2 result",
                                            )
                                        ],
                                    )
                                ],
                            )
                        ],
                    )
                ],
            ),
        ],
    )

    dashboard_path = write_standard_html_report(
        result=result,
        reports_dir=tmp_path / "reports",
        results_run_dir=tmp_path / "results" / "2026-Mar-07-12-00-00-testing",
        test_case_result_paths={
            "Scenario 1::steady-state::Group A::test-1": (
                "test-cases/scenario-1-steady-state-test-1/result.json"
            ),
            "Scenario 2::steady-state::Group A::test-1": (
                "test-cases/scenario-2-steady-state-test-1/result.json"
            ),
        },
    )

    first_detail = (
        dashboard_path.parent / "test-cases" / "scenario-1-steady-state-test-1.html"
    ).read_text(encoding="utf-8")
    second_detail = (
        dashboard_path.parent / "test-cases" / "scenario-2-steady-state-test-1.html"
    ).read_text(encoding="utf-8")

    assert "Scenario 1 test" in first_detail
    assert "scenario-1 result" in first_detail
    assert "Scenario 2 test" in second_detail
    assert "scenario-2 result" in second_detail


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
        scenarios=[
            ExecutedScenario(
                name="Scenario 1",
                status="failed",
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
                                        scenario="Scenario 1",
                                        phase="Phase 1",
                                        group="Group A",
                                        test_id="test-1",
                                        title="Version Check",
                                        status="passed",
                                        metadata_sections=[
                                            MetadataSection(
                                                heading="Description",
                                                content=(
                                                    "Verify **version** output\n\n"
                                                    "- collect evidence\n"
                                                    "- compare parsed fields"
                                                ),
                                            ),
                                            MetadataSection(
                                                heading="Procedure",
                                                content=(
                                                    "Run show version and compare "
                                                    "fields."
                                                ),
                                            ),
                                        ],
                                        checks=[
                                            CheckResult(
                                                status="info",
                                                message="Collected version details",
                                            ),
                                            CheckResult(
                                                status="passed",
                                                message=(
                                                    "Version matched expected release"
                                                ),
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
                                        scenario="Scenario 1",
                                        phase="Phase 1",
                                        group="Group A",
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
        ],
    )

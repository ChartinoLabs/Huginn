"""Minimal end-to-end test plan runner for first implementation slice."""

from collections import Counter
from dataclasses import asdict
from pathlib import Path

from huginn.brokers.null import NullBroker
from huginn.context import Context
from huginn.enums import ExecutionMode, ResultStatus
from huginn.jobs import JobLoadError, load_test_case_class
from huginn.loaders import ConfigurationError, load_test_plan, load_testbed
from huginn.models import (
    ExecutedPhase,
    ExecutedTestCase,
    ExecutedTestCaseGroup,
    RunReport,
    RunSummary,
    Testbed,
)
from huginn.results import ResultCollector


class RunExecutionError(RuntimeError):
    """Raised when inputs cannot be loaded or jobs cannot be resolved."""


async def run_test_plan(
    *,
    mode: ExecutionMode,
    testbed_path: Path,
    plan_path: Path,
    project_root: Path,
    reports_dir: Path,
) -> RunReport:
    """Execute a minimal test plan and persist JSON output."""
    try:
        testbed = load_testbed(testbed_path)
        test_plan = load_test_plan(plan_path)
    except ConfigurationError as error:
        raise RunExecutionError(str(error)) from error

    broker = NullBroker()
    executed_phases: list[ExecutedPhase] = []

    for phase in test_plan.phases.values():
        executed_groups: list[ExecutedTestCaseGroup] = []
        for group_name in phase.test_case_groups:
            group = test_plan.test_case_groups[group_name]
            executed_tests: list[ExecutedTestCase] = []
            for test_id in group.tests:
                test_case_definition = test_plan.test_cases[test_id]
                executed_tests.append(
                    await _execute_test_case(
                        test_id=test_case_definition.test_id,
                        title=test_case_definition.title,
                        job=test_case_definition.job,
                        mode=mode,
                        project_root=project_root,
                        testbed=testbed,
                        broker=broker,
                    )
                )

            group_status = _derive_group_status(executed_tests)
            executed_groups.append(
                ExecutedTestCaseGroup(
                    name=group.name,
                    status=group_status.value,
                    test_cases=executed_tests,
                )
            )

        phase_status = _derive_phase_status(executed_groups)
        executed_phases.append(
            ExecutedPhase(
                name=phase.name,
                status=phase_status.value,
                test_case_groups=executed_groups,
            )
        )

    summary = _build_summary(executed_phases)
    report = RunReport(summary=summary, phases=executed_phases)
    _write_report(report=report, reports_dir=reports_dir)
    return report


async def _execute_test_case(
    *,
    test_id: str,
    title: str,
    job: str,
    mode: ExecutionMode,
    project_root: Path,
    testbed: Testbed,
    broker: NullBroker,
) -> ExecutedTestCase:
    result_collector = ResultCollector()
    context = Context(
        test_id=test_id,
        test_title=title,
        mode=mode,
        testbed=testbed,
        targets=list(testbed.devices.values()),
        broker=broker,
        results=result_collector,
    )

    try:
        test_case_class = load_test_case_class(job=job, project_root=project_root)
    except JobLoadError as error:
        return ExecutedTestCase(
            test_id=test_id,
            title=title,
            status=ResultStatus.ERRORED.value,
            error=str(error),
        )

    test_case = test_case_class()
    test_error: str | None = None

    try:
        await test_case.setup(context)
        await test_case.test(context)
    except Exception as error:  # noqa: BLE001
        test_error = f"{error.__class__.__name__}: {error}"
    finally:
        try:
            await test_case.cleanup(context)
        except Exception as cleanup_error:  # noqa: BLE001
            if test_error is None:
                test_error = f"{cleanup_error.__class__.__name__}: {cleanup_error}"

    if test_error is not None:
        return ExecutedTestCase(
            test_id=test_id,
            title=title,
            status=ResultStatus.ERRORED.value,
            checks=result_collector.checks,
            error=test_error,
        )

    status = result_collector.derive_status().value
    return ExecutedTestCase(
        test_id=test_id,
        title=title,
        status=status,
        checks=result_collector.checks,
    )


def _derive_group_status(test_cases: list[ExecutedTestCase]) -> ResultStatus:
    return _derive_status_from_values([test_case.status for test_case in test_cases])


def _derive_phase_status(groups: list[ExecutedTestCaseGroup]) -> ResultStatus:
    return _derive_status_from_values([group.status for group in groups])


def _derive_status_from_values(statuses: list[str]) -> ResultStatus:
    if any(status == ResultStatus.ERRORED.value for status in statuses):
        return ResultStatus.ERRORED
    if any(status == ResultStatus.FAILED.value for status in statuses):
        return ResultStatus.FAILED
    if statuses and all(status == ResultStatus.SKIPPED.value for status in statuses):
        return ResultStatus.SKIPPED
    return ResultStatus.PASSED


def _build_summary(phases: list[ExecutedPhase]) -> RunSummary:
    statuses = _collect_test_case_statuses(phases)
    counts = Counter(statuses)
    overall_status = _derive_status_from_values(statuses).value
    return RunSummary(
        status=overall_status,
        total=len(statuses),
        passed=counts[ResultStatus.PASSED.value],
        failed=counts[ResultStatus.FAILED.value],
        errored=counts[ResultStatus.ERRORED.value],
        skipped=counts[ResultStatus.SKIPPED.value],
        blocked=counts[ResultStatus.BLOCKED.value],
    )


def _collect_test_case_statuses(phases: list[ExecutedPhase]) -> list[str]:
    """Collect all test case statuses from executed phase output."""
    statuses: list[str] = []
    for phase in phases:
        for group in phase.test_case_groups:
            for test_case in group.test_cases:
                statuses.append(test_case.status)
    return statuses


def _write_report(report: RunReport, reports_dir: Path) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "run.json"
    import json

    report_path.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")

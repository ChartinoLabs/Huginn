"""Minimal end-to-end test plan runner for first implementation slice."""

from collections import Counter
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from huginn.context import Context
from huginn.enums import ExecutionMode, ResultStatus
from huginn.jobs import JobLoadError, load_test_case_class
from huginn.loaders import ConfigurationError, load_test_plan, load_testbed
from huginn.models import (
    CheckResult,
    Device,
    ExecutedPhase,
    ExecutedTestCase,
    ExecutedTestCaseGroup,
    RunReport,
    RunSummary,
    Testbed,
    TestCaseDefinition,
)
from huginn.results import ResultCollector
from huginn.runtime_broker import RuntimeBroker, RuntimeBrokerError
from huginn.testcase import TestCase


class RunExecutionError(RuntimeError):
    """Raised when inputs cannot be loaded or jobs cannot be resolved."""


async def run_test_plan(
    *,
    mode: ExecutionMode,
    testbed_path: Path,
    plan_path: Path,
    project_root: Path,
    reports_dir: Path,
    broker_factory: Callable[[], RuntimeBroker] | None = None,
) -> RunReport:
    """Execute a minimal test plan and persist JSON output."""
    try:
        testbed = load_testbed(testbed_path)
        test_plan = load_test_plan(plan_path)
    except ConfigurationError as error:
        raise RunExecutionError(str(error)) from error

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
                        definition=test_case_definition,
                        mode=mode,
                        project_root=project_root,
                        testbed=testbed,
                        broker=_create_broker(broker_factory),
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
    definition: TestCaseDefinition,
    mode: ExecutionMode,
    project_root: Path,
    testbed: Testbed,
    broker: RuntimeBroker,
) -> ExecutedTestCase:
    targets, target_error = _resolve_targets(testbed, definition)
    if target_error is not None:
        return _errored_test_case(definition, error=target_error)

    result_collector = ResultCollector()
    context = Context(
        test_id=definition.test_id,
        test_title=definition.title,
        mode=mode,
        testbed=testbed,
        targets=targets,
        broker=broker,
        results=result_collector,
    )

    try:
        test_case_class = load_test_case_class(
            job=definition.job,
            project_root=project_root,
        )
    except JobLoadError as error:
        return _errored_test_case(definition, error=str(error))

    test_case = test_case_class()
    test_error: str | None = None
    broker_error: str | None = None

    try:
        await _connect_targets_or_raise(broker, targets)
    except RuntimeBrokerError as error:
        return _errored_test_case(definition, error=str(error))

    try:
        await test_case.setup(context)
        await test_case.test(context)
    except Exception as error:  # noqa: BLE001
        test_error = f"{error.__class__.__name__}: {error}"
    finally:
        test_error = await _run_cleanup(test_case, context, test_error)
        broker_error = await _disconnect_targets(broker)

    if test_error is not None or broker_error is not None:
        final_error = test_error if test_error is not None else broker_error
        if final_error is None:
            final_error = "unknown execution error"
        return _errored_test_case(
            definition,
            checks=result_collector.checks,
            error=final_error,
        )

    status = result_collector.derive_status().value
    return ExecutedTestCase(
        test_id=definition.test_id,
        title=definition.title,
        status=status,
        checks=result_collector.checks,
    )


def _errored_test_case(
    definition: TestCaseDefinition,
    *,
    error: str,
    checks: list[CheckResult] | None = None,
) -> ExecutedTestCase:
    """Build a standardized errored test case output."""
    normalized_checks: list[CheckResult] = checks if checks is not None else []
    return ExecutedTestCase(
        test_id=definition.test_id,
        title=definition.title,
        status=ResultStatus.ERRORED.value,
        checks=normalized_checks,
        error=error,
    )


async def _connect_targets_or_raise(
    broker: RuntimeBroker,
    targets: list[Device],
) -> None:
    """Connect all resolved target devices via runtime broker."""
    await broker.connect_targets(targets)


async def _run_cleanup(
    test_case: TestCase,
    context: Context,
    test_error: str | None,
) -> str | None:
    """Run test cleanup and preserve first execution error."""
    try:
        await test_case.cleanup(context)
    except Exception as cleanup_error:  # noqa: BLE001
        if test_error is None:
            return f"{cleanup_error.__class__.__name__}: {cleanup_error}"
    return test_error


async def _disconnect_targets(broker: RuntimeBroker) -> str | None:
    """Disconnect broker targets and return an error message when needed."""
    try:
        await broker.disconnect_targets()
    except RuntimeBrokerError as disconnect_error:
        return str(disconnect_error)
    return None


def _create_broker(
    broker_factory: Callable[[], RuntimeBroker] | None,
) -> RuntimeBroker:
    """Construct a broker instance for one test case execution."""
    if broker_factory is None:
        return RuntimeBroker()
    return broker_factory()


def _resolve_targets(
    testbed: Testbed,
    definition: TestCaseDefinition,
) -> tuple[list[Device], str | None]:
    """Resolve test targets from test-case definition and testbed."""
    if definition.target is None or definition.target.devices is None:
        return list(testbed.devices.values()), None

    targets: list[Device] = []
    for device_name in definition.target.devices:
        device = testbed.devices.get(device_name)
        if device is None:
            return [], f"Unknown target device '{device_name}' for {definition.test_id}"
        targets.append(device)
    return targets, None


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

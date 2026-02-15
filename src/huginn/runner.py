"""Minimal end-to-end test plan runner for first implementation slice."""

from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from huginn.context import Context
from huginn.enums import BrokerType, ExecutionMode, ResultStatus
from huginn.jobs import JobLoadError, load_test_case_class
from huginn.loaders import ConfigurationError, load_test_plan, load_testbed
from huginn.models import (
    CheckResult,
    Device,
    ExecutedPhase,
    ExecutedTestCase,
    ExecutedTestCaseGroup,
    Phase,
    RunReport,
    RunSummary,
    Testbed,
    TestCaseDefinition,
    TestPlan,
)
from huginn.results import ResultCollector
from huginn.runtime_broker import (
    RuntimeBroker,
    RuntimeBrokerError,
    normalize_broker_key,
)
from huginn.testcase import TestCase


class RunExecutionError(RuntimeError):
    """Raised when inputs cannot be loaded or jobs cannot be resolved."""


@dataclass(frozen=True)
class PlannedExecution:
    """Preflight plan for a single test case execution."""

    test_case_class: type[TestCase] | None
    required_brokers: set[BrokerType]
    planning_error: str | None


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

    planned_executions = _plan_executions(
        test_plan=test_plan,
        project_root=project_root,
    )
    planned_brokers = _collect_planned_brokers(planned_executions)
    runtime_broker = _create_broker(
        broker_factory=broker_factory,
        required_brokers=planned_brokers,
    )

    executed_phases = await _execute_phases_with_dependencies(
        mode=mode,
        testbed=testbed,
        test_plan=test_plan,
        planned_executions=planned_executions,
        broker=runtime_broker,
    )

    summary = _build_summary(executed_phases)
    report = RunReport(summary=summary, phases=executed_phases)
    _write_report(report=report, reports_dir=reports_dir)
    return report


async def _execute_phases_with_dependencies(
    *,
    mode: ExecutionMode,
    testbed: Testbed,
    test_plan: TestPlan,
    planned_executions: dict[str, PlannedExecution],
    broker: RuntimeBroker,
) -> list[ExecutedPhase]:
    """Execute phases while honoring phase dependency constraints."""
    phase_results: dict[str, ExecutedPhase] = {}
    pending = set(test_plan.phases.keys())

    while pending:
        progressed = False
        for phase_name in list(pending):
            phase = test_plan.phases[phase_name]
            if not all(dep in phase_results for dep in phase.depends_on):
                continue

            if _is_blocked_by_dependencies(phase, phase_results):
                executed_phase = _build_blocked_phase(phase, test_plan)
            else:
                executed_phase = await _execute_phase(
                    phase=phase,
                    mode=mode,
                    testbed=testbed,
                    test_plan=test_plan,
                    planned_executions=planned_executions,
                    broker=broker,
                )

            phase_results[phase_name] = executed_phase
            pending.remove(phase_name)
            progressed = True

        if not progressed:
            unresolved = sorted(pending)
            raise RunExecutionError(
                f"Unable to resolve phase dependencies for: {unresolved}"
            )

    return [phase_results[name] for name in test_plan.phases]


def _is_blocked_by_dependencies(
    phase: Phase,
    phase_results: dict[str, ExecutedPhase],
) -> bool:
    """Return True when any dependency phase did not pass."""
    blocking_statuses = {
        ResultStatus.FAILED.value,
        ResultStatus.ERRORED.value,
        ResultStatus.BLOCKED.value,
    }
    return any(
        phase_results[dependency].status in blocking_statuses
        for dependency in phase.depends_on
    )


async def _execute_phase(
    *,
    phase: Phase,
    mode: ExecutionMode,
    testbed: Testbed,
    test_plan: TestPlan,
    planned_executions: dict[str, PlannedExecution],
    broker: RuntimeBroker,
) -> ExecutedPhase:
    """Execute all groups and test cases for a phase."""
    executed_groups: list[ExecutedTestCaseGroup] = []
    for group_name in phase.test_case_groups:
        group = test_plan.test_case_groups[group_name]
        executed_tests: list[ExecutedTestCase] = []
        for test_id in group.tests:
            test_case_definition = test_plan.test_cases[test_id]
            executed_tests.append(
                await _execute_test_case(
                    definition=test_case_definition,
                    planned=planned_executions[test_case_definition.test_id],
                    mode=mode,
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
    return ExecutedPhase(
        name=phase.name,
        status=phase_status.value,
        test_case_groups=executed_groups,
    )


def _build_blocked_phase(phase: Phase, test_plan: TestPlan) -> ExecutedPhase:
    """Build blocked phase output when dependencies failed."""
    blocked_groups: list[ExecutedTestCaseGroup] = []
    for group_name in phase.test_case_groups:
        group = test_plan.test_case_groups[group_name]
        blocked_tests = [
            ExecutedTestCase(
                test_id=test_id,
                title=test_plan.test_cases[test_id].title,
                status=ResultStatus.BLOCKED.value,
                error="Blocked by failed phase dependency",
            )
            for test_id in group.tests
        ]
        blocked_groups.append(
            ExecutedTestCaseGroup(
                name=group.name,
                status=ResultStatus.BLOCKED.value,
                test_cases=blocked_tests,
            )
        )

    return ExecutedPhase(
        name=phase.name,
        status=ResultStatus.BLOCKED.value,
        test_case_groups=blocked_groups,
    )


def _plan_executions(
    *,
    test_plan: TestPlan,
    project_root: Path,
) -> dict[str, PlannedExecution]:
    """Preload jobs and required broker declarations for all test cases."""
    planned: dict[str, PlannedExecution] = {}
    for test_case in test_plan.test_cases.values():
        try:
            test_case_class = load_test_case_class(
                job=test_case.job,
                project_root=project_root,
            )
            required_brokers = _required_brokers_for_test_case_class(test_case_class)
            planned[test_case.test_id] = PlannedExecution(
                test_case_class=test_case_class,
                required_brokers=required_brokers,
                planning_error=None,
            )
        except (JobLoadError, RuntimeBrokerError) as error:
            planned[test_case.test_id] = PlannedExecution(
                test_case_class=None,
                required_brokers={BrokerType.SSH},
                planning_error=str(error),
            )
    return planned


def _required_brokers_for_test_case_class(
    test_case_class: type[TestCase],
) -> set[BrokerType]:
    """Read and normalize required broker declarations from a test class."""
    raw_required = getattr(test_case_class, "required_brokers", {BrokerType.SSH})
    if not isinstance(raw_required, set) or not raw_required:
        raise RuntimeBrokerError(
            f"{test_case_class.__name__}.required_brokers must be a non-empty set"
        )
    normalized: set[BrokerType] = set()
    for broker in raw_required:
        if not isinstance(broker, str):
            raise RuntimeBrokerError(
                f"{test_case_class.__name__}.required_brokers values must be strings"
            )
        normalized.add(normalize_broker_key(broker))
    return normalized


def _collect_planned_brokers(planned: dict[str, PlannedExecution]) -> set[BrokerType]:
    """Aggregate required brokers for all successfully planned test cases."""
    required: set[BrokerType] = set()
    for execution in planned.values():
        if execution.planning_error is None:
            required.update(execution.required_brokers)
    if not required:
        return {BrokerType.SSH}
    return required


async def _execute_test_case(
    *,
    definition: TestCaseDefinition,
    planned: PlannedExecution,
    mode: ExecutionMode,
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

    if planned.planning_error is not None:
        return _errored_test_case(definition, error=planned.planning_error)
    if planned.test_case_class is None:
        return _errored_test_case(definition, error="Missing planned test case class")

    test_case = planned.test_case_class()
    test_error: str | None = None
    broker_error: str | None = None

    try:
        await _connect_targets_or_raise(
            broker,
            targets,
            planned.required_brokers,
        )
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
    required_brokers: set[BrokerType],
) -> None:
    """Connect all resolved target devices via runtime broker."""
    await broker.connect_targets(targets, required_brokers)


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
    required_brokers: set[BrokerType],
) -> RuntimeBroker:
    """Construct a broker instance for one test case execution."""
    if broker_factory is None:
        return RuntimeBroker(required_brokers=required_brokers)
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

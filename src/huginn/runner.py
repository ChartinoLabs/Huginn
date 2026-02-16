"""Minimal end-to-end test plan runner for first implementation slice."""

import asyncio
import traceback
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from huginn.context import Context
from huginn.enums import BrokerType, ErrorCode, ExecutionMode, ResultStatus
from huginn.inventory_plugins import (
    InventoryPluginError,
    resolve_inventory_testbed,
)
from huginn.jobs import JobLoadError, load_test_case_class
from huginn.loaders import ConfigurationError, load_test_plan
from huginn.models import (
    CheckResult,
    Device,
    ExecutedPhase,
    ExecutedTestCase,
    ExecutedTestCaseGroup,
    Phase,
    RunReport,
    RunSummary,
    TargetDefinition,
    Testbed,
    TestCaseDefinition,
    TestCaseGroup,
    TestPlan,
)
from huginn.parameters import ParameterManager
from huginn.plan_filtering import PlanFilterOptions, filter_test_plan
from huginn.report_plugins import (
    ReportPlugin,
    ReportPluginError,
    resolve_report_plugins,
    write_run_reports,
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

    def __init__(
        self,
        message: str,
        code: ErrorCode,
        *,
        traceback_text: str | None = None,
    ) -> None:
        """Initialize structured run execution error."""
        super().__init__(message)
        self.code = code
        self.traceback_text = traceback_text


@dataclass(frozen=True)
class PlannedExecution:
    """Validation plan for a single test case execution."""

    test_case_class: type[TestCase] | None
    required_brokers: set[BrokerType]
    planning_error: str | None
    planning_error_traceback: str | None = None


async def run_test_plan(
    *,
    mode: ExecutionMode,
    testbed_path: Path | None,
    inventory_plugin: str | None,
    plan_path: Path,
    filters: PlanFilterOptions,
    project_root: Path,
    parameters_dir: Path,
    reports_dir: Path,
    report_plugins: list[ReportPlugin] | None = None,
    broker_factory: Callable[[], RuntimeBroker] | None = None,
) -> RunReport:
    """Execute a minimal test plan and persist JSON output."""
    try:
        testbed = await resolve_inventory_testbed(
            testbed_path=testbed_path,
            inventory_plugin=inventory_plugin,
            project_root=project_root,
        )
        test_plan = filter_test_plan(load_test_plan(plan_path), filters)
    except (ConfigurationError, InventoryPluginError) as error:
        raise RunExecutionError(
            str(error),
            code=ErrorCode.CONFIGURATION_ERROR,
            traceback_text=traceback.format_exc(),
        ) from error

    planned_executions = _plan_executions(
        test_plan=test_plan,
        project_root=project_root,
    )
    planned_brokers = _collect_planned_brokers(planned_executions)
    runtime_broker = _create_broker(
        broker_factory=broker_factory,
        required_brokers=planned_brokers,
    )

    try:
        await _prime_runtime_connections(
            testbed=testbed,
            test_plan=test_plan,
            planned_executions=planned_executions,
            broker=runtime_broker,
        )
        executed_phases = await _execute_phases_with_dependencies(
            mode=mode,
            testbed=testbed,
            test_plan=test_plan,
            planned_executions=planned_executions,
            broker=runtime_broker,
            parameters_dir=parameters_dir,
        )
    finally:
        disconnect_error, disconnect_traceback = await _disconnect_runtime_broker(
            runtime_broker
        )
        if disconnect_error is not None:
            raise RunExecutionError(
                disconnect_error,
                code=ErrorCode.BROKER_ERROR,
                traceback_text=disconnect_traceback,
            )

    summary = _build_summary(executed_phases)
    report = RunReport(summary=summary, phases=executed_phases)
    try:
        write_run_reports(
            report=report,
            reports_dir=reports_dir,
            plugins=report_plugins or resolve_report_plugins(None),
        )
    except ReportPluginError as error:
        raise RunExecutionError(
            str(error),
            code=ErrorCode.CONFIGURATION_ERROR,
            traceback_text=traceback.format_exc(),
        ) from error
    return report


async def _execute_phases_with_dependencies(
    *,
    mode: ExecutionMode,
    testbed: Testbed,
    test_plan: TestPlan,
    planned_executions: dict[str, PlannedExecution],
    broker: RuntimeBroker,
    parameters_dir: Path,
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
                    parameters_dir=parameters_dir,
                )

            phase_results[phase_name] = executed_phase
            pending.remove(phase_name)
            progressed = True

        if not progressed:
            unresolved = sorted(pending)
            raise RunExecutionError(
                f"Unable to resolve phase dependencies for: {unresolved}",
                code=ErrorCode.VALIDATION_ERROR,
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
    parameters_dir: Path,
) -> ExecutedPhase:
    """Execute all groups and test cases for a phase."""
    if phase.strategy.mode == "serial":
        executed_groups = await _execute_phase_groups_serial(
            phase=phase,
            mode=mode,
            testbed=testbed,
            test_plan=test_plan,
            planned_executions=planned_executions,
            broker=broker,
            parameters_dir=parameters_dir,
        )
    else:
        executed_groups = await _execute_phase_groups_parallel(
            phase=phase,
            mode=mode,
            testbed=testbed,
            test_plan=test_plan,
            planned_executions=planned_executions,
            broker=broker,
            parameters_dir=parameters_dir,
        )

    phase_status = _derive_phase_status(executed_groups)
    return ExecutedPhase(
        name=phase.name,
        status=phase_status.value,
        test_case_groups=executed_groups,
    )


async def _execute_phase_groups_serial(
    *,
    phase: Phase,
    mode: ExecutionMode,
    testbed: Testbed,
    test_plan: TestPlan,
    planned_executions: dict[str, PlannedExecution],
    broker: RuntimeBroker,
    parameters_dir: Path,
) -> list[ExecutedTestCaseGroup]:
    """Execute test case groups in phase order, one at a time."""
    executed_groups: list[ExecutedTestCaseGroup] = []
    for group_name in phase.test_case_groups:
        executed_groups.append(
            await _execute_group(
                phase=phase,
                group_name=group_name,
                mode=mode,
                testbed=testbed,
                test_plan=test_plan,
                planned_executions=planned_executions,
                broker=broker,
                parameters_dir=parameters_dir,
            )
        )
    return executed_groups


async def _execute_phase_groups_parallel(
    *,
    phase: Phase,
    mode: ExecutionMode,
    testbed: Testbed,
    test_plan: TestPlan,
    planned_executions: dict[str, PlannedExecution],
    broker: RuntimeBroker,
    parameters_dir: Path,
) -> list[ExecutedTestCaseGroup]:
    """Execute test case groups in parallel with optional max concurrency."""
    semaphore = _build_parallel_semaphore(phase.strategy.maximum)
    tasks: list[asyncio.Task[tuple[int, ExecutedTestCaseGroup]]] = []

    for index, group_name in enumerate(phase.test_case_groups):
        tasks.append(
            asyncio.create_task(
                _execute_group_with_optional_semaphore(
                    index=index,
                    semaphore=semaphore,
                    phase=phase,
                    group_name=group_name,
                    mode=mode,
                    testbed=testbed,
                    test_plan=test_plan,
                    planned_executions=planned_executions,
                    broker=broker,
                    parameters_dir=parameters_dir,
                )
            )
        )

    indexed_groups = await asyncio.gather(*tasks)
    indexed_groups.sort(key=lambda item: item[0])
    return [group for _, group in indexed_groups]


async def _execute_group_with_optional_semaphore(
    *,
    index: int,
    semaphore: asyncio.Semaphore | None,
    phase: Phase,
    group_name: str,
    mode: ExecutionMode,
    testbed: Testbed,
    test_plan: TestPlan,
    planned_executions: dict[str, PlannedExecution],
    broker: RuntimeBroker,
    parameters_dir: Path,
) -> tuple[int, ExecutedTestCaseGroup]:
    """Execute one group with optional phase-level concurrency limiting."""
    if semaphore is None:
        return (
            index,
            await _execute_group(
                phase=phase,
                group_name=group_name,
                mode=mode,
                testbed=testbed,
                test_plan=test_plan,
                planned_executions=planned_executions,
                broker=broker,
                parameters_dir=parameters_dir,
            ),
        )

    async with semaphore:
        return (
            index,
            await _execute_group(
                phase=phase,
                group_name=group_name,
                mode=mode,
                testbed=testbed,
                test_plan=test_plan,
                planned_executions=planned_executions,
                broker=broker,
                parameters_dir=parameters_dir,
            ),
        )


async def _execute_group(
    *,
    phase: Phase,
    group_name: str,
    mode: ExecutionMode,
    testbed: Testbed,
    test_plan: TestPlan,
    planned_executions: dict[str, PlannedExecution],
    broker: RuntimeBroker,
    parameters_dir: Path,
) -> ExecutedTestCaseGroup:
    """Execute one group using its configured strategy."""
    group = test_plan.test_case_groups[group_name]

    if group.strategy.mode == "serial":
        executed_tests = await _execute_group_tests_serial(
            phase=phase,
            group=group,
            mode=mode,
            testbed=testbed,
            test_plan=test_plan,
            planned_executions=planned_executions,
            broker=broker,
            parameters_dir=parameters_dir,
        )
    else:
        executed_tests = await _execute_group_tests_parallel(
            phase=phase,
            group=group,
            mode=mode,
            testbed=testbed,
            test_plan=test_plan,
            planned_executions=planned_executions,
            broker=broker,
            parameters_dir=parameters_dir,
        )

    group_status = _derive_group_status(executed_tests)
    return ExecutedTestCaseGroup(
        name=group.name,
        status=group_status.value,
        test_cases=executed_tests,
    )


async def _execute_group_tests_serial(
    *,
    phase: Phase,
    group: TestCaseGroup,
    mode: ExecutionMode,
    testbed: Testbed,
    test_plan: TestPlan,
    planned_executions: dict[str, PlannedExecution],
    broker: RuntimeBroker,
    parameters_dir: Path,
) -> list[ExecutedTestCase]:
    """Execute tests in group order, one at a time."""
    executed_tests: list[ExecutedTestCase] = []
    for test_id in group.tests:
        test_case_definition = test_plan.test_cases[test_id]
        executed_tests.append(
            await _execute_test_case(
                phase=phase,
                group=group,
                definition=test_case_definition,
                planned=planned_executions[test_case_definition.test_id],
                mode=mode,
                testbed=testbed,
                broker=broker,
                parameters_dir=parameters_dir,
            )
        )
    return executed_tests


async def _execute_group_tests_parallel(
    *,
    phase: Phase,
    group: TestCaseGroup,
    mode: ExecutionMode,
    testbed: Testbed,
    test_plan: TestPlan,
    planned_executions: dict[str, PlannedExecution],
    broker: RuntimeBroker,
    parameters_dir: Path,
) -> list[ExecutedTestCase]:
    """Execute tests in parallel with optional max concurrency."""
    semaphore = _build_parallel_semaphore(group.strategy.maximum)
    tasks: list[asyncio.Task[tuple[int, ExecutedTestCase]]] = []

    for index, test_id in enumerate(group.tests):
        test_case_definition = test_plan.test_cases[test_id]
        tasks.append(
            asyncio.create_task(
                _execute_test_case_with_optional_semaphore(
                    index=index,
                    semaphore=semaphore,
                    phase=phase,
                    group=group,
                    definition=test_case_definition,
                    planned=planned_executions[test_case_definition.test_id],
                    mode=mode,
                    testbed=testbed,
                    broker=broker,
                    parameters_dir=parameters_dir,
                )
            )
        )

    indexed_tests = await asyncio.gather(*tasks)
    indexed_tests.sort(key=lambda item: item[0])
    return [test_case for _, test_case in indexed_tests]


async def _execute_test_case_with_optional_semaphore(
    *,
    index: int,
    semaphore: asyncio.Semaphore | None,
    phase: Phase,
    group: TestCaseGroup,
    definition: TestCaseDefinition,
    planned: PlannedExecution,
    mode: ExecutionMode,
    testbed: Testbed,
    broker: RuntimeBroker,
    parameters_dir: Path,
) -> tuple[int, ExecutedTestCase]:
    """Execute one test case with optional group-level concurrency limiting."""
    if semaphore is None:
        return (
            index,
            await _execute_test_case(
                phase=phase,
                group=group,
                definition=definition,
                planned=planned,
                mode=mode,
                testbed=testbed,
                broker=broker,
                parameters_dir=parameters_dir,
            ),
        )

    async with semaphore:
        return (
            index,
            await _execute_test_case(
                phase=phase,
                group=group,
                definition=definition,
                planned=planned,
                mode=mode,
                testbed=testbed,
                broker=broker,
                parameters_dir=parameters_dir,
            ),
        )


def _build_parallel_semaphore(maximum: int | None) -> asyncio.Semaphore | None:
    """Build optional concurrency semaphore from strategy maximum."""
    if maximum is None:
        return None
    return asyncio.Semaphore(maximum)


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
                planning_error_traceback=None,
            )
        except (JobLoadError, RuntimeBrokerError) as error:
            planned[test_case.test_id] = PlannedExecution(
                test_case_class=None,
                required_brokers={BrokerType.SSH},
                planning_error=str(error),
                planning_error_traceback=traceback.format_exc(),
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
    phase: Phase,
    group: TestCaseGroup,
    definition: TestCaseDefinition,
    planned: PlannedExecution,
    mode: ExecutionMode,
    testbed: Testbed,
    broker: RuntimeBroker,
    parameters_dir: Path,
) -> ExecutedTestCase:
    targets, target_error = _resolve_targets(
        testbed=testbed,
        phase=phase,
        group=group,
        test_case=definition,
    )
    if target_error is not None:
        return _errored_test_case(
            definition,
            error=target_error,
            error_code=ErrorCode.VALIDATION_ERROR,
        )
    if not targets:
        return _skipped_test_case(
            definition,
            reason="No devices matched target selectors",
        )

    result_collector = ResultCollector()
    context = Context(
        test_id=definition.test_id,
        test_title=definition.title,
        mode=mode,
        testbed=testbed,
        targets=targets,
        broker=broker,
        parameters=ParameterManager(
            parameters_dir=parameters_dir,
            test_id=definition.test_id,
        ),
        results=result_collector,
    )

    if planned.planning_error is not None:
        return _errored_test_case(
            definition,
            error=planned.planning_error,
            error_code=ErrorCode.PLANNING_ERROR,
            error_traceback=planned.planning_error_traceback,
        )
    if planned.test_case_class is None:
        return _errored_test_case(
            definition,
            error="Missing planned test case class",
            error_code=ErrorCode.PLANNING_ERROR,
        )

    test_case = planned.test_case_class()
    test_error: str | None = None
    test_error_traceback: str | None = None

    try:
        await test_case.setup(context)
        await test_case.test(context)
    except Exception as error:  # noqa: BLE001
        test_error = f"{error.__class__.__name__}: {error}"
        test_error_traceback = traceback.format_exc()
    finally:
        test_error, test_error_traceback = await _run_cleanup(
            test_case,
            context,
            test_error,
            test_error_traceback,
        )

    if test_error is not None:
        return _errored_test_case(
            definition,
            checks=result_collector.checks,
            error=test_error,
            error_code=ErrorCode.EXECUTION_ERROR,
            error_traceback=test_error_traceback,
        )

    status = result_collector.derive_status().value
    return ExecutedTestCase(
        test_id=definition.test_id,
        title=definition.title,
        status=status,
        checks=result_collector.checks,
        command_executions=result_collector.command_executions,
    )


def _errored_test_case(
    definition: TestCaseDefinition,
    *,
    error: str,
    error_code: ErrorCode,
    checks: list[CheckResult] | None = None,
    error_traceback: str | None = None,
) -> ExecutedTestCase:
    """Build a standardized errored test case output."""
    normalized_checks: list[CheckResult] = checks if checks is not None else []
    return ExecutedTestCase(
        test_id=definition.test_id,
        title=definition.title,
        status=ResultStatus.ERRORED.value,
        checks=normalized_checks,
        command_executions=[],
        error=error,
        error_code=error_code.value,
        error_traceback=error_traceback,
    )


def _skipped_test_case(
    definition: TestCaseDefinition,
    *,
    reason: str,
) -> ExecutedTestCase:
    """Build a standardized skipped test case output."""
    return ExecutedTestCase(
        test_id=definition.test_id,
        title=definition.title,
        status=ResultStatus.SKIPPED.value,
        command_executions=[],
        error=reason,
    )


async def _connect_targets_or_raise(
    broker: RuntimeBroker,
    targets: list[Device],
    required_brokers: set[BrokerType],
) -> None:
    """Connect all resolved target devices via runtime broker."""
    await broker.connect_targets(targets, required_brokers)


async def _prime_runtime_connections(
    *,
    testbed: Testbed,
    test_plan: TestPlan,
    planned_executions: dict[str, PlannedExecution],
    broker: RuntimeBroker,
) -> None:
    """Connect all planned test targets once before phase execution."""
    targets_by_brokers: dict[frozenset[BrokerType], dict[str, Device]] = {}

    for phase in test_plan.phases.values():
        for group_name in phase.test_case_groups:
            group = test_plan.test_case_groups[group_name]
            for test_id in group.tests:
                definition = test_plan.test_cases[test_id]
                planned = planned_executions[test_id]
                if planned.planning_error is not None:
                    continue
                targets, target_error = _resolve_targets(
                    testbed=testbed,
                    phase=phase,
                    group=group,
                    test_case=definition,
                )
                if target_error is not None or not targets:
                    continue

                broker_key = frozenset(planned.required_brokers)
                grouped_targets = targets_by_brokers.setdefault(broker_key, {})
                for target in targets:
                    grouped_targets[target.name] = target

    try:
        for required_brokers, target_lookup in targets_by_brokers.items():
            await _connect_targets_or_raise(
                broker,
                list(target_lookup.values()),
                set(required_brokers),
            )
    except RuntimeBrokerError as error:
        raise RunExecutionError(
            str(error),
            code=ErrorCode.BROKER_ERROR,
            traceback_text=traceback.format_exc(),
        ) from error


async def _run_cleanup(
    test_case: TestCase,
    context: Context,
    test_error: str | None,
    test_error_traceback: str | None,
) -> tuple[str | None, str | None]:
    """Run test cleanup and preserve first execution error."""
    try:
        await test_case.cleanup(context)
    except Exception as cleanup_error:  # noqa: BLE001
        cleanup_traceback = traceback.format_exc()
        if test_error is None:
            return (
                f"{cleanup_error.__class__.__name__}: {cleanup_error}",
                cleanup_traceback,
            )
        if test_error_traceback is None:
            return test_error, cleanup_traceback
        return test_error, (
            f"{test_error_traceback}\n\nDuring cleanup:\n{cleanup_traceback}"
        )
    return test_error, test_error_traceback


async def _disconnect_runtime_broker(
    broker: RuntimeBroker,
) -> tuple[str | None, str | None]:
    """Disconnect all runtime broker connections at run teardown."""
    try:
        await broker.disconnect_targets()
    except RuntimeBrokerError as disconnect_error:
        return (
            f"Broker teardown failed: {disconnect_error}",
            traceback.format_exc(),
        )
    return None, None


def _create_broker(
    broker_factory: Callable[[], RuntimeBroker] | None,
    required_brokers: set[BrokerType],
) -> RuntimeBroker:
    """Construct a broker instance for one test case execution."""
    if broker_factory is None:
        return RuntimeBroker(required_brokers=required_brokers)
    return broker_factory()


def _resolve_targets(
    *,
    testbed: Testbed,
    phase: Phase,
    group: TestCaseGroup,
    test_case: TestCaseDefinition,
) -> tuple[list[Device], str | None]:
    """Resolve targets with phase -> group -> test-case selector intersection."""
    devices = list(testbed.devices.values())

    for scope_name, target in (
        (f"Phase '{phase.name}'", phase.target),
        (f"Test case group '{group.name}'", group.target),
        (f"Test case '{test_case.test_id}'", test_case.target),
    ):
        devices, error = _apply_target_scope(
            devices=devices,
            testbed=testbed,
            target=target,
            scope_name=scope_name,
        )
        if error is not None:
            return [], error

    return devices, None


def _resolve_target_devices(
    *,
    testbed: Testbed,
    devices: list[Device],
    target: TargetDefinition,
    scope_name: str,
) -> tuple[list[Device], str | None]:
    """Resolve target device list, validating explicit device references."""
    target_devices = target.devices
    if target_devices is None:
        return devices, None

    allowed_names = {device.name for device in devices}
    selected_devices: list[Device] = []
    for device_name in target_devices:
        device = testbed.devices.get(device_name)
        if device is None:
            return [], f"Unknown target device '{device_name}' in {scope_name}"
        if device_name not in allowed_names:
            continue
        selected_devices.append(device)
    return selected_devices, None


def _apply_target_scope(
    *,
    devices: list[Device],
    testbed: Testbed,
    target: TargetDefinition | None,
    scope_name: str,
) -> tuple[list[Device], str | None]:
    """Apply one target scope to an incoming device set."""
    if target is None:
        return devices, None

    selected_devices, error = _resolve_target_devices(
        testbed=testbed,
        devices=devices,
        target=target,
        scope_name=scope_name,
    )
    if error is not None:
        return [], error

    return _apply_target_filters(selected_devices, target), None


def _apply_target_filters(
    devices: list[Device],
    target: TargetDefinition,
) -> list[Device]:
    """Apply optional groups/os filters to selected devices."""
    group_filter = set(target.groups or [])
    os_filter = set(target.os or [])

    filtered: list[Device] = []
    for device in devices:
        if group_filter and not group_filter.intersection(device.groups):
            continue
        if os_filter and device.os not in os_filter:
            continue
        filtered.append(device)
    return filtered


def _derive_group_status(test_cases: list[ExecutedTestCase]) -> ResultStatus:
    return _derive_status_from_values([test_case.status for test_case in test_cases])


def _derive_phase_status(groups: list[ExecutedTestCaseGroup]) -> ResultStatus:
    return _derive_status_from_values([group.status for group in groups])


def _derive_status_from_values(statuses: list[str]) -> ResultStatus:
    if _contains_status(statuses, ResultStatus.ERRORED):
        return ResultStatus.ERRORED
    if _contains_status(statuses, ResultStatus.FAILED):
        return ResultStatus.FAILED
    if _all_statuses_match(statuses, ResultStatus.NOT_APPLICABLE):
        return ResultStatus.NOT_APPLICABLE
    if _all_statuses_match(statuses, ResultStatus.SKIPPED):
        return ResultStatus.SKIPPED
    return ResultStatus.PASSED


def _contains_status(statuses: list[str], status: ResultStatus) -> bool:
    """Return True when the given status exists in values."""
    return any(value == status.value for value in statuses)


def _all_statuses_match(statuses: list[str], status: ResultStatus) -> bool:
    """Return True when all values match the given status."""
    return bool(statuses) and all(value == status.value for value in statuses)


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
        not_applicable=counts[ResultStatus.NOT_APPLICABLE.value],
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

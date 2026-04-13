"""Minimal end-to-end test plan runner for first implementation slice."""

import asyncio
import copy
import traceback
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter

from huginn.context import Context
from huginn.enums import BrokerType, ErrorCode, ExecutionMode, ResultStatus
from huginn.inventory_plugins import (
    InventoryPluginError,
    resolve_inventory_testbed,
)
from huginn.jobs import JobLoadError, load_test_case_class
from huginn.loaders import ConfigurationError, load_test_plan
from huginn.logging_helpers import log_debug, log_info, log_warning
from huginn.models import (
    CheckResult,
    Device,
    ExecutedPhase,
    ExecutedScenario,
    ExecutedTestCase,
    ExecutedTestCaseGroup,
    Phase,
    RunResult,
    RunSummary,
    Scenario,
    TargetDefinition,
    Testbed,
    TestCaseDefinition,
    TestCaseGroup,
    TestPlan,
)
from huginn.output import Output
from huginn.parameters import ParameterManager
from huginn.plan_filtering import PlanFilterOptions, filter_test_plan
from huginn.reporting.html import ReportRenderError, write_standard_html_report
from huginn.result_store import ResultWriteError, write_run_result
from huginn.results import ResultCollector
from huginn.runtime_broker import (
    RuntimeBroker,
    RuntimeBrokerError,
    normalize_broker_key,
)
from huginn.testcase import LearningTestCase, TestCase


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
    skip_reason: str | None = None


async def run_test_plan(
    *,
    mode: ExecutionMode,
    testbed_path: Path | None,
    inventory_plugin: str | None,
    plan_path: Path,
    filters: PlanFilterOptions,
    project_root: Path,
    parameters_dir: Path,
    results_dir: Path,
    output: Output | None = None,
    broker_factory: Callable[[], RuntimeBroker] | None = None,
) -> RunResult:
    """Execute a minimal test plan and persist run artifacts."""
    run_started = perf_counter()
    started_at = datetime.now().astimezone()
    log_info(
        output,
        "Run starting",
        mode=mode.value,
        plan=plan_path,
        testbed=testbed_path,
        inventory_plugin=inventory_plugin,
    )
    _emit_status(output, "Loading inventory and test plan")
    load_started = perf_counter()
    try:
        testbed = await resolve_inventory_testbed(
            testbed_path=testbed_path,
            inventory_plugin=inventory_plugin,
            project_root=project_root,
        )
        test_plan = filter_test_plan(load_test_plan(plan_path), filters)
        log_debug(
            output,
            "Configuration loaded",
            devices=len(testbed.devices),
            scenarios=len(test_plan.scenarios),
            phases=sum(
                len(scenario.phases) for scenario in test_plan.scenarios.values()
            ),
            groups=len(test_plan.test_case_groups),
            test_cases=len(test_plan.test_cases),
        )
    except (ConfigurationError, InventoryPluginError) as error:
        raise RunExecutionError(
            str(error),
            code=ErrorCode.CONFIGURATION_ERROR,
            traceback_text=traceback.format_exc(),
        ) from error
    _emit_status(
        output,
        f"Loaded inventory and test plan in {_format_elapsed(load_started)}",
    )

    _emit_status(output, "Planning test execution")
    planning_started = perf_counter()
    planned_executions = _plan_executions(
        mode=mode,
        test_plan=test_plan,
        project_root=project_root,
        output=output,
    )
    planned_brokers = _collect_planned_brokers(planned_executions)
    planning_errors = sum(
        1 for execution in planned_executions.values() if execution.planning_error
    )
    log_info(
        output,
        "Execution planning complete",
        planned_test_cases=len(planned_executions),
        planning_errors=planning_errors,
        required_brokers=sorted(broker.value for broker in planned_brokers),
    )
    _emit_status(
        output,
        (
            "Planned test execution in "
            f"{_format_elapsed(planning_started)} "
            f"(tests={len(planned_executions)} errors={planning_errors})"
        ),
    )
    _emit_execution_order(output, test_plan)
    runtime_broker = _create_broker(
        broker_factory=broker_factory,
        required_brokers=planned_brokers,
    )

    try:
        _emit_status(output, "Priming runtime connections")
        priming_started = perf_counter()
        await _prime_runtime_connections(
            testbed=testbed,
            test_plan=test_plan,
            planned_executions=planned_executions,
            broker=runtime_broker,
            output=output,
        )
        _emit_status(
            output,
            f"Primed runtime connections in {_format_elapsed(priming_started)}",
        )

        _emit_status(output, "Executing scenarios and phases")
        execution_started = perf_counter()
        executed_scenarios = await _execute_scenarios(
            mode=mode,
            testbed=testbed,
            test_plan=test_plan,
            planned_executions=planned_executions,
            broker=runtime_broker,
            parameters_dir=parameters_dir,
            output=output,
        )
        _emit_status(
            output,
            f"Finished phase execution in {_format_elapsed(execution_started)}",
        )
    finally:
        log_debug(output, "Run teardown starting")
        disconnect_error, disconnect_traceback = await _disconnect_runtime_broker(
            runtime_broker
        )
        if disconnect_error is not None:
            raise RunExecutionError(
                disconnect_error,
                code=ErrorCode.BROKER_ERROR,
                traceback_text=disconnect_traceback,
            )

    summary = _build_summary(executed_scenarios)
    completed_at = datetime.now().astimezone()
    result = RunResult(
        summary=summary,
        scenarios=executed_scenarios,
        mode=mode.value,
        started_at=started_at.isoformat(timespec="seconds"),
        completed_at=completed_at.isoformat(timespec="seconds"),
        elapsed_seconds=completed_at.timestamp() - started_at.timestamp(),
    )
    try:
        run_files = write_run_result(result=result, results_dir=results_dir, mode=mode)
        dashboard_path = write_standard_html_report(
            result=result,
            reports_dir=project_root / "reports",
            results_run_dir=run_files.run_dir,
            test_case_result_paths=run_files.test_case_paths,
        )
    except (ResultWriteError, ReportRenderError) as error:
        raise RunExecutionError(
            str(error),
            code=ErrorCode.CONFIGURATION_ERROR,
            traceback_text=traceback.format_exc(),
        ) from error
    log_info(
        output,
        "Run completed",
        status=result.summary.status,
        total=result.summary.total,
        passed=result.summary.passed,
        failed=result.summary.failed,
        errored=result.summary.errored,
        not_applicable=result.summary.not_applicable,
        skipped=result.summary.skipped,
        blocked=result.summary.blocked,
    )
    log_info(output, "HTML report written", path=str(dashboard_path))
    _emit_status(output, f"HTML report written to {dashboard_path}")
    _emit_status(output, f"Run completed in {_format_elapsed(run_started)}")
    return result


async def _execute_scenarios(
    *,
    mode: ExecutionMode,
    testbed: Testbed,
    test_plan: TestPlan,
    planned_executions: dict[str, PlannedExecution],
    broker: RuntimeBroker,
    parameters_dir: Path,
    output: Output | None,
) -> list[ExecutedScenario]:
    """Execute scenarios and their phases in declared order."""
    log_debug(
        output,
        "Executing scenarios",
        scenario_count=len(test_plan.scenarios),
    )
    executed_scenarios: list[ExecutedScenario] = []
    learning_execution_cache: dict[str, asyncio.Task[ExecutedTestCase]] | None = None
    if mode == ExecutionMode.LEARNING:
        learning_execution_cache = {}
    for scenario in test_plan.scenarios.values():
        _emit_status(output, f"Starting scenario: {scenario.identifier}")
        executed_scenario = await _execute_scenario(
            scenario=scenario,
            mode=mode,
            testbed=testbed,
            test_plan=test_plan,
            planned_executions=planned_executions,
            broker=broker,
            parameters_dir=parameters_dir,
            learning_execution_cache=learning_execution_cache,
            output=output,
        )
        executed_scenarios.append(executed_scenario)
    return executed_scenarios


async def _execute_scenario(
    *,
    scenario: Scenario,
    mode: ExecutionMode,
    testbed: Testbed,
    test_plan: TestPlan,
    planned_executions: dict[str, PlannedExecution],
    broker: RuntimeBroker,
    parameters_dir: Path,
    learning_execution_cache: dict[str, asyncio.Task[ExecutedTestCase]] | None,
    output: Output | None,
) -> ExecutedScenario:
    """Execute one scenario and halt on the first non-passing phase."""
    log_debug(
        output,
        "Executing scenario phases",
        scenario=scenario.identifier,
        phase_count=len(scenario.phases),
    )
    phase_results: dict[str, ExecutedPhase] = {}
    pending = set(scenario.phases.keys())

    while pending:
        phase_name = _select_next_phase_name(scenario, pending, phase_results)
        if phase_name is None:
            _raise_unresolved_scenario_dependencies(scenario.identifier, pending)
            return ExecutedScenario(
                identifier=scenario.identifier,
                status=ResultStatus.ERRORED.value,
                name=scenario.name,
            )

        phase = scenario.phases[phase_name]
        executed_phase = await _execute_ready_phase(
            scenario_name=scenario.identifier,
            phase=phase,
            mode=mode,
            testbed=testbed,
            test_plan=test_plan,
            planned_executions=planned_executions,
            broker=broker,
            parameters_dir=parameters_dir,
            learning_execution_cache=learning_execution_cache,
            output=output,
            phase_results=phase_results,
        )
        _record_phase_result(
            scenario_name=scenario.identifier,
            phase_name=phase_name,
            executed_phase=executed_phase,
            phase_results=phase_results,
            pending=pending,
            output=output,
        )

        if _should_halt_scenario_after_phase(executed_phase):
            _block_remaining_phases(
                scenario=scenario,
                failed_phase=phase,
                pending=pending,
                phase_results=phase_results,
                test_plan=test_plan,
            )
            break

    executed_phases = [phase_results[name] for name in scenario.phases]
    return ExecutedScenario(
        identifier=scenario.identifier,
        status=_derive_scenario_status(executed_phases).value,
        name=scenario.name,
        phases=executed_phases,
    )


def _select_next_phase_name(
    scenario: Scenario,
    pending: set[str],
    phase_results: dict[str, ExecutedPhase],
) -> str | None:
    """Return the next phase whose dependencies are satisfied."""
    for phase_name, phase in scenario.phases.items():
        if phase_name not in pending:
            continue
        if all(dep in phase_results for dep in phase.depends_on):
            return phase_name
    return None


async def _execute_ready_phase(
    *,
    scenario_name: str,
    phase: Phase,
    mode: ExecutionMode,
    testbed: Testbed,
    test_plan: TestPlan,
    planned_executions: dict[str, PlannedExecution],
    broker: RuntimeBroker,
    parameters_dir: Path,
    learning_execution_cache: dict[str, asyncio.Task[ExecutedTestCase]] | None,
    output: Output | None,
    phase_results: dict[str, ExecutedPhase],
) -> ExecutedPhase:
    """Execute or block one dependency-ready phase."""
    if _is_blocked_by_dependencies(phase, phase_results):
        return _build_dependency_blocked_phase(
            scenario_name=scenario_name,
            phase=phase,
            test_plan=test_plan,
            output=output,
        )

    _emit_status(output, f"  Starting phase: {phase.identifier}")
    executed_phase = await _execute_phase(
        scenario_name=scenario_name,
        phase=phase,
        mode=mode,
        testbed=testbed,
        test_plan=test_plan,
        planned_executions=planned_executions,
        broker=broker,
        parameters_dir=parameters_dir,
        learning_execution_cache=learning_execution_cache,
        output=output,
    )
    log_info(
        output,
        "Phase finished",
        scenario=scenario_name,
        phase=phase.identifier,
        status=executed_phase.status,
    )
    return executed_phase


def _build_dependency_blocked_phase(
    *,
    scenario_name: str,
    phase: Phase,
    test_plan: TestPlan,
    output: Output | None,
) -> ExecutedPhase:
    """Build a blocked phase after a failed dependency."""
    _emit_status(
        output,
        f"Skipping phase: {phase.identifier} (blocked by dependencies)",
    )
    log_info(
        output,
        "Phase blocked by dependencies",
        scenario=scenario_name,
        phase=phase.identifier,
        depends_on=phase.depends_on,
    )
    return _build_blocked_phase(
        scenario_name=scenario_name,
        phase=phase,
        test_plan=test_plan,
        reason="Blocked by failed phase dependency",
    )


def _record_phase_result(
    *,
    scenario_name: str,
    phase_name: str,
    executed_phase: ExecutedPhase,
    phase_results: dict[str, ExecutedPhase],
    pending: set[str],
    output: Output | None,
) -> None:
    """Store a phase result and emit its rollup."""
    _emit_phase_rollup(output, scenario_name, executed_phase)
    phase_results[phase_name] = executed_phase
    pending.remove(phase_name)


def _block_remaining_phases(
    *,
    scenario: Scenario,
    failed_phase: Phase,
    pending: set[str],
    phase_results: dict[str, ExecutedPhase],
    test_plan: TestPlan,
) -> None:
    """Mark all remaining phases as blocked after a failure halt."""
    for remaining_phase_name in scenario.phases:
        if remaining_phase_name not in pending:
            continue
        remaining_phase = scenario.phases[remaining_phase_name]
        phase_results[remaining_phase_name] = _build_blocked_phase(
            scenario_name=scenario.identifier,
            phase=remaining_phase,
            test_plan=test_plan,
            reason=f"Blocked because phase '{failed_phase.identifier}' failed",
        )
    pending.clear()


def _raise_unresolved_scenario_dependencies(
    scenario_name: str,
    pending: set[str],
) -> None:
    """Raise when a scenario's phase graph can no longer progress."""
    unresolved = sorted(pending)
    raise RunExecutionError(
        (
            "Unable to resolve phase dependencies in scenario "
            f"'{scenario_name}' for: {unresolved}"
        ),
        code=ErrorCode.VALIDATION_ERROR,
    )


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
    scenario_name: str,
    phase: Phase,
    mode: ExecutionMode,
    testbed: Testbed,
    test_plan: TestPlan,
    planned_executions: dict[str, PlannedExecution],
    broker: RuntimeBroker,
    parameters_dir: Path,
    learning_execution_cache: dict[str, asyncio.Task[ExecutedTestCase]] | None,
    output: Output | None,
) -> ExecutedPhase:
    """Execute all groups and test cases for a phase."""
    log_debug(
        output,
        "Phase execution starting",
        phase=phase.identifier,
        mode=mode.value,
        group_count=len(phase.test_case_groups),
        strategy=phase.strategy.mode,
        maximum=phase.strategy.maximum,
    )
    if phase.strategy.mode == "serial":
        executed_groups = await _execute_phase_groups_serial(
            scenario_name=scenario_name,
            phase=phase,
            mode=mode,
            testbed=testbed,
            test_plan=test_plan,
            planned_executions=planned_executions,
            broker=broker,
            parameters_dir=parameters_dir,
            learning_execution_cache=learning_execution_cache,
            output=output,
        )
    else:
        executed_groups = await _execute_phase_groups_parallel(
            scenario_name=scenario_name,
            phase=phase,
            mode=mode,
            testbed=testbed,
            test_plan=test_plan,
            planned_executions=planned_executions,
            broker=broker,
            parameters_dir=parameters_dir,
            learning_execution_cache=learning_execution_cache,
            output=output,
        )

    phase_status = _derive_phase_status(executed_groups)
    return ExecutedPhase(
        identifier=phase.identifier,
        status=phase_status.value,
        name=phase.name,
        test_case_groups=executed_groups,
    )


async def _execute_phase_groups_serial(
    *,
    scenario_name: str,
    phase: Phase,
    mode: ExecutionMode,
    testbed: Testbed,
    test_plan: TestPlan,
    planned_executions: dict[str, PlannedExecution],
    broker: RuntimeBroker,
    parameters_dir: Path,
    learning_execution_cache: dict[str, asyncio.Task[ExecutedTestCase]] | None,
    output: Output | None,
) -> list[ExecutedTestCaseGroup]:
    """Execute test case groups in phase order, one at a time."""
    executed_groups: list[ExecutedTestCaseGroup] = []
    for group_name in phase.test_case_groups:
        executed_groups.append(
            await _execute_group(
                scenario_name=scenario_name,
                phase=phase,
                group_name=group_name,
                mode=mode,
                testbed=testbed,
                test_plan=test_plan,
                planned_executions=planned_executions,
                broker=broker,
                parameters_dir=parameters_dir,
                learning_execution_cache=learning_execution_cache,
                output=output,
            )
        )
    return executed_groups


async def _execute_phase_groups_parallel(
    *,
    scenario_name: str,
    phase: Phase,
    mode: ExecutionMode,
    testbed: Testbed,
    test_plan: TestPlan,
    planned_executions: dict[str, PlannedExecution],
    broker: RuntimeBroker,
    parameters_dir: Path,
    learning_execution_cache: dict[str, asyncio.Task[ExecutedTestCase]] | None,
    output: Output | None,
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
                    scenario_name=scenario_name,
                    phase=phase,
                    group_name=group_name,
                    mode=mode,
                    testbed=testbed,
                    test_plan=test_plan,
                    planned_executions=planned_executions,
                    broker=broker,
                    parameters_dir=parameters_dir,
                    learning_execution_cache=learning_execution_cache,
                    output=output,
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
    scenario_name: str,
    phase: Phase,
    group_name: str,
    mode: ExecutionMode,
    testbed: Testbed,
    test_plan: TestPlan,
    planned_executions: dict[str, PlannedExecution],
    broker: RuntimeBroker,
    parameters_dir: Path,
    learning_execution_cache: dict[str, asyncio.Task[ExecutedTestCase]] | None,
    output: Output | None,
) -> tuple[int, ExecutedTestCaseGroup]:
    """Execute one group with optional phase-level concurrency limiting."""
    if semaphore is None:
        return (
            index,
            await _execute_group(
                scenario_name=scenario_name,
                phase=phase,
                group_name=group_name,
                mode=mode,
                testbed=testbed,
                test_plan=test_plan,
                planned_executions=planned_executions,
                broker=broker,
                parameters_dir=parameters_dir,
                learning_execution_cache=learning_execution_cache,
                output=output,
            ),
        )

    async with semaphore:
        return (
            index,
            await _execute_group(
                scenario_name=scenario_name,
                phase=phase,
                group_name=group_name,
                mode=mode,
                testbed=testbed,
                test_plan=test_plan,
                planned_executions=planned_executions,
                broker=broker,
                parameters_dir=parameters_dir,
                learning_execution_cache=learning_execution_cache,
                output=output,
            ),
        )


async def _execute_group(
    *,
    scenario_name: str,
    phase: Phase,
    group_name: str,
    mode: ExecutionMode,
    testbed: Testbed,
    test_plan: TestPlan,
    planned_executions: dict[str, PlannedExecution],
    broker: RuntimeBroker,
    parameters_dir: Path,
    learning_execution_cache: dict[str, asyncio.Task[ExecutedTestCase]] | None,
    output: Output | None,
) -> ExecutedTestCaseGroup:
    """Execute one group using its configured strategy."""
    group = test_plan.test_case_groups[group_name]
    log_debug(
        output,
        "Group execution starting",
        phase=phase.identifier,
        group=group.identifier,
        test_count=len(group.tests),
        strategy=group.strategy.mode,
        maximum=group.strategy.maximum,
    )

    if group.strategy.mode == "serial":
        executed_tests = await _execute_group_tests_serial(
            scenario_name=scenario_name,
            phase=phase,
            group=group,
            mode=mode,
            testbed=testbed,
            test_plan=test_plan,
            planned_executions=planned_executions,
            broker=broker,
            parameters_dir=parameters_dir,
            learning_execution_cache=learning_execution_cache,
            output=output,
        )
    else:
        executed_tests = await _execute_group_tests_parallel(
            scenario_name=scenario_name,
            phase=phase,
            group=group,
            mode=mode,
            testbed=testbed,
            test_plan=test_plan,
            planned_executions=planned_executions,
            broker=broker,
            parameters_dir=parameters_dir,
            learning_execution_cache=learning_execution_cache,
            output=output,
        )

    group_status = _derive_group_status(executed_tests)
    log_debug(
        output,
        "Group execution finished",
        phase=phase.identifier,
        group=group.identifier,
        status=group_status.value,
    )
    return ExecutedTestCaseGroup(
        identifier=group.identifier,
        status=group_status.value,
        name=group.name,
        test_cases=executed_tests,
    )


async def _execute_group_tests_serial(
    *,
    scenario_name: str,
    phase: Phase,
    group: TestCaseGroup,
    mode: ExecutionMode,
    testbed: Testbed,
    test_plan: TestPlan,
    planned_executions: dict[str, PlannedExecution],
    broker: RuntimeBroker,
    parameters_dir: Path,
    learning_execution_cache: dict[str, asyncio.Task[ExecutedTestCase]] | None,
    output: Output | None,
) -> list[ExecutedTestCase]:
    """Execute tests in group order, one at a time."""
    executed_tests: list[ExecutedTestCase] = []
    for test_id in group.tests:
        test_case_definition = test_plan.test_cases[test_id]
        executed_tests.append(
            await _execute_test_case(
                scenario_name=scenario_name,
                phase=phase,
                group=group,
                definition=test_case_definition,
                planned=planned_executions[test_case_definition.test_id],
                mode=mode,
                testbed=testbed,
                broker=broker,
                parameters_dir=parameters_dir,
                learning_execution_cache=learning_execution_cache,
                output=output,
            )
        )
    return executed_tests


async def _execute_group_tests_parallel(
    *,
    scenario_name: str,
    phase: Phase,
    group: TestCaseGroup,
    mode: ExecutionMode,
    testbed: Testbed,
    test_plan: TestPlan,
    planned_executions: dict[str, PlannedExecution],
    broker: RuntimeBroker,
    parameters_dir: Path,
    learning_execution_cache: dict[str, asyncio.Task[ExecutedTestCase]] | None,
    output: Output | None,
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
                    scenario_name=scenario_name,
                    phase=phase,
                    group=group,
                    definition=test_case_definition,
                    planned=planned_executions[test_case_definition.test_id],
                    mode=mode,
                    testbed=testbed,
                    broker=broker,
                    parameters_dir=parameters_dir,
                    learning_execution_cache=learning_execution_cache,
                    output=output,
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
    scenario_name: str,
    phase: Phase,
    group: TestCaseGroup,
    definition: TestCaseDefinition,
    planned: PlannedExecution,
    mode: ExecutionMode,
    testbed: Testbed,
    broker: RuntimeBroker,
    parameters_dir: Path,
    learning_execution_cache: dict[str, asyncio.Task[ExecutedTestCase]] | None,
    output: Output | None,
) -> tuple[int, ExecutedTestCase]:
    """Execute one test case with optional group-level concurrency limiting."""
    if semaphore is None:
        return (
            index,
            await _execute_test_case(
                scenario_name=scenario_name,
                phase=phase,
                group=group,
                definition=definition,
                planned=planned,
                mode=mode,
                testbed=testbed,
                broker=broker,
                parameters_dir=parameters_dir,
                learning_execution_cache=learning_execution_cache,
                output=output,
            ),
        )

    async with semaphore:
        return (
            index,
            await _execute_test_case(
                scenario_name=scenario_name,
                phase=phase,
                group=group,
                definition=definition,
                planned=planned,
                mode=mode,
                testbed=testbed,
                broker=broker,
                parameters_dir=parameters_dir,
                learning_execution_cache=learning_execution_cache,
                output=output,
            ),
        )


def _build_parallel_semaphore(maximum: int | None) -> asyncio.Semaphore | None:
    """Build optional concurrency semaphore from strategy maximum."""
    if maximum is None:
        return None
    return asyncio.Semaphore(maximum)


def _build_blocked_phase(
    *,
    scenario_name: str,
    phase: Phase,
    test_plan: TestPlan,
    reason: str,
) -> ExecutedPhase:
    """Build blocked phase output when a scenario cannot progress."""
    blocked_groups: list[ExecutedTestCaseGroup] = []
    for group_name in phase.test_case_groups:
        group = test_plan.test_case_groups[group_name]
        blocked_tests = [
            ExecutedTestCase(
                scenario=scenario_name,
                phase=phase.identifier,
                group=group.identifier,
                test_id=test_id,
                title=test_plan.test_cases[test_id].title,
                status=ResultStatus.BLOCKED.value,
                error=reason,
            )
            for test_id in group.tests
        ]
        blocked_groups.append(
            ExecutedTestCaseGroup(
                identifier=group.identifier,
                status=ResultStatus.BLOCKED.value,
                name=group.name,
                test_cases=blocked_tests,
            )
        )

    return ExecutedPhase(
        identifier=phase.identifier,
        status=ResultStatus.BLOCKED.value,
        name=phase.name,
        test_case_groups=blocked_groups,
    )


def _plan_executions(
    *,
    mode: ExecutionMode,
    test_plan: TestPlan,
    project_root: Path,
    output: Output | None,
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
            skip_reason: str | None = None
            if mode == ExecutionMode.LEARNING and not issubclass(
                test_case_class,
                LearningTestCase,
            ):
                skip_reason = "Learning mode requires tests to inherit LearningTestCase"
            planned[test_case.test_id] = PlannedExecution(
                test_case_class=test_case_class,
                required_brokers=required_brokers,
                planning_error=None,
                planning_error_traceback=None,
                skip_reason=skip_reason,
            )
        except (JobLoadError, RuntimeBrokerError) as error:
            log_warning(
                output,
                "Planning failed for test case",
                test_id=test_case.test_id,
                error=error,
            )
            planned[test_case.test_id] = PlannedExecution(
                test_case_class=None,
                required_brokers={BrokerType.SSH},
                planning_error=str(error),
                planning_error_traceback=traceback.format_exc(),
                skip_reason=None,
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
        if execution.planning_error is None and execution.skip_reason is None:
            required.update(execution.required_brokers)
    if not required:
        return {BrokerType.SSH}
    return required


async def _execute_test_case(
    *,
    scenario_name: str,
    phase: Phase,
    group: TestCaseGroup,
    definition: TestCaseDefinition,
    planned: PlannedExecution,
    mode: ExecutionMode,
    testbed: Testbed,
    broker: RuntimeBroker,
    parameters_dir: Path,
    learning_execution_cache: dict[str, asyncio.Task[ExecutedTestCase]] | None,
    output: Output | None,
) -> ExecutedTestCase:
    if mode != ExecutionMode.LEARNING or learning_execution_cache is None:
        return await _execute_test_case_once(
            scenario_name=scenario_name,
            phase=phase,
            group=group,
            definition=definition,
            planned=planned,
            mode=mode,
            testbed=testbed,
            broker=broker,
            parameters_dir=parameters_dir,
            output=output,
        )

    cached_execution = learning_execution_cache.get(definition.test_id)
    if cached_execution is None:
        cached_execution = asyncio.create_task(
            _execute_test_case_once(
                scenario_name=scenario_name,
                phase=phase,
                group=group,
                definition=definition,
                planned=planned,
                mode=mode,
                testbed=testbed,
                broker=broker,
                parameters_dir=parameters_dir,
                output=output,
            )
        )
        learning_execution_cache[definition.test_id] = cached_execution
    else:
        _emit_status(
            output,
            (
                "Skipping test: "
                f"{definition.test_id} ({definition.title}) "
                "already learned earlier in this run"
            ),
        )
        log_info(
            output,
            "Reusing learned test execution",
            test_id=definition.test_id,
            scenario=scenario_name,
            phase=phase.identifier,
            group=group.identifier,
        )

    executed_test_case = await cached_execution
    return _clone_executed_test_case_for_location(
        executed_test_case,
        scenario_name=scenario_name,
        phase_name=phase.identifier,
        group_name=group.identifier,
    )


async def _execute_test_case_once(
    *,
    scenario_name: str,
    phase: Phase,
    group: TestCaseGroup,
    definition: TestCaseDefinition,
    planned: PlannedExecution,
    mode: ExecutionMode,
    testbed: Testbed,
    broker: RuntimeBroker,
    parameters_dir: Path,
    output: Output | None,
) -> ExecutedTestCase:
    _emit_status(output, f"Starting test: {definition.test_id} ({definition.title})")
    log_debug(
        output,
        "Test execution starting",
        scenario=scenario_name,
        phase=phase.identifier,
        group=group.identifier,
        test_id=definition.test_id,
        mode=mode.value,
    )
    targets, target_error = _resolve_targets(
        testbed=testbed,
        phase=phase,
        group=group,
        test_case=definition,
    )
    if target_error is not None:
        log_warning(
            output,
            "Test target resolution failed",
            scenario=scenario_name,
            phase=phase.identifier,
            group=group.identifier,
            test_id=definition.test_id,
            error=target_error,
        )
        _emit_test_result(
            output,
            definition,
            status=ResultStatus.ERRORED.value,
            detail=target_error,
        )
        return _errored_test_case(
            scenario_name=scenario_name,
            phase_name=phase.identifier,
            group_name=group.identifier,
            definition=definition,
            error=target_error,
            error_code=ErrorCode.VALIDATION_ERROR,
        )
    if not targets:
        log_info(
            output,
            "Test skipped due to empty target set",
            scenario=scenario_name,
            phase=phase.identifier,
            group=group.identifier,
            test_id=definition.test_id,
        )
        _emit_test_result(
            output,
            definition,
            status=ResultStatus.SKIPPED.value,
            detail="No devices matched target selectors",
        )
        return _skipped_test_case(
            scenario_name=scenario_name,
            phase_name=phase.identifier,
            group_name=group.identifier,
            definition=definition,
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
        output=output,
        parameters=ParameterManager(
            parameters_dir=parameters_dir,
            test_id=definition.test_id,
        ),
        results=result_collector,
    )

    if planned.planning_error is not None:
        log_warning(
            output,
            "Test skipped due to planning error",
            test_id=definition.test_id,
            error=planned.planning_error,
        )
        _emit_test_result(
            output,
            definition,
            status=ResultStatus.ERRORED.value,
            detail=planned.planning_error,
        )
        return _errored_test_case(
            scenario_name=scenario_name,
            phase_name=phase.identifier,
            group_name=group.identifier,
            definition=definition,
            error=planned.planning_error,
            error_code=ErrorCode.PLANNING_ERROR,
            error_traceback=planned.planning_error_traceback,
        )

    if planned.skip_reason is not None:
        _emit_test_result(
            output,
            definition,
            status=ResultStatus.SKIPPED.value,
            detail=planned.skip_reason,
        )
        return _skipped_test_case(
            scenario_name=scenario_name,
            phase_name=phase.identifier,
            group_name=group.identifier,
            definition=definition,
            reason=planned.skip_reason,
        )
    if planned.test_case_class is None:
        log_warning(
            output,
            "Planned test class missing",
            test_id=definition.test_id,
        )
        _emit_test_result(
            output,
            definition,
            status=ResultStatus.ERRORED.value,
            detail="Missing planned test case class",
        )
        return _errored_test_case(
            scenario_name=scenario_name,
            phase_name=phase.identifier,
            group_name=group.identifier,
            definition=definition,
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
        log_warning(
            output,
            "Test execution raised exception",
            test_id=definition.test_id,
            error=error,
        )
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
        log_warning(
            output,
            "Test finished with error",
            test_id=definition.test_id,
            error=test_error,
        )
        _emit_test_result(
            output,
            definition,
            status=ResultStatus.ERRORED.value,
            detail=test_error,
        )
        return _errored_test_case(
            scenario_name=scenario_name,
            phase_name=phase.identifier,
            group_name=group.identifier,
            definition=definition,
            checks=result_collector.checks,
            error=test_error,
            error_code=ErrorCode.EXECUTION_ERROR,
            error_traceback=test_error_traceback,
        )

    status = result_collector.derive_status().value
    log_debug(
        output,
        "Test execution finished",
        test_id=definition.test_id,
        status=status,
        checks=len(result_collector.checks),
        command_executions=len(result_collector.command_executions),
    )
    _emit_test_result(output, definition, status=status)
    return ExecutedTestCase(
        scenario=scenario_name,
        phase=phase.identifier,
        group=group.identifier,
        test_id=definition.test_id,
        title=definition.title,
        status=status,
        metadata_sections=result_collector.metadata_sections,
        checks=result_collector.checks,
        command_executions=result_collector.command_executions,
    )


def _errored_test_case(
    scenario_name: str,
    phase_name: str,
    group_name: str,
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
        scenario=scenario_name,
        phase=phase_name,
        group=group_name,
        test_id=definition.test_id,
        title=definition.title,
        status=ResultStatus.ERRORED.value,
        metadata_sections=[],
        checks=normalized_checks,
        command_executions=[],
        error=error,
        error_code=error_code.value,
        error_traceback=error_traceback,
    )


def _clone_executed_test_case_for_location(
    test_case: ExecutedTestCase,
    *,
    scenario_name: str,
    phase_name: str,
    group_name: str,
) -> ExecutedTestCase:
    """Copy an executed test case while updating its execution location."""
    cloned = copy.deepcopy(test_case)
    cloned.scenario = scenario_name
    cloned.phase = phase_name
    cloned.group = group_name
    return cloned


def _skipped_test_case(
    scenario_name: str,
    phase_name: str,
    group_name: str,
    definition: TestCaseDefinition,
    *,
    reason: str,
) -> ExecutedTestCase:
    """Build a standardized skipped test case output."""
    return ExecutedTestCase(
        scenario=scenario_name,
        phase=phase_name,
        group=group_name,
        test_id=definition.test_id,
        title=definition.title,
        status=ResultStatus.SKIPPED.value,
        metadata_sections=[],
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
    output: Output | None,
) -> None:
    """Connect all planned test targets once before phase execution."""
    targets_by_brokers = _collect_prime_targets(
        testbed=testbed,
        test_plan=test_plan,
        planned_executions=planned_executions,
    )

    try:
        log_debug(
            output,
            "Runtime connection priming starting",
            broker_sets=len(targets_by_brokers),
        )
        for required_brokers, target_lookup in targets_by_brokers.items():
            method_names = sorted(broker_type.value for broker_type in required_brokers)
            target_names = sorted(target_lookup)
            broker_name = broker.__class__.__name__
            set_started = perf_counter()
            _emit_status(
                output,
                (
                    "Priming connection set: "
                    f"broker={broker_name} "
                    f"methods={','.join(method_names)} "
                    f"targets={','.join(target_names)}"
                ),
            )
            log_info(
                output,
                "Priming connection set",
                broker=broker_name,
                methods=method_names,
                targets=target_names,
                target_count=len(target_names),
            )
            log_debug(
                output,
                "Priming broker connection set",
                required_brokers=method_names,
                targets=target_names,
            )
            await _connect_targets_or_raise(
                broker,
                list(target_lookup.values()),
                set(required_brokers),
            )
            elapsed = _format_elapsed(set_started)
            _emit_status(
                output,
                (
                    "Primed connection set: "
                    f"broker={broker_name} "
                    f"methods={','.join(method_names)} "
                    f"targets={','.join(target_names)} "
                    f"duration={elapsed}"
                ),
            )
            log_info(
                output,
                "Primed connection set",
                broker=broker_name,
                methods=method_names,
                targets=target_names,
                target_count=len(target_names),
                duration=elapsed,
            )
        log_debug(output, "Runtime connection priming completed")
    except RuntimeBrokerError as error:
        raise RunExecutionError(
            str(error),
            code=ErrorCode.BROKER_ERROR,
            traceback_text=traceback.format_exc(),
        ) from error


def _collect_prime_targets(
    *,
    testbed: Testbed,
    test_plan: TestPlan,
    planned_executions: dict[str, PlannedExecution],
) -> dict[frozenset[BrokerType], dict[str, Device]]:
    """Collect per-broker target sets that require run-start connections."""
    targets_by_brokers: dict[frozenset[BrokerType], dict[str, Device]] = {}

    for scenario in test_plan.scenarios.values():
        for phase in scenario.phases.values():
            for group_name in phase.test_case_groups:
                group = test_plan.test_case_groups[group_name]
                for test_id in group.tests:
                    planned = planned_executions[test_id]
                    if _skip_planned_execution(planned):
                        continue

                    definition = test_plan.test_cases[test_id]
                    targets = _resolve_prime_targets(
                        testbed=testbed,
                        phase=phase,
                        group=group,
                        definition=definition,
                    )
                    if not targets:
                        continue

                    _add_targets_for_brokers(
                        targets_by_brokers=targets_by_brokers,
                        broker_key=frozenset(planned.required_brokers),
                        targets=targets,
                    )

    return targets_by_brokers


def _skip_planned_execution(planned: PlannedExecution) -> bool:
    """Return True when a planned execution should not be run."""
    return planned.planning_error is not None or planned.skip_reason is not None


def _resolve_prime_targets(
    *,
    testbed: Testbed,
    phase: Phase,
    group: TestCaseGroup,
    definition: TestCaseDefinition,
) -> list[Device]:
    """Resolve targets for run-start connection priming."""
    targets, target_error = _resolve_targets(
        testbed=testbed,
        phase=phase,
        group=group,
        test_case=definition,
    )
    if target_error is not None:
        return []
    return targets


def _add_targets_for_brokers(
    *,
    targets_by_brokers: dict[frozenset[BrokerType], dict[str, Device]],
    broker_key: frozenset[BrokerType],
    targets: list[Device],
) -> None:
    """Add resolved targets into per-broker-key lookup map."""
    grouped_targets = targets_by_brokers.setdefault(broker_key, {})
    for target in targets:
        grouped_targets[target.name] = target


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


def _emit_status(output: Output | None, message: str) -> None:
    """Print user-facing run status messages when output is available."""
    if output is None:
        return
    output.status(message)


def _emit_execution_order(output: Output | None, test_plan: TestPlan) -> None:
    """Emit scenario/phase execution order to stdout."""
    if not test_plan.scenarios:
        _emit_status(output, "Execution order: (none)")
        return

    _emit_status(output, "Execution order:")
    for scenario in test_plan.scenarios.values():
        _emit_status(output, f"  Scenario: {scenario.identifier}")
        if not scenario.phases:
            _emit_status(output, "    Phases: (none)")
            continue
        for phase_name in scenario.phases:
            _emit_status(output, f"    Phase: {phase_name}")


def _emit_phase_rollup(
    output: Output | None,
    scenario_name: str,
    phase: ExecutedPhase,
) -> None:
    """Emit per-phase status counts after completion."""
    statuses = _collect_phase_statuses(phase)
    counts = Counter(statuses)
    _emit_status(
        output,
        "Phase complete: "
        f"{scenario_name}."
        f"{phase.identifier} "
        f"status={phase.status} "
        f"total={len(statuses)} "
        f"passed={counts[ResultStatus.PASSED.value]} "
        f"failed={counts[ResultStatus.FAILED.value]} "
        f"errored={counts[ResultStatus.ERRORED.value]} "
        f"not_applicable={counts[ResultStatus.NOT_APPLICABLE.value]} "
        f"skipped={counts[ResultStatus.SKIPPED.value]} "
        f"blocked={counts[ResultStatus.BLOCKED.value]}",
    )


def _collect_phase_statuses(phase: ExecutedPhase) -> list[str]:
    """Collect statuses for all tests within one executed phase."""
    statuses: list[str] = []
    for group in phase.test_case_groups:
        for test_case in group.test_cases:
            statuses.append(test_case.status)
    return statuses


def _emit_test_result(
    output: Output | None,
    definition: TestCaseDefinition,
    *,
    status: str,
    detail: str | None = None,
) -> None:
    """Emit one-line test completion status to stdout."""
    suffix = f" ({detail})" if detail else ""
    _emit_status(
        output,
        f"Finished test: {definition.test_id} status={status}{suffix}",
    )


def _format_elapsed(started_at: float) -> str:
    """Format elapsed seconds from a perf_counter start timestamp."""
    return f"{perf_counter() - started_at:.3f}s"


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
        (f"Phase '{phase.identifier}'", phase.target),
        (f"Test case group '{group.identifier}'", group.target),
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


def _build_summary(scenarios: list[ExecutedScenario]) -> RunSummary:
    statuses = _collect_test_case_statuses(scenarios)
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


def _collect_test_case_statuses(scenarios: list[ExecutedScenario]) -> list[str]:
    """Collect all test case statuses from executed scenario output."""
    statuses: list[str] = []
    for scenario in scenarios:
        for phase in scenario.phases:
            for group in phase.test_case_groups:
                for test_case in group.test_cases:
                    statuses.append(test_case.status)
    return statuses


def _derive_scenario_status(phases: list[ExecutedPhase]) -> ResultStatus:
    """Derive one scenario status from its executed phases."""
    return _derive_status_from_values([phase.status for phase in phases])


def _should_halt_scenario_after_phase(phase: ExecutedPhase) -> bool:
    """Return True when a scenario should stop after this phase."""
    return phase.status != ResultStatus.PASSED.value

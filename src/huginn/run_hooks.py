"""Build hook event payloads at each lifecycle point of a test plan run.

The runner calls one ``RunHooks`` method per lifecycle point. Each method
builds the event's context from plain data (IDs, statuses, and lists and dicts
copied from runner state), so a hook cannot change the run by mutating its
context. Nothing is built when no hook subscribes to the event.

``RunHooks`` also holds the run's abort state. The first ``HookAbort`` a hook
returns is recorded, and the runner checks ``RunHooks.aborted`` before it
starts each scenario, phase, group and test case. The runner is one asyncio
event loop, and the check and the record never await, so concurrent parallel
siblings see one consistent state: an item either started before the abort
and finishes, or it sees the abort and does not start.
"""

import copy
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import asdict
from pathlib import Path

from huginn.enums import ExecutionMode, ResultStatus
from huginn.hooks import HookDispatcher, HookEvent, HookOutcome
from huginn.logging_helpers import log_warning
from huginn.models import (
    ExecutedPhase,
    ExecutedTestCase,
    ExecutedTestCaseGroup,
    Phase,
    RunAbort,
    RunResult,
    Scenario,
    TestCaseDefinition,
    TestCaseGroup,
    TestPlan,
)
from huginn.output import Output

# Test case statuses that dispatch ``on_failure`` after ``test_case_end``.
_FAILURE_STATUSES = frozenset(
    {ResultStatus.FAILED.value, ResultStatus.LOST_APPLICABILITY.value}
)

Payload = Callable[[], dict[str, object]]


class RunHooks:
    """Dispatch hook events for one run, with a stable payload per event."""

    def __init__(
        self,
        dispatcher: HookDispatcher,
        *,
        mode: ExecutionMode,
        output: Output | None,
    ) -> None:
        """Bind the dispatcher to the run's mode and output."""
        self._dispatcher = dispatcher
        self._mode = mode.value
        self._output = output
        self._abort: RunAbort | None = None

    @property
    def aborted(self) -> RunAbort | None:
        """Return the first abort a hook requested in this run, or None."""
        return self._abort

    async def run_start(self, *, plan_path: Path, test_plan: TestPlan) -> None:
        """Dispatch ``run_start`` once the plan is loaded, filtered and planned."""
        await self._notify(
            HookEvent.RUN_START,
            lambda: {
                "plan": str(plan_path),
                "scenarios": list(test_plan.scenarios),
                "test_ids": list(test_plan.test_cases),
            },
        )

    async def run_end(
        self,
        *,
        run_dir: Path,
        result: RunResult | None = None,
        error: str | None = None,
    ) -> None:
        """Dispatch ``run_end`` after results are written, or when the run aborts."""
        await self._notify(
            HookEvent.RUN_END,
            lambda: {
                "status": (
                    result.summary.status
                    if result is not None
                    else ResultStatus.ERRORED.value
                ),
                "summary": asdict(result.summary) if result is not None else None,
                "elapsed_seconds": (
                    result.elapsed_seconds if result is not None else None
                ),
                "run_dir": str(run_dir),
                "error": error,
                "aborted": asdict(self._abort) if self._abort is not None else None,
            },
        )

    async def scenario_start(self, scenario: Scenario) -> None:
        """Dispatch ``scenario_start`` before a scenario's first phase."""
        await self._notify(
            HookEvent.SCENARIO_START,
            lambda: {
                "scenario": scenario.identifier,
                "name": scenario.name,
                "description": scenario.description,
                "phases": list(scenario.phases),
            },
        )

    async def scenario_end(self, scenario_id: str, status: str) -> None:
        """Dispatch ``scenario_end`` after a scenario's last phase."""
        await self._notify(
            HookEvent.SCENARIO_END,
            lambda: {"scenario": scenario_id, "status": status},
        )

    async def phase_start(self, scenario_id: str, phase: Phase) -> list[str]:
        """Dispatch ``phase_start`` and return the hooks' skip reasons."""
        return await self._influence(
            HookEvent.PHASE_START,
            lambda: {
                "scenario": scenario_id,
                "phase": phase.identifier,
                "name": phase.name,
                "description": phase.description,
                "depends_on": list(phase.depends_on),
                "groups": list(phase.test_case_groups),
            },
        )

    async def phase_end(self, scenario_id: str, phase: ExecutedPhase) -> None:
        """Dispatch ``phase_end`` with the phase's status and status counts."""
        await self._notify(
            HookEvent.PHASE_END,
            lambda: {
                "scenario": scenario_id,
                "phase": phase.identifier,
                "status": phase.status,
                "counts": _status_counts(
                    test_case
                    for group in phase.test_case_groups
                    for test_case in group.test_cases
                ),
            },
        )

    async def group_start(
        self, scenario_id: str, phase_id: str, group: TestCaseGroup
    ) -> list[str]:
        """Dispatch ``group_start`` and return the hooks' skip reasons."""
        return await self._influence(
            HookEvent.GROUP_START,
            lambda: {
                "scenario": scenario_id,
                "phase": phase_id,
                "group": group.identifier,
                "name": group.name,
                "description": group.description,
                "test_ids": list(group.tests),
            },
        )

    async def group_end(
        self, scenario_id: str, phase_id: str, group: ExecutedTestCaseGroup
    ) -> None:
        """Dispatch ``group_end`` with the group's status and status counts."""
        await self._notify(
            HookEvent.GROUP_END,
            lambda: {
                "scenario": scenario_id,
                "phase": phase_id,
                "group": group.identifier,
                "status": group.status,
                "counts": _status_counts(group.test_cases),
            },
        )

    async def test_case_start(
        self,
        *,
        scenario_id: str,
        phase_id: str,
        group_id: str,
        definition: TestCaseDefinition,
        target_names: Callable[[], list[str]],
    ) -> list[str]:
        """Dispatch ``test_case_start`` and return the hooks' skip reasons."""
        return await self._influence(
            HookEvent.TEST_CASE_START,
            lambda: {
                "scenario": scenario_id,
                "phase": phase_id,
                "group": group_id,
                "test_id": definition.test_id,
                "title": definition.title,
                "job": definition.job,
                "tags": list(definition.tags),
                "metadata": copy.deepcopy(definition.metadata),
                "targets": target_names(),
            },
        )

    async def test_case_end(self, test_case: ExecutedTestCase) -> None:
        """Dispatch ``test_case_end``, then ``on_failure`` or ``on_error``."""
        await self._notify(
            HookEvent.TEST_CASE_END, lambda: _test_case_result(test_case)
        )
        if test_case.status in _FAILURE_STATUSES:
            await self._notify(
                HookEvent.ON_FAILURE, lambda: _test_case_result(test_case)
            )
        elif test_case.status == ResultStatus.ERRORED.value:
            await self._notify(HookEvent.ON_ERROR, lambda: _test_case_result(test_case))

    async def _notify(self, event: HookEvent, payload: Payload) -> None:
        """Dispatch an event that cannot skip, recording an abort."""
        await self._influence(event, payload)

    async def _influence(self, event: HookEvent, payload: Payload) -> list[str]:
        """Dispatch an event, building its payload only when a hook listens.

        Returns the hooks' skip reasons. A requested abort is recorded in
        ``aborted`` instead; callers check it before they start an item.
        """
        if not self._dispatcher.listens(event):
            return []
        outcome = await self._dispatcher.dispatch_outcome(
            event,
            **payload(),
            mode=self._mode,
            output=self._output,
        )
        self._record_abort(outcome)
        return outcome.skip_reasons

    def _record_abort(self, outcome: HookOutcome) -> None:
        """Keep the first abort of the run and report it."""
        if outcome.abort is None or self._abort is not None:
            return
        self._abort = outcome.abort
        log_warning(
            self._output,
            "Run aborted by hook",
            hook=outcome.abort.hook,
            event=outcome.abort.event,
            reason=outcome.abort.reason,
        )
        if self._output is not None:
            self._output.warning(
                f"{outcome.abort.message} during '{outcome.abort.event}'; "
                "finishing running test cases and starting nothing new"
            )


def _status_counts(test_cases: Iterable[ExecutedTestCase]) -> dict[str, int]:
    """Count test cases by status."""
    return dict(Counter(test_case.status for test_case in test_cases))


def _test_case_result(test_case: ExecutedTestCase) -> dict[str, object]:
    """Return the payload of ``test_case_end``, ``on_failure`` and ``on_error``."""
    return {
        "scenario": test_case.scenario,
        "phase": test_case.phase,
        "group": test_case.group,
        "test_id": test_case.test_id,
        "title": test_case.title,
        "status": test_case.status,
        "error": test_case.error,
        "error_code": test_case.error_code,
        "skip_kind": test_case.skip_kind,
        "block_kind": test_case.block_kind,
        "checks": [
            {"status": check.status, "message": check.message}
            for check in test_case.checks
        ],
    }

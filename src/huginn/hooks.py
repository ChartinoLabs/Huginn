"""Lifecycle hook protocol and event dispatch for Huginn."""

import logging
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


class HookEvent(StrEnum):
    """Lifecycle events that hook plugins can subscribe to."""

    RUN_START = "run_start"
    RUN_END = "run_end"
    SCENARIO_START = "scenario_start"
    SCENARIO_END = "scenario_end"
    PHASE_START = "phase_start"
    PHASE_END = "phase_end"
    GROUP_START = "group_start"
    GROUP_END = "group_end"
    TEST_CASE_START = "test_case_start"
    TEST_CASE_END = "test_case_end"
    ON_FAILURE = "on_failure"
    ON_ERROR = "on_error"


class HookSignal(StrEnum):
    """Signals a hook can return to influence execution."""

    CONTINUE = "continue"
    SKIP = "skip"


INFLUENCING_EVENTS: set[HookEvent] = {
    HookEvent.TEST_CASE_START,
    HookEvent.PHASE_START,
    HookEvent.GROUP_START,
}


@runtime_checkable
class HookPlugin(Protocol):
    """Protocol for lifecycle hook plugins."""

    @property
    def name(self) -> str:
        """Unique hook identifier."""
        ...

    def subscriptions(self) -> set[HookEvent]:
        """Return the set of events this hook listens to."""
        ...

    async def on_event(
        self,
        event: HookEvent,
        context: dict[str, Any],
    ) -> HookSignal | None:
        """Handle a lifecycle event.

        Args:
            event: The lifecycle event that occurred.
            context: Event-specific context data. Keys vary by event but
                always include 'output' (Output | None).

        Returns:
            For influencing events (PHASE_START, GROUP_START,
            TEST_CASE_START): return HookSignal.SKIP to skip the item,
            or HookSignal.CONTINUE / None to proceed normally.
            For all other events: return value is ignored.
        """
        ...


class HookDispatcher:
    """Invokes registered hook plugins for lifecycle events."""

    def __init__(self, hooks: list[HookPlugin]) -> None:
        """Initialize dispatcher with hook plugins grouped by subscription."""
        self._hooks_by_event: dict[HookEvent, list[HookPlugin]] = {}
        for hook in hooks:
            for event in hook.subscriptions():
                self._hooks_by_event.setdefault(event, []).append(hook)

    async def dispatch(self, event: HookEvent, **context: object) -> HookSignal:
        """Dispatch event to all subscribed hooks.

        Args:
            event: The lifecycle event to dispatch.
            **context: Event-specific context passed to each hook.

        Returns:
            HookSignal.SKIP if any hook requests a skip on an influencing
            event; HookSignal.CONTINUE otherwise.
        """
        hooks = self._hooks_by_event.get(event, [])
        signal = HookSignal.CONTINUE

        for hook in hooks:
            try:
                result = await hook.on_event(event, context)
                if (
                    event in INFLUENCING_EVENTS
                    and result == HookSignal.SKIP
                ):
                    signal = HookSignal.SKIP
            except Exception:
                logger.warning(
                    "Hook '%s' raised during '%s'; continuing execution",
                    hook.name,
                    event,
                    exc_info=True,
                )

        return signal

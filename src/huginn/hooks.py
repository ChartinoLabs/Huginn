"""Lifecycle hook protocol and event dispatch for Huginn."""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from huginn.enums import StrEnum

if TYPE_CHECKING:
    from huginn.output import Output

logger = logging.getLogger(__name__)

HOOK_ERROR_WARNING_CODE = "hook_error"


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


@dataclass(frozen=True)
class HookSkip:
    """Skip the item of an influencing event, recording ``reason``.

    Returning ``HookSkip("Change freeze")`` from ``on_event`` has the same
    effect as ``HookSignal.SKIP``, but the test cases are recorded as skipped
    with ``reason`` instead of the generic "Skipped by hook '<name>'".
    """

    reason: str


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
    ) -> HookSignal | HookSkip | None:
        """Handle a lifecycle event.

        Args:
            event: The lifecycle event that occurred.
            context: Event-specific context data. Keys vary by event but
                always include 'mode' (str) and 'output' (Output | None).

        Returns:
            For influencing events (PHASE_START, GROUP_START,
            TEST_CASE_START): return HookSignal.SKIP or HookSkip(reason) to
            skip the item, or HookSignal.CONTINUE / None to proceed normally.
            For all other events: return value is ignored.
        """
        ...


def skip_reason(hook: HookPlugin, result: object) -> str | None:
    """Return the skip reason a hook's result requests, or None to continue."""
    if isinstance(result, HookSkip):
        return result.reason or _generic_skip_reason(hook)
    if result == HookSignal.SKIP:
        return _generic_skip_reason(hook)
    return None


def _generic_skip_reason(hook: HookPlugin) -> str:
    """Return the reason recorded for a skip that gives none."""
    return f"Skipped by hook '{hook.name}'"


class HookDispatcher:
    """Invokes registered hook plugins for lifecycle events.

    Hooks subscribed to one event are called one at a time, in the order they
    were given. The dispatcher keeps no per-call state, so concurrent
    dispatches for parallel groups or test cases are safe.
    """

    def __init__(
        self,
        hooks: list[HookPlugin],
        output: "Output | None" = None,
    ) -> None:
        """Initialize dispatcher with hook plugins grouped by subscription.

        Args:
            hooks: The hook plugins to call.
            output: Where a warning about a hook that raised is printed, in
                addition to the ``huginn.hooks`` logger.
        """
        self._output = output
        self._hooks_by_event: dict[HookEvent, list[HookPlugin]] = {}
        for hook in hooks:
            for event in hook.subscriptions():
                self._hooks_by_event.setdefault(event, []).append(hook)

    def listens(self, event: HookEvent) -> bool:
        """Return True when at least one hook subscribes to ``event``."""
        return event in self._hooks_by_event

    async def dispatch(self, event: HookEvent, **context: object) -> HookSignal:
        """Dispatch event to all subscribed hooks.

        Args:
            event: The lifecycle event to dispatch.
            **context: Event-specific context passed to each hook.

        Returns:
            HookSignal.SKIP if any hook requests a skip on an influencing
            event; HookSignal.CONTINUE otherwise.
        """
        reasons = await self.dispatch_skip_reasons(event, **context)
        return HookSignal.SKIP if reasons else HookSignal.CONTINUE

    async def dispatch_skip_reasons(
        self, event: HookEvent, **context: object
    ) -> list[str]:
        """Dispatch event to all subscribed hooks and collect skip reasons.

        Every subscribed hook is called, even after one requests a skip. A
        hook that raises is reported as a warning and does not stop the others.

        Args:
            event: The lifecycle event to dispatch.
            **context: Event-specific context passed to each hook.

        Returns:
            One reason per hook that requested a skip, in hook order. Always
            empty for events that are not influencing events.
        """
        reasons: list[str] = []
        for hook in self._hooks_by_event.get(event, []):
            try:
                result = await hook.on_event(event, context)
            except Exception as error:  # noqa: BLE001
                self._warn_hook_error(hook, event, error)
                continue
            reason = skip_reason(hook, result)
            if event in INFLUENCING_EVENTS and reason is not None:
                reasons.append(reason)
        return reasons

    def _warn_hook_error(
        self, hook: HookPlugin, event: HookEvent, error: Exception
    ) -> None:
        """Report a hook that raised through the logger and the output."""
        logger.warning(
            "Hook '%s' raised during '%s'; continuing execution",
            hook.name,
            event,
            exc_info=True,
        )
        if self._output is not None:
            self._output.warning(
                f"WARNING [{HOOK_ERROR_WARNING_CODE}]: Hook '{hook.name}' raised "
                f"during '{event}': {error.__class__.__name__}: {error}; "
                "continuing execution"
            )

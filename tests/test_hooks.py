"""Unit tests for huginn.hooks module."""

import pytest

from huginn.hooks import (
    INFLUENCING_EVENTS,
    HookDispatcher,
    HookEvent,
    HookSignal,
)


class _ObservingHook:
    """Hook that records events it receives."""

    def __init__(self) -> None:
        self.received: list[tuple[HookEvent, dict]] = []

    @property
    def name(self) -> str:
        return "observer"

    def subscriptions(self) -> set[HookEvent]:
        return {HookEvent.RUN_START, HookEvent.RUN_END, HookEvent.TEST_CASE_START}

    async def on_event(self, event: HookEvent, context: dict) -> HookSignal | None:
        self.received.append((event, context))
        return None


class _SkipHook:
    """Hook that requests skipping on influencing events."""

    @property
    def name(self) -> str:
        return "skipper"

    def subscriptions(self) -> set[HookEvent]:
        return {HookEvent.TEST_CASE_START, HookEvent.PHASE_START}

    async def on_event(self, event: HookEvent, context: dict) -> HookSignal | None:
        return HookSignal.SKIP


class _ErrorHook:
    """Hook that always raises."""

    @property
    def name(self) -> str:
        return "broken"

    def subscriptions(self) -> set[HookEvent]:
        return {HookEvent.RUN_START, HookEvent.TEST_CASE_START}

    async def on_event(self, event: HookEvent, context: dict) -> HookSignal | None:
        raise RuntimeError("hook exploded")


@pytest.mark.asyncio
async def test_dispatcher_delivers_events_to_subscribed_hooks() -> None:
    """Hooks receive events they subscribe to with correct context."""
    hook = _ObservingHook()
    dispatcher = HookDispatcher(hooks=[hook])

    await dispatcher.dispatch(HookEvent.RUN_START, foo="bar")
    await dispatcher.dispatch(HookEvent.RUN_END, status="passed")

    assert len(hook.received) == 2
    assert hook.received[0] == (HookEvent.RUN_START, {"foo": "bar"})
    assert hook.received[1] == (HookEvent.RUN_END, {"status": "passed"})


@pytest.mark.asyncio
async def test_dispatcher_does_not_deliver_unsubscribed_events() -> None:
    """Hooks do not receive events they did not subscribe to."""
    hook = _ObservingHook()
    dispatcher = HookDispatcher(hooks=[hook])

    await dispatcher.dispatch(HookEvent.SCENARIO_START, name="s1")

    assert len(hook.received) == 0


@pytest.mark.asyncio
async def test_dispatcher_returns_skip_on_influencing_events() -> None:
    """Skip signal from a hook causes dispatcher to return SKIP."""
    dispatcher = HookDispatcher(hooks=[_SkipHook()])

    signal = await dispatcher.dispatch(HookEvent.TEST_CASE_START, test_id="1.0.0")

    assert signal == HookSignal.SKIP


@pytest.mark.asyncio
async def test_dispatcher_returns_continue_when_no_skip() -> None:
    """Default signal is CONTINUE when no hook requests skip."""
    hook = _ObservingHook()
    dispatcher = HookDispatcher(hooks=[hook])

    signal = await dispatcher.dispatch(HookEvent.TEST_CASE_START, test_id="1.0.0")

    assert signal == HookSignal.CONTINUE


@pytest.mark.asyncio
async def test_dispatcher_ignores_skip_on_non_influencing_events() -> None:
    """Skip signal is ignored for non-influencing events."""

    class _AlwaysSkip:
        @property
        def name(self) -> str:
            return "always-skip"

        def subscriptions(self) -> set[HookEvent]:
            return {HookEvent.RUN_START}

        async def on_event(self, event: HookEvent, context: dict) -> HookSignal | None:
            return HookSignal.SKIP

    dispatcher = HookDispatcher(hooks=[_AlwaysSkip()])
    signal = await dispatcher.dispatch(HookEvent.RUN_START)

    assert signal == HookSignal.CONTINUE


@pytest.mark.asyncio
async def test_dispatcher_isolates_hook_exceptions() -> None:
    """A broken hook does not prevent other hooks from running."""
    observer = _ObservingHook()
    dispatcher = HookDispatcher(hooks=[_ErrorHook(), observer])

    signal = await dispatcher.dispatch(HookEvent.RUN_START, key="val")

    assert signal == HookSignal.CONTINUE
    assert len(observer.received) == 1


@pytest.mark.asyncio
async def test_dispatcher_isolates_exceptions_on_influencing_events() -> None:
    """A broken hook on an influencing event does not block skip from others."""
    dispatcher = HookDispatcher(hooks=[_ErrorHook(), _SkipHook()])

    signal = await dispatcher.dispatch(HookEvent.TEST_CASE_START, test_id="1.0.0")

    assert signal == HookSignal.SKIP


@pytest.mark.asyncio
async def test_empty_dispatcher_returns_continue() -> None:
    """Dispatcher with no hooks returns CONTINUE."""
    dispatcher = HookDispatcher(hooks=[])

    signal = await dispatcher.dispatch(HookEvent.PHASE_START, phase="p1")

    assert signal == HookSignal.CONTINUE


def test_influencing_events_are_correct() -> None:
    """INFLUENCING_EVENTS contains the expected event set."""
    assert INFLUENCING_EVENTS == {
        HookEvent.TEST_CASE_START,
        HookEvent.PHASE_START,
        HookEvent.GROUP_START,
    }

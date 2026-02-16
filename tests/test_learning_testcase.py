"""Unit tests for LearningTestCase base class behavior."""

from dataclasses import dataclass, field
from typing import cast

import pytest

from huginn import Context, ExecutionMode, LearningTestCase, ResultStatus


@dataclass
class _FakeParameters:
    saved_payloads: list[object] = field(default_factory=list)
    loaded_payload: object = field(default_factory=lambda: {"expected": True})

    async def save(self, data: object) -> None:
        self.saved_payloads.append(data)

    async def load(self) -> object:
        return self.loaded_payload


@dataclass
class _FakeResults:
    entries: list[tuple[ResultStatus, str]] = field(default_factory=list)

    def add_result(self, status: ResultStatus, message: str) -> None:
        self.entries.append((status, message))


@dataclass
class _FakeContext:
    mode: ExecutionMode
    parameters: _FakeParameters = field(default_factory=_FakeParameters)
    results: _FakeResults = field(default_factory=_FakeResults)


class _ExampleLearningTest(LearningTestCase):
    gathered_state: object = {"current": True}
    compared: list[tuple[object, object]]

    def __init__(self) -> None:
        self.compared = []

    async def gather_state(self, context: Context) -> object:
        return self.gathered_state

    async def compare_state(
        self,
        *,
        expected: object,
        current: object,
        context: Context,
    ) -> None:
        self.compared.append((expected, current))


@pytest.mark.asyncio
async def test_learning_testcase_saves_state_in_learning_mode() -> None:
    """Learning mode saves gathered state and records success check."""
    test_case = _ExampleLearningTest()
    context = _FakeContext(mode=ExecutionMode.LEARNING)

    await test_case.test(cast(Context, context))

    assert context.parameters.saved_payloads == [{"current": True}]
    assert test_case.compared == []
    assert context.results.entries == [
        (ResultStatus.PASSED, "Learned parameters saved successfully")
    ]


@pytest.mark.asyncio
async def test_learning_testcase_compares_state_in_testing_mode() -> None:
    """Testing mode loads expected parameters and runs compare_state."""
    test_case = _ExampleLearningTest()
    context = _FakeContext(mode=ExecutionMode.TESTING)

    await test_case.test(cast(Context, context))

    assert context.parameters.saved_payloads == []
    assert test_case.compared == [({"expected": True}, {"current": True})]
    assert context.results.entries == []


@pytest.mark.asyncio
async def test_learning_testcase_default_setup_and_cleanup_are_noop() -> None:
    """Base class default setup and cleanup run without side effects."""
    test_case = _ExampleLearningTest()
    context = _FakeContext(mode=ExecutionMode.TESTING)

    await test_case.setup(cast(Context, context))
    await test_case.cleanup(cast(Context, context))

    assert context.results.entries == []

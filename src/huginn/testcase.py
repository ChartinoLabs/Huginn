"""Base test case definition for Huginn jobs."""

from abc import ABC, abstractmethod
from typing import Any

from huginn.context import Context
from huginn.enums import BrokerType, ExecutionMode, ResultStatus


class TestCase(ABC):
    """Abstract base class for Huginn test jobs."""

    required_brokers: set[BrokerType] = {BrokerType.SSH}

    @abstractmethod
    async def setup(self, context: Context) -> None:
        """Prepare state before test execution."""

    @abstractmethod
    async def test(self, context: Context) -> None:
        """Execute test logic and record check results."""

    @abstractmethod
    async def cleanup(self, context: Context) -> None:
        """Clean up test-specific state after execution."""


class LearningTestCase(TestCase, ABC):
    """Reusable base class for learning/testing state comparison patterns."""

    async def setup(self, context: Context) -> None:
        """Default no-op setup for learning/testing style tests."""
        return None

    async def test(self, context: Context) -> None:
        """Save state in learning mode or compare state in testing mode."""
        current_state = await self.gather_state(context)

        if context.mode == ExecutionMode.LEARNING:
            await context.parameters.save(current_state)
            context.results.add_result(
                ResultStatus.PASSED,
                "Learned parameters saved successfully",
            )
            return

        expected_state = await context.parameters.load()
        await self.compare_state(
            expected=expected_state,
            current=current_state,
            context=context,
        )

    async def cleanup(self, context: Context) -> None:
        """Default no-op cleanup for learning/testing style tests."""
        return None

    @abstractmethod
    async def gather_state(self, context: Context) -> Any:  # noqa: ANN401
        """Gather current state from targets for learning/testing flows."""

    @abstractmethod
    async def compare_state(
        self,
        *,
        expected: Any,  # noqa: ANN401
        current: Any,  # noqa: ANN401
        context: Context,
    ) -> None:
        """Compare expected and current state, recording test results."""

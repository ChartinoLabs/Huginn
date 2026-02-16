"""Base test case definition for Huginn jobs."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from huginn.context import Context
from huginn.enums import BrokerType, ExecutionMode, ResultStatus
from huginn.models import Device


@dataclass
class ApplicabilityResult:
    """Outcome of dynamic applicability checks for assigned targets."""

    applicable: list[Device] = field(default_factory=list)
    not_applicable: dict[str, str] = field(default_factory=dict)


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
        applicability = await self.check_applicability(context)
        original_targets = list(context.targets)
        applicable_targets = list(applicability.applicable)

        for target in original_targets:
            if target in applicable_targets:
                continue
            reason = applicability.not_applicable.get(
                target.name,
                "Target not applicable for this test",
            )
            context.results.add_result(
                ResultStatus.SKIPPED,
                f"{target.name}: {reason}",
            )

        if not applicable_targets:
            context.results.add_result(
                ResultStatus.SKIPPED,
                "No applicable targets after applicability check",
            )
            return

        context.targets = applicable_targets
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

    async def check_applicability(self, context: Context) -> ApplicabilityResult:
        """Return applicable targets and reasons for non-applicable ones."""
        return ApplicabilityResult(applicable=list(context.targets), not_applicable={})

    async def cleanup(self, context: Context) -> None:
        """Default no-op cleanup for learning/testing style tests."""
        return None

    @abstractmethod
    async def gather_state(self, context: Context) -> dict[str, object]:
        """Gather current state from targets for learning/testing flows."""

    @abstractmethod
    async def compare_state(
        self,
        *,
        expected: dict[str, object],
        current: dict[str, object],
        context: Context,
    ) -> None:
        """Compare expected and current state, recording test results."""

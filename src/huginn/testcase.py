"""Base test case definition for Huginn jobs."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Generic, TypeVar, cast

from jinja2 import Environment

from huginn.context import Context
from huginn.enums import BrokerType, ExecutionMode, ResultStatus
from huginn.models import Device

_METADATA_TEMPLATE_ENV = Environment(
    autoescape=True,
    trim_blocks=True,
    lstrip_blocks=True,
)

ParametersT = TypeVar("ParametersT", bound=Mapping[str, object])


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


class LearningTestCase(TestCase, Generic[ParametersT], ABC):
    """Reusable base class for learning/testing state comparison patterns."""

    DESCRIPTION: str | None = None
    SETUP: str | None = None
    PROCEDURE: str | None = None
    PASS_FAIL_CRITERIA: str | None = None

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
                ResultStatus.NOT_APPLICABLE,
                f"{target.name}: {reason}",
            )

        if not applicable_targets:
            context.results.add_result(
                ResultStatus.INFO,
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

        expected_state = cast(ParametersT, await context.parameters.load())
        self._add_rendered_metadata_result(context=context, parameters=expected_state)
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

    def _add_rendered_metadata_result(
        self,
        *,
        context: Context,
        parameters: ParametersT,
    ) -> None:
        """Render optional metadata templates and append one INFO result."""
        metadata_sections = self._metadata_sections()
        if not metadata_sections:
            return

        title = f"Test Metadata: {context.test_title}"
        lines: list[str] = [title]
        for heading, template in metadata_sections:
            rendered = _METADATA_TEMPLATE_ENV.from_string(template).render(
                parameters=parameters
            )
            rendered_text = rendered.strip()
            context.results.add_metadata_section(heading, rendered_text)
            lines.extend(["", f"{heading}:", rendered_text])

        context.results.add_result(ResultStatus.INFO, "\n".join(lines).strip())

    def _metadata_sections(self) -> list[tuple[str, str]]:
        """Return available metadata templates in report display order."""
        sections: list[tuple[str, str | None]] = [
            ("Description", self.DESCRIPTION),
            ("Setup", self.SETUP),
            ("Procedure", self.PROCEDURE),
            ("Pass/Fail Criteria", self.PASS_FAIL_CRITERIA),
        ]
        return [
            (heading, template.strip())
            for heading, template in sections
            if isinstance(template, str) and template.strip()
        ]

    @abstractmethod
    async def gather_state(self, context: Context) -> ParametersT:
        """Gather current state from targets for learning/testing flows."""

    @abstractmethod
    async def compare_state(
        self,
        *,
        expected: ParametersT,
        current: ParametersT,
        context: Context,
    ) -> None:
        """Compare expected and current state, recording test results."""

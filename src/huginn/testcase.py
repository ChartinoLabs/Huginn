"""Base test case definition for Huginn jobs."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar, cast

from jinja2 import Environment

from huginn.context import Context
from huginn.enums import BrokerType, ExecutionMode, ResultStatus
from huginn.models import Device
from huginn.parameters import ParameterStoreError

_METADATA_TEMPLATE_ENV = Environment(
    autoescape=True,
    trim_blocks=True,
    lstrip_blocks=True,
)

ParametersT = TypeVar("ParametersT", bound=Mapping[str, object])


@dataclass
class CommandSupportResult:
    """Outcome of command-support checks for assigned targets."""

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
        support = await self.check_command_support(context)
        supported_targets = list(support.applicable)
        expected_state = await self._record_command_support(context, support)

        if not supported_targets:
            context.results.add_result(
                ResultStatus.INFO,
                "No supported targets after command support check",
            )
            return

        context.targets = supported_targets
        current_state = await self.gather_state(context)

        self._capture_gather_state_na(
            current_state,
            supported_targets,
            context,
        )

        derive_status = getattr(context.results, "derive_status", None)
        if callable(derive_status) and derive_status() == ResultStatus.ERRORED:
            return

        if context.mode == ExecutionMode.LEARNING:
            await context.parameters.save(current_state)
            all_not_applicable = (
                callable(derive_status)
                and derive_status() == ResultStatus.NOT_APPLICABLE
            )
            if not all_not_applicable:
                context.results.add_result(
                    ResultStatus.PASSED,
                    "Learned parameters saved successfully",
                )
            return

        if expected_state is None:
            expected_state = cast(ParametersT, await context.parameters.load())
        self._add_rendered_metadata_result(context=context, parameters=expected_state)
        await self.compare_state(
            expected=expected_state,
            current=current_state,
            context=context,
        )

    async def _record_command_support(
        self,
        context: Context,
        support: CommandSupportResult,
    ) -> ParametersT | None:
        """Record one result per unsupported target.

        In testing mode, a target the learned parameters contain (see
        ``learned_devices()``) lost applicability since learning, which fails
        the test. It is left out of ``not_applicable_devices`` so prune never
        excludes it. Any other unsupported target is NOT_APPLICABLE.

        Returns the learned parameters when they were loaded for this check,
        so ``test()`` does not load them twice.
        """
        unsupported = [t for t in context.targets if t not in support.applicable]
        expected_state = await self._load_expected_for_support_check(
            context,
            unsupported,
        )
        learned = (
            set() if expected_state is None else self.learned_devices(expected_state)
        )
        not_applicable = dict(support.not_applicable)
        for target in unsupported:
            reason = support.not_applicable.get(
                target.name,
                "Command not supported on this device",
            )
            if target.name in learned:
                context.results.add_result(
                    ResultStatus.LOST_APPLICABILITY,
                    f"{target.name}: {reason}, but it was supported when "
                    "parameters were learned",
                )
                not_applicable.pop(target.name, None)
                continue
            context.results.add_result(
                ResultStatus.NOT_APPLICABLE,
                f"{target.name}: {reason}",
            )
        context.results.not_applicable_devices = not_applicable
        return expected_state

    @staticmethod
    async def _load_expected_for_support_check(
        context: Context,
        unsupported_targets: list[Device],
    ) -> ParametersT | None:
        """Load learned parameters when unsupported targets need classifying.

        Only testing mode with at least one unsupported target loads early.
        Parameters that cannot be loaded return None here, so the targets are
        recorded as NOT_APPLICABLE. When supported targets remain, the load
        in ``test()`` after ``gather_state()`` still raises the
        ``ParameterStoreError``, as it did before this check existed.
        """
        if context.mode != ExecutionMode.TESTING or not unsupported_targets:
            return None
        try:
            return cast(ParametersT, await context.parameters.load())
        except ParameterStoreError:
            return None

    def learned_devices(self, parameters: ParametersT) -> set[str]:
        """Return the names of the devices the learned parameters cover.

        In testing mode, an unsupported target named here is recorded as
        LOST_APPLICABILITY instead of NOT_APPLICABLE. The default reads the
        keys of ``parameters["devices"]``. Override it for jobs whose
        parameters use a different schema.
        """
        devices = parameters.get("devices")
        if not isinstance(devices, Mapping):
            return set()
        return {str(name) for name in cast(Mapping[object, object], devices)}

    @staticmethod
    def _capture_gather_state_na(
        current_state: object,
        supported_targets: list[Device],
        context: Context,
    ) -> None:
        """Detect devices excluded by gather_state and merge into N/A map.

        After gather_state runs, any supported target whose name does not
        appear in the returned ``devices`` dict was marked not-applicable
        by the job (e.g., empty extracted data). This method finds those
        devices and populates ``context.results.not_applicable_devices``
        so the prune command can act on them.
        """
        if not isinstance(current_state, dict):
            return
        returned_devices = cast(dict[str, Any], current_state).get("devices")
        if not isinstance(returned_devices, dict):
            return
        for target in supported_targets:
            if (
                target.name not in returned_devices
                and target.name not in context.results.not_applicable_devices
            ):
                reason = "No applicable data for this test"
                for check in context.results.checks:
                    if (
                        check.status == ResultStatus.NOT_APPLICABLE.value
                        and check.message.startswith(target.name)
                    ):
                        reason = check.message[len(target.name) :].lstrip(": ")
                        break
                context.results.not_applicable_devices[target.name] = reason

    async def check_command_support(self, context: Context) -> CommandSupportResult:
        """Check whether target devices support the required command(s)."""
        return CommandSupportResult(applicable=list(context.targets), not_applicable={})

    async def cleanup(self, context: Context) -> None:
        """Default no-op cleanup for learning/testing style tests."""
        return None

    def _add_rendered_metadata_result(
        self,
        *,
        context: Context,
        parameters: ParametersT,
    ) -> None:
        """Render metadata templates into structured report sections."""
        metadata_sections = self._metadata_sections()
        if not metadata_sections:
            return

        for heading, template in metadata_sections:
            rendered = _METADATA_TEMPLATE_ENV.from_string(template).render(
                parameters=parameters
            )
            context.results.add_metadata_section(heading, rendered.strip())

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

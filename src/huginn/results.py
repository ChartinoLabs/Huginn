"""Result collection utilities for test execution."""

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from huginn.brokers.protocol import CommandResult
from huginn.enums import ResultStatus
from huginn.models import CheckResult, CommandExecution, MetadataSection


@runtime_checkable
class _OutputCarrier(Protocol):
    output: str


@dataclass
class ResultCollector:
    """Collect check-level results for one test case."""

    metadata_sections: list[MetadataSection] = field(default_factory=list)
    checks: list[CheckResult] = field(default_factory=list)
    command_executions: list[CommandExecution] = field(default_factory=list)

    def add_metadata_section(self, heading: str, content: str) -> None:
        """Record one rendered metadata section for reporting."""
        self.metadata_sections.append(MetadataSection(heading=heading, content=content))

    def add_result(self, status: ResultStatus, message: str) -> None:
        """Record a check result entry."""
        self.checks.append(CheckResult(status=status.value, message=message))

    def add_command_execution(
        self,
        *,
        device: str,
        command: str,
        output: str | object,
        parsed: dict[str, object] | None = None,
    ) -> None:
        """Record one command execution with optional parsed payload."""
        output_text: str
        elapsed_ms: float | None = None
        cached: bool | None = None

        if isinstance(output, CommandResult):
            output_text = output.output
            elapsed_ms = output.elapsed_ms
            cached = output.cached
            parsed_payload = parsed if parsed is not None else output.structured
        elif isinstance(output, _OutputCarrier):
            output_text = output.output
            parsed_payload = parsed
        else:
            output_text = str(output)
            parsed_payload = parsed

        self.command_executions.append(
            CommandExecution(
                device=device,
                command=command,
                output=output_text,
                parsed=parsed_payload,
                elapsed_ms=elapsed_ms,
                cached=cached,
            )
        )

    def derive_status(self) -> ResultStatus:
        """Compute overall test status from collected checks."""
        if self._has_status(ResultStatus.ERRORED):
            return ResultStatus.ERRORED
        if self._has_status(ResultStatus.FAILED):
            return ResultStatus.FAILED

        non_info_checks = self._non_info_checks()
        if self._all_checks_match(non_info_checks, ResultStatus.NOT_APPLICABLE):
            return ResultStatus.NOT_APPLICABLE
        if self._all_checks_match(non_info_checks, ResultStatus.SKIPPED):
            return ResultStatus.SKIPPED
        return ResultStatus.PASSED

    def _has_status(self, status: ResultStatus) -> bool:
        """Return True when any check has the requested status."""
        return any(check.status == status.value for check in self.checks)

    def _non_info_checks(self) -> list[CheckResult]:
        """Return checks excluding informational entries."""
        return [
            check for check in self.checks if check.status != ResultStatus.INFO.value
        ]

    @staticmethod
    def _all_checks_match(
        checks: list[CheckResult],
        status: ResultStatus,
    ) -> bool:
        """Return True when all checks match the given status."""
        return bool(checks) and all(check.status == status.value for check in checks)

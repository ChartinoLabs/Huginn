"""Result collection utilities for test execution."""

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from huginn.brokers.protocol import CommandResult
from huginn.enums import ResultStatus
from huginn.models import CheckResult, CommandExecution


@runtime_checkable
class _OutputCarrier(Protocol):
    output: str


@dataclass
class ResultCollector:
    """Collect check-level results for one test case."""

    checks: list[CheckResult] = field(default_factory=list)
    command_executions: list[CommandExecution] = field(default_factory=list)

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
        if any(check.status == ResultStatus.ERRORED.value for check in self.checks):
            return ResultStatus.ERRORED
        if any(check.status == ResultStatus.FAILED.value for check in self.checks):
            return ResultStatus.FAILED

        non_info_checks = [
            check for check in self.checks if check.status != ResultStatus.INFO.value
        ]
        if non_info_checks and all(
            check.status == ResultStatus.NOT_APPLICABLE.value
            for check in non_info_checks
        ):
            return ResultStatus.NOT_APPLICABLE

        if non_info_checks and all(
            check.status == ResultStatus.SKIPPED.value for check in non_info_checks
        ):
            return ResultStatus.SKIPPED
        return ResultStatus.PASSED

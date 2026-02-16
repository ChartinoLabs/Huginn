"""Result collection utilities for test execution."""

from dataclasses import dataclass, field

from huginn.enums import ResultStatus
from huginn.models import CheckResult


@dataclass
class ResultCollector:
    """Collect check-level results for one test case."""

    checks: list[CheckResult] = field(default_factory=list)

    def add_result(self, status: ResultStatus, message: str) -> None:
        """Record a check result entry."""
        self.checks.append(CheckResult(status=status.value, message=message))

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
            check.status == ResultStatus.SKIPPED.value for check in non_info_checks
        ):
            return ResultStatus.SKIPPED
        return ResultStatus.PASSED

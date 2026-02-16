"""Unit tests for test-case result collection and status derivation."""

from huginn.enums import ResultStatus
from huginn.results import ResultCollector


def test_result_collector_returns_passed_for_info_only_checks() -> None:
    """Informational checks do not change overall status from passed."""
    collector = ResultCollector()
    collector.add_result(ResultStatus.INFO, "device has 5 neighbors")

    assert collector.derive_status() == ResultStatus.PASSED


def test_result_collector_returns_skipped_for_skipped_plus_info_checks() -> None:
    """Info checks do not prevent a skipped-only result set from being skipped."""
    collector = ResultCollector()
    collector.add_result(ResultStatus.SKIPPED, "feature disabled")
    collector.add_result(ResultStatus.INFO, "data-model path absent")

    assert collector.derive_status() == ResultStatus.SKIPPED


def test_result_collector_returns_failed_when_failed_and_info_present() -> None:
    """Failure still dominates informational checks."""
    collector = ResultCollector()
    collector.add_result(ResultStatus.INFO, "starting assertions")
    collector.add_result(ResultStatus.FAILED, "bgp session is down")

    assert collector.derive_status() == ResultStatus.FAILED


def test_result_collector_returns_errored_when_errored_and_info_present() -> None:
    """Error still dominates informational checks."""
    collector = ResultCollector()
    collector.add_result(ResultStatus.INFO, "parsing response")
    collector.add_result(ResultStatus.ERRORED, "JSONDecodeError")

    assert collector.derive_status() == ResultStatus.ERRORED

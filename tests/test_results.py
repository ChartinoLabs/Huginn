"""Unit tests for test-case result collection and status derivation."""

from dataclasses import dataclass

from huginn.brokers.protocol import CommandResult
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


def test_result_collector_returns_not_applicable_for_not_applicable_checks() -> None:
    """Not-applicable checks yield NOT_APPLICABLE aggregate status."""
    collector = ResultCollector()
    collector.add_result(ResultStatus.NOT_APPLICABLE, "feature not enabled")
    collector.add_result(ResultStatus.INFO, "target in maintenance window")

    assert collector.derive_status() == ResultStatus.NOT_APPLICABLE


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


def test_result_collector_records_command_execution_from_command_result() -> None:
    """CommandResult payloads are captured with output/cache metadata."""
    collector = ResultCollector()
    collector.add_command_execution(
        device="leaf-01",
        command="show ip ospf neighbor",
        output=CommandResult(
            output="neighbor output",
            structured={"neighbors": 3},
            elapsed_ms=15.2,
            cached=True,
        ),
    )

    execution = collector.command_executions[0]
    assert execution.device == "leaf-01"
    assert execution.command == "show ip ospf neighbor"
    assert execution.output == "neighbor output"
    assert execution.parsed == {"neighbors": 3}
    assert execution.elapsed_ms == 15.2
    assert execution.cached is True


def test_result_collector_records_command_execution_from_output_attribute() -> None:
    """Objects with an output attribute are normalized for recording."""

    @dataclass
    class _FakeOutput:
        output: str

    collector = ResultCollector()
    collector.add_command_execution(
        device="leaf-02",
        command="show version",
        output=_FakeOutput(output="version output"),
        parsed={"model": "n9k"},
    )

    execution = collector.command_executions[0]
    assert execution.output == "version output"
    assert execution.parsed == {"model": "n9k"}

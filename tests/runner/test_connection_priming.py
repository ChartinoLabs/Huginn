"""Tests for how connection priming reports devices that fail to connect."""

from typing import cast

import pytest

from huginn.enums import BrokerType, ErrorCode
from huginn.models import (
    Device,
    Phase,
    Scenario,
    Testbed as _Testbed,
    TestCaseDefinition,
    TestCaseGroup,
    TestPlan,
)
from huginn.runner import (
    PlannedExecution,
    RunExecutionError,
    _prime_runtime_connections as prime_runtime_connections,
)
from huginn.runtime_broker import ConnectFailure, ConnectTargetsError, RuntimeBroker


class _PrimingFakeBroker:
    """Runtime broker that fails every pair for the named devices."""

    def __init__(self, unreachable: set[str]) -> None:
        self.unreachable = unreachable
        self.attempted: list[tuple[str, str]] = []

    async def connect_targets(
        self,
        targets: list[Device],
        required_brokers: set[str],
    ) -> None:
        failures: list[ConnectFailure] = []
        for target in targets:
            for broker_key in sorted(required_brokers):
                self.attempted.append((target.name, broker_key))
                if target.name in self.unreachable:
                    failures.append(
                        ConnectFailure(
                            device_name=target.name,
                            broker_key=broker_key,
                            message=f"Device '{target.name}' ({broker_key}): lost",
                        )
                    )
        if failures:
            raise ConnectTargetsError(tuple(failures))


def _plan_with_two_broker_sets() -> TestPlan:
    """Build a plan whose two test cases need different broker sets."""
    group = TestCaseGroup(tests=["ssh-only", "ssh-and-netconf"], identifier="g")
    phase = Phase(test_case_groups=["g"], identifier="p")
    return TestPlan(
        scenarios={"s": Scenario(phases={"p": phase}, identifier="s")},
        test_case_groups={"g": group},
        test_cases={
            "ssh-only": TestCaseDefinition(test_id="ssh-only", title="", job="j"),
            "ssh-and-netconf": TestCaseDefinition(
                test_id="ssh-and-netconf", title="", job="j"
            ),
        },
    )


def _planned(*brokers: str) -> PlannedExecution:
    return PlannedExecution(
        test_case_class=None,
        required_brokers=set(brokers),
        planning_error=None,
    )


@pytest.mark.asyncio
async def test_priming_reports_every_failed_device_once() -> None:
    """Every broker set is attempted, and a failed pair is reported once."""
    testbed = _Testbed(
        devices={name: Device(name=name, os="iosxe") for name in ("r1", "r2")}
    )
    broker = _PrimingFakeBroker(unreachable={"r2"})

    with pytest.raises(RunExecutionError) as exc_info:
        await prime_runtime_connections(
            testbed=testbed,
            test_plan=_plan_with_two_broker_sets(),
            planned_executions={
                "ssh-only": _planned(BrokerType.SSH),
                "ssh-and-netconf": _planned(BrokerType.SSH, BrokerType.NETCONF),
            },
            broker=cast(RuntimeBroker, broker),
            output=None,
        )

    assert exc_info.value.code == ErrorCode.BROKER_ERROR
    assert str(exc_info.value) == (
        "2 device connections failed:\n"
        "  - Device 'r2' (ssh): lost\n"
        "  - Device 'r2' (netconf): lost"
    )
    assert ("r1", "netconf") in broker.attempted

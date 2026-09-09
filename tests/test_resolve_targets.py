"""Unit tests for target device resolution."""

import pytest

from huginn.models import (
    Device,
    ExecutionStrategy,
    Phase,
    TargetDefinition,
    Testbed,
    TestCaseDefinition,
    TestCaseGroup,
)
from huginn.runner import TargetResolutionError, resolve_targets

_SPINE = Device(name="spine-01", os="nxos", groups=["spine"])
_LEAF = Device(name="leaf-01", os="nxos", groups=["leaf"])
_ROUTER = Device(name="router-01", os="iosxe", groups=["router"])

_TESTBED = Testbed(
    devices={"spine-01": _SPINE, "leaf-01": _LEAF, "router-01": _ROUTER},
)

_DEFAULT_STRATEGY = ExecutionStrategy(mode="parallel")


def _group(*, target: TargetDefinition | None = None) -> TestCaseGroup:
    """Build a minimal TestCaseGroup."""
    return TestCaseGroup(
        tests=["1.0.0"],
        identifier="group-1",
        strategy=_DEFAULT_STRATEGY,
        target=target,
    )


def _phase(*, target: TargetDefinition | None = None) -> Phase:
    """Build a minimal Phase."""
    return Phase(
        test_case_groups=["group-1"],
        identifier="phase-1",
        strategy=_DEFAULT_STRATEGY,
        target=target,
    )


def _test_case(*, target: TargetDefinition | None = None) -> TestCaseDefinition:
    """Build a minimal TestCaseDefinition."""
    return TestCaseDefinition(
        test_id="1.0.0",
        title="Verify something",
        job="jobs/verify.py",
        target=target,
    )


def test_resolve_targets_returns_all_devices_without_selectors() -> None:
    """No target selectors returns the full testbed."""
    devices = resolve_targets(
        testbed=_TESTBED,
        phase=_phase(),
        group=_group(),
        test_case=_test_case(),
    )
    assert {d.name for d in devices} == {"spine-01", "leaf-01", "router-01"}


def test_resolve_targets_filters_by_phase_device_selector() -> None:
    """Phase-level device selector narrows the set."""
    devices = resolve_targets(
        testbed=_TESTBED,
        phase=_phase(target=TargetDefinition(devices=["spine-01"])),
        group=_group(),
        test_case=_test_case(),
    )
    assert [d.name for d in devices] == ["spine-01"]


def test_resolve_targets_intersects_phase_and_group() -> None:
    """Group selector further narrows the phase-scoped set."""
    devices = resolve_targets(
        testbed=_TESTBED,
        phase=_phase(target=TargetDefinition(groups=["spine", "leaf"])),
        group=_group(target=TargetDefinition(groups=["leaf"])),
        test_case=_test_case(),
    )
    assert [d.name for d in devices] == ["leaf-01"]


def test_resolve_targets_filters_by_os() -> None:
    """OS selector filters to matching devices."""
    devices = resolve_targets(
        testbed=_TESTBED,
        phase=_phase(),
        group=_group(target=TargetDefinition(os=["iosxe"])),
        test_case=_test_case(),
    )
    assert [d.name for d in devices] == ["router-01"]


def test_resolve_targets_raises_on_unknown_device() -> None:
    """Unknown device in a selector raises TargetResolutionError."""
    with pytest.raises(TargetResolutionError, match="Unknown target device"):
        resolve_targets(
            testbed=_TESTBED,
            phase=_phase(
                target=TargetDefinition(devices=["nonexistent"]),
            ),
            group=_group(),
            test_case=_test_case(),
        )


def test_resolve_targets_applies_exclude_devices() -> None:
    """Exclude list removes devices from the resolved set."""
    devices = resolve_targets(
        testbed=_TESTBED,
        phase=_phase(),
        group=_group(),
        test_case=_test_case(
            target=TargetDefinition(exclude_devices=["router-01"]),
        ),
    )
    assert {d.name for d in devices} == {"spine-01", "leaf-01"}

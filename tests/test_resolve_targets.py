"""Unit tests for target device resolution."""

from pathlib import Path

import pytest

from huginn.loaders import load_test_plan
from huginn.models import (
    Device,
    ExecutionStrategy,
    InclusionPath,
    Phase,
    TargetDefinition,
    Testbed,
    TestCaseDefinition,
    TestCaseGroup,
)
from huginn.runner import TargetResolutionError, resolve_targets

NESTED_PLAN = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "loaders"
    / "plan_with_nested_group_inheritance.yaml"
)

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


_SPINE_EOS = Device(name="spine-02", os="eos", groups=["spine"])
_LEAF_EOS = Device(name="leaf-02", os="eos", groups=["leaf"])
_NESTED_TESTBED = Testbed(
    devices={
        device.name: device
        for device in (_SPINE, _SPINE_EOS, _LEAF, _LEAF_EOS, _ROUTER)
    },
)


def _nested_targets(
    test_id: str, *, phase_target: TargetDefinition | None = None
) -> list[str]:
    """Resolve a test in the nested-inheritance fixture's parent group."""
    test_plan = load_test_plan(NESTED_PLAN)
    devices = resolve_targets(
        testbed=_NESTED_TESTBED,
        phase=_phase(target=phase_target),
        group=test_plan.test_case_groups["parent"],
        test_case=test_plan.test_cases[test_id],
    )
    return [device.name for device in devices]


def test_resolve_targets_intersects_nested_child_targets_at_every_level() -> None:
    """A test two levels down is narrowed by both the child and grandchild."""
    assert _nested_targets("2.0.0") == ["spine-01"]


def test_resolve_targets_nested_child_target_only_narrows_the_parent() -> None:
    """A child's target cannot widen what the phase already selected."""
    leaf_phase = TargetDefinition(groups=["leaf"])
    assert _nested_targets("2.0.0", phase_target=leaf_phase) == []


def test_resolve_targets_ignores_nested_targets_for_direct_parent_tests() -> None:
    """A test the parent lists itself is unaffected by its child groups."""
    assert _nested_targets("1.0.0") == list(_NESTED_TESTBED.devices)


def test_resolve_targets_unions_paths_for_a_diamond_test() -> None:
    """A test reached through two children targets devices either path selects."""
    assert _nested_targets("3.0.0") == ["spine-01", "leaf-01", "leaf-02"]


def test_resolve_targets_reports_unknown_device_in_nested_child() -> None:
    """An unknown device in a nested child's target names that child group."""
    group = TestCaseGroup(
        tests=["1.0.0"],
        identifier="parent",
        inclusion_paths={
            "1.0.0": (
                InclusionPath(
                    groups=("child",),
                    targets=(("child", TargetDefinition(devices=["missing-01"])),),
                ),
            )
        },
    )
    with pytest.raises(
        TargetResolutionError,
        match="Unknown target device 'missing-01' in Test case group 'child'",
    ):
        resolve_targets(
            testbed=_TESTBED, phase=_phase(), group=group, test_case=_test_case()
        )

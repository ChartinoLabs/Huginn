"""Unit tests for YAML loader helpers."""

from pathlib import Path

import pytest

from huginn.enums import ConnectionProtocol
from huginn.loaders import ConfigurationError, load_test_plan, load_testbed

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "loaders"


def test_load_testbed_success() -> None:
    """Load a minimal valid testbed file."""
    path = FIXTURES / "testbed_valid.yaml"

    testbed = load_testbed(path)

    assert set(testbed.devices.keys()) == {"spine-01", "leaf-01"}
    assert testbed.devices["spine-01"].os == "nxos"


def test_load_testbed_requires_devices_mapping() -> None:
    """Raise when devices section is missing or empty."""
    path = FIXTURES / "testbed_empty_devices.yaml"

    with pytest.raises(ConfigurationError, match="non-empty 'devices' mapping"):
        load_testbed(path)


def test_load_testbed_requires_device_os() -> None:
    """Raise when a device does not declare a non-empty os."""
    path = FIXTURES / "testbed_missing_os.yaml"

    with pytest.raises(ConfigurationError, match="must define non-empty 'os'"):
        load_testbed(path)


def test_load_testbed_parses_ssh_connection_and_credentials() -> None:
    """Parse optional device groups, credentials, and SSH connection details."""
    path = FIXTURES / "testbed_with_ssh.yaml"

    testbed = load_testbed(path)
    device = testbed.devices["spine-01"]

    assert device.groups == ["spine"]
    assert device.credentials["default"]["username"] == "admin"
    assert device.connections["ssh"].protocol == ConnectionProtocol.SSH
    assert device.connections["ssh"].host == "10.0.0.1"
    assert device.connections["ssh"].options["auth_strict_key"] is False


def test_load_test_plan_success() -> None:
    """Load a minimal valid test plan file."""
    path = FIXTURES / "plan_valid.yaml"

    test_plan = load_test_plan(path)

    assert list(test_plan.test_cases.keys()) == ["1.0.0"]
    assert test_plan.test_cases["1.0.0"].job == "jobs/verify_bgp.py"
    assert test_plan.test_case_groups["routing"].tests == ["1.0.0"]
    assert test_plan.phases["phase-1"].test_case_groups == ["routing"]


def test_load_test_plan_parses_test_case_device_targets() -> None:
    """Parse optional test-case target device selectors."""
    path = FIXTURES / "plan_with_target_devices.yaml"

    test_plan = load_test_plan(path)

    target = test_plan.test_cases["1.0.0"].target
    assert target is not None
    assert target.devices == ["spine-01"]


def test_load_test_plan_parses_target_groups_and_os() -> None:
    """Parse optional target groups and os selectors."""
    path = FIXTURES / "plan_with_target_selectors.yaml"

    test_plan = load_test_plan(path)

    target = test_plan.test_cases["1.0.0"].target
    assert target is not None
    assert target.devices is None
    assert target.groups == ["spine"]
    assert target.os == ["nxos"]


def test_load_test_plan_parses_test_case_tags() -> None:
    """Parse optional test case tags list."""
    path = FIXTURES / "plan_with_tags.yaml"

    test_plan = load_test_plan(path)

    assert test_plan.test_cases["1.0.0"].tags == ["ospf", "routing"]


def test_load_test_plan_rejects_mixed_target_selectors() -> None:
    """Raise when explicit devices are mixed with groups/os selectors."""
    path = FIXTURES / "plan_with_mixed_target_selectors.yaml"

    with pytest.raises(ConfigurationError, match="cannot define target.devices"):
        load_test_plan(path)


def test_load_test_plan_parses_hierarchical_targets() -> None:
    """Parse phase/group/test-case target definitions."""
    path = FIXTURES / "plan_with_hierarchical_targets.yaml"

    test_plan = load_test_plan(path)

    case_target = test_plan.test_cases["1.0.0"].target
    group_target = test_plan.test_case_groups["group-1"].target
    phase_target = test_plan.phases["phase-1"].target
    assert case_target is not None
    assert group_target is not None
    assert phase_target is not None
    assert case_target.devices == ["leaf-01"]
    assert group_target.os == ["nxos"]
    assert phase_target.groups == ["leaf"]


def test_load_test_plan_rejects_mixed_group_target_selectors() -> None:
    """Raise when group target mixes explicit and dynamic selectors."""
    path = FIXTURES / "plan_with_mixed_group_target_selectors.yaml"

    with pytest.raises(ConfigurationError, match="Test case group 'group-1'"):
        load_test_plan(path)


def test_load_test_plan_rejects_mixed_phase_target_selectors() -> None:
    """Raise when phase target mixes explicit and dynamic selectors."""
    path = FIXTURES / "plan_with_mixed_phase_target_selectors.yaml"

    with pytest.raises(ConfigurationError, match="Phase 'phase-1'"):
        load_test_plan(path)


def test_load_test_plan_parses_phase_dependencies() -> None:
    """Parse optional depends_on phase references."""
    path = FIXTURES / "plan_with_phase_dependency.yaml"

    test_plan = load_test_plan(path)

    assert test_plan.phases["phase-1"].depends_on == []
    assert test_plan.phases["phase-2"].depends_on == ["phase-1"]


def test_load_test_plan_rejects_missing_required_sections() -> None:
    """Raise when required top-level sections are missing."""
    path = FIXTURES / "plan_missing_sections.yaml"

    with pytest.raises(ConfigurationError, match="non-empty 'test_cases' mapping"):
        load_test_plan(path)


def test_load_test_plan_rejects_group_with_unknown_test_id() -> None:
    """Raise when a group references an undefined test case id."""
    path = FIXTURES / "plan_unknown_test_id.yaml"

    with pytest.raises(ConfigurationError, match="references undefined test ids"):
        load_test_plan(path)


def test_load_test_plan_rejects_phase_with_unknown_group() -> None:
    """Raise when a phase references an undefined group."""
    path = FIXTURES / "plan_unknown_group.yaml"

    with pytest.raises(
        ConfigurationError,
        match="references undefined test case groups",
    ):
        load_test_plan(path)


def test_load_test_plan_rejects_unknown_phase_dependency() -> None:
    """Raise when phase depends_on references missing phase names."""
    path = FIXTURES / "plan_unknown_dependency.yaml"

    with pytest.raises(ConfigurationError, match="undefined depends_on phases"):
        load_test_plan(path)


def test_load_test_plan_rejects_invalid_tests_list() -> None:
    """Raise when test_case_groups.tests contains invalid values."""
    path = FIXTURES / "plan_invalid_tests.yaml"

    with pytest.raises(ConfigurationError, match="non-empty 'tests'"):
        load_test_plan(path)


def test_load_test_plan_parses_nested_groups() -> None:
    """Flatten nested test case group includes for execution."""
    path = FIXTURES / "plan_with_nested_groups.yaml"

    test_plan = load_test_plan(path)

    assert test_plan.test_case_groups["ospf-tests"].tests == ["3.0.0", "3.1.0"]
    assert test_plan.test_case_groups["bgp-tests"].tests == ["4.0.0"]
    assert test_plan.test_case_groups["pre-change-validation"].tests == [
        "1.0.0",
        "3.0.0",
        "3.1.0",
        "4.0.0",
    ]


def test_load_test_plan_rejects_nested_group_with_unknown_group() -> None:
    """Raise when nested group includes reference unknown group names."""
    path = FIXTURES / "plan_unknown_nested_group.yaml"

    with pytest.raises(ConfigurationError, match="undefined nested groups"):
        load_test_plan(path)


def test_load_test_plan_rejects_nested_group_cycles() -> None:
    """Raise when nested group includes form a cycle."""
    path = FIXTURES / "plan_nested_group_cycle.yaml"

    with pytest.raises(ConfigurationError, match="form a cycle"):
        load_test_plan(path)


def test_load_test_plan_requires_tests_or_groups_for_group() -> None:
    """Raise when a test case group declares neither tests nor groups."""
    path = FIXTURES / "plan_group_missing_tests_and_groups.yaml"

    with pytest.raises(ConfigurationError, match="at least one of 'tests' or 'groups'"):
        load_test_plan(path)

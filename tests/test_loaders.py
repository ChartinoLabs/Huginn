"""Unit tests for YAML loader helpers."""

import copy
import time
from pathlib import Path
from typing import cast

import pytest
import yaml

from huginn import models
from huginn.enums import ConnectionProtocol
from huginn.loaders import ConfigurationError, load_test_plan, load_testbed
from huginn.models import ExecutionStrategy, InclusionPath, TargetDefinition

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


def test_load_testbed_applies_global_credentials_with_device_overrides() -> None:
    """Global credentials are inherited and device credentials override by name."""
    path = FIXTURES / "testbed_with_global_credentials.yaml"

    testbed = load_testbed(path)

    assert testbed.credentials["default"]["username"] == "global-admin"
    assert (
        testbed.devices["spine-01"].credentials["default"]["username"] == "global-admin"
    )
    assert (
        testbed.devices["spine-01"].credentials["readonly"]["username"] == "global-ro"
    )
    assert (
        testbed.devices["leaf-01"].credentials["default"]["username"] == "device-admin"
    )
    assert testbed.devices["leaf-01"].credentials["readonly"]["username"] == "global-ro"


def test_load_test_plan_success() -> None:
    """Load a minimal valid test plan file."""
    path = FIXTURES / "plan_valid.yaml"

    test_plan = load_test_plan(path)

    assert list(test_plan.test_cases.keys()) == ["1.0.0"]
    assert test_plan.test_cases["1.0.0"].job == "jobs/verify_bgp.py"
    assert test_plan.test_case_groups["routing"].tests == ["1.0.0"]
    assert test_plan.scenarios["scenario-1"].phases["phase-1"].test_case_groups == [
        "routing"
    ]


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


def test_load_test_plan_parses_test_case_metadata_fields() -> None:
    """Parse optional test case metadata fields."""
    path = FIXTURES / "plan_with_test_case_metadata.yaml"

    test_plan = load_test_plan(path)

    tc = test_plan.test_cases["1.0.0"]
    assert tc.description == "Confirm BGP neighbor reaches Established state"
    assert tc.priority == "high"
    assert tc.category == "routing"
    assert tc.is_automated is True
    assert tc.metadata == {"jira_ticket": "NET-1234", "owner": "network-team"}


def test_load_test_plan_parses_is_automated_false() -> None:
    """is_automated=false is preserved on test cases."""
    path = FIXTURES / "plan_with_test_case_metadata.yaml"

    test_plan = load_test_plan(path)

    assert test_plan.test_cases["2.0.0"].is_automated is False


def test_load_test_plan_defaults_metadata_fields() -> None:
    """Metadata fields default to None/True when absent."""
    path = FIXTURES / "plan_with_test_case_metadata.yaml"

    test_plan = load_test_plan(path)

    tc = test_plan.test_cases["3.0.0"]
    assert tc.description is None
    assert tc.priority is None
    assert tc.category is None
    assert tc.is_automated is True
    assert tc.metadata is None


def test_load_test_plan_parses_test_case_group_tags() -> None:
    """Parse optional test case group tags list."""
    path = FIXTURES / "plan_with_group_tags.yaml"

    test_plan = load_test_plan(path)

    assert test_plan.test_case_groups["routing"].tags == ["network", "critical"]


def test_load_test_plan_parses_optional_display_names() -> None:
    """Scenario, phase, and group names are optional display labels."""
    path = FIXTURES / "plan_with_names.yaml"

    test_plan = load_test_plan(path)

    scenario = test_plan.scenarios["scenario-1"]
    phase = scenario.phases["steady-state"]
    group = test_plan.test_case_groups["state-baseline"]

    assert scenario.identifier == "scenario-1"
    assert scenario.name == "Pre-Change Validation"
    assert scenario.display_name == "Pre-Change Validation"
    assert phase.identifier == "steady-state"
    assert phase.name == "Steady State Verification"
    assert phase.display_name == "Steady State Verification"
    assert group.identifier == "state-baseline"
    assert group.name == "State Baseline Checks"
    assert group.display_name == "State Baseline Checks"


_DESCRIBED_PLAN: dict[str, object] = {
    "test_cases": {"1.0.0": {"title": "Verify BGP", "job": "jobs/verify_bgp.py"}},
    "test_case_groups": {
        "child": {"description": "Child group", "tests": ["1.0.0"]},
        "parent": {"description": "Parent group", "groups": ["child"]},
    },
    "scenarios": {
        "scenario-1": {
            "description": "Scenario text",
            "phases": {
                "pre": {"description": "Phase text", "test_case_groups": ["parent"]},
            },
        }
    },
}


def _assert_described_plan(plan: models.TestPlan) -> None:
    """Assert the descriptions from ``_DESCRIBED_PLAN`` were loaded."""
    scenario = plan.scenarios["scenario-1"]
    assert scenario.description == "Scenario text"
    assert scenario.phases["pre"].description == "Phase text"
    assert plan.test_case_groups["child"].description == "Child group"
    assert plan.test_case_groups["parent"].description == "Parent group"


def test_load_test_plan_parses_descriptions(tmp_path: Path) -> None:
    """Parse scenario, phase, and group descriptions from a single file."""
    plan_file = tmp_path / "plan.yaml"
    plan_file.write_text(yaml.safe_dump(_DESCRIBED_PLAN))

    _assert_described_plan(load_test_plan(plan_file))


def test_load_test_plan_directory_parses_descriptions(tmp_path: Path) -> None:
    """Parse scenario, phase, and group descriptions from a directory plan."""
    for section, value in _DESCRIBED_PLAN.items():
        (tmp_path / f"{section}.yaml").write_text(yaml.safe_dump({section: value}))

    _assert_described_plan(load_test_plan(tmp_path))


def test_load_test_plan_defaults_descriptions_to_none() -> None:
    """Descriptions are None when a plan does not set them."""
    plan = load_test_plan(FIXTURES / "plan_with_names.yaml")

    scenario = plan.scenarios["scenario-1"]
    assert scenario.description is None
    assert scenario.phases["steady-state"].description is None
    assert plan.test_case_groups["state-baseline"].description is None


@pytest.mark.parametrize(
    ("keys", "message"),
    [
        (
            ("scenarios", "scenario-1"),
            r"Scenario 'scenario-1' description must be a string",
        ),
        (
            ("scenarios", "scenario-1", "phases", "pre"),
            r"Phase 'pre' in scenario 'scenario-1' description must be a string",
        ),
        (
            ("test_case_groups", "child"),
            r"Test case group 'child' description must be a string",
        ),
    ],
    ids=["scenario", "phase", "group"],
)
def test_load_test_plan_rejects_non_string_description(
    tmp_path: Path, keys: tuple[str, ...], message: str
) -> None:
    """Raise when a scenario, phase, or group description is not a string."""
    data = copy.deepcopy(_DESCRIBED_PLAN)
    entry: dict[str, object] = data
    for key in keys:
        entry = cast(dict[str, object], entry[key])
    entry["description"] = ["not", "a", "string"]
    plan_file = tmp_path / "plan.yaml"
    plan_file.write_text(yaml.safe_dump(data))

    with pytest.raises(ConfigurationError, match=message):
        load_test_plan(plan_file)


def test_load_test_plan_parses_execution_strategies() -> None:
    """Parse phase and group execution strategy mappings."""
    path = FIXTURES / "plan_with_execution_strategies.yaml"

    test_plan = load_test_plan(path)

    assert (
        test_plan.scenarios["scenario-1"].phases["phase-1"].strategy.mode == "parallel"
    )
    assert test_plan.scenarios["scenario-1"].phases["phase-1"].strategy.maximum == 2
    assert test_plan.test_case_groups["serial-group"].strategy.mode == "serial"
    assert test_plan.test_case_groups["serial-group"].strategy.maximum is None
    assert test_plan.test_case_groups["parallel-group"].strategy.mode == "parallel"
    assert test_plan.test_case_groups["parallel-group"].strategy.maximum == 3


def test_load_test_plan_rejects_strategy_with_multiple_modes() -> None:
    """Reject strategies that define both serial and parallel keys."""
    path = FIXTURES / "plan_invalid_strategy_multiple_modes.yaml"

    with pytest.raises(ConfigurationError, match="cannot define both"):
        load_test_plan(path)


def test_load_test_plan_rejects_strategy_with_invalid_maximum() -> None:
    """Reject parallel strategy maximum values that are not positive ints."""
    path = FIXTURES / "plan_invalid_strategy_maximum.yaml"

    with pytest.raises(ConfigurationError, match="must be a positive integer"):
        load_test_plan(path)


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
    phase_target = test_plan.scenarios["scenario-1"].phases["phase-1"].target
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

    assert test_plan.scenarios["scenario-1"].phases["phase-1"].depends_on == []
    assert test_plan.scenarios["scenario-1"].phases["phase-2"].depends_on == ["phase-1"]


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


def test_load_test_plan_records_nested_group_inclusion_paths() -> None:
    """Flattening records each nested child's target and tags for its tests."""
    test_plan = load_test_plan(FIXTURES / "plan_with_nested_group_inheritance.yaml")
    parent = test_plan.test_case_groups["parent"]

    assert parent.tests == ["1.0.0", "2.0.0", "3.0.0"]
    assert parent.tags == ["parent-tag"]
    assert parent.target is None
    assert parent.strategy == ExecutionStrategy(mode="parallel")
    assert parent.paths_for("1.0.0") == (InclusionPath(),)
    assert parent.paths_for("2.0.0") == (
        InclusionPath(
            groups=("child", "grandchild"),
            targets=(
                ("child", TargetDefinition(groups=["spine"])),
                ("grandchild", TargetDefinition(os=["nxos"])),
            ),
            tags=("child-tag", "grandchild-tag"),
        ),
    )


def test_load_test_plan_keeps_every_path_to_a_diamond_test() -> None:
    """A test reached through two child groups keeps one path per child."""
    test_plan = load_test_plan(FIXTURES / "plan_with_nested_group_inheritance.yaml")
    parent = test_plan.test_case_groups["parent"]

    assert parent.tests.count("3.0.0") == 1
    assert parent.paths_for("3.0.0") == (
        InclusionPath(
            groups=("nxos-only",),
            targets=(("nxos-only", TargetDefinition(os=["nxos"])),),
            tags=("nxos-tag",),
        ),
        InclusionPath(
            groups=("leaf-only",),
            targets=(("leaf-only", TargetDefinition(groups=["leaf"])),),
            tags=("leaf-tag",),
        ),
    )


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


def test_load_test_plan_applies_exclude_tests() -> None:
    """Exclude specific test IDs inherited from nested groups."""
    path = FIXTURES / "plan_with_exclude_tests.yaml"

    test_plan = load_test_plan(path)

    post_group = test_plan.test_case_groups["post-change-validation"]
    assert "3.0.0" not in post_group.tests
    assert "3.0.0-post-change" in post_group.tests
    assert "1.0.0" in post_group.tests
    assert "3.1.0" in post_group.tests
    assert "4.0.0" in post_group.tests


def test_load_test_plan_rejects_exclude_tests_without_groups() -> None:
    """Raise when exclude_tests is used without groups."""
    path = FIXTURES / "plan_exclude_tests_without_groups.yaml"

    with pytest.raises(ConfigurationError, match="exclude_tests.*without.*groups"):
        load_test_plan(path)


# --- Multi-file (directory) test plan loading ---


def test_load_test_plan_directory_merges_files() -> None:
    """Load a directory of YAML files into a single merged TestPlan."""
    path = FIXTURES / "multi_file_plan"

    plan = load_test_plan(path)

    assert set(plan.test_cases.keys()) == {"1.0.0", "1.1.0", "2.0.0"}
    assert set(plan.test_case_groups.keys()) == {"connectivity-checks", "ospf-checks"}
    assert "validation" in plan.scenarios
    assert plan.test_cases["2.0.0"].tags == ["ospf"]


def test_load_test_plan_directory_populates_metadata() -> None:
    """Metadata fields are extracted from directory YAML files."""
    path = FIXTURES / "multi_file_plan"

    plan = load_test_plan(path)

    assert plan.name == "Multi-File Test Plan"
    assert plan.description == "A test plan split across multiple files."


def test_load_test_plan_directory_cross_file_references() -> None:
    """Groups in one file can reference test cases defined in another file."""
    path = FIXTURES / "multi_file_plan"

    plan = load_test_plan(path)

    # ospf-checks group (routing/ospf.yaml) references test 2.0.0 (same file)
    # connectivity-checks group references 1.0.0 and 1.1.0 (connectivity.yaml)
    # scenario references both groups across files
    scenario = plan.scenarios["validation"]
    phase = scenario.phases["check-all"]
    assert "connectivity-checks" in phase.test_case_groups
    assert "ospf-checks" in phase.test_case_groups


def test_load_test_plan_directory_excludes_underscore_prefixed() -> None:
    """Files in directories starting with _ are excluded from discovery."""
    path = FIXTURES / "multi_file_plan"

    plan = load_test_plan(path)

    # _drafts/wip.yaml defines test case 99.0.0 — should not appear
    assert "99.0.0" not in plan.test_cases


def test_load_test_plan_directory_rejects_duplicate_test_case() -> None:
    """Raise when the same test case ID appears in multiple files."""
    path = FIXTURES / "duplicate_test_case"

    with pytest.raises(ConfigurationError, match="Duplicate test_cases key '1.0.0'"):
        load_test_plan(path)


def test_load_test_plan_directory_rejects_duplicate_group() -> None:
    """Raise when the same group name appears in multiple files."""
    path = FIXTURES / "duplicate_group"

    with pytest.raises(
        ConfigurationError, match="Duplicate test_case_groups key 'grp'"
    ):
        load_test_plan(path)


def test_load_test_plan_directory_rejects_duplicate_scenario() -> None:
    """Raise when the same scenario name appears in multiple files."""
    path = FIXTURES / "duplicate_scenario"

    with pytest.raises(ConfigurationError, match="Duplicate scenarios key 's'"):
        load_test_plan(path)


def test_load_test_plan_directory_rejects_duplicate_metadata() -> None:
    """Raise when the same metadata key appears in multiple files."""
    path = FIXTURES / "duplicate_metadata"

    with pytest.raises(ConfigurationError, match="Duplicate metadata 'name'"):
        load_test_plan(path)


def test_load_test_plan_rejects_removed_defaults_key(tmp_path: Path) -> None:
    """Raise when a single-file plan still sets the removed 'defaults' key."""
    plan_file = tmp_path / "plan.yaml"
    plan_file.write_text(
        (FIXTURES / "plan_valid.yaml").read_text() + "defaults:\n  tags: [ospf]\n"
    )

    with pytest.raises(
        ConfigurationError,
        match=r"'defaults' in .*plan\.yaml was removed.*'tags' or 'target'",
    ):
        load_test_plan(plan_file)


def test_load_test_plan_directory_rejects_removed_defaults_key(
    tmp_path: Path,
) -> None:
    """Raise when any file in a directory plan sets the removed 'defaults' key."""
    (tmp_path / "plan.yaml").write_text((FIXTURES / "plan_valid.yaml").read_text())
    (tmp_path / "project.yaml").write_text("defaults:\n  tags: [ospf]\n")

    with pytest.raises(
        ConfigurationError,
        match=r"'defaults' in .*project\.yaml was removed.*'tags' or 'target'",
    ):
        load_test_plan(tmp_path)


def test_load_test_plan_directory_rejects_empty_directory(tmp_path: Path) -> None:
    """Raise when directory contains no YAML files."""
    with pytest.raises(ConfigurationError, match="contains no YAML files"):
        load_test_plan(tmp_path)


def test_load_test_plan_rejects_invalid_yaml_syntax(tmp_path: Path) -> None:
    """Raise ConfigurationError with file path when YAML syntax is invalid."""
    bad_file = tmp_path / "bad.yaml"
    bad_file.write_text("test_cases:\n  - id: foo\n bad_indent: bar\n")
    with pytest.raises(
        ConfigurationError, match=r"Failed to parse YAML file.*bad\.yaml"
    ):
        load_test_plan(bad_file)


def test_load_test_plan_single_file_populates_metadata() -> None:
    """Single-file plans populate metadata fields when present."""
    path = FIXTURES / "plan_valid.yaml"

    plan = load_test_plan(path)

    # plan_valid.yaml doesn't define metadata, so fields should be None
    assert plan.name is None
    assert plan.description is None
    assert plan.data_model is None


def _write_stacked_diamonds(
    tmp_path: Path, depth: int, *, distinct_tags: bool = False
) -> Path:
    """Write a plan whose ``top`` group reaches one test through stacked diamonds.

    Each level has two groups that both include both groups of the level
    below, so ``top`` reaches ``1.0.0`` through ``2 ** depth`` group chains.
    With ``distinct_tags``, every group has its own tag, so no two chains are
    equivalent.
    """
    groups: dict[str, dict[str, object]] = {"base": {"tests": ["1.0.0"]}}
    below = ["base"]
    for level in range(depth):
        names = [f"a{level}", f"b{level}"]
        for name in names:
            groups[name] = {"groups": list(below)}
            if distinct_tags:
                groups[name]["tags"] = [name]
        below = names
    groups["top"] = {"groups": below}
    plan = {
        "test_cases": {"1.0.0": {"title": "Diamond test", "job": "jobs/x.py"}},
        "test_case_groups": groups,
        "scenarios": {"s": {"phases": {"p": {"test_case_groups": ["top"]}}}},
    }
    path = tmp_path / "plan.yaml"
    path.write_text(yaml.safe_dump(plan), encoding="utf-8")
    return path


def test_load_test_plan_merges_equivalent_inclusion_paths(tmp_path: Path) -> None:
    """Paths with the same targets and tags merge and keep every group ID."""
    test_plan = load_test_plan(_write_stacked_diamonds(tmp_path, 2))
    paths = test_plan.test_case_groups["top"].paths_for("1.0.0")

    assert len(paths) == 1
    assert paths[0].targets == ()
    assert paths[0].tags == ()
    assert set(paths[0].groups) == {"a1", "b1", "a0", "b0", "base"}


def test_load_test_plan_stacked_diamonds_load_quickly(tmp_path: Path) -> None:
    """Fourteen stacked diamonds, 16384 group chains, load well under a second."""
    path = _write_stacked_diamonds(tmp_path, 14)

    started = time.perf_counter()
    test_plan = load_test_plan(path)
    elapsed = time.perf_counter() - started

    assert elapsed < 1.0
    assert len(test_plan.test_case_groups["top"].paths_for("1.0.0")) == 1


def test_load_test_plan_rejects_too_many_distinct_inclusion_paths(
    tmp_path: Path,
) -> None:
    """Distinct paths beyond the cap raise instead of growing exponentially."""
    path = _write_stacked_diamonds(tmp_path, 14, distinct_tags=True)

    with pytest.raises(ConfigurationError, match="nested-group paths"):
        load_test_plan(path)

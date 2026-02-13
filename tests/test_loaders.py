"""Unit tests for YAML loader helpers."""

from pathlib import Path

import pytest

from huginn.loaders import ConfigurationError, load_test_plan, load_testbed


def test_load_testbed_success(tmp_path: Path) -> None:
    """Load a minimal valid testbed file."""
    path = _write_yaml(
        tmp_path,
        "testbed.yaml",
        """
devices:
  spine-01:
    os: nxos
  leaf-01:
    os: eos
""",
    )

    testbed = load_testbed(path)

    assert set(testbed.devices.keys()) == {"spine-01", "leaf-01"}
    assert testbed.devices["spine-01"].os == "nxos"


def test_load_testbed_requires_devices_mapping(tmp_path: Path) -> None:
    """Raise when devices section is missing or empty."""
    path = _write_yaml(
        tmp_path,
        "testbed.yaml",
        """
devices: {}
""",
    )

    with pytest.raises(ConfigurationError, match="non-empty 'devices' mapping"):
        load_testbed(path)


def test_load_testbed_requires_device_os(tmp_path: Path) -> None:
    """Raise when a device does not declare a non-empty os."""
    path = _write_yaml(
        tmp_path,
        "testbed.yaml",
        """
devices:
  spine-01:
    os: ""
""",
    )

    with pytest.raises(ConfigurationError, match="must define non-empty 'os'"):
        load_testbed(path)


def test_load_test_plan_success(tmp_path: Path) -> None:
    """Load a minimal valid test plan file."""
    path = _write_yaml(
        tmp_path,
        "test_plan.yaml",
        """
test_cases:
  "1.0.0":
    title: Verify BGP
    job: jobs/verify_bgp.py

test_case_groups:
  routing:
    tests:
      - "1.0.0"

phases:
  phase-1:
    test_case_groups:
      - routing
""",
    )

    test_plan = load_test_plan(path)

    assert list(test_plan.test_cases.keys()) == ["1.0.0"]
    assert test_plan.test_cases["1.0.0"].job == "jobs/verify_bgp.py"
    assert test_plan.test_case_groups["routing"].tests == ["1.0.0"]
    assert test_plan.phases["phase-1"].test_case_groups == ["routing"]


def test_load_test_plan_rejects_missing_required_sections(tmp_path: Path) -> None:
    """Raise when required top-level sections are missing."""
    path = _write_yaml(
        tmp_path,
        "test_plan.yaml",
        """
test_cases: {}
""",
    )

    with pytest.raises(ConfigurationError, match="non-empty 'test_cases' mapping"):
        load_test_plan(path)


def test_load_test_plan_rejects_group_with_unknown_test_id(tmp_path: Path) -> None:
    """Raise when a group references an undefined test case id."""
    path = _write_yaml(
        tmp_path,
        "test_plan.yaml",
        """
test_cases:
  "1.0.0":
    title: Verify BGP
    job: jobs/verify_bgp.py

test_case_groups:
  routing:
    tests:
      - "1.0.1"

phases:
  phase-1:
    test_case_groups:
      - routing
""",
    )

    with pytest.raises(ConfigurationError, match="references undefined test ids"):
        load_test_plan(path)


def test_load_test_plan_rejects_phase_with_unknown_group(tmp_path: Path) -> None:
    """Raise when a phase references an undefined group."""
    path = _write_yaml(
        tmp_path,
        "test_plan.yaml",
        """
test_cases:
  "1.0.0":
    title: Verify BGP
    job: jobs/verify_bgp.py

test_case_groups:
  routing:
    tests:
      - "1.0.0"

phases:
  phase-1:
    test_case_groups:
      - missing-group
""",
    )

    with pytest.raises(
        ConfigurationError,
        match="references undefined test case groups",
    ):
        load_test_plan(path)


def test_load_test_plan_rejects_invalid_tests_list(tmp_path: Path) -> None:
    """Raise when test_case_groups.tests contains invalid values."""
    path = _write_yaml(
        tmp_path,
        "test_plan.yaml",
        """
test_cases:
  "1.0.0":
    title: Verify BGP
    job: jobs/verify_bgp.py

test_case_groups:
  routing:
    tests:
      - ""

phases:
  phase-1:
    test_case_groups:
      - routing
""",
    )

    with pytest.raises(ConfigurationError, match="non-empty 'tests'"):
        load_test_plan(path)


def _write_yaml(tmp_path: Path, name: str, body: str) -> Path:
    """Write YAML fixture content and return file path."""
    path = tmp_path / name
    path.write_text(body.strip() + "\n", encoding="utf-8")
    return path

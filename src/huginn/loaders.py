"""YAML loaders for testbed and test plan files."""

from pathlib import Path

import yaml

from huginn.models import (
    Device,
    Phase,
    Testbed,
    TestCaseDefinition,
    TestCaseGroup,
    TestPlan,
)


class ConfigurationError(ValueError):
    """Raised when input YAML is missing required structure."""


def _load_yaml(path: Path) -> dict[str, object]:
    """Load and validate a YAML file into a mapping."""
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ConfigurationError(f"Expected mapping at root of {path}")
    return loaded


def load_testbed(path: Path) -> Testbed:
    """Load a testbed file with minimal first-slice validation."""
    data = _load_yaml(path)
    raw_devices = data.get("devices")
    if not isinstance(raw_devices, dict) or not raw_devices:
        raise ConfigurationError("Testbed must include a non-empty 'devices' mapping")

    devices: dict[str, Device] = {}
    for device_name, raw_device in raw_devices.items():
        if not isinstance(device_name, str):
            raise ConfigurationError("Device names must be strings")
        if not isinstance(raw_device, dict):
            raise ConfigurationError(f"Device '{device_name}' must be a mapping")
        os_name = raw_device.get("os")
        if not isinstance(os_name, str) or not os_name:
            raise ConfigurationError(
                f"Device '{device_name}' must define non-empty 'os'"
            )
        devices[device_name] = Device(name=device_name, os=os_name)

    return Testbed(devices=devices)


def load_test_plan(path: Path) -> TestPlan:
    """Load a test plan file with minimal first-slice validation."""
    data = _load_yaml(path)

    test_cases = _load_test_cases(data)
    groups = _load_test_case_groups(data)
    phases = _load_phases(data)

    _validate_test_case_group_references(groups, test_cases)
    _validate_phase_references(phases, groups)

    return TestPlan(test_cases=test_cases, test_case_groups=groups, phases=phases)


def _load_test_cases(data: dict[str, object]) -> dict[str, TestCaseDefinition]:
    raw_test_cases = data.get("test_cases")
    if not isinstance(raw_test_cases, dict) or not raw_test_cases:
        raise ConfigurationError(
            "Test plan must include a non-empty 'test_cases' mapping"
        )

    test_cases: dict[str, TestCaseDefinition] = {}
    for test_id, raw_test_case in raw_test_cases.items():
        if not isinstance(test_id, str):
            raise ConfigurationError("Test case ids must be strings")
        if not isinstance(raw_test_case, dict):
            raise ConfigurationError(f"Test case '{test_id}' must be a mapping")

        title = raw_test_case.get("title")
        job = raw_test_case.get("job")
        if not isinstance(title, str) or not title:
            raise ConfigurationError(
                f"Test case '{test_id}' must include non-empty 'title'"
            )
        if not isinstance(job, str) or not job:
            raise ConfigurationError(
                f"Test case '{test_id}' must include non-empty 'job'"
            )

        test_cases[test_id] = TestCaseDefinition(test_id=test_id, title=title, job=job)
    return test_cases


def _load_test_case_groups(data: dict[str, object]) -> dict[str, TestCaseGroup]:
    raw_groups = data.get("test_case_groups")
    if not isinstance(raw_groups, dict) or not raw_groups:
        raise ConfigurationError(
            "Test plan must include a non-empty 'test_case_groups' mapping"
        )

    groups: dict[str, TestCaseGroup] = {}
    for group_name, raw_group in raw_groups.items():
        if not isinstance(group_name, str):
            raise ConfigurationError("Test case group names must be strings")
        if not isinstance(raw_group, dict):
            raise ConfigurationError(
                f"Test case group '{group_name}' must be a mapping"
            )

        tests = raw_group.get("tests")
        if not isinstance(tests, list) or not tests:
            raise ConfigurationError(
                f"Test case group '{group_name}' must include non-empty 'tests'"
            )
        if not all(isinstance(test_id, str) and test_id for test_id in tests):
            raise ConfigurationError(
                f"Test case group '{group_name}' includes invalid test id values"
            )

        groups[group_name] = TestCaseGroup(name=group_name, tests=tests)
    return groups


def _load_phases(data: dict[str, object]) -> dict[str, Phase]:
    raw_phases = data.get("phases")
    if not isinstance(raw_phases, dict) or not raw_phases:
        raise ConfigurationError("Test plan must include a non-empty 'phases' mapping")

    phases: dict[str, Phase] = {}
    for phase_name, raw_phase in raw_phases.items():
        if not isinstance(phase_name, str):
            raise ConfigurationError("Phase names must be strings")
        if not isinstance(raw_phase, dict):
            raise ConfigurationError(f"Phase '{phase_name}' must be a mapping")

        test_case_groups = raw_phase.get("test_case_groups")
        if not isinstance(test_case_groups, list) or not test_case_groups:
            raise ConfigurationError(
                f"Phase '{phase_name}' must include non-empty 'test_case_groups'"
            )
        if not all(
            isinstance(group_name, str) and group_name
            for group_name in test_case_groups
        ):
            raise ConfigurationError(
                f"Phase '{phase_name}' includes invalid test case group names"
            )

        phases[phase_name] = Phase(name=phase_name, test_case_groups=test_case_groups)
    return phases


def _validate_test_case_group_references(
    groups: dict[str, TestCaseGroup],
    test_cases: dict[str, TestCaseDefinition],
) -> None:
    for group in groups.values():
        missing = [test_id for test_id in group.tests if test_id not in test_cases]
        if missing:
            raise ConfigurationError(
                f"Test case group '{group.name}' references undefined test ids:"
                f" {missing}"
            )


def _validate_phase_references(
    phases: dict[str, Phase],
    groups: dict[str, TestCaseGroup],
) -> None:
    for phase in phases.values():
        missing = [
            group_name
            for group_name in phase.test_case_groups
            if group_name not in groups
        ]
        if missing:
            raise ConfigurationError(
                f"Phase '{phase.name}' references undefined test case groups: {missing}"
            )

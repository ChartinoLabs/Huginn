"""YAML loaders for testbed and test plan files."""

from pathlib import Path
from typing import cast

import yaml

from huginn.models import (
    ConnectionDefinition,
    Device,
    Phase,
    TargetDefinition,
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
    return cast(dict[str, object], loaded)


def _require_mapping(value: object, error_message: str) -> dict[str, object]:
    """Validate and cast a YAML value as a dictionary mapping."""
    if not isinstance(value, dict):
        raise ConfigurationError(error_message)
    return cast(dict[str, object], value)


def _require_non_empty_string_list(value: object, error_message: str) -> list[str]:
    """Validate and cast a non-empty list of non-empty strings."""
    if not isinstance(value, list) or not value:
        raise ConfigurationError(error_message)
    if not all(isinstance(item, str) and item for item in value):
        raise ConfigurationError(error_message)
    return cast(list[str], value)


def _load_optional_string_list(value: object) -> list[str]:
    """Load an optional list of non-empty strings."""
    if value is None:
        return []
    return _require_non_empty_string_list(value, "Expected non-empty string list")


def _load_credentials(value: object) -> dict[str, dict[str, str]]:
    """Load optional credential mappings for a device."""
    if value is None:
        return {}

    credentials_mapping = _require_mapping(value, "credentials must be a mapping")
    credentials: dict[str, dict[str, str]] = {}
    for credential_name, raw_credential in credentials_mapping.items():
        if not isinstance(credential_name, str) or not credential_name:
            raise ConfigurationError("Credential names must be non-empty strings")
        credential_mapping = _require_mapping(
            raw_credential,
            f"Credential '{credential_name}' must be a mapping",
        )
        normalized: dict[str, str] = {}
        for key, credential_value in credential_mapping.items():
            if not isinstance(key, str) or not key:
                raise ConfigurationError(
                    f"Credential '{credential_name}' has an invalid key"
                )
            if not isinstance(credential_value, str):
                raise ConfigurationError(
                    f"Credential '{credential_name}' field '{key}' must be string"
                )
            normalized[key] = credential_value
        credentials[credential_name] = normalized
    return credentials


def _load_connections(
    device_name: str,
    value: object,
) -> dict[str, ConnectionDefinition]:
    """Load optional connection definitions for a device."""
    if value is None:
        return {}

    connections_mapping = _require_mapping(value, "connections must be a mapping")
    parsed_connections: dict[str, ConnectionDefinition] = {}
    for connection_name, raw_connection in connections_mapping.items():
        parsed_connections[connection_name] = _parse_connection_definition(
            device_name=device_name,
            connection_name=connection_name,
            raw_connection=raw_connection,
        )

    return parsed_connections


def _parse_connection_definition(
    *,
    device_name: str,
    connection_name: object,
    raw_connection: object,
) -> ConnectionDefinition:
    """Parse and validate one device connection entry."""
    if not isinstance(connection_name, str) or not connection_name:
        raise ConfigurationError("Connection names must be non-empty strings")

    connection_mapping = _require_mapping(
        raw_connection,
        f"Connection '{connection_name}' on '{device_name}' must be a mapping",
    )

    protocol = _require_non_empty_string(
        connection_mapping.get("protocol"),
        f"Connection '{connection_name}' on '{device_name}' must define protocol",
    )
    host = _require_non_empty_string(
        connection_mapping.get("host"),
        f"Connection '{connection_name}' on '{device_name}' must define host",
    )
    port = _require_int(
        connection_mapping.get("port", 22),
        f"Connection '{connection_name}' on '{device_name}' port must be int",
    )
    credential = _require_optional_string(
        connection_mapping.get("credential"),
        (
            f"Connection '{connection_name}' on '{device_name}' credential "
            "must be string"
        ),
    )

    options = {
        key: option_value
        for key, option_value in connection_mapping.items()
        if key not in {"protocol", "host", "port", "credential"}
    }
    return ConnectionDefinition(
        name=connection_name,
        protocol=protocol,
        host=host,
        port=port,
        credential=credential,
        options=options,
    )


def _require_non_empty_string(value: object, error_message: str) -> str:
    """Validate and cast a required non-empty string."""
    if not isinstance(value, str) or not value:
        raise ConfigurationError(error_message)
    return value


def _require_optional_string(value: object, error_message: str) -> str | None:
    """Validate and cast an optional string value."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigurationError(error_message)
    return value


def _require_int(value: object, error_message: str) -> int:
    """Validate and cast a required integer value."""
    if not isinstance(value, int):
        raise ConfigurationError(error_message)
    return value


def _load_target_definition(
    value: object,
    test_id: str,
) -> TargetDefinition | None:
    """Load optional test-case-level target definition."""
    if value is None:
        return None

    target_mapping = _require_mapping(
        value,
        f"Test case '{test_id}' target must be a mapping",
    )
    devices_value = target_mapping.get("devices")
    if devices_value is None:
        return TargetDefinition(devices=None)

    devices = _require_non_empty_string_list(
        devices_value,
        f"Test case '{test_id}' target.devices must be a non-empty list of strings",
    )
    return TargetDefinition(devices=devices)


def load_testbed(path: Path) -> Testbed:
    """Load a testbed file with minimal first-slice validation."""
    data = _load_yaml(path)
    raw_devices = _require_mapping(
        data.get("devices"),
        "Testbed must include a non-empty 'devices' mapping",
    )
    if not raw_devices:
        raise ConfigurationError("Testbed must include a non-empty 'devices' mapping")

    devices: dict[str, Device] = {}
    for device_name, raw_device in raw_devices.items():
        if not isinstance(device_name, str):
            raise ConfigurationError("Device names must be strings")
        device_mapping = _require_mapping(
            raw_device,
            f"Device '{device_name}' must be a mapping",
        )
        os_name = device_mapping.get("os")
        if not isinstance(os_name, str) or not os_name:
            raise ConfigurationError(
                f"Device '{device_name}' must define non-empty 'os'"
            )
        devices[device_name] = Device(
            name=device_name,
            os=os_name,
            groups=_load_optional_string_list(device_mapping.get("groups")),
            credentials=_load_credentials(device_mapping.get("credentials")),
            connections=_load_connections(
                device_name,
                device_mapping.get("connections"),
            ),
        )

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
    raw_test_cases = _require_mapping(
        data.get("test_cases"),
        "Test plan must include a non-empty 'test_cases' mapping",
    )
    if not raw_test_cases:
        raise ConfigurationError(
            "Test plan must include a non-empty 'test_cases' mapping"
        )

    test_cases: dict[str, TestCaseDefinition] = {}
    for test_id, raw_test_case in raw_test_cases.items():
        if not isinstance(test_id, str):
            raise ConfigurationError("Test case ids must be strings")
        test_case_mapping = _require_mapping(
            raw_test_case,
            f"Test case '{test_id}' must be a mapping",
        )

        title = test_case_mapping.get("title")
        job = test_case_mapping.get("job")
        target = _load_target_definition(test_case_mapping.get("target"), test_id)
        if not isinstance(title, str) or not title:
            raise ConfigurationError(
                f"Test case '{test_id}' must include non-empty 'title'"
            )
        if not isinstance(job, str) or not job:
            raise ConfigurationError(
                f"Test case '{test_id}' must include non-empty 'job'"
            )

        test_cases[test_id] = TestCaseDefinition(
            test_id=test_id,
            title=title,
            job=job,
            target=target,
        )
    return test_cases


def _load_test_case_groups(data: dict[str, object]) -> dict[str, TestCaseGroup]:
    raw_groups = _require_mapping(
        data.get("test_case_groups"),
        "Test plan must include a non-empty 'test_case_groups' mapping",
    )
    if not raw_groups:
        raise ConfigurationError(
            "Test plan must include a non-empty 'test_case_groups' mapping"
        )

    groups: dict[str, TestCaseGroup] = {}
    for group_name, raw_group in raw_groups.items():
        groups[group_name] = _parse_test_case_group(group_name, raw_group)
    return groups


def _parse_test_case_group(group_name: object, raw_group: object) -> TestCaseGroup:
    """Parse and validate one test case group mapping entry."""
    if not isinstance(group_name, str):
        raise ConfigurationError("Test case group names must be strings")

    group_mapping = _require_mapping(
        raw_group,
        f"Test case group '{group_name}' must be a mapping",
    )
    tests = _require_non_empty_string_list(
        group_mapping.get("tests"),
        f"Test case group '{group_name}' must include non-empty 'tests'",
    )
    return TestCaseGroup(name=group_name, tests=tests)


def _load_phases(data: dict[str, object]) -> dict[str, Phase]:
    raw_phases = _require_mapping(
        data.get("phases"),
        "Test plan must include a non-empty 'phases' mapping",
    )
    if not raw_phases:
        raise ConfigurationError("Test plan must include a non-empty 'phases' mapping")

    phases: dict[str, Phase] = {}
    for phase_name, raw_phase in raw_phases.items():
        phases[phase_name] = _parse_phase(phase_name, raw_phase)
    return phases


def _parse_phase(phase_name: object, raw_phase: object) -> Phase:
    """Parse and validate one phase mapping entry."""
    if not isinstance(phase_name, str):
        raise ConfigurationError("Phase names must be strings")

    phase_mapping = _require_mapping(
        raw_phase,
        f"Phase '{phase_name}' must be a mapping",
    )
    test_case_groups = _require_non_empty_string_list(
        phase_mapping.get("test_case_groups"),
        f"Phase '{phase_name}' must include non-empty 'test_case_groups'",
    )
    return Phase(name=phase_name, test_case_groups=test_case_groups)


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

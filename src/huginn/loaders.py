"""YAML loaders for testbed and test plan files."""

from pathlib import Path
from typing import cast

import yaml

from huginn.enums import ConnectionProtocol
from huginn.models import (
    ConnectionDefinition,
    CredentialFields,
    CredentialMap,
    Device,
    ExecutionStrategy,
    Phase,
    Scenario,
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
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Failed to parse YAML file {path}: {exc}") from exc
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


def _load_optional_string_list_allow_empty_strings(value: object) -> list[str]:
    """Load an optional list of non-empty strings, allowing empty list values."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigurationError("Expected string list")
    if not all(isinstance(item, str) and item for item in value):
        raise ConfigurationError("Expected string list")
    return cast(list[str], value)


def _load_optional_string_list_allow_empty(value: object) -> list[str]:
    """Load an optional list of non-empty strings, allowing empty list."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigurationError("Expected string list")
    if not all(isinstance(item, str) and item for item in value):
        raise ConfigurationError("Expected string list")
    return cast(list[str], value)


def _load_credentials(value: object) -> CredentialMap:
    """Load optional credential mappings for a device."""
    if value is None:
        return {}

    credentials_mapping = _require_mapping(value, "credentials must be a mapping")
    credentials: CredentialMap = {}
    for credential_name, raw_credential in credentials_mapping.items():
        if not isinstance(credential_name, str) or not credential_name:
            raise ConfigurationError("Credential names must be non-empty strings")
        credential_mapping = _require_mapping(
            raw_credential,
            f"Credential '{credential_name}' must be a mapping",
        )
        normalized: CredentialFields = {}
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

    protocol_value = _require_non_empty_string(
        connection_mapping.get("protocol"),
        f"Connection '{connection_name}' on '{device_name}' must define protocol",
    )
    protocol = _load_connection_protocol(
        protocol=protocol_value,
        device_name=device_name,
        connection_name=connection_name,
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

    options: dict[str, object] = {}
    for key, option_value in connection_mapping.items():
        if not isinstance(key, str):
            raise ConfigurationError(
                f"Connection '{connection_name}' on '{device_name}' has invalid key"
            )
        if key in {"protocol", "host", "port", "credential"}:
            continue
        options[key] = option_value
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


def _load_connection_protocol(
    *,
    protocol: str,
    device_name: str,
    connection_name: str,
) -> ConnectionProtocol:
    """Validate and parse a connection protocol identifier."""
    try:
        return ConnectionProtocol(protocol)
    except ValueError as error:
        supported = ", ".join(member.value for member in ConnectionProtocol)
        raise ConfigurationError(
            f"Connection '{connection_name}' on '{device_name}' has unsupported "
            f"protocol '{protocol}'. Supported: {supported}"
        ) from error


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
    context_name: str,
) -> TargetDefinition | None:
    """Load optional target definition for a plan object."""
    if value is None:
        return None

    target_mapping = _require_mapping(
        value,
        f"{context_name} target must be a mapping",
    )
    devices = _load_target_selector_values(
        target_mapping.get("devices"),
        context_name=context_name,
        field_name="devices",
    )
    groups = _load_target_selector_values(
        target_mapping.get("groups"),
        context_name=context_name,
        field_name="groups",
    )
    os_values = _load_target_selector_values(
        target_mapping.get("os"),
        context_name=context_name,
        field_name="os",
    )
    target = TargetDefinition(devices=devices, groups=groups, os=os_values)
    _validate_target_selector_exclusivity(context_name=context_name, target=target)
    return target


def _load_target_selector_values(
    value: object,
    *,
    context_name: str,
    field_name: str,
) -> list[str] | None:
    """Load optional target selector list values."""
    if value is None:
        return None
    return _require_non_empty_string_list(
        value,
        (f"{context_name} target.{field_name} must be a non-empty list of strings"),
    )


def _validate_target_selector_exclusivity(
    *,
    context_name: str,
    target: TargetDefinition,
) -> None:
    """Enforce mutually exclusive explicit vs dynamic target selectors."""
    if target.devices is None:
        return
    if target.groups is None and target.os is None:
        return

    raise ConfigurationError(
        f"{context_name} cannot define target.devices together with "
        "target.groups and/or target.os. Use explicit device targets OR "
        "dynamic group/os selectors."
    )


def load_testbed(path: Path) -> Testbed:
    """Load a testbed file with minimal first-slice validation."""
    data = _load_yaml(path)
    global_credentials = _load_credentials(data.get("credentials"))
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
            credentials=_merge_credentials(
                global_credentials,
                _load_credentials(device_mapping.get("credentials")),
            ),
            connections=_load_connections(
                device_name,
                device_mapping.get("connections"),
            ),
        )

    return Testbed(devices=devices, credentials=global_credentials)


def _merge_credentials(
    global_credentials: CredentialMap,
    device_credentials: CredentialMap,
) -> CredentialMap:
    """Merge global credentials with device-local overrides."""
    merged = {name: dict(values) for name, values in global_credentials.items()}
    for name, values in device_credentials.items():
        merged[name] = dict(values)
    return merged


def load_test_plan(path: Path) -> TestPlan:
    """Load a test plan from a YAML file or a directory of YAML files."""
    if path.is_dir():
        return _load_test_plan_directory(path)
    return _load_test_plan_file(path)


def _load_test_plan_file(path: Path) -> TestPlan:
    """Load a single-file test plan with validation."""
    data = _load_yaml(path)

    test_cases = _load_test_cases(data)
    groups = _load_test_case_groups(data)
    scenarios = _load_scenarios(data)

    _validate_test_case_group_references(groups, test_cases)
    _validate_scenario_references(scenarios, groups)

    return TestPlan(
        test_cases=test_cases,
        test_case_groups=groups,
        scenarios=scenarios,
        name=_load_optional_metadata_string(data.get("name"), "name"),
        description=_load_optional_metadata_string(
            data.get("description"), "description"
        ),
        defaults=_load_optional_metadata_mapping(data.get("defaults"), "defaults"),
        data_model=_load_optional_metadata_mapping(
            data.get("data_model"), "data_model"
        ),
    )


def _load_optional_metadata_string(value: object, field: str) -> str | None:
    """Load an optional string metadata field from a test plan."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigurationError(f"Test plan '{field}' must be a string")
    return value


def _load_optional_metadata_mapping(
    value: object, field: str
) -> dict[str, object] | None:
    """Load an optional mapping metadata field from a test plan."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ConfigurationError(f"Test plan '{field}' must be a mapping")
    return cast(dict[str, object], value)


_SECTION_KEYS = frozenset({"test_cases", "test_case_groups", "scenarios"})
_METADATA_SCALAR_KEYS = frozenset({"name", "description"})
_METADATA_MAPPING_KEYS = frozenset({"defaults", "data_model"})
_RECOGNIZED_KEYS = _SECTION_KEYS | _METADATA_SCALAR_KEYS | _METADATA_MAPPING_KEYS


def discover_yaml_files(directory: Path) -> list[Path]:
    """Recursively discover YAML files, excluding _/. prefixed names."""
    files: list[Path] = []
    for pattern in ("**/*.yaml", "**/*.yml"):
        for path in sorted(directory.glob(pattern)):
            relative = path.relative_to(directory)
            if any(part.startswith(("_", ".")) for part in relative.parts):
                continue
            files.append(path)
    # Deduplicate (a file matching both patterns) and sort for determinism
    return sorted(set(files))


def _merge_section_maps(
    target: dict[str, object],
    source: dict[str, object],
    *,
    section_name: str,
    source_path: Path,
    registry: dict[str, Path],
) -> None:
    """Merge source mapping into target, raising on duplicate keys."""
    for key, value in source.items():
        if key in registry:
            raise ConfigurationError(
                f"Duplicate {section_name} key '{key}' defined in "
                f"{registry[key]} and {source_path}"
            )
        registry[key] = source_path
        target[key] = value


def _merge_metadata_scalar(
    data: dict[str, object],
    *,
    source_path: Path,
    scalars: dict[str, str],
    sources: dict[str, Path],
) -> None:
    """Extract and merge scalar metadata keys from one YAML file."""
    for key in _METADATA_SCALAR_KEYS:
        raw = data.get(key)
        if raw is None:
            continue
        if key in sources:
            raise ConfigurationError(
                f"Duplicate metadata '{key}' defined in "
                f"{sources[key]} and {source_path}"
            )
        if not isinstance(raw, str):
            raise ConfigurationError(
                f"Test plan '{key}' in {source_path} must be a string"
            )
        scalars[key] = raw
        sources[key] = source_path


def _merge_metadata_mapping(
    data: dict[str, object],
    *,
    source_path: Path,
    mappings: dict[str, dict[str, object]],
    sources: dict[str, Path],
) -> None:
    """Extract and merge mapping metadata keys from one YAML file."""
    for key in _METADATA_MAPPING_KEYS:
        raw = data.get(key)
        if raw is None:
            continue
        if key in sources:
            raise ConfigurationError(
                f"Duplicate metadata '{key}' defined in "
                f"{sources[key]} and {source_path}"
            )
        if not isinstance(raw, dict):
            raise ConfigurationError(
                f"Test plan '{key}' in {source_path} must be a mapping"
            )
        mappings[key] = cast(dict[str, object], raw)
        sources[key] = source_path


def _load_test_plan_directory(directory: Path) -> TestPlan:
    """Load and merge a directory of YAML files into a single TestPlan."""
    yaml_files = discover_yaml_files(directory)
    if not yaml_files:
        raise ConfigurationError(
            f"Test plan directory {directory} contains no YAML files"
        )

    merged_sections: dict[str, dict[str, object]] = {
        "test_cases": {},
        "test_case_groups": {},
        "scenarios": {},
    }
    section_registries: dict[str, dict[str, Path]] = {
        "test_cases": {},
        "test_case_groups": {},
        "scenarios": {},
    }
    metadata_scalars: dict[str, str] = {}
    metadata_scalar_sources: dict[str, Path] = {}
    metadata_mappings: dict[str, dict[str, object]] = {}
    metadata_mapping_sources: dict[str, Path] = {}

    for yaml_path in yaml_files:
        data = _load_yaml(yaml_path)

        for section_key in _SECTION_KEYS:
            raw = data.get(section_key)
            if raw is None:
                continue
            section_data = _require_mapping(
                raw,
                f"'{section_key}' in {yaml_path} must be a mapping",
            )
            _merge_section_maps(
                merged_sections[section_key],
                section_data,
                section_name=section_key,
                source_path=yaml_path,
                registry=section_registries[section_key],
            )

        _merge_metadata_scalar(
            data,
            source_path=yaml_path,
            scalars=metadata_scalars,
            sources=metadata_scalar_sources,
        )
        _merge_metadata_mapping(
            data,
            source_path=yaml_path,
            mappings=metadata_mappings,
            sources=metadata_mapping_sources,
        )

    combined_data: dict[str, object] = {
        key: section for key, section in merged_sections.items() if section
    }

    test_cases = _load_test_cases(combined_data)
    groups = _load_test_case_groups(combined_data)
    scenarios = _load_scenarios(combined_data)

    _validate_test_case_group_references(groups, test_cases)
    _validate_scenario_references(scenarios, groups)

    return TestPlan(
        test_cases=test_cases,
        test_case_groups=groups,
        scenarios=scenarios,
        name=metadata_scalars.get("name"),
        description=metadata_scalars.get("description"),
        defaults=metadata_mappings.get("defaults"),
        data_model=metadata_mappings.get("data_model"),
    )


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
        tags = _load_optional_string_list_allow_empty_strings(
            test_case_mapping.get("tags")
        )
        target = _load_target_definition(
            test_case_mapping.get("target"),
            f"Test case '{test_id}'",
        )
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
            tags=tags,
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
    group_includes: dict[str, list[str]] = {}
    for group_name, raw_group in raw_groups.items():
        group, includes = _parse_test_case_group(group_name, raw_group)
        groups[group_name] = group
        group_includes[group_name] = includes

    _validate_nested_group_references(groups, group_includes)
    _validate_nested_group_cycles(group_includes)
    return _flatten_nested_test_case_groups(groups, group_includes)


def _parse_test_case_group(
    group_name: object,
    raw_group: object,
) -> tuple[TestCaseGroup, list[str]]:
    """Parse and validate one test case group mapping entry."""
    if not isinstance(group_name, str):
        raise ConfigurationError("Test case group names must be strings")

    group_mapping = _require_mapping(
        raw_group,
        f"Test case group '{group_name}' must be a mapping",
    )
    tests = _load_optional_group_tests(
        group_mapping.get("tests"),
        group_name=group_name,
    )
    includes = _load_optional_group_includes(
        group_mapping.get("groups"),
        group_name=group_name,
    )
    exclude_tests = _load_optional_group_exclude_tests(
        group_mapping.get("exclude_tests"),
        group_name=group_name,
    )
    if not tests and not includes:
        raise ConfigurationError(
            f"Test case group '{group_name}' must include at least one of "
            "'tests' or 'groups'"
        )
    if exclude_tests and not includes:
        raise ConfigurationError(
            f"Test case group '{group_name}' defines 'exclude_tests' without "
            "'groups' -- exclude_tests only applies to inherited group tests"
        )
    tags = _load_optional_string_list_allow_empty_strings(group_mapping.get("tags"))
    strategy = _load_execution_strategy(
        group_mapping.get("strategy"),
        context_name=f"Test case group '{group_name}'",
    )
    target = _load_target_definition(
        group_mapping.get("target"),
        f"Test case group '{group_name}'",
    )
    display_name = _require_optional_string(
        group_mapping.get("name"),
        f"Test case group '{group_name}' name must be a string",
    )
    return (
        TestCaseGroup(
            identifier=group_name,
            tests=tests,
            name=display_name,
            tags=tags,
            target=target,
            strategy=strategy,
            exclude_tests=exclude_tests,
        ),
        includes,
    )


def _load_optional_group_tests(value: object, *, group_name: str) -> list[str]:
    """Load optional group tests list, allowing empty lists when groups exist."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigurationError(
            f"Test case group '{group_name}' must include non-empty 'tests'"
        )
    if not all(isinstance(item, str) and item for item in value):
        raise ConfigurationError(
            f"Test case group '{group_name}' must include non-empty 'tests'"
        )
    return cast(list[str], value)


def _load_optional_group_includes(value: object, *, group_name: str) -> list[str]:
    """Load optional nested group include list."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigurationError(
            f"Test case group '{group_name}' groups must be a list of strings"
        )
    if not all(isinstance(item, str) and item for item in value):
        raise ConfigurationError(
            f"Test case group '{group_name}' groups must be a list of strings"
        )
    return cast(list[str], value)


def _load_optional_group_exclude_tests(value: object, *, group_name: str) -> list[str]:
    """Load optional exclude_tests list for a test case group."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigurationError(
            f"Test case group '{group_name}' exclude_tests must be a list of strings"
        )
    if not all(isinstance(item, str) and item for item in value):
        raise ConfigurationError(
            f"Test case group '{group_name}' exclude_tests must be a list of strings"
        )
    return cast(list[str], value)


def _validate_nested_group_references(
    groups: dict[str, TestCaseGroup],
    group_includes: dict[str, list[str]],
) -> None:
    """Ensure nested group references point to defined groups."""
    for group_name, includes in group_includes.items():
        missing = [include for include in includes if include not in groups]
        if missing:
            raise ConfigurationError(
                f"Test case group '{group_name}' references undefined nested groups: "
                f"{missing}"
            )


def _validate_nested_group_cycles(group_includes: dict[str, list[str]]) -> None:
    """Ensure nested group includes form an acyclic graph."""
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(group_name: str, chain: list[str]) -> None:
        if group_name in visited:
            return
        if group_name in visiting:
            cycle_start = chain.index(group_name)
            cycle = chain[cycle_start:] + [group_name]
            raise ConfigurationError(
                "Nested test case group references form a cycle: " + " -> ".join(cycle)
            )

        visiting.add(group_name)
        chain.append(group_name)
        for include in group_includes[group_name]:
            visit(include, chain)
        chain.pop()
        visiting.remove(group_name)
        visited.add(group_name)

    for group_name in group_includes:
        visit(group_name, [])


def _flatten_nested_test_case_groups(
    groups: dict[str, TestCaseGroup],
    group_includes: dict[str, list[str]],
) -> dict[str, TestCaseGroup]:
    """Expand nested group includes into flattened test id lists."""
    cache: dict[str, list[str]] = {}

    def flatten(group_name: str) -> list[str]:
        if group_name in cache:
            return cache[group_name]

        group = groups[group_name]
        excluded = set(group.exclude_tests)

        flattened = list(group.tests)
        seen = set(flattened)
        for include in group_includes[group_name]:
            for test_id in flatten(include):
                if test_id in seen or test_id in excluded:
                    continue
                seen.add(test_id)
                flattened.append(test_id)

        cache[group_name] = flattened
        return flattened

    resolved: dict[str, TestCaseGroup] = {}
    for group_name, group in groups.items():
        resolved[group_name] = TestCaseGroup(
            identifier=group.identifier,
            tests=flatten(group_name),
            name=group.name,
            tags=group.tags,
            target=group.target,
            strategy=group.strategy,
            exclude_tests=group.exclude_tests,
        )
    return resolved


def _load_scenarios(data: dict[str, object]) -> dict[str, Scenario]:
    raw_scenarios = _require_mapping(
        data.get("scenarios"),
        "Test plan must include a non-empty 'scenarios' mapping",
    )
    if not raw_scenarios:
        raise ConfigurationError(
            "Test plan must include a non-empty 'scenarios' mapping"
        )

    scenarios: dict[str, Scenario] = {}
    for scenario_name, raw_scenario in raw_scenarios.items():
        scenarios[scenario_name] = _parse_scenario(scenario_name, raw_scenario)
    return scenarios


def _parse_scenario(scenario_name: object, raw_scenario: object) -> Scenario:
    """Parse and validate one scenario mapping entry."""
    if not isinstance(scenario_name, str):
        raise ConfigurationError("Scenario names must be strings")

    scenario_mapping = _require_mapping(
        raw_scenario,
        f"Scenario '{scenario_name}' must be a mapping",
    )
    raw_phases = _require_mapping(
        scenario_mapping.get("phases"),
        f"Scenario '{scenario_name}' must include a non-empty 'phases' mapping",
    )
    if not raw_phases:
        raise ConfigurationError(
            f"Scenario '{scenario_name}' must include a non-empty 'phases' mapping"
        )

    phases: dict[str, Phase] = {}
    for phase_name, raw_phase in raw_phases.items():
        phases[phase_name] = _parse_phase(scenario_name, phase_name, raw_phase)
    display_name = _require_optional_string(
        scenario_mapping.get("name"),
        f"Scenario '{scenario_name}' name must be a string",
    )
    return Scenario(identifier=scenario_name, phases=phases, name=display_name)


def _parse_phase(
    scenario_name: str,
    phase_name: object,
    raw_phase: object,
) -> Phase:
    """Parse and validate one phase mapping entry."""
    if not isinstance(phase_name, str):
        raise ConfigurationError("Phase names must be strings")

    phase_mapping = _require_mapping(
        raw_phase,
        f"Phase '{phase_name}' in scenario '{scenario_name}' must be a mapping",
    )
    test_case_groups = _require_non_empty_string_list(
        phase_mapping.get("test_case_groups"),
        (
            f"Phase '{phase_name}' in scenario '{scenario_name}' must include "
            "non-empty 'test_case_groups'"
        ),
    )
    depends_on = _load_optional_string_list_allow_empty(phase_mapping.get("depends_on"))
    strategy = _load_execution_strategy(
        phase_mapping.get("strategy"),
        context_name=f"Phase '{phase_name}' in scenario '{scenario_name}'",
    )
    target = _load_target_definition(
        phase_mapping.get("target"),
        f"Phase '{phase_name}' in scenario '{scenario_name}'",
    )
    display_name = _require_optional_string(
        phase_mapping.get("name"),
        f"Phase '{phase_name}' in scenario '{scenario_name}' name must be a string",
    )
    return Phase(
        identifier=phase_name,
        test_case_groups=test_case_groups,
        name=display_name,
        depends_on=depends_on,
        target=target,
        strategy=strategy,
    )


def _load_execution_strategy(value: object, *, context_name: str) -> ExecutionStrategy:
    """Load optional execution strategy mapping for phases/groups."""
    if value is None:
        return ExecutionStrategy(mode="parallel")

    strategy_mapping = _require_mapping(
        value,
        f"{context_name} strategy must be a mapping",
    )
    if not strategy_mapping:
        raise ConfigurationError(
            f"{context_name} strategy must define one of 'serial' or 'parallel'"
        )

    strategy_mode = _resolve_strategy_mode(strategy_mapping, context_name=context_name)
    if strategy_mode == "serial":
        return _load_serial_strategy(
            strategy_mapping=strategy_mapping,
            context_name=context_name,
        )

    parallel_value = strategy_mapping.get("parallel")
    return _load_parallel_strategy(parallel_value, context_name=context_name)


def _resolve_strategy_mode(
    strategy_mapping: dict[str, object],
    *,
    context_name: str,
) -> str:
    """Resolve and validate declared strategy mode key."""
    serial_present = "serial" in strategy_mapping
    parallel_present = "parallel" in strategy_mapping
    if serial_present and parallel_present:
        raise ConfigurationError(
            f"{context_name} strategy cannot define both 'serial' and 'parallel'"
        )
    if not serial_present and not parallel_present:
        raise ConfigurationError(
            f"{context_name} strategy must define one of 'serial' or 'parallel'"
        )
    return "serial" if serial_present else "parallel"


def _load_serial_strategy(
    *,
    strategy_mapping: dict[str, object],
    context_name: str,
) -> ExecutionStrategy:
    """Load strategy.serial and validate empty/null payload."""
    serial_value = strategy_mapping.get("serial")
    if serial_value not in (None, {}):
        raise ConfigurationError(
            f"{context_name} strategy.serial must be null or empty mapping"
        )
    return ExecutionStrategy(mode="serial")


def _load_parallel_strategy(
    parallel_value: object,
    *,
    context_name: str,
) -> ExecutionStrategy:
    """Load strategy.parallel and validate optional maximum setting."""
    if parallel_value is None:
        return ExecutionStrategy(mode="parallel")

    parallel_mapping = _require_mapping(
        parallel_value,
        f"{context_name} strategy.parallel must be null or a mapping",
    )
    unsupported_keys = [key for key in parallel_mapping if key != "maximum"]
    if unsupported_keys:
        raise ConfigurationError(
            f"{context_name} strategy.parallel has unsupported keys: {unsupported_keys}"
        )

    maximum_value = parallel_mapping.get("maximum")
    if maximum_value is None:
        return ExecutionStrategy(mode="parallel")
    if not isinstance(maximum_value, int) or maximum_value <= 0:
        raise ConfigurationError(
            f"{context_name} strategy.parallel.maximum must be a positive integer"
        )
    return ExecutionStrategy(mode="parallel", maximum=maximum_value)


def _validate_test_case_group_references(
    groups: dict[str, TestCaseGroup],
    test_cases: dict[str, TestCaseDefinition],
) -> None:
    for group in groups.values():
        missing = [test_id for test_id in group.tests if test_id not in test_cases]
        if missing:
            raise ConfigurationError(
                f"Test case group '{group.identifier}' references undefined test ids:"
                f" {missing}"
            )


def _validate_scenario_references(
    scenarios: dict[str, Scenario],
    groups: dict[str, TestCaseGroup],
) -> None:
    for scenario in scenarios.values():
        for phase in scenario.phases.values():
            missing = [
                group_name
                for group_name in phase.test_case_groups
                if group_name not in groups
            ]
            if missing:
                raise ConfigurationError(
                    f"Phase '{phase.identifier}' in scenario '{scenario.identifier}' "
                    "references "
                    f"undefined test case groups: {missing}"
                )

            missing_phase_dependencies = [
                phase_name
                for phase_name in phase.depends_on
                if phase_name not in scenario.phases
            ]
            if missing_phase_dependencies:
                raise ConfigurationError(
                    f"Phase '{phase.identifier}' in scenario '{scenario.identifier}' "
                    "references "
                    "undefined depends_on phases: "
                    f"{missing_phase_dependencies}"
                )

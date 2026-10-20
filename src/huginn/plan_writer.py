"""Add test cases, groups and phase references to a test plan directory.

Shared by the commands that grow a test plan (`huginn inject` and
`huginn import`). Each helper loads one YAML file, changes it, and writes it
back only when something changed. Files are written with PyYAML, so comments
in a file that a helper rewrites are not kept.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import cast

import yaml

from huginn.loaders import discover_yaml_files


class PlanWriteError(ValueError):
    """Raised when the test plan files cannot be updated."""


def cases_file_path(plan_path: Path, name: str) -> Path:
    """Return the file under ``test_cases/`` that holds a set of test cases."""
    return plan_path / "test_cases" / f"{name}.yaml"


def groups_file_path(plan_path: Path, name: str) -> Path:
    """Return the file under ``groups/`` that holds a set of groups."""
    return plan_path / "groups" / f"{name}.yaml"


def write_test_cases(
    path: Path, test_cases: Mapping[str, Mapping[str, object]]
) -> None:
    """Add or replace test case definitions in one YAML file."""
    data = load_raw_yaml(path) if path.exists() else {}
    existing = cast(dict[str, object], data.get("test_cases", {}))
    for test_id, entry in test_cases.items():
        existing[test_id] = dict(entry)
    data["test_cases"] = existing
    write_yaml(path, data)


def write_group(path: Path, group_id: str, entry: Mapping[str, object]) -> None:
    """Add or replace one group definition in one YAML file."""
    data = load_raw_yaml(path) if path.exists() else {}
    groups = cast(dict[str, object], data.get("test_case_groups", {}))
    groups[group_id] = dict(entry)
    data["test_case_groups"] = groups
    write_yaml(path, data)


def find_group_file(plan_path: Path, group_id: str) -> Path | None:
    """Return the file directly under ``groups/`` that defines a group."""
    for path in _group_files(plan_path):
        data = load_raw_yaml(path)
        groups = data.get("test_case_groups")
        if isinstance(groups, dict) and isinstance(groups.get(group_id), dict):
            return path
    return None


def extend_group(
    plan_path: Path,
    group_id: str,
    *,
    tests: Iterable[str] = (),
    groups: Iterable[str] = (),
) -> bool:
    """Append tests and child groups to a group defined under ``groups/``.

    IDs the group already lists are not added again.

    Returns:
        False if no file directly under ``groups/`` defines the group.
    """
    path = find_group_file(plan_path, group_id)
    if path is None:
        return False
    data = load_raw_yaml(path)
    group = cast(
        dict[str, object], cast(dict[str, object], data["test_case_groups"])[group_id]
    )
    changed = _append_missing(group, "tests", tests)
    changed = _append_missing(group, "groups", groups) or changed
    if changed:
        write_yaml(path, data)
    return True


def add_group_to_phases(plan_path: Path, group_id: str, phases: Iterable[str]) -> None:
    """Add a group to each named phase, in every scenario that has the phase.

    Raises:
        PlanWriteError: If the plan has no scenarios file, or the file has no
            ``scenarios`` mapping.
    """
    path = find_scenarios_file(plan_path)
    data = load_raw_yaml(path)
    scenarios = data.get("scenarios")
    if not isinstance(scenarios, dict):
        raise PlanWriteError("No scenarios mapping found in scenarios file")

    wanted = list(phases)
    changed = False
    for scenario in cast(dict[str, object], scenarios).values():
        if not isinstance(scenario, dict):
            continue
        raw_phases = cast(dict[str, object], scenario).get("phases")
        if not isinstance(raw_phases, dict):
            continue
        for name in wanted:
            phase = cast(dict[str, object], raw_phases).get(name)
            if isinstance(phase, dict):
                changed = (
                    _append_missing(
                        cast(dict[str, object], phase), "test_case_groups", [group_id]
                    )
                    or changed
                )
    if changed:
        write_yaml(path, data)


def find_scenarios_file(plan_path: Path) -> Path:
    """Locate the scenarios YAML file in a test plan directory.

    Raises:
        PlanWriteError: If there is no ``scenarios*.yaml`` file.
    """
    path = plan_path / "scenarios.yaml"
    if path.exists():
        return path
    candidates = list(plan_path.glob("scenarios*.yaml"))
    if candidates:
        return candidates[0]
    raise PlanWriteError("No scenarios.yaml found in test plan")


def load_raw_yaml(path: Path) -> dict[str, object]:
    """Load a YAML file into a raw dictionary.

    Raises:
        PlanWriteError: If the root of the file is not a mapping.
    """
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise PlanWriteError(f"Expected mapping at root of {path}")
    return cast(dict[str, object], loaded)


def write_yaml(path: Path, data: Mapping[str, object]) -> None:
    """Write a dictionary to a YAML file, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(dict(data), default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def _group_files(plan_path: Path) -> list[Path]:
    directory = plan_path / "groups"
    return list(directory.glob("*.yaml")) + list(directory.glob("*.yml"))


def _append_missing(
    mapping: dict[str, object], key: str, values: Iterable[str]
) -> bool:
    """Append values missing from ``mapping[key]``, creating the list if needed."""
    new = list(values)
    if not new:
        return False
    current = mapping.get(key)
    items = cast(list[str], current) if isinstance(current, list) else []
    added = [value for value in new if value not in items]
    if not added:
        return False
    items.extend(added)
    mapping[key] = items
    return True


def extend_test_case_target(
    plan_path: Path, test_id: str, field: str, values: Iterable[str]
) -> bool:
    """Append values to ``target.<field>`` of a test case anywhere in the plan.

    Returns:
        False if no YAML file in the plan directory defines the test case
        with a ``target.<field>`` list.
    """
    for path in discover_yaml_files(plan_path):
        data = load_raw_yaml(path)
        test_cases = data.get("test_cases")
        if not isinstance(test_cases, dict):
            continue
        entry = cast(dict[str, object], test_cases).get(test_id)
        if not isinstance(entry, dict):
            continue
        target = cast(dict[str, object], entry).get("target")
        if not isinstance(target, dict) or not isinstance(target.get(field), list):
            return False
        if _append_missing(cast(dict[str, object], target), field, values):
            write_yaml(path, data)
        return True
    return False

"""Prune non-applicable test cases and device targets from a test plan."""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import cast

import yaml
from ruamel.yaml import YAML

_ruamel = YAML()
_ruamel.preserve_quotes = True

from huginn.loaders import ConfigurationError, discover_yaml_files, load_test_plan
from huginn.models import TestPlan
from huginn.output import Output


class PruneError(ValueError):
    """Raised when pruning cannot proceed."""


@dataclass(frozen=True)
class NotApplicableTestCase:
    """A test case with one or more non-applicable devices."""

    test_id: str
    group_id: str
    scenario_id: str
    not_applicable_devices: dict[str, str]
    applicable_devices: list[str]


@dataclass(frozen=True)
class PruneInput:
    """Parsed applicability data from a learning run."""

    partial_tests: list[NotApplicableTestCase]
    full_tests: list[NotApplicableTestCase]


@dataclass(frozen=True)
class PrunePlan:
    """The complete set of prune changes to apply."""

    exclude_devices_updates: dict[str, list[str]]
    exclude_from_groups: dict[str, list[str]]
    skipped_already_pruned: list[str]
    orphaned_test_cases: list[str] = field(default_factory=list)


def _parse_results_dir_timestamp(name: str) -> datetime:
    """Parse the timestamp from a results directory name."""
    stem = name.removesuffix("-learning")
    if stem == name:
        parts = name.rsplit("-learning-", 1)
        stem = parts[0]
    return datetime.strptime(stem, "%Y-%b-%d-%H-%M-%S")


def find_latest_learning_results(results_dir: Path) -> Path:
    """Find the most recent learning run directory and return its run.json path."""
    if not results_dir.is_dir():
        raise PruneError(f"Results directory does not exist: {results_dir}")

    candidates = sorted(
        (
            entry
            for entry in results_dir.iterdir()
            if entry.is_dir() and entry.name.endswith("-learning")
        ),
        key=lambda p: _parse_results_dir_timestamp(p.name),
    )
    if not candidates:
        raise PruneError(
            f"No learning run directories found in {results_dir}. "
            "Run tests in learning mode first."
        )

    run_json = candidates[-1] / "run.json"
    if not run_json.is_file():
        raise PruneError(f"run.json not found in {candidates[-1]}")
    return run_json


def parse_applicability_from_run(run_json_path: Path) -> PruneInput:
    """Read learning results and extract non-applicable device information."""
    raw = json.loads(run_json_path.read_text(encoding="utf-8"))
    run_dir = run_json_path.parent

    partial_tests: list[NotApplicableTestCase] = []
    full_tests: list[NotApplicableTestCase] = []
    seen_test_ids: set[str] = set()

    for scenario in raw.get("scenarios", []):
        scenario_id = scenario["id"]
        for phase in scenario.get("phases", []):
            for group in phase.get("test_case_groups", []):
                group_id = group["id"]
                for test_case in group.get("test_cases", []):
                    test_id = test_case["test_id"]
                    if test_id in seen_test_ids:
                        continue

                    result_path = test_case.get("result_path")
                    if result_path is None:
                        continue

                    detail = _load_test_case_detail(run_dir / result_path)
                    if detail is None:
                        continue

                    na_devices = detail.get("not_applicable_devices", {})
                    if not na_devices:
                        continue

                    seen_test_ids.add(test_id)
                    all_devices = _extract_all_devices(detail)
                    applicable = [
                        d for d in all_devices
                        if d not in na_devices
                    ]

                    entry = NotApplicableTestCase(
                        test_id=test_id,
                        group_id=group_id,
                        scenario_id=scenario_id,
                        not_applicable_devices=dict(na_devices),
                        applicable_devices=applicable,
                    )

                    if applicable:
                        partial_tests.append(entry)
                    else:
                        full_tests.append(entry)

    return PruneInput(partial_tests=partial_tests, full_tests=full_tests)


def _load_test_case_detail(path: Path) -> dict[str, object] | None:
    """Load a test case result.json, returning None on failure."""
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _extract_all_devices(detail: dict[str, object]) -> list[str]:
    """Extract all device names that participated in this test case.

    Uses command_executions as the primary source (most reliable), then
    falls back to not_applicable_devices keys for tests where commands
    were never executed (e.g., all devices filtered by check_command_support).
    """
    devices: list[str] = []
    seen: set[str] = set()

    for ce in detail.get("command_executions", []):
        if not isinstance(ce, dict):
            continue
        name = ce.get("device")
        if isinstance(name, str) and name not in seen:
            devices.append(name)
            seen.add(name)

    na_devices = detail.get("not_applicable_devices", {})
    if isinstance(na_devices, dict):
        for name in na_devices:
            if name not in seen:
                devices.append(name)
                seen.add(name)

    return devices


def compute_prune_plan(
    prune_input: PruneInput,
    test_plan: TestPlan,
    *,
    remove_orphans: bool = False,
) -> PrunePlan:
    """Compute all prune changes without performing I/O."""
    exclude_devices_updates: dict[str, list[str]] = {}
    exclude_from_groups: dict[str, list[str]] = {}
    skipped: list[str] = []

    for entry in prune_input.partial_tests:
        tc_def = test_plan.test_cases.get(entry.test_id)
        if tc_def is None:
            continue

        na_device_names = sorted(entry.not_applicable_devices.keys())
        existing_excludes = (
            tc_def.target.exclude_devices if tc_def.target and tc_def.target.exclude_devices else []
        )
        if set(na_device_names).issubset(set(existing_excludes)):
            skipped.append(entry.test_id)
            continue

        merged = sorted(set(existing_excludes) | set(na_device_names))
        exclude_devices_updates[entry.test_id] = merged

    for entry in prune_input.full_tests:
        for group_id, group in test_plan.test_case_groups.items():
            if entry.test_id in group.tests:
                if entry.test_id in group.exclude_tests:
                    skipped.append(entry.test_id)
                    continue
                exclude_from_groups.setdefault(group_id, []).append(entry.test_id)

    orphaned: list[str] = []
    if remove_orphans:
        removed_ids = {tid for tids in exclude_from_groups.values() for tid in tids}
        for test_id in removed_ids:
            still_referenced = False
            for group in test_plan.test_case_groups.values():
                if test_id not in group.tests:
                    continue
                if test_id in group.exclude_tests:
                    continue
                group_removals = exclude_from_groups.get(group.identifier, [])
                if test_id not in group_removals:
                    still_referenced = True
                    break
            if not still_referenced:
                orphaned.append(test_id)
        orphaned.sort()

    return PrunePlan(
        exclude_devices_updates=exclude_devices_updates,
        exclude_from_groups=exclude_from_groups,
        skipped_already_pruned=skipped,
        orphaned_test_cases=orphaned,
    )


def apply_prune_plan(
    *,
    plan_path: Path,
    prune_plan: PrunePlan,
    output: Output,
) -> None:
    """Apply prune changes to test plan YAML files."""
    if plan_path.is_file():
        _apply_single_file(plan_path, prune_plan, output)
    elif plan_path.is_dir():
        _apply_directory(plan_path, prune_plan, output)
    else:
        raise PruneError(f"Test plan path does not exist: {plan_path}")


def validate_after_prune(plan_path: Path) -> None:
    """Load the modified test plan to verify it is still valid."""
    try:
        load_test_plan(plan_path)
    except ConfigurationError as error:
        raise PruneError(
            f"Pruned test plan failed validation: {error}"
        ) from error


def _apply_single_file(
    plan_path: Path,
    prune_plan: PrunePlan,
    output: Output,
) -> None:
    """Apply prune changes to a single YAML file."""
    data = _load_raw_yaml(plan_path)
    _apply_exclude_devices(data, prune_plan, output)
    _apply_exclude_from_groups(data, prune_plan, output)
    _remove_orphaned_test_cases(data, prune_plan.orphaned_test_cases)
    _write_yaml(plan_path, data)


def _apply_directory(
    plan_dir: Path,
    prune_plan: PrunePlan,
    output: Output,
) -> None:
    """Apply prune changes to a directory of YAML files."""
    if prune_plan.exclude_devices_updates:
        tc_file_map = _find_test_case_files(plan_dir)
        files_to_write: dict[Path, dict[str, object]] = {}

        for test_id, devices in prune_plan.exclude_devices_updates.items():
            file_path = tc_file_map.get(test_id)
            if file_path is None:
                output.warning(
                    f"Cannot locate YAML file containing test case '{test_id}'"
                )
                continue

            if file_path not in files_to_write:
                files_to_write[file_path] = _load_raw_yaml(file_path)

            data = files_to_write[file_path]
            _set_exclude_devices_on_test_case(data, test_id, devices)

        for file_path, data in files_to_write.items():
            _write_yaml(file_path, data)

    if prune_plan.exclude_from_groups:
        group_file_map = _find_group_files(plan_dir)
        files_to_write_groups: dict[Path, dict[str, object]] = {}

        for group_id, test_ids in prune_plan.exclude_from_groups.items():
            file_path = group_file_map.get(group_id)
            if file_path is None:
                output.warning(
                    f"Cannot locate YAML file containing group '{group_id}'"
                )
                continue

            if file_path not in files_to_write_groups:
                files_to_write_groups[file_path] = _load_raw_yaml(file_path)

            data = files_to_write_groups[file_path]
            _add_exclude_tests_to_group(data, group_id, test_ids)

        for file_path, data in files_to_write_groups.items():
            _write_yaml(file_path, data)

    if prune_plan.orphaned_test_cases:
        tc_file_map = (
            tc_file_map
            if prune_plan.exclude_devices_updates
            else _find_test_case_files(plan_dir)
        )
        orphan_files: dict[Path, dict[str, object]] = {}
        for test_id in prune_plan.orphaned_test_cases:
            file_path = tc_file_map.get(test_id)
            if file_path is None:
                continue
            if file_path not in orphan_files:
                orphan_files[file_path] = _load_raw_yaml(file_path)
            _remove_orphaned_test_cases(
                orphan_files[file_path], [test_id],
            )
        for file_path, data in orphan_files.items():
            _write_yaml(file_path, data)


def _apply_exclude_devices(
    data: dict[str, object],
    prune_plan: PrunePlan,
    output: Output,
) -> None:
    """Apply exclude_devices updates to test cases in a raw YAML dict."""
    for test_id, devices in prune_plan.exclude_devices_updates.items():
        _set_exclude_devices_on_test_case(data, test_id, devices)


def _apply_exclude_from_groups(
    data: dict[str, object],
    prune_plan: PrunePlan,
    output: Output,
) -> None:
    """Apply exclude_tests additions to groups in a raw YAML dict."""
    for group_id, test_ids in prune_plan.exclude_from_groups.items():
        _add_exclude_tests_to_group(data, group_id, test_ids)


def _set_exclude_devices_on_test_case(
    data: dict[str, object],
    test_id: str,
    devices: list[str],
) -> None:
    """Set exclude_devices on a test case's target within raw YAML data."""
    raw_test_cases = data.get("test_cases")
    if not isinstance(raw_test_cases, dict):
        return

    raw_tc = raw_test_cases.get(test_id)
    if not isinstance(raw_tc, dict):
        return

    tc_dict = cast(dict[str, object], raw_tc)
    target = tc_dict.get("target")
    if target is None:
        tc_dict["target"] = {"exclude_devices": devices}
    elif isinstance(target, dict):
        target["exclude_devices"] = devices


def _add_exclude_tests_to_group(
    data: dict[str, object],
    group_id: str,
    test_ids: list[str],
) -> None:
    """Remove fully N/A test IDs from a group.

    For composite groups (those with a ``groups`` key for inheritance),
    add to ``exclude_tests``. For leaf groups (those with only ``tests``),
    remove the test IDs from the ``tests`` list directly.
    """
    raw_groups = data.get("test_case_groups")
    if not isinstance(raw_groups, dict):
        return

    raw_group = raw_groups.get(group_id)
    if not isinstance(raw_group, dict):
        return

    group_dict = cast(dict[str, object], raw_group)
    has_groups_inheritance = "groups" in group_dict

    if has_groups_inheritance:
        existing = group_dict.get("exclude_tests")
        if existing is None:
            group_dict["exclude_tests"] = list(test_ids)
        elif isinstance(existing, list):
            for tid in test_ids:
                if tid not in existing:
                    existing.append(tid)
    else:
        tests_list = group_dict.get("tests")
        if isinstance(tests_list, list):
            for tid in test_ids:
                while tid in tests_list:
                    tests_list.remove(tid)


def _remove_orphaned_test_cases(
    data: dict[str, object],
    test_ids: list[str],
) -> None:
    """Remove test case definitions from raw YAML data."""
    raw_test_cases = data.get("test_cases")
    if not isinstance(raw_test_cases, dict):
        return
    for test_id in test_ids:
        raw_test_cases.pop(test_id, None)


def _find_test_case_files(plan_dir: Path) -> dict[str, Path]:
    """Map test case IDs to the YAML files that define them."""
    tc_map: dict[str, Path] = {}
    for yaml_path in discover_yaml_files(plan_dir):
        data = _load_raw_yaml(yaml_path)
        raw_tcs = data.get("test_cases")
        if not isinstance(raw_tcs, dict):
            continue
        for tc_id in raw_tcs:
            if isinstance(tc_id, str):
                tc_map[tc_id] = yaml_path
    return tc_map


def _find_group_files(plan_dir: Path) -> dict[str, Path]:
    """Map group IDs to the YAML files that define them."""
    group_map: dict[str, Path] = {}
    for yaml_path in discover_yaml_files(plan_dir):
        data = _load_raw_yaml(yaml_path)
        raw_groups = data.get("test_case_groups")
        if not isinstance(raw_groups, dict):
            continue
        for group_id in raw_groups:
            if isinstance(group_id, str):
                group_map[group_id] = yaml_path
    return group_map


def _load_raw_yaml(path: Path) -> dict[str, object]:
    """Load a YAML file preserving formatting for round-trip editing."""
    loaded = _ruamel.load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise PruneError(f"Expected mapping at root of {path}")
    return cast(dict[str, object], loaded)


def _write_yaml(path: Path, data: dict[str, object]) -> None:
    """Write a dictionary to a YAML file preserving original formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        _ruamel.dump(data, fh)

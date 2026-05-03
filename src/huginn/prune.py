"""Prune non-applicable test cases and device targets from a test plan."""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from ruamel.yaml import YAML

from huginn.loaders import ConfigurationError, discover_yaml_files, load_test_plan
from huginn.models import TestPlan
from huginn.output import Output

_ruamel = YAML()
_ruamel.preserve_quotes = True

# Raw YAML data loaded from files -- inherently dynamic, so ``Any``
# is the correct type for values.
RawYAML = dict[str, Any]


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
                    _collect_na_test_case(
                        test_case,
                        group_id=group_id,
                        scenario_id=scenario_id,
                        run_dir=run_dir,
                        seen=seen_test_ids,
                        partial=partial_tests,
                        full=full_tests,
                    )

    return PruneInput(partial_tests=partial_tests, full_tests=full_tests)


def _collect_na_test_case(
    test_case: RawYAML,
    *,
    group_id: str,
    scenario_id: str,
    run_dir: Path,
    seen: set[str],
    partial: list[NotApplicableTestCase],
    full: list[NotApplicableTestCase],
) -> None:
    """Process a single test case entry and append to partial/full lists."""
    test_id = test_case["test_id"]
    if not isinstance(test_id, str) or test_id in seen:
        return

    result_path = test_case.get("result_path")
    if not isinstance(result_path, str):
        return

    detail = _load_test_case_detail(run_dir / result_path)
    if detail is None:
        return

    na_devices = detail.get("not_applicable_devices", {})
    if not isinstance(na_devices, dict) or not na_devices:
        return

    seen.add(test_id)
    all_devices = _extract_all_devices(detail)
    applicable = [d for d in all_devices if d not in na_devices]

    entry = NotApplicableTestCase(
        test_id=test_id,
        group_id=group_id,
        scenario_id=scenario_id,
        not_applicable_devices=dict(na_devices),
        applicable_devices=applicable,
    )

    if applicable:
        partial.append(entry)
    else:
        full.append(entry)


def _load_test_case_detail(path: Path) -> RawYAML | None:
    """Load a test case result.json, returning None on failure."""
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _extract_all_devices(detail: RawYAML) -> list[str]:
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
        _compute_partial_entry(entry, test_plan, exclude_devices_updates, skipped)

    for entry in prune_input.full_tests:
        for group_id, group in test_plan.test_case_groups.items():
            if entry.test_id in group.tests:
                if entry.test_id in group.exclude_tests:
                    skipped.append(entry.test_id)
                    continue
                exclude_from_groups.setdefault(group_id, []).append(entry.test_id)

    orphaned = (
        _find_orphaned_tests(exclude_from_groups, test_plan) if remove_orphans else []
    )

    return PrunePlan(
        exclude_devices_updates=exclude_devices_updates,
        exclude_from_groups=exclude_from_groups,
        skipped_already_pruned=skipped,
        orphaned_test_cases=orphaned,
    )


def _compute_partial_entry(
    entry: NotApplicableTestCase,
    test_plan: TestPlan,
    updates: dict[str, list[str]],
    skipped: list[str],
) -> None:
    """Compute exclude_devices for a partially-applicable test case."""
    tc_def = test_plan.test_cases.get(entry.test_id)
    if tc_def is None:
        return

    na_device_names = sorted(entry.not_applicable_devices.keys())
    existing_excludes = (
        tc_def.target.exclude_devices
        if tc_def.target and tc_def.target.exclude_devices
        else []
    )
    if set(na_device_names).issubset(set(existing_excludes)):
        skipped.append(entry.test_id)
        return

    merged = sorted(set(existing_excludes) | set(na_device_names))
    updates[entry.test_id] = merged


def _find_orphaned_tests(
    exclude_from_groups: dict[str, list[str]],
    test_plan: TestPlan,
) -> list[str]:
    """Identify tests no longer referenced by any group after exclusions."""
    removed_ids = {tid for tids in exclude_from_groups.values() for tid in tids}
    orphaned: list[str] = []
    for test_id in removed_ids:
        if not _is_still_referenced(test_id, exclude_from_groups, test_plan):
            orphaned.append(test_id)
    orphaned.sort()
    return orphaned


def _is_still_referenced(
    test_id: str,
    exclude_from_groups: dict[str, list[str]],
    test_plan: TestPlan,
) -> bool:
    """Return True if test_id is still active in at least one group."""
    for group in test_plan.test_case_groups.values():
        if test_id not in group.tests:
            continue
        if test_id in group.exclude_tests:
            continue
        group_removals = exclude_from_groups.get(group.identifier, [])
        if test_id not in group_removals:
            return True
    return False


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
        raise PruneError(f"Pruned test plan failed validation: {error}") from error


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
    tc_file_map: dict[str, Path] = {}

    if prune_plan.exclude_devices_updates:
        tc_file_map = _find_test_case_files(plan_dir)
        _apply_dir_exclude_devices(prune_plan, tc_file_map, output)

    if prune_plan.exclude_from_groups:
        _apply_dir_exclude_from_groups(prune_plan, plan_dir, output)

    if prune_plan.orphaned_test_cases:
        if not tc_file_map:
            tc_file_map = _find_test_case_files(plan_dir)
        _apply_dir_remove_orphans(prune_plan, tc_file_map)


def _apply_dir_exclude_devices(
    prune_plan: PrunePlan,
    tc_file_map: dict[str, Path],
    output: Output,
) -> None:
    """Apply exclude_devices updates across a directory of YAML files."""
    files_to_write: dict[Path, RawYAML] = {}

    for test_id, devices in prune_plan.exclude_devices_updates.items():
        file_path = tc_file_map.get(test_id)
        if file_path is None:
            output.warning(f"Cannot locate YAML file containing test case '{test_id}'")
            continue

        if file_path not in files_to_write:
            files_to_write[file_path] = _load_raw_yaml(file_path)

        _set_exclude_devices_on_test_case(files_to_write[file_path], test_id, devices)

    for file_path, data in files_to_write.items():
        _write_yaml(file_path, data)


def _apply_dir_exclude_from_groups(
    prune_plan: PrunePlan,
    plan_dir: Path,
    output: Output,
) -> None:
    """Apply exclude_tests additions across a directory of YAML files."""
    group_file_map = _find_group_files(plan_dir)
    files_to_write: dict[Path, RawYAML] = {}

    for group_id, test_ids in prune_plan.exclude_from_groups.items():
        file_path = group_file_map.get(group_id)
        if file_path is None:
            output.warning(f"Cannot locate YAML file containing group '{group_id}'")
            continue

        if file_path not in files_to_write:
            files_to_write[file_path] = _load_raw_yaml(file_path)

        _add_exclude_tests_to_group(files_to_write[file_path], group_id, test_ids)

    for file_path, data in files_to_write.items():
        _write_yaml(file_path, data)


def _apply_dir_remove_orphans(
    prune_plan: PrunePlan,
    tc_file_map: dict[str, Path],
) -> None:
    """Remove orphaned test case definitions across a directory."""
    orphan_files: dict[Path, RawYAML] = {}
    for test_id in prune_plan.orphaned_test_cases:
        file_path = tc_file_map.get(test_id)
        if file_path is None:
            continue
        if file_path not in orphan_files:
            orphan_files[file_path] = _load_raw_yaml(file_path)
        _remove_orphaned_test_cases(orphan_files[file_path], [test_id])
    for file_path, data in orphan_files.items():
        _write_yaml(file_path, data)


def _apply_exclude_devices(
    data: RawYAML,
    prune_plan: PrunePlan,
    output: Output,
) -> None:
    """Apply exclude_devices updates to test cases in a raw YAML dict."""
    for test_id, devices in prune_plan.exclude_devices_updates.items():
        _set_exclude_devices_on_test_case(data, test_id, devices)


def _apply_exclude_from_groups(
    data: RawYAML,
    prune_plan: PrunePlan,
    output: Output,
) -> None:
    """Apply exclude_tests additions to groups in a raw YAML dict."""
    for group_id, test_ids in prune_plan.exclude_from_groups.items():
        _add_exclude_tests_to_group(data, group_id, test_ids)


def _set_exclude_devices_on_test_case(
    data: RawYAML,
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

    tc_dict = cast(RawYAML, raw_tc)
    target = tc_dict.get("target")
    if target is None:
        tc_dict["target"] = {"exclude_devices": devices}
    elif isinstance(target, dict):
        target["exclude_devices"] = devices


def _add_exclude_tests_to_group(
    data: RawYAML,
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

    group_dict = cast(RawYAML, raw_group)

    if "groups" in group_dict:
        _append_exclude_tests(group_dict, test_ids)
    else:
        _remove_tests_from_list(group_dict, test_ids)


def _append_exclude_tests(group_dict: RawYAML, test_ids: list[str]) -> None:
    """Append test IDs to exclude_tests on a composite group."""
    existing = group_dict.get("exclude_tests")
    if not isinstance(existing, list):
        group_dict["exclude_tests"] = list(test_ids)
        return
    for tid in test_ids:
        if tid not in existing:
            existing.append(tid)


def _remove_tests_from_list(group_dict: RawYAML, test_ids: list[str]) -> None:
    """Remove test IDs from a leaf group's tests list."""
    tests_list = group_dict.get("tests")
    if not isinstance(tests_list, list):
        return
    for tid in test_ids:
        while tid in tests_list:
            tests_list.remove(tid)


def _remove_orphaned_test_cases(
    data: RawYAML,
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


def _load_raw_yaml(path: Path) -> RawYAML:
    """Load a YAML file preserving formatting for round-trip editing."""
    loaded = _ruamel.load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise PruneError(f"Expected mapping at root of {path}")
    return cast(RawYAML, loaded)


def _write_yaml(path: Path, data: RawYAML) -> None:
    """Write a dictionary to a YAML file preserving original formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        _ruamel.dump(data, fh)

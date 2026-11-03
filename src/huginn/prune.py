"""Prune non-applicable test cases and device targets from a test plan."""

import io
import json
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from ruamel.yaml import YAML

from huginn.loaders import ConfigurationError, discover_yaml_files, load_test_plan
from huginn.models import DIRECT_INCLUSION, TestPlan
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
    # Group ID -> fully N/A test IDs to remove from the group's own ``tests``.
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
        listing_groups = _groups_listing_test(entry.test_id, test_plan)
        if not listing_groups:
            skipped.append(entry.test_id)
            continue
        for group_id in listing_groups:
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


def _groups_listing_test(test_id: str, test_plan: TestPlan) -> list[str]:
    """Return the groups that list ``test_id`` in their own ``tests``.

    Groups that only inherit the test through nested ``groups`` are left out:
    removing the test from the groups that list it removes it from them too.
    """
    return [
        group_id
        for group_id, group in test_plan.test_case_groups.items()
        if test_id in group.tests and DIRECT_INCLUSION in group.paths_for(test_id)
    ]


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
    """Identify defined test cases that no group references after exclusions.

    Every test case in the plan is considered, not only those removed by
    this run, so orphans left behind by earlier runs (and test cases that
    were never placed in any group) are found too.
    """
    referenced = _referenced_test_ids(exclude_from_groups, test_plan)
    return sorted(set(test_plan.test_cases) - referenced)


def _referenced_test_ids(
    exclude_from_groups: dict[str, list[str]],
    test_plan: TestPlan,
) -> set[str]:
    """Return test IDs still active in at least one group.

    A group's ``tests`` is already flattened by the loader (it includes
    tests inherited through nested ``groups``). Tests in the group's
    ``exclude_tests`` do not count as references. Nor do tests this run
    prunes: they leave every group that lists them, and so every group
    that inherits them too.
    """
    pruned = {tid for tids in exclude_from_groups.values() for tid in tids}
    referenced: set[str] = set()
    for group in test_plan.test_case_groups.values():
        inactive = set(group.exclude_tests) | pruned
        referenced.update(tid for tid in group.tests if tid not in inactive)
    return referenced


@dataclass(frozen=True)
class RemovedPhase:
    """A phase removed because pruning left it with no test case groups."""

    scenario_id: str
    phase_id: str


@dataclass
class PruneEdit:
    """Prune changes applied to the test plan documents in memory.

    Nothing is written until :func:`write_prune_edit` is called, so a dry
    run and a run whose result fails validation leave every file untouched.
    """

    documents: dict[Path, RawYAML]
    changed_paths: set[Path] = field(default_factory=set)
    removed_groups: list[str] = field(default_factory=list)
    removed_phases: list[RemovedPhase] = field(default_factory=list)
    removed_scenarios: list[str] = field(default_factory=list)


def apply_prune_plan(
    *,
    plan_path: Path,
    prune_plan: PrunePlan,
    output: Output,
) -> PruneEdit:
    """Apply prune changes to the test plan files.

    The changes are validated in memory first. If the pruned plan would be
    invalid, :class:`PruneError` is raised and no file is written.
    """
    edit = prepare_prune_edit(plan_path=plan_path, prune_plan=prune_plan, output=output)
    write_prune_edit(edit)
    return edit


def prepare_prune_edit(
    *,
    plan_path: Path,
    prune_plan: PrunePlan,
    output: Output,
) -> PruneEdit:
    """Apply prune changes in memory and validate the result.

    Groups that pruning empties are removed together with their references in
    parent groups and phases. Phases and scenarios left empty are removed in
    turn. Raises :class:`PruneError` when the pruned plan would not load.
    """
    edit = PruneEdit(documents=_load_plan_documents(plan_path))
    _edit_test_cases(edit, prune_plan, output)
    touched_groups = _remove_tests_from_groups(edit, prune_plan, output)
    _cascade_group_removals(edit, touched_groups)
    _cascade_phase_removals(edit)
    _validate_prune_edit(plan_path, edit)
    return edit


def write_prune_edit(edit: PruneEdit) -> None:
    """Write the documents a prune edit changed."""
    for path in sorted(edit.changed_paths):
        _write_yaml(path, edit.documents[path])


def validate_after_prune(plan_path: Path) -> None:
    """Load the modified test plan to verify it is still valid."""
    try:
        load_test_plan(plan_path)
    except ConfigurationError as error:
        raise PruneError(f"Pruned test plan failed validation: {error}") from error


def _load_plan_documents(plan_path: Path) -> dict[Path, RawYAML]:
    """Load every YAML document of a test plan for round-trip editing."""
    if plan_path.is_file():
        return {plan_path: _load_raw_yaml(plan_path)}
    if plan_path.is_dir():
        return {path: _load_raw_yaml(path) for path in discover_yaml_files(plan_path)}
    raise PruneError(f"Test plan path does not exist: {plan_path}")


def _section_entries(
    edit: PruneEdit, section: str
) -> dict[str, tuple[Path, dict[str, Any], RawYAML]]:
    """Map each entry ID in a plan section to its file, section and mapping."""
    entries: dict[str, tuple[Path, dict[str, Any], RawYAML]] = {}
    for path, data in edit.documents.items():
        raw_section = data.get(section)
        if not isinstance(raw_section, dict):
            continue
        for key, value in raw_section.items():
            if isinstance(key, str) and isinstance(value, dict):
                entries[key] = (path, raw_section, cast(RawYAML, value))
    return entries


def _edit_test_cases(edit: PruneEdit, prune_plan: PrunePlan, output: Output) -> None:
    """Set exclude_devices and remove orphaned test case definitions."""
    test_cases = _section_entries(edit, "test_cases")
    for test_id, devices in prune_plan.exclude_devices_updates.items():
        entry = test_cases.get(test_id)
        if entry is None:
            output.warning(f"Cannot locate YAML file containing test case '{test_id}'")
            continue
        path, _, raw_test_case = entry
        _set_exclude_devices(raw_test_case, devices)
        edit.changed_paths.add(path)

    for test_id in prune_plan.orphaned_test_cases:
        entry = test_cases.get(test_id)
        if entry is None:
            continue
        path, section, _ = entry
        del section[test_id]
        edit.changed_paths.add(path)


def _set_exclude_devices(raw_test_case: RawYAML, devices: list[str]) -> None:
    """Set exclude_devices on a raw test case's target."""
    target = raw_test_case.get("target")
    if target is None:
        raw_test_case["target"] = {"exclude_devices": devices}
    elif isinstance(target, dict):
        target["exclude_devices"] = devices


def _remove_tests_from_groups(
    edit: PruneEdit, prune_plan: PrunePlan, output: Output
) -> set[str]:
    """Remove fully N/A tests from the groups that list them in ``tests``.

    Composite groups that inherit a test through ``groups`` lose it with the
    child group, so no ``exclude_tests`` entry is added. Returns the IDs of
    the groups that were changed.
    """
    groups = _section_entries(edit, "test_case_groups")
    touched: set[str] = set()
    for group_id, test_ids in prune_plan.exclude_from_groups.items():
        entry = groups.get(group_id)
        if entry is None:
            output.warning(f"Cannot locate YAML file containing group '{group_id}'")
            continue
        path, _, raw_group = entry
        tests = raw_group.get("tests")
        if not isinstance(tests, list):
            continue
        for test_id in test_ids:
            while test_id in tests:
                tests.remove(test_id)
        touched.add(group_id)
        edit.changed_paths.add(path)
    return touched


def _cascade_group_removals(edit: PruneEdit, touched: set[str]) -> None:
    """Remove groups left with no tests and no child groups, bottom up.

    Each pass drops the groups removed so far from their parents' ``groups``
    lists, which can empty a parent in turn; passes repeat until none does.
    """
    groups = _section_entries(edit, "test_case_groups")
    removed: set[str] = set()
    while True:
        newly_removed = _group_removal_pass(edit, groups, removed, touched)
        if not newly_removed:
            break
        removed.update(newly_removed)

    for group_id in edit.removed_groups:
        path, section, _ = groups[group_id]
        del section[group_id]
        edit.changed_paths.add(path)
    for group_id in touched - removed:
        _tidy_group(groups[group_id][2])


def _group_removal_pass(
    edit: PruneEdit,
    groups: dict[str, tuple[Path, dict[str, Any], RawYAML]],
    removed: set[str],
    touched: set[str],
) -> list[str]:
    """Run one pass of the group cascade and return the groups it empties."""
    newly_removed: list[str] = []
    for group_id, (path, _, raw_group) in groups.items():
        if group_id in removed:
            continue
        if _drop_from_list(raw_group, "groups", removed):
            touched.add(group_id)
            edit.changed_paths.add(path)
        if group_id in touched and _is_empty_group(raw_group):
            newly_removed.append(group_id)
            edit.removed_groups.append(group_id)
    return newly_removed


def _is_empty_group(raw_group: RawYAML) -> bool:
    """Return whether a raw group lists no tests and includes no groups."""
    return not raw_group.get("tests") and not raw_group.get("groups")


def _drop_from_list(mapping: RawYAML, key: str, values: set[str]) -> bool:
    """Remove ``values`` from the list at ``mapping[key]`` in place.

    Returns whether anything was removed.
    """
    items = mapping.get(key)
    if not isinstance(items, list) or not values.intersection(items):
        return False
    items[:] = [item for item in items if item not in values]
    return True


def _tidy_group(raw_group: RawYAML) -> None:
    """Drop keys pruning left empty on a surviving group.

    An empty ``groups`` list goes, and with it ``exclude_tests``, which the
    loader rejects without ``groups``. An empty ``tests`` list goes once the
    group still includes child groups.
    """
    if "groups" in raw_group and not raw_group["groups"]:
        del raw_group["groups"]
        raw_group.pop("exclude_tests", None)
    if "tests" in raw_group and not raw_group["tests"] and raw_group.get("groups"):
        del raw_group["tests"]


def _cascade_phase_removals(edit: PruneEdit) -> None:
    """Drop removed groups from phases, then remove empty phases and scenarios.

    A ``depends_on`` entry naming a removed phase is dropped too, so the
    remaining phases still load.
    """
    if not edit.removed_groups:
        return
    removed_groups = set(edit.removed_groups)
    scenarios = _section_entries(edit, "scenarios")
    for scenario_id, (path, section, raw_scenario) in scenarios.items():
        phases = raw_scenario.get("phases")
        if not isinstance(phases, dict):
            continue
        changed, removed_phases = _prune_scenario_phases(phases, removed_groups)
        if not changed:
            continue
        edit.changed_paths.add(path)
        edit.removed_phases.extend(
            RemovedPhase(scenario_id=scenario_id, phase_id=phase_id)
            for phase_id in removed_phases
        )
        if not phases:
            del section[scenario_id]
            edit.removed_scenarios.append(scenario_id)


def _prune_scenario_phases(
    phases: dict[str, Any], removed_groups: set[str]
) -> tuple[bool, list[str]]:
    """Edit one scenario's phases in place.

    Returns whether any phase changed and the IDs of the phases removed.
    """
    raw_phases = {
        phase_id: cast(RawYAML, raw_phase)
        for phase_id, raw_phase in phases.items()
        if isinstance(raw_phase, dict)
    }
    changed = False
    removed: list[str] = []
    for phase_id, raw_phase in raw_phases.items():
        if not _drop_from_list(raw_phase, "test_case_groups", removed_groups):
            continue
        changed = True
        if not raw_phase.get("test_case_groups"):
            del phases[phase_id]
            removed.append(phase_id)
    for phase_id, raw_phase in raw_phases.items():
        if phase_id not in removed:
            _drop_from_list(raw_phase, "depends_on", set(removed))
    return changed, removed


def _validate_prune_edit(plan_path: Path, edit: PruneEdit) -> None:
    """Load the edited plan from a temporary copy; raise if it is invalid.

    The copy goes through the same loader as every other command, so the
    plan on disk is only rewritten when the result is known to load.
    """
    with tempfile.TemporaryDirectory(prefix="huginn-prune-") as tmp:
        tmp_root = Path(tmp)
        base = plan_path.parent if plan_path.is_file() else plan_path
        copy_root = tmp_root / "plan"
        for path, data in edit.documents.items():
            target = copy_root / path.relative_to(base)
            target.parent.mkdir(parents=True, exist_ok=True)
            if path in edit.changed_paths:
                target.write_text(_dump_yaml(data), encoding="utf-8")
            else:
                target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        copy_path = copy_root / plan_path.name if plan_path.is_file() else copy_root
        try:
            load_test_plan(copy_path)
        except ConfigurationError as error:
            message = str(error).replace(str(copy_root), str(base))
            raise PruneError(
                "Pruning would leave an invalid test plan, so no files were "
                f"changed: {message}"
            ) from error


def _load_raw_yaml(path: Path) -> RawYAML:
    """Load a YAML file preserving formatting for round-trip editing."""
    loaded = _ruamel.load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise PruneError(f"Expected mapping at root of {path}")
    return cast(RawYAML, loaded)


def _dump_yaml(data: RawYAML) -> str:
    """Render round-trip YAML data to text."""
    buffer = io.StringIO()
    _ruamel.dump(data, buffer)
    return buffer.getvalue()


def _write_yaml(path: Path, data: RawYAML) -> None:
    """Write a dictionary to a YAML file preserving original formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump_yaml(data), encoding="utf-8")

"""Reconcile failing test cases into new test case groups after a change."""

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import cast

import yaml

from huginn.loaders import ConfigurationError, discover_yaml_files, load_test_plan
from huginn.models import (
    InclusionPath,
    TargetDefinition,
    TestCaseDefinition,
    TestCaseGroup,
    TestPlan,
)
from huginn.output import Output


class ReconcileError(ValueError):
    """Raised when reconciliation cannot proceed."""


@dataclass(frozen=True)
class FailingTestCase:
    """A test case that failed in a specific group within the target phase."""

    test_id: str
    group_id: str
    scenario_id: str


@dataclass(frozen=True)
class ReconcileInput:
    """Parsed result data relevant to reconciliation."""

    failing_tests: list[FailingTestCase]
    passing_test_ids_by_group: dict[str, list[str]]
    affected_group_ids: set[str]
    phase_name: str
    scenarios_with_phase: list[str]


@dataclass(frozen=True)
class NewGroupSpec:
    """Specification for a new reconciled test case group.

    The group repeats the parent group's ``target`` and ``tags`` so that
    variants listed in ``tests`` are narrowed and tagged like the originals
    they replace. Variants the parent inherited through nested groups are
    placed in the ``path_groups`` instead, which rebuild those nested groups'
    targets and tags.
    """

    parent_group: str
    exclude_tests: list[str]
    tests: list[str]
    target: TargetDefinition | None = None
    tags: list[str] = field(default_factory=list)
    path_groups: list[str] = field(default_factory=list)
    description: str | None = None


@dataclass(frozen=True)
class PathGroupSpec:
    """A generated group that rebuilds one link of a nested inclusion path."""

    tests: list[str]
    groups: list[str]
    target: TargetDefinition | None = None
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReconcilePlan:
    """The complete set of changes to apply."""

    new_test_cases: dict[str, dict[str, object]]
    new_groups: dict[str, NewGroupSpec]
    phase_group_replacements: dict[str, dict[str, str]]
    parameter_copies: list[tuple[str, str]]
    skipped_existing: list[str]
    path_groups: dict[str, PathGroupSpec] = field(default_factory=dict)


_FAILURE_STATUSES = frozenset({"failed", "errored"})


def _parse_results_dir_timestamp(name: str) -> datetime:
    """Parse the timestamp from a results directory name."""
    # Strip the -testing (or -testing-NN) suffix to get the timestamp portion
    stem = name.removesuffix("-testing")
    # Handle collision suffixes like -testing-01
    if stem == name:
        parts = name.rsplit("-testing-", 1)
        stem = parts[0]
    return datetime.strptime(stem, "%Y-%b-%d-%H-%M-%S")


def find_latest_testing_results(results_dir: Path) -> Path:
    """Find the most recent testing run directory and return its run.json path."""
    if not results_dir.is_dir():
        raise ReconcileError(f"Results directory does not exist: {results_dir}")

    candidates = sorted(
        (
            entry
            for entry in results_dir.iterdir()
            if entry.is_dir() and entry.name.endswith("-testing")
        ),
        key=lambda p: _parse_results_dir_timestamp(p.name),
    )
    if not candidates:
        raise ReconcileError(
            f"No testing run directories found in {results_dir}. "
            "Run tests in testing mode first."
        )

    run_json = candidates[-1] / "run.json"
    if not run_json.is_file():
        raise ReconcileError(f"run.json not found in {candidates[-1]}")
    return run_json


def parse_failures_from_run(
    run_json_path: Path,
    phase_name: str,
    scenario_filter: str | None = None,
) -> ReconcileInput:
    """Read run.json and extract failing test cases for the given phase."""
    raw = json.loads(run_json_path.read_text(encoding="utf-8"))
    scenarios = raw.get("scenarios", [])

    failing_tests: list[FailingTestCase] = []
    passing_by_group: dict[str, list[str]] = {}
    affected_groups: set[str] = set()
    scenarios_with_phase: list[str] = []

    for scenario in scenarios:
        scenario_id = scenario["id"]
        if scenario_filter is not None and scenario_id != scenario_filter:
            continue

        for phase in scenario.get("phases", []):
            if phase["id"] != phase_name:
                continue

            scenarios_with_phase.append(scenario_id)
            _collect_phase_results(
                phase,
                scenario_id,
                failing_tests,
                passing_by_group,
                affected_groups,
            )

    if not scenarios_with_phase:
        scope = f"scenario '{scenario_filter}'" if scenario_filter else "any scenario"
        raise ReconcileError(
            f"Phase '{phase_name}' not found in {scope} within run results"
        )

    return ReconcileInput(
        failing_tests=failing_tests,
        passing_test_ids_by_group=passing_by_group,
        affected_group_ids=affected_groups,
        phase_name=phase_name,
        scenarios_with_phase=scenarios_with_phase,
    )


def _collect_phase_results(
    phase: dict[str, object],
    scenario_id: str,
    failing_tests: list[FailingTestCase],
    passing_by_group: dict[str, list[str]],
    affected_groups: set[str],
) -> None:
    """Extract failures and passing tests from a single phase."""
    raw_groups = cast(list[dict[str, object]], phase.get("test_case_groups", []))
    for group in raw_groups:
        group_id = cast(str, group["id"])
        group_passing: list[str] = []

        test_cases = cast(list[dict[str, object]], group.get("test_cases", []))
        for test_case in test_cases:
            test_id = cast(str, test_case["test_id"])
            if test_case["status"] in _FAILURE_STATUSES:
                failing_tests.append(
                    FailingTestCase(
                        test_id=test_id,
                        group_id=group_id,
                        scenario_id=scenario_id,
                    )
                )
                affected_groups.add(group_id)
            else:
                group_passing.append(test_id)

        if group_id not in passing_by_group:
            passing_by_group[group_id] = group_passing
        else:
            for tid in group_passing:
                if tid not in passing_by_group[group_id]:
                    passing_by_group[group_id].append(tid)


def _reconciled_id(original_id: str, scenario_name: str, phase_name: str) -> str:
    """Build a reconciled ID that is unique per scenario and phase.

    When ``original_id`` equals ``phase_name``, the original is redundant and
    the result is simply ``{scenario_name}-{phase_name}``.  Otherwise the full
    form ``{original_id}-{scenario_name}-{phase_name}`` is used.
    """
    if original_id == phase_name:
        return f"{scenario_name}-{phase_name}"
    return f"{original_id}-{scenario_name}-{phase_name}"


def compute_reconcile_plan(
    reconcile_input: ReconcileInput,
    test_plan: TestPlan,
    phase_name: str,
    scenario_name: str,
) -> ReconcilePlan:
    """Compute all changes needed without performing I/O."""
    _validate_phase_exists_in_plan(test_plan, phase_name, reconcile_input)

    skipped_existing: list[str] = []
    new_test_cases, parameter_copies, seen_failing_ids = _build_new_test_cases(
        reconcile_input, test_plan, phase_name, scenario_name, skipped_existing
    )
    new_groups, path_groups = _build_new_groups(
        reconcile_input,
        test_plan,
        phase_name,
        scenario_name,
        new_test_cases,
        seen_failing_ids,
        skipped_existing,
    )
    phase_group_replacements = _build_phase_replacements(
        reconcile_input, new_groups, phase_name, scenario_name
    )

    return ReconcilePlan(
        new_test_cases=new_test_cases,
        new_groups=new_groups,
        phase_group_replacements=phase_group_replacements,
        parameter_copies=parameter_copies,
        skipped_existing=skipped_existing,
        path_groups=path_groups,
    )


def _build_new_test_cases(
    reconcile_input: ReconcileInput,
    test_plan: TestPlan,
    phase_name: str,
    scenario_name: str,
    skipped_existing: list[str],
) -> tuple[dict[str, dict[str, object]], list[tuple[str, str]], set[str]]:
    """Create new test case definitions for each unique failing test."""
    new_test_cases: dict[str, dict[str, object]] = {}
    parameter_copies: list[tuple[str, str]] = []
    seen_failing_ids: set[str] = set()

    for failure in reconcile_input.failing_tests:
        if failure.test_id in seen_failing_ids:
            continue
        seen_failing_ids.add(failure.test_id)

        new_id = _reconciled_id(failure.test_id, scenario_name, phase_name)
        if new_id in test_plan.test_cases:
            skipped_existing.append(new_id)
            continue

        original = test_plan.test_cases.get(failure.test_id)
        if original is None:
            continue

        tc_entry = _serialize_test_case(original, scenario_name, phase_name)
        new_test_cases[new_id] = tc_entry
        parameter_copies.append((failure.test_id, new_id))

    return new_test_cases, parameter_copies, seen_failing_ids


def _serialize_test_case(
    original: TestCaseDefinition,
    scenario_name: str,
    phase_name: str,
) -> dict[str, object]:
    """Build a raw test case entry from an existing definition."""
    tc_entry: dict[str, object] = {
        "title": f"{original.title} ({scenario_name} {phase_name})",
        "job": original.job,
    }
    if original.tags:
        tc_entry["tags"] = list(original.tags)
    _add_target(tc_entry, original.target)
    return tc_entry


def _add_target(entry: dict[str, object], target: TargetDefinition | None) -> None:
    """Add a raw ``target`` mapping to ``entry`` when a selector is set."""
    if target is None:
        return
    target_dict: dict[str, object] = {}
    if target.devices is not None:
        target_dict["devices"] = list(target.devices)
    if target.groups is not None:
        target_dict["groups"] = list(target.groups)
    if target.os is not None:
        target_dict["os"] = list(target.os)
    if target.exclude_devices is not None:
        target_dict["exclude_devices"] = list(target.exclude_devices)
    if target_dict:
        entry["target"] = target_dict


def _build_new_groups(
    reconcile_input: ReconcileInput,
    test_plan: TestPlan,
    phase_name: str,
    scenario_name: str,
    new_test_cases: dict[str, dict[str, object]],
    seen_failing_ids: set[str],
    skipped_existing: list[str],
) -> tuple[dict[str, NewGroupSpec], dict[str, PathGroupSpec]]:
    """Create new group specs for each affected group."""
    new_groups: dict[str, NewGroupSpec] = {}
    path_groups: dict[str, PathGroupSpec] = {}
    for group_id in sorted(reconcile_input.affected_group_ids):
        new_group_id = _reconciled_id(group_id, scenario_name, phase_name)
        if new_group_id in test_plan.test_case_groups:
            skipped_existing.append(new_group_id)
            continue

        original_group = test_plan.test_case_groups.get(group_id)
        if original_group is None:
            continue

        variants: list[tuple[str, str]] = []
        for tid in original_group.tests:
            if tid not in seen_failing_ids:
                continue
            candidate = _reconciled_id(tid, scenario_name, phase_name)
            if candidate in new_test_cases or candidate in test_plan.test_cases:
                variants.append((tid, candidate))

        new_groups[new_group_id] = _build_group_spec(
            original_group,
            variants,
            _PathGroupBuilder(new_group_id, test_plan.test_case_groups, path_groups),
        )
    return new_groups, path_groups


def _build_group_spec(
    original_group: TestCaseGroup,
    variants: list[tuple[str, str]],
    path_groups: "_PathGroupBuilder",
) -> NewGroupSpec:
    """Build the reconciled group that swaps ``variants`` in for the originals.

    ``variants`` pairs each failing test ID with its variant ID. A variant
    replaces its original on every inclusion path the original had, so it
    runs on the same devices and carries the same group tags.
    """
    direct_tests: list[str] = []
    for test_id, variant_id in variants:
        for path in original_group.paths_for(test_id):
            if path.targets or path.tags:
                path_groups.add(variant_id, path)
            else:
                direct_tests.append(variant_id)
    return NewGroupSpec(
        parent_group=original_group.identifier,
        exclude_tests=[test_id for test_id, _ in variants],
        tests=direct_tests,
        target=original_group.target,
        tags=list(original_group.tags),
        path_groups=path_groups.heads(),
        description=original_group.description,
    )


class _PathGroupBuilder:
    """Generate the groups that rebuild nested inclusion paths for variants.

    Each distinct path becomes a chain with one group per target on the path,
    outermost first, named ``<reconciled group>-path<N>`` and then
    ``-path<N>-<level>`` for the inner levels. The innermost group lists the
    variants reached through that path and carries the path's tags. Including
    the chain from the reconciled group gives each variant the same path its
    original had, so target resolution and tag filtering treat both alike. A
    variant reached through several paths is listed in several chains, and
    the loader again takes the union of their devices.
    """

    def __init__(
        self,
        group_id: str,
        existing_groups: dict[str, TestCaseGroup],
        generated: dict[str, PathGroupSpec],
    ) -> None:
        self._group_id = group_id
        self._existing_groups = existing_groups
        self._generated = generated
        self._chains: list[tuple[InclusionPath, list[str]]] = []

    def add(self, variant_id: str, path: InclusionPath) -> None:
        """List ``variant_id`` in the chain for ``path``, creating it if new."""
        for chain_path, names in self._chains:
            if _same_path(chain_path, path):
                self._generated[names[-1]].tests.append(variant_id)
                return

        targets = [target for _, target in path.targets] or [None]
        names = self._chain_names(len(targets))
        for index, (name, target) in enumerate(zip(names, targets, strict=True)):
            innermost = index == len(names) - 1
            self._generated[name] = PathGroupSpec(
                tests=[variant_id] if innermost else [],
                groups=[] if innermost else [names[index + 1]],
                target=target,
                tags=list(path.tags) if innermost else [],
            )
        self._chains.append((path, names))

    def heads(self) -> list[str]:
        """Return the outermost group of each chain, in creation order."""
        return [names[0] for _, names in self._chains]

    def _chain_names(self, length: int) -> list[str]:
        """Return the first unused set of group IDs for a chain of ``length``."""
        number = 1
        while True:
            head = f"{self._group_id}-path{number}"
            names = [head, *(f"{head}-{level}" for level in range(2, length + 1))]
            if not any(self._is_taken(name) for name in names):
                return names
            number += 1

    def _is_taken(self, name: str) -> bool:
        return name in self._existing_groups or name in self._generated


def _same_path(first: InclusionPath, second: InclusionPath) -> bool:
    """Return True when two paths apply the same targets and tags."""
    return [target for _, target in first.targets] == [
        target for _, target in second.targets
    ] and set(first.tags) == set(second.tags)


def _build_phase_replacements(
    reconcile_input: ReconcileInput,
    new_groups: dict[str, NewGroupSpec],
    phase_name: str,
    scenario_name: str,
) -> dict[str, dict[str, str]]:
    """Map old group references to new ones per scenario."""
    phase_group_replacements: dict[str, dict[str, str]] = {}
    for scenario_id in reconcile_input.scenarios_with_phase:
        replacements: dict[str, str] = {}
        for group_id in reconcile_input.affected_group_ids:
            new_group_id = _reconciled_id(group_id, scenario_name, phase_name)
            if new_group_id in new_groups:
                replacements[group_id] = new_group_id
        if replacements:
            phase_group_replacements[scenario_id] = replacements
    return phase_group_replacements


def apply_reconcile_plan(
    *,
    plan_path: Path,
    reconcile_plan: ReconcilePlan,
    phase_name: str,
    output: Output,
) -> None:
    """Apply reconciliation changes to test plan YAML files."""
    if plan_path.is_file():
        _apply_single_file(plan_path, reconcile_plan, phase_name)
    elif plan_path.is_dir():
        new_file = _apply_directory(plan_path, reconcile_plan, phase_name)
        output.status(f"Created reconciled definitions: {new_file}")
    else:
        raise ReconcileError(f"Test plan path does not exist: {plan_path}")


def copy_parameter_files(
    *,
    parameters_dir: Path,
    copies: list[tuple[str, str]],
    output: Output,
) -> int:
    """Copy parameter JSON files for reconciled test cases.

    Returns the number of files successfully copied.
    """
    copied = 0
    for source_id, dest_id in copies:
        source_path = parameters_dir / f"{source_id}.json"
        dest_path = parameters_dir / f"{dest_id}.json"

        if not source_path.is_file():
            output.warning(
                f"Parameter file not found for test '{source_id}' -- skipping copy"
            )
            continue

        if dest_path.is_file():
            output.warning(
                f"Parameter file already exists for test '{dest_id}' -- skipping copy"
            )
            continue

        parameters_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, dest_path)
        copied += 1

    return copied


def validate_after_reconcile(plan_path: Path) -> None:
    """Load the modified test plan to verify it is still valid."""
    try:
        load_test_plan(plan_path)
    except ConfigurationError as error:
        raise ReconcileError(
            f"Reconciled test plan failed validation: {error}"
        ) from error


def _validate_phase_exists_in_plan(
    test_plan: TestPlan,
    phase_name: str,
    reconcile_input: ReconcileInput,
) -> None:
    """Verify that the target phase exists in the test plan."""
    for scenario_id in reconcile_input.scenarios_with_phase:
        scenario = test_plan.scenarios.get(scenario_id)
        if scenario is None:
            raise ReconcileError(
                f"Scenario '{scenario_id}' from run results not found in test plan"
            )
        if phase_name not in scenario.phases:
            raise ReconcileError(
                f"Phase '{phase_name}' not found in scenario '{scenario_id}' "
                "in test plan"
            )


def _apply_single_file(
    plan_path: Path,
    reconcile_plan: ReconcilePlan,
    phase_name: str,
) -> None:
    """Apply reconciliation to a single YAML file in-place."""
    data = _load_raw_yaml(plan_path)

    _inject_new_definitions(data, reconcile_plan)
    _update_phase_references(data, reconcile_plan, phase_name)

    _write_yaml(plan_path, data)


def _apply_directory(
    plan_dir: Path,
    reconcile_plan: ReconcilePlan,
    phase_name: str,
) -> Path:
    """Apply reconciliation to a directory of YAML files.

    Returns the path to the new definitions file.
    """
    new_file = plan_dir / f"reconciled-{phase_name}.yaml"
    existing_data: dict[str, object] = (
        _load_raw_yaml(new_file) if new_file.is_file() else {}
    )

    if reconcile_plan.new_test_cases:
        test_cases = cast(dict[str, object], existing_data.get("test_cases", {}))
        test_cases.update(reconcile_plan.new_test_cases)
        existing_data["test_cases"] = test_cases

    if reconcile_plan.new_groups:
        groups = cast(dict[str, object], existing_data.get("test_case_groups", {}))
        groups.update(_serialize_new_groups(reconcile_plan))
        existing_data["test_case_groups"] = groups

    if existing_data:
        _write_yaml(new_file, existing_data)

    scenario_files = _find_scenario_files(plan_dir)
    for scenario_id in reconcile_plan.phase_group_replacements:
        file_path = scenario_files.get(scenario_id)
        if file_path is None:
            raise ReconcileError(
                f"Cannot locate YAML file containing scenario '{scenario_id}'"
            )
        data = _load_raw_yaml(file_path)
        _update_phase_references(data, reconcile_plan, phase_name)
        _write_yaml(file_path, data)

    return new_file


def _find_scenario_files(plan_dir: Path) -> dict[str, Path]:
    """Map scenario identifiers to the YAML files that define them."""
    scenario_map: dict[str, Path] = {}
    for yaml_path in discover_yaml_files(plan_dir):
        data = _load_raw_yaml(yaml_path)
        raw_scenarios = data.get("scenarios")
        if not isinstance(raw_scenarios, dict):
            continue
        for scenario_id in raw_scenarios:
            if isinstance(scenario_id, str):
                scenario_map[scenario_id] = yaml_path
    return scenario_map


def _inject_new_definitions(
    data: dict[str, object],
    reconcile_plan: ReconcilePlan,
) -> None:
    """Add new test case and group definitions to a raw YAML dict."""
    if reconcile_plan.new_test_cases:
        test_cases = cast(dict[str, object], data.get("test_cases", {}))
        for tc_id, tc_entry in reconcile_plan.new_test_cases.items():
            test_cases[tc_id] = tc_entry
        data["test_cases"] = test_cases

    if reconcile_plan.new_groups:
        groups = cast(dict[str, object], data.get("test_case_groups", {}))
        groups.update(_serialize_new_groups(reconcile_plan))
        data["test_case_groups"] = groups


def _serialize_new_groups(reconcile_plan: ReconcilePlan) -> dict[str, object]:
    """Return the raw YAML entries for the reconciled and path groups."""
    entries: dict[str, object] = {
        group_id: _serialize_group_spec(spec)
        for group_id, spec in reconcile_plan.new_groups.items()
    }
    for group_id, spec in reconcile_plan.path_groups.items():
        entries[group_id] = _serialize_path_group_spec(spec)
    return entries


def _serialize_group_spec(spec: NewGroupSpec) -> dict[str, object]:
    """Convert a NewGroupSpec into the raw YAML dictionary form."""
    entry: dict[str, object] = {
        "groups": [spec.parent_group, *spec.path_groups],
        "exclude_tests": spec.exclude_tests,
    }
    if spec.tests:
        entry["tests"] = spec.tests
    if spec.tags:
        entry["tags"] = list(spec.tags)
    _add_target(entry, spec.target)
    if spec.description is not None:
        entry["description"] = spec.description
    return entry


def _serialize_path_group_spec(spec: PathGroupSpec) -> dict[str, object]:
    """Convert a PathGroupSpec into the raw YAML dictionary form."""
    entry: dict[str, object] = {}
    if spec.groups:
        entry["groups"] = list(spec.groups)
    if spec.tests:
        entry["tests"] = list(spec.tests)
    if spec.tags:
        entry["tags"] = list(spec.tags)
    _add_target(entry, spec.target)
    return entry


def _update_phase_references(
    data: dict[str, object],
    reconcile_plan: ReconcilePlan,
    phase_name: str,
) -> None:
    """Update phase group references in scenario definitions."""
    raw_scenarios = data.get("scenarios")
    if not isinstance(raw_scenarios, dict):
        return
    raw_scenarios_map = cast(dict[str, object], raw_scenarios)

    for scenario_id, replacements in reconcile_plan.phase_group_replacements.items():
        raw_scenario = raw_scenarios_map.get(scenario_id)
        if not isinstance(raw_scenario, dict):
            continue
        scenario_dict = cast(dict[str, object], raw_scenario)

        raw_phases = scenario_dict.get("phases")
        if not isinstance(raw_phases, dict):
            continue
        phases_dict = cast(dict[str, object], raw_phases)

        raw_phase = phases_dict.get(phase_name)
        if not isinstance(raw_phase, dict):
            continue
        phase_dict = cast(dict[str, object], raw_phase)

        current_groups = phase_dict.get("test_case_groups")
        if not isinstance(current_groups, list):
            continue
        group_ids = cast(list[str], current_groups)

        phase_dict["test_case_groups"] = [
            replacements.get(gid, gid) for gid in group_ids
        ]


def _load_raw_yaml(path: Path) -> dict[str, object]:
    """Load a YAML file into a raw dictionary."""
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ReconcileError(f"Expected mapping at root of {path}")
    return cast(dict[str, object], loaded)


def _write_yaml(path: Path, data: dict[str, object]) -> None:
    """Write a dictionary to a YAML file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(data, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )

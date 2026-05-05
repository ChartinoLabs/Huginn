"""Inject job files into a test plan as new test cases and groups."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import yaml

from huginn.jobs import JobLoadError, load_test_case_class
from huginn.models import TestPlan


class InjectError(ValueError):
    """Raised when injection cannot proceed."""


@dataclass(frozen=True)
class JobMetadata:
    """Metadata extracted from a single job file."""

    path: Path
    job_ref: str
    title: str
    command: str | None


@dataclass(frozen=True)
class InjectPlan:
    """The complete set of changes to apply."""

    new_test_cases: dict[str, dict[str, object]]
    group_id: str
    group_name: str | None
    is_new_group: bool
    skipped_jobs: list[str] = field(default_factory=list)
    phase_updates: list[str] = field(default_factory=list)


def discover_jobs(path: Path) -> list[Path]:
    """Find Python job files in a path (file or directory)."""
    if path.is_file():
        if path.suffix == ".py":
            return [path]
        raise InjectError(f"Path is not a Python file: {path}")

    if not path.is_dir():
        raise InjectError(f"Path does not exist: {path}")

    jobs = sorted(
        p
        for p in path.iterdir()
        if p.is_file() and p.suffix == ".py" and not p.name.startswith("_")
    )
    if not jobs:
        raise InjectError(f"No Python job files found in: {path}")
    return jobs


def derive_prefix(job_path: Path, project_root: Path) -> str:
    """Derive an ID prefix from the job directory path.

    Example: jobs/iosxe/cdp_global/ -> IOSXE-CDP-GLOBAL
    """
    if job_path.is_file():
        job_path = job_path.parent

    try:
        rel = job_path.resolve().relative_to(project_root.resolve())
    except ValueError:
        rel = job_path

    parts = list(rel.parts)
    if parts and parts[0].lower() == "jobs":
        parts = parts[1:]

    segments = [part.upper().replace("_", "-") for part in parts if part]
    if not segments:
        raise InjectError(f"Cannot derive ID prefix from path: {job_path}")
    return "-".join(segments)


def allocate_ids(prefix: str, count: int, existing_ids: set[str]) -> list[str]:
    """Allocate sequential IDs with the given prefix."""
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
    max_counter = 0
    for existing_id in existing_ids:
        m = pattern.match(existing_id)
        if m:
            max_counter = max(max_counter, int(m.group(1)))

    return [f"{prefix}-{max_counter + i + 1}" for i in range(count)]


def extract_job_metadata(job_path: Path, project_root: Path) -> JobMetadata:
    """Load a job class and extract metadata."""
    job_ref = str(job_path.resolve().relative_to(project_root.resolve()))

    try:
        job_class = load_test_case_class(job_ref, project_root)
    except JobLoadError as exc:
        raise InjectError(f"Failed to load job {job_path.name}: {exc}") from exc

    title = getattr(job_class, "DESCRIPTION", None) or _title_from_filename(job_path)
    command = getattr(job_class, "command", None)

    return JobMetadata(
        path=job_path,
        job_ref=job_ref,
        title=title,
        command=command,
    )


def _title_from_filename(path: Path) -> str:
    """Derive a human-readable title from a job filename."""
    stem = path.stem
    stem = re.sub(r"^verify_", "", stem)
    words = stem.replace("_", " ").strip()
    return words[0].upper() + words[1:] if words else path.stem


def compute_inject_plan(
    *,
    job_path: Path,
    project_root: Path,
    test_plan: TestPlan,
    group_id: str | None = None,
    group_name: str | None = None,
    is_new_group: bool,
    target_groups: list[str] | None = None,
    tags: list[str] | None = None,
    phases: list[str] | None = None,
    id_style: str = "prefix-counter",
) -> InjectPlan:
    """Compute what needs to be injected without writing anything."""
    jobs = discover_jobs(job_path)

    existing_job_refs = {tc.job for tc in test_plan.test_cases.values()}
    existing_ids = set(test_plan.test_cases.keys())

    prefix = derive_prefix(job_path, project_root)
    resolved_group_id = group_id or prefix.lower()
    resolved_group_name = group_name or _humanize_prefix(prefix)

    new_jobs, skipped = _partition_jobs(jobs, existing_job_refs, project_root)

    if not new_jobs:
        return InjectPlan(
            new_test_cases={},
            group_id=resolved_group_id,
            group_name=resolved_group_name if is_new_group else None,
            is_new_group=is_new_group,
            skipped_jobs=skipped,
            phase_updates=phases or [],
        )

    ids = allocate_ids(prefix, len(new_jobs), existing_ids)
    new_test_cases = _build_test_case_entries(
        ids, new_jobs, tags=tags, target_groups=target_groups
    )

    return InjectPlan(
        new_test_cases=new_test_cases,
        group_id=resolved_group_id,
        group_name=resolved_group_name if is_new_group else None,
        is_new_group=is_new_group,
        skipped_jobs=skipped,
        phase_updates=phases or [],
    )


def _partition_jobs(
    jobs: list[Path],
    existing_job_refs: set[str],
    project_root: Path,
) -> tuple[list[JobMetadata], list[str]]:
    """Partition jobs into new (to inject) and skipped (already present)."""
    new_jobs: list[JobMetadata] = []
    skipped: list[str] = []
    for jp in jobs:
        job_ref = str(jp.resolve().relative_to(project_root.resolve()))
        if job_ref in existing_job_refs:
            skipped.append(job_ref)
            continue
        metadata = extract_job_metadata(jp, project_root)
        new_jobs.append(metadata)
    return new_jobs, skipped


def _build_test_case_entries(
    ids: list[str],
    jobs: list[JobMetadata],
    *,
    tags: list[str] | None,
    target_groups: list[str] | None,
) -> dict[str, dict[str, object]]:
    """Build serialized test case entries from allocated IDs and metadata."""
    new_test_cases: dict[str, dict[str, object]] = {}
    for test_id, metadata in zip(ids, jobs, strict=True):
        entry: dict[str, object] = {
            "title": metadata.title,
            "job": metadata.job_ref,
        }
        if tags:
            entry["tags"] = list(tags)
        if target_groups:
            entry["target"] = {"groups": list(target_groups)}
        new_test_cases[test_id] = entry
    return new_test_cases


def apply_inject_plan(
    *,
    plan_path: Path,
    inject_plan: InjectPlan,
) -> None:
    """Write the inject plan to disk."""
    if not inject_plan.new_test_cases:
        return

    _write_test_cases(plan_path, inject_plan)

    if inject_plan.is_new_group:
        _write_new_group(plan_path, inject_plan)
    else:
        _append_to_existing_group(plan_path, inject_plan)

    if inject_plan.phase_updates:
        _update_phase_references(plan_path, inject_plan)


def _write_test_cases(plan_path: Path, inject_plan: InjectPlan) -> None:
    """Write test case definitions to a YAML file."""
    tc_file = plan_path / "test_cases" / f"{inject_plan.group_id}.yaml"

    if tc_file.exists():
        data = _load_raw_yaml(tc_file)
    else:
        data = {}

    test_cases = cast(dict[str, object], data.get("test_cases", {}))
    for test_id, tc_entry in inject_plan.new_test_cases.items():
        test_cases[test_id] = tc_entry
    data["test_cases"] = test_cases

    _write_yaml(tc_file, data)


def _write_new_group(plan_path: Path, inject_plan: InjectPlan) -> None:
    """Write a new group definition file."""
    group_file = plan_path / "groups" / f"{inject_plan.group_id}.yaml"

    if group_file.exists():
        data = _load_raw_yaml(group_file)
    else:
        data = {}

    groups = cast(dict[str, object], data.get("test_case_groups", {}))
    group_entry: dict[str, object] = {
        "name": inject_plan.group_name,
        "tests": list(inject_plan.new_test_cases.keys()),
    }
    groups[inject_plan.group_id] = group_entry
    data["test_case_groups"] = groups

    _write_yaml(group_file, data)


def _append_to_existing_group(plan_path: Path, inject_plan: InjectPlan) -> None:
    """Append new test IDs to an existing group's tests list."""
    group_files = list((plan_path / "groups").glob("*.yaml")) + list(
        (plan_path / "groups").glob("*.yml")
    )

    for gf in group_files:
        data = _load_raw_yaml(gf)
        raw_groups = data.get("test_case_groups")
        if not isinstance(raw_groups, dict):
            continue
        groups_map = cast(dict[str, object], raw_groups)
        if inject_plan.group_id not in groups_map:
            continue

        raw_group = groups_map[inject_plan.group_id]
        if not isinstance(raw_group, dict):
            continue
        group_data = cast(dict[str, object], raw_group)
        existing_tests: list[str] = list(cast(list[str], group_data.get("tests", [])))
        existing_tests.extend(inject_plan.new_test_cases.keys())
        group_data["tests"] = existing_tests

        _write_yaml(gf, data)
        return

    raise InjectError(
        f"Group '{inject_plan.group_id}' not found in any "
        f"groups file under {plan_path / 'groups'}"
    )


def _update_phase_references(plan_path: Path, inject_plan: InjectPlan) -> None:
    """Add the new group to specified phases in scenarios."""
    scenarios_file = _find_scenarios_file(plan_path)

    data = _load_raw_yaml(scenarios_file)
    raw_scenarios = data.get("scenarios")
    if not isinstance(raw_scenarios, dict):
        raise InjectError("No scenarios mapping found in scenarios file")

    for _scenario_id, scenario_data in cast(dict[str, object], raw_scenarios).items():
        if not isinstance(scenario_data, dict):
            continue
        raw_phases = cast(dict[str, object], scenario_data).get("phases")
        if not isinstance(raw_phases, dict):
            continue
        _inject_group_into_phases(raw_phases, inject_plan)

    _write_yaml(scenarios_file, data)


def _find_scenarios_file(plan_path: Path) -> Path:
    """Locate the scenarios YAML file in the test plan."""
    scenarios_file = plan_path / "scenarios.yaml"
    if scenarios_file.exists():
        return scenarios_file
    candidates = list(plan_path.glob("scenarios*.yaml"))
    if candidates:
        return candidates[0]
    raise InjectError("No scenarios.yaml found in test plan")


def _inject_group_into_phases(
    raw_phases: object,
    inject_plan: InjectPlan,
) -> None:
    """Add the group to matching phases within a single scenario."""
    phases_dict = cast(dict[str, object], raw_phases)
    for phase_name in inject_plan.phase_updates:
        raw_phase = phases_dict.get(phase_name)
        if not isinstance(raw_phase, dict):
            continue
        phase_dict = cast(dict[str, object], raw_phase)
        raw_group_list = phase_dict.get("test_case_groups")
        if isinstance(raw_group_list, list):
            group_list = cast(list[str], raw_group_list)
        else:
            group_list: list[str] = []
        if inject_plan.group_id not in group_list:
            group_list.append(inject_plan.group_id)
            phase_dict["test_case_groups"] = group_list


def _humanize_prefix(prefix: str) -> str:
    """Convert an ID prefix to a human-readable group name.

    IOSXE-CDP-GLOBAL -> IOS-XE CDP Global
    """
    parts = prefix.split("-")
    result: list[str] = []
    for part in parts:
        if part == "IOSXE":
            result.append("IOS-XE")
        elif part == "NXOS":
            result.append("NX-OS")
        else:
            result.append(part.capitalize())
    return " ".join(result)


def _load_raw_yaml(path: Path) -> dict[str, object]:
    """Load a YAML file into a raw dictionary."""
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise InjectError(f"Expected mapping at root of {path}")
    return cast(dict[str, object], loaded)


def _write_yaml(path: Path, data: dict[str, object]) -> None:
    """Write a dictionary to a YAML file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(data, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )

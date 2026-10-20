"""Inject job files into a test plan as new test cases and groups."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from huginn.jobs import JobLoadError, load_test_case_class
from huginn.models import TestPlan
from huginn.plan_writer import (
    PlanWriteError,
    add_group_to_phases,
    cases_file_path,
    extend_group,
    groups_file_path,
    write_group,
    write_test_cases,
)


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
    parent_group: str | None = None


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
    parent_group: str | None = None,
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
            parent_group=parent_group,
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
        parent_group=parent_group,
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

    try:
        _apply(plan_path, inject_plan)
    except PlanWriteError as exc:
        raise InjectError(str(exc)) from exc


def _apply(plan_path: Path, inject_plan: InjectPlan) -> None:
    group_id = inject_plan.group_id
    new_ids = list(inject_plan.new_test_cases)
    write_test_cases(cases_file_path(plan_path, group_id), inject_plan.new_test_cases)

    if inject_plan.is_new_group:
        write_group(
            groups_file_path(plan_path, group_id),
            group_id,
            {"name": inject_plan.group_name, "tests": new_ids},
        )
    elif not extend_group(plan_path, group_id, tests=new_ids):
        raise InjectError(
            f"Group '{group_id}' not found in any "
            f"groups file under {plan_path / 'groups'}"
        )

    parent_id = inject_plan.parent_group
    if parent_id and not extend_group(plan_path, parent_id, groups=[group_id]):
        raise InjectError(
            f"Parent group '{parent_id}' not found in any "
            f"groups file under {plan_path / 'groups'}"
        )

    if inject_plan.phase_updates:
        add_group_to_phases(plan_path, group_id, inject_plan.phase_updates)


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

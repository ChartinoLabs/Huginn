"""Select jobs from a catalog by the features scoped on each device.

A catalog is a package of jobs plus an index describing each one. A scope lists
the features found on each device. ``compute_import_plan`` matches the two and
returns the test cases to add to a test plan, without reading or writing files,
so other tools can call it and render the result their own way.

The three input formats are documented in ``docs/reference/catalog-import.md``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from importlib.util import find_spec
from pathlib import Path
from typing import cast

import yaml

from huginn.enums import MatchLevel, TargetMode
from huginn.models import TestCaseDefinition, TestPlan

INDEX_FILENAMES = ("index.json", "index.yaml", "index.yml")
TAXONOMY_FILENAMES = ("taxonomy.yaml", "taxonomy.yml", "taxonomy.json")
DEFAULT_ARCHETYPES = ("static-validation", "volatile-validation")
DEFAULT_GROUP = "catalog-import"
CATALOG_TAG = "catalog"
FRAMEWORK = "huginn"

_MATCH_ORDER = (MatchLevel.SUBFEATURE, MatchLevel.FEATURE, MatchLevel.CATEGORY)


class CatalogImportError(ValueError):
    """Raised when catalog, taxonomy or scope input cannot be used."""


@dataclass(frozen=True)
class CatalogEntry:
    """One job described by a catalog index."""

    key: str
    job: str
    title: str
    operating_systems: tuple[str, ...]
    category: str
    feature: str
    subfeature: str
    archetype: str


@dataclass(frozen=True)
class Taxonomy:
    """Optional names and aliases that make matching broader than exact text.

    ``os_aliases`` maps each normalized alias, and each canonical name, to its
    canonical name. ``subfeatures_by_feature`` and ``features_by_category``
    hold normalized names.
    """

    os_aliases: Mapping[str, str] = field(default_factory=dict)
    subfeatures_by_feature: Mapping[str, frozenset[str]] = field(default_factory=dict)
    features_by_category: Mapping[str, frozenset[str]] = field(default_factory=dict)
    always_include: tuple[str, ...] = ()

    def canonical_os(self, name: str) -> str:
        """Return the canonical name for an operating system name or alias."""
        normalized = _normalize(name)
        return self.os_aliases.get(normalized, normalized)


@dataclass(frozen=True)
class Catalog:
    """A loaded catalog: its Huginn entries and optional taxonomy."""

    entries: tuple[CatalogEntry, ...]
    taxonomy: Taxonomy = field(default_factory=Taxonomy)
    source: str = ""


@dataclass(frozen=True)
class ScopedDevice:
    """The features found on one device."""

    name: str
    os: str
    features: tuple[str, ...]


@dataclass(frozen=True)
class Scope:
    """The features found on every scoped device."""

    devices: tuple[ScopedDevice, ...]


@dataclass(frozen=True)
class ImportOptions:
    """Choices that shape matching and the test cases created."""

    match_level: MatchLevel = MatchLevel.FEATURE
    archetypes: tuple[str, ...] = DEFAULT_ARCHETYPES
    target_mode: TargetMode = TargetMode.OS
    features: tuple[str, ...] = ()
    group_id: str = DEFAULT_GROUP
    tags: tuple[str, ...] = ()
    phases: tuple[str, ...] = ()
    parent_group: str | None = None


@dataclass(frozen=True)
class FeatureMatch:
    """Catalog jobs selected for one scoped feature on one device."""

    device: str
    os: str
    feature: str
    level: MatchLevel | None
    jobs: tuple[str, ...]


@dataclass(frozen=True)
class FeatureGap:
    """A scoped feature with no matching catalog job, on one or more devices."""

    feature: str
    os: str
    devices: tuple[str, ...]


@dataclass(frozen=True)
class NewTestCase:
    """A test case the import adds, and the child group it belongs to."""

    test_id: str
    group_id: str
    group_name: str
    entry: dict[str, object]


@dataclass(frozen=True)
class TargetUpdate:
    """New targets for a catalog job already in the test plan."""

    test_id: str
    job: str
    field: str
    added: tuple[str, ...]


@dataclass(frozen=True)
class ImportPlan:
    """Everything an import would change, and why.

    ``matches`` and ``gaps`` explain the selection. ``new_test_cases``,
    ``target_updates`` and ``skipped_jobs`` describe the change to the plan.
    """

    matches: tuple[FeatureMatch, ...]
    gaps: tuple[FeatureGap, ...]
    new_test_cases: tuple[NewTestCase, ...]
    target_updates: tuple[TargetUpdate, ...]
    skipped_jobs: tuple[str, ...]
    group_id: str
    phases: tuple[str, ...] = ()
    parent_group: str | None = None

    @property
    def has_changes(self) -> bool:
        """Return whether applying the plan would change any file."""
        return bool(self.new_test_cases or self.target_updates)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable form of the plan for reports."""
        return {
            "group": self.group_id,
            "phases": list(self.phases),
            "parent_group": self.parent_group,
            "matches": [
                {
                    "device": m.device,
                    "os": m.os,
                    "feature": m.feature,
                    "level": str(m.level) if m.level else None,
                    "jobs": list(m.jobs),
                }
                for m in self.matches
            ],
            "gaps": [
                {"feature": g.feature, "os": g.os, "devices": list(g.devices)}
                for g in self.gaps
            ],
            "new_test_cases": [
                {"id": tc.test_id, "group": tc.group_id, **tc.entry}
                for tc in self.new_test_cases
            ],
            "target_updates": [
                {
                    "id": u.test_id,
                    "job": u.job,
                    "field": u.field,
                    "added": list(u.added),
                }
                for u in self.target_updates
            ],
            "skipped_jobs": list(self.skipped_jobs),
        }


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_catalog(location: str | Path, taxonomy: Path | None = None) -> Catalog:
    """Load the Huginn entries of a catalog index.

    Args:
        location: The catalog package directory, or the name of an importable
            package. The index file must be directly inside it.
        taxonomy: Taxonomy file. Defaults to a taxonomy file beside the index,
            if there is one.

    Raises:
        CatalogImportError: If the catalog, its index or the taxonomy cannot
            be found or read.
    """
    directory, package = _resolve_catalog_location(location)
    index_path = _find_file(directory, INDEX_FILENAMES)
    if index_path is None:
        raise CatalogImportError(
            f"No catalog index ({', '.join(INDEX_FILENAMES)}) found in {directory}"
        )
    raw_index = _require_mapping(_read_data_file(index_path), str(index_path))
    entries = tuple(
        entry
        for key, raw in sorted(raw_index.items())
        if (entry := _load_entry(key, raw, package, index_path)) is not None
    )

    taxonomy_path = taxonomy or _find_file(directory, TAXONOMY_FILENAMES)
    loaded_taxonomy = load_taxonomy(taxonomy_path) if taxonomy_path else Taxonomy()
    return Catalog(entries=entries, taxonomy=loaded_taxonomy, source=str(directory))


def load_taxonomy(path: Path) -> Taxonomy:
    """Load a taxonomy file.

    Raises:
        CatalogImportError: If the file is missing or malformed.
    """
    if not path.is_file():
        raise CatalogImportError(f"Taxonomy file not found: {path}")
    data = _require_mapping(_read_data_file(path), str(path))
    features_by_category: dict[str, frozenset[str]] = {}
    subfeatures_by_feature: dict[str, set[str]] = {}
    for category, raw_category in _optional_mapping(
        data.get("categories"), f"{path}: categories"
    ).items():
        raw_features = _optional_mapping(
            _require_mapping(raw_category, f"{path}: categories.{category}").get(
                "features"
            ),
            f"{path}: categories.{category}.features",
        )
        features_by_category[_normalize(category)] = frozenset(
            _normalize(name) for name in raw_features
        )
        for feature, raw_subfeatures in raw_features.items():
            names = _string_list(
                raw_subfeatures, f"{path}: categories.{category}.features.{feature}"
            )
            subfeatures_by_feature.setdefault(_normalize(feature), set()).update(
                _normalize(name) for name in names
            )

    return Taxonomy(
        os_aliases=_load_os_aliases(data.get("operating_systems"), path),
        subfeatures_by_feature={
            name: frozenset(values) for name, values in subfeatures_by_feature.items()
        },
        features_by_category=features_by_category,
        always_include=tuple(
            _normalize(name)
            for name in _string_list(
                data.get("always_include", []), f"{path}: always_include"
            )
        ),
    )


def load_scope(path: Path) -> Scope:
    """Load a scope file listing the features found on each device.

    Raises:
        CatalogImportError: If the file is missing or malformed.
    """
    if not path.is_file():
        raise CatalogImportError(f"Scope file not found: {path}")
    data = _require_mapping(_read_data_file(path), str(path))
    raw_devices = data.get("platform_metadata")
    if not isinstance(raw_devices, list):
        raise CatalogImportError(f"{path}: 'platform_metadata' must be a list")

    devices: list[ScopedDevice] = []
    for index, raw in enumerate(cast(list[object], raw_devices)):
        location = f"{path}: platform_metadata[{index}]"
        device = _require_mapping(raw, location)
        name = device.get("device_name")
        os_name = device.get("os_type")
        if not isinstance(name, str) or not name:
            raise CatalogImportError(f"{location}: 'device_name' must be a string")
        if not isinstance(os_name, str) or not os_name:
            raise CatalogImportError(f"{location}: 'os_type' must be a string")
        features = _string_list(device.get("features", []), f"{location}: features")
        devices.append(ScopedDevice(name=name, os=os_name, features=tuple(features)))
    return Scope(devices=tuple(devices))


def _resolve_catalog_location(location: str | Path) -> tuple[Path, str | None]:
    """Return the catalog directory and, when importable, its package name."""
    path = Path(location)
    if path.is_dir():
        package = path.resolve().name
        return path.resolve(), package if package.isidentifier() else None

    name = str(location)
    if not all(part.isidentifier() for part in name.split(".")):
        raise CatalogImportError(f"Catalog not found: {location}")
    try:
        spec = find_spec(name)
    except (ImportError, ValueError) as exc:
        raise CatalogImportError(f"Catalog package not importable: {name}") from exc
    if spec is None or not spec.submodule_search_locations:
        raise CatalogImportError(f"Catalog not found: {location}")
    return Path(next(iter(spec.submodule_search_locations))), name


def _find_file(directory: Path, names: Iterable[str]) -> Path | None:
    for name in names:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


def _read_data_file(path: Path) -> object:
    text = path.read_text(encoding="utf-8")
    try:
        if path.suffix == ".json":
            return json.loads(text)
        return yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise CatalogImportError(f"Failed to parse {path}: {exc}") from exc


def _load_entry(
    key: object, raw: object, package: str | None, index_path: Path
) -> CatalogEntry | None:
    """Return the entry for one index item, or None if it is not a Huginn job."""
    location = f"{index_path}: {key}"
    if not isinstance(key, str):
        raise CatalogImportError(f"{index_path}: index keys must be strings")
    data = _require_mapping(raw, location)
    framework = data.get("framework")
    if framework is not None and str(framework).lower() != FRAMEWORK:
        return None

    title = _optional_string(data.get("title"), f"{location}: title")
    return CatalogEntry(
        key=key,
        job=_entry_job(key, data.get("job"), package, location),
        title=title or _title_from_key(key),
        operating_systems=tuple(
            _string_list(data.get("operating_systems", []), f"{location}: os")
        ),
        category=_optional_string(data.get("category"), f"{location}: category"),
        feature=_optional_string(data.get("feature"), f"{location}: feature"),
        subfeature=_optional_string(data.get("subfeature"), f"{location}: subfeature"),
        archetype=_optional_string(data.get("archetype"), f"{location}: archetype")
        or DEFAULT_ARCHETYPES[0],
    )


def _entry_job(key: str, explicit: object, package: str | None, location: str) -> str:
    """Return an entry's job reference, deriving it from the key if needed."""
    if explicit is not None:
        if not isinstance(explicit, str) or not explicit:
            raise CatalogImportError(f"{location}: 'job' must be a string")
        return explicit
    if package is None:
        raise CatalogImportError(
            f"{location}: no 'job' given, and the catalog directory is not "
            "a package name a job reference can be derived from"
        )
    relative = Path(key)
    if relative.suffix != ".py" or relative.is_absolute() or ".." in relative.parts:
        raise CatalogImportError(f"{location}: key must be a relative '.py' path")
    parts = relative.with_suffix("").parts
    if not all(part.isidentifier() for part in parts):
        raise CatalogImportError(
            f"{location}: key does not form an importable module path"
        )
    return ".".join((package, *parts))


def _title_from_key(key: str) -> str:
    words = Path(key).stem.replace("_", " ").strip()
    return words[:1].upper() + words[1:]


def _load_os_aliases(value: object, path: Path) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for name, raw in _optional_mapping(value, f"{path}: operating_systems").items():
        canonical = _normalize(name)
        aliases[canonical] = canonical
        details = _optional_mapping(raw, f"{path}: operating_systems.{name}")
        for alias in _string_list(
            details.get("aliases", []), f"{path}: operating_systems.{name}.aliases"
        ):
            aliases[_normalize(alias)] = canonical
    return aliases


def _require_mapping(value: object, location: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise CatalogImportError(f"{location}: expected a mapping")
    return cast(dict[str, object], value)


def _optional_mapping(value: object, location: str) -> dict[str, object]:
    return {} if value is None else _require_mapping(value, location)


def _optional_string(value: object, location: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise CatalogImportError(f"{location}: expected a string")
    return value


def _string_list(value: object, location: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise CatalogImportError(f"{location}: expected a list of strings")
    return cast(list[str], value)


def _normalize(name: str) -> str:
    return " ".join(name.lower().replace("_", " ").split())


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


@dataclass
class _Selection:
    """Jobs selected so far, with the OSes and devices each was selected for."""

    os_by_job: dict[str, set[str]] = field(default_factory=dict)
    devices_by_job: dict[str, set[str]] = field(default_factory=dict)

    def add(self, entry: CatalogEntry, device: ScopedDevice) -> None:
        self.os_by_job.setdefault(entry.job, set()).add(device.os)
        self.devices_by_job.setdefault(entry.job, set()).add(device.name)

    def targets(self, job: str, mode: TargetMode) -> list[str]:
        values = self.os_by_job if mode is TargetMode.OS else self.devices_by_job
        return sorted(values[job])


def match_feature(
    catalog: Catalog,
    entries: Iterable[CatalogEntry],
    feature: str,
    max_level: MatchLevel,
) -> tuple[MatchLevel | None, list[CatalogEntry]]:
    """Return the narrowest level at which ``feature`` matches, and its entries.

    ``entries`` should already be limited to the device's OS and the chosen
    archetypes. Levels broader than ``max_level`` are not tried.
    """
    candidates = list(entries)
    wanted = _normalize(feature)
    for level in _MATCH_ORDER[: _MATCH_ORDER.index(max_level) + 1]:
        subfeatures = _subfeatures_for(catalog.taxonomy, level, wanted)
        matched = [
            entry
            for entry in candidates
            if _entry_matches(entry, level, wanted, subfeatures)
        ]
        if matched:
            return level, matched
    return None, []


def _subfeatures_for(
    taxonomy: Taxonomy, level: MatchLevel, name: str
) -> frozenset[str]:
    """Return the subfeatures a taxonomy places under a feature or category."""
    if level is MatchLevel.FEATURE:
        return taxonomy.subfeatures_by_feature.get(name, frozenset())
    if level is MatchLevel.CATEGORY:
        features = taxonomy.features_by_category.get(name, frozenset())
        return frozenset().union(
            *(taxonomy.subfeatures_by_feature.get(f, frozenset()) for f in features)
        )
    return frozenset()


def _entry_matches(
    entry: CatalogEntry, level: MatchLevel, name: str, subfeatures: frozenset[str]
) -> bool:
    """Return whether an entry falls under ``name`` at ``level``."""
    if level is MatchLevel.SUBFEATURE:
        return _normalize(entry.subfeature) == name
    if level is MatchLevel.FEATURE:
        return _normalize(entry.feature) == name or (
            _normalize(entry.subfeature) in subfeatures
        )
    return _normalize(entry.category) == name or (
        _normalize(entry.subfeature) in subfeatures
    )


def _entries_for_device(
    catalog: Catalog, device: ScopedDevice, archetypes: frozenset[str]
) -> list[CatalogEntry]:
    device_os = catalog.taxonomy.canonical_os(device.os)
    return [
        entry
        for entry in catalog.entries
        if _normalize(entry.archetype) in archetypes
        and any(
            catalog.taxonomy.canonical_os(o) == device_os
            for o in entry.operating_systems
        )
    ]


def _select(
    catalog: Catalog, scope: Scope, options: ImportOptions
) -> tuple[list[FeatureMatch], list[FeatureMatch], _Selection]:
    """Match every scoped feature and return matches, misses and selection."""
    archetypes = frozenset(_normalize(name) for name in options.archetypes)
    records: list[FeatureMatch] = []
    selection = _Selection()
    for device in sorted(scope.devices, key=lambda d: d.name):
        candidates = _entries_for_device(catalog, device, archetypes)
        for feature in _device_features(device, options.features):
            records.append(
                _match_device_feature(
                    catalog, candidates, device, feature, options, selection
                )
            )
        _select_always_included(catalog.taxonomy, candidates, device, selection)
    matches = [record for record in records if record.jobs]
    misses = [record for record in records if not record.jobs]
    return matches, misses, selection


def _device_features(device: ScopedDevice, only: Iterable[str]) -> list[str]:
    """Return a device's distinct features, limited to ``only`` when given."""
    wanted = {_normalize(name) for name in only}
    features = {f for f in device.features if not wanted or _normalize(f) in wanted}
    return sorted(features, key=_normalize)


def _match_device_feature(
    catalog: Catalog,
    candidates: list[CatalogEntry],
    device: ScopedDevice,
    feature: str,
    options: ImportOptions,
    selection: _Selection,
) -> FeatureMatch:
    """Match one feature on one device and add its jobs to ``selection``."""
    level, entries = match_feature(catalog, candidates, feature, options.match_level)
    for entry in entries:
        selection.add(entry, device)
    return FeatureMatch(
        device=device.name,
        os=device.os,
        feature=feature,
        level=level,
        jobs=tuple(sorted(entry.job for entry in entries)),
    )


def _select_always_included(
    taxonomy: Taxonomy,
    candidates: list[CatalogEntry],
    device: ScopedDevice,
    selection: _Selection,
) -> None:
    """Add the device's entries for every ``always_include`` subfeature."""
    always = set(taxonomy.always_include)
    for entry in candidates:
        if _normalize(entry.subfeature) in always:
            selection.add(entry, device)


def _gaps(misses: Iterable[FeatureMatch]) -> list[FeatureGap]:
    devices_by_gap: dict[tuple[str, str], set[str]] = {}
    for miss in misses:
        devices_by_gap.setdefault((miss.feature, miss.os), set()).add(miss.device)
    return [
        FeatureGap(feature=feature, os=os_name, devices=tuple(sorted(devices)))
        for (feature, os_name), devices in sorted(devices_by_gap.items())
    ]


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def compute_import_plan(
    catalog: Catalog,
    scope: Scope,
    test_plan: TestPlan,
    options: ImportOptions | None = None,
) -> ImportPlan:
    """Compute the test cases an import adds, without reading or writing files.

    A job already in the test plan is not added again. If the scope now
    targets it on more operating systems or devices, the existing test case
    gets a target update instead. Nothing is ever removed.
    """
    options = options or ImportOptions()
    matches, misses, selection = _select(catalog, scope, options)
    entries_by_job = {entry.job: entry for entry in catalog.entries}
    new_jobs, updates, skipped = _partition_selected(selection, test_plan, options)

    return ImportPlan(
        matches=tuple(matches),
        gaps=tuple(_gaps(misses)),
        new_test_cases=tuple(
            _new_test_cases(new_jobs, entries_by_job, selection, test_plan, options)
        ),
        target_updates=tuple(updates),
        skipped_jobs=tuple(skipped),
        group_id=options.group_id,
        phases=options.phases,
        parent_group=options.parent_group,
    )


def _partition_selected(
    selection: _Selection, test_plan: TestPlan, options: ImportOptions
) -> tuple[list[str], list[TargetUpdate], list[str]]:
    """Split selected jobs into new jobs, target updates and skipped jobs."""
    existing_by_job = {tc.job: tc for tc in test_plan.test_cases.values()}
    new_jobs: list[str] = []
    updates: list[TargetUpdate] = []
    skipped: list[str] = []
    for job in sorted(selection.os_by_job):
        existing = existing_by_job.get(job)
        if existing is None:
            new_jobs.append(job)
        elif update := _target_update(existing, job, selection, options):
            updates.append(update)
        else:
            skipped.append(job)
    return new_jobs, updates, skipped


def _target_update(
    existing: TestCaseDefinition,
    job: str,
    selection: _Selection,
    options: ImportOptions,
) -> TargetUpdate | None:
    """Return the targets to add to an existing test case, if any."""
    target = existing.target
    if target is None:
        # No target means every device, which already covers the selection.
        return None
    field_name = "os" if options.target_mode is TargetMode.OS else "devices"
    current = target.os if options.target_mode is TargetMode.OS else target.devices
    if current is None:
        # The test case targets by another selector; leave it to its author.
        return None
    added = [
        value
        for value in selection.targets(job, options.target_mode)
        if value not in current
    ]
    if not added:
        return None
    return TargetUpdate(
        test_id=existing.test_id, job=job, field=field_name, added=tuple(added)
    )


def _new_test_cases(
    jobs: list[str],
    entries_by_job: Mapping[str, CatalogEntry],
    selection: _Selection,
    test_plan: TestPlan,
    options: ImportOptions,
) -> list[NewTestCase]:
    existing_ids = set(test_plan.test_cases)
    counters: dict[str, int] = {}
    created: list[NewTestCase] = []
    for job in jobs:
        entry = entries_by_job[job]
        group_id = child_group_id(options.group_id, entry.subfeature or entry.feature)
        prefix = group_id.upper()
        counter = counters.get(prefix, _highest_counter(prefix, existing_ids)) + 1
        counters[prefix] = counter
        target_field = "os" if options.target_mode is TargetMode.OS else "devices"
        tags = [CATALOG_TAG]
        if entry.subfeature:
            tags.append(entry.subfeature)
        tags.extend(tag for tag in options.tags if tag not in tags)
        created.append(
            NewTestCase(
                test_id=f"{prefix}-{counter}",
                group_id=group_id,
                group_name=entry.subfeature or entry.feature or group_id,
                entry={
                    "title": entry.title,
                    "job": job,
                    "tags": tags,
                    "target": {
                        target_field: selection.targets(job, options.target_mode)
                    },
                },
            )
        )
    return created


def child_group_id(parent: str, name: str) -> str:
    """Return the child group ID for a subfeature under the import group."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"{parent}-{slug}" if slug else f"{parent}-other"


def _highest_counter(prefix: str, existing_ids: set[str]) -> int:
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
    return max(
        (int(m.group(1)) for test_id in existing_ids if (m := pattern.match(test_id))),
        default=0,
    )

"""Unit tests for selecting catalog jobs by scoped device features."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner, Result

from huginn.catalog_import import (
    Catalog,
    CatalogImportError,
    ImportOptions,
    ImportPlan,
    Scope,
    ScopedDevice,
    apply_import_plan,
    compute_import_plan,
    load_catalog,
    load_scope,
    load_taxonomy,
)
from huginn.cli import app
from huginn.enums import MatchLevel, TargetMode
from huginn.jobs import load_test_case_class
from huginn.loaders import load_test_plan
from huginn.models import TargetDefinition, TestCaseDefinition, TestPlan

CATALOGS = Path(__file__).resolve().parent / "fixtures" / "catalogs"
CATALOG_DIR = CATALOGS / "fake_catalog"

PEERS_UP = "fake_catalog.alpha.routing.verify_peers_up"
PEER_COUNT = "fake_catalog.alpha.routing.verify_peer_count"
ROUTES = "fake_catalog.alpha.routing.verify_routes_present"
RIB = "fake_catalog.alpha.routing.verify_rib_counters_increasing"
ADJACENCY = "fake_catalog.alpha.routing.verify_area_adjacency"
UPTIME = "fake_catalog.alpha.health.verify_uptime"
RESET = "fake_catalog.alpha.change.apply_peer_reset"
GATE = "fake_catalog.alpha.change.gate_peers_stable"
BUNDLE = "fake_catalog.beta.switching.verify_bundle_members"
KEEPALIVE = "fake_catalog.beta.switching.verify_pair_keepalive"


@pytest.fixture
def catalog() -> Catalog:
    """Load the fake catalog with its taxonomy."""
    return load_catalog(CATALOG_DIR)


@pytest.fixture
def no_always_catalog(tmp_path: Path) -> Catalog:
    """Load the fake catalog with a taxonomy that has no ``always_include``."""
    taxonomy = yaml.safe_load((CATALOG_DIR / "taxonomy.yaml").read_text())
    del taxonomy["always_include"]
    path = tmp_path / "taxonomy.yaml"
    path.write_text(yaml.safe_dump(taxonomy))
    return load_catalog(CATALOG_DIR, taxonomy=path)


@pytest.fixture
def importable_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the fake catalog importable as a package."""
    monkeypatch.syspath_prepend(str(CATALOGS))
    for module in list(sys.modules):
        if module == "fake_catalog" or module.startswith("fake_catalog."):
            monkeypatch.delitem(sys.modules, module, raising=False)


def _plan(test_cases: dict[str, TestCaseDefinition] | None = None) -> TestPlan:
    return TestPlan(scenarios={}, test_case_groups={}, test_cases=test_cases or {})


def _scope(*devices: tuple[str, str, list[str]]) -> Scope:
    return Scope(
        devices=tuple(
            ScopedDevice(name=name, os=os_name, features=tuple(features))
            for name, os_name, features in devices
        )
    )


def _target_values(entry: dict[str, object], field: str) -> list[str]:
    target = entry["target"]
    assert isinstance(target, dict)
    return list(target[field])


def _jobs(plan: ImportPlan) -> list[str]:
    return [str(tc.entry["job"]) for tc in plan.new_test_cases]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def test_load_catalog_keeps_only_huginn_entries(catalog: Catalog) -> None:
    """Entries for another framework are dropped; a missing framework is kept."""
    jobs = {entry.job for entry in catalog.entries}
    assert len(jobs) == 10
    assert KEEPALIVE in jobs
    assert not any("robot" in job for job in jobs)


def test_load_catalog_derives_job_title_and_archetype(catalog: Catalog) -> None:
    """Job references come from keys; missing title and archetype get defaults."""
    by_job = {entry.job: entry for entry in catalog.entries}
    assert by_job[ROUTES].title == "Verify routes present"
    assert by_job[KEEPALIVE].archetype == "static-validation"


def test_load_catalog_from_package_name(importable_catalog: None) -> None:
    """A catalog can be named by its importable package."""
    loaded = load_catalog("fake_catalog")
    assert PEERS_UP in {entry.job for entry in loaded.entries}


def test_derived_job_reference_loads(importable_catalog: None) -> None:
    """A job reference derived from an index key loads as a test case class."""
    job_class = load_test_case_class(PEERS_UP, Path.cwd())
    assert job_class.__name__ == "VerifyPeersUp"


def test_explicit_job_reference_wins(tmp_path: Path) -> None:
    """An entry's explicit ``job`` is used as written."""
    (tmp_path / "index.json").write_text(
        json.dumps({"x.py": {"job": "pkg.mod:Cls", "subfeature": "a"}})
    )
    loaded = load_catalog(tmp_path)
    assert loaded.entries[0].job == "pkg.mod:Cls"


@pytest.mark.parametrize(
    ("index", "message"),
    [
        ({"../x.py": {}}, "relative '.py' path"),
        ({"x.robot": {}}, "relative '.py' path"),
        ({"1bad/x.py": {}}, "importable module path"),
        ({"x.py": {"operating_systems": "alpha"}}, "list of strings"),
        ({"x.py": {"title": 3}}, "expected a string"),
    ],
)
def test_load_catalog_rejects_bad_entries(
    tmp_path: Path, index: dict[str, object], message: str
) -> None:
    """Malformed entries name the entry and the problem."""
    catalog_dir = tmp_path / "pkg"
    catalog_dir.mkdir()
    (catalog_dir / "index.json").write_text(json.dumps(index))
    with pytest.raises(CatalogImportError, match=message):
        load_catalog(catalog_dir)


def test_load_catalog_without_package_needs_explicit_jobs(tmp_path: Path) -> None:
    """A directory that is not a package name cannot derive job references."""
    catalog_dir = tmp_path / "not-a-package"
    catalog_dir.mkdir()
    (catalog_dir / "index.json").write_text(json.dumps({"x.py": {}}))
    with pytest.raises(CatalogImportError, match="no 'job' given"):
        load_catalog(catalog_dir)


def test_load_catalog_errors(tmp_path: Path) -> None:
    """Missing catalogs and indexes are reported."""
    with pytest.raises(CatalogImportError, match="Catalog not found"):
        load_catalog(tmp_path / "missing")
    with pytest.raises(CatalogImportError, match="Catalog not found"):
        load_catalog("no_such_catalog_package")
    with pytest.raises(CatalogImportError, match="No catalog index"):
        load_catalog(tmp_path)


def test_load_catalog_rejects_unparseable_index(tmp_path: Path) -> None:
    """A broken index file is a catalog error, not a traceback."""
    (tmp_path / "index.json").write_text("{not json")
    with pytest.raises(CatalogImportError, match="Failed to parse"):
        load_catalog(tmp_path)


def test_load_catalog_with_explicit_taxonomy(tmp_path: Path) -> None:
    """An explicit taxonomy file replaces the one beside the index."""
    taxonomy = tmp_path / "other.yaml"
    taxonomy.write_text(yaml.safe_dump({"always_include": ["route tables"]}))
    loaded = load_catalog(CATALOG_DIR, taxonomy=taxonomy)
    assert loaded.taxonomy.always_include == ("route tables",)
    assert loaded.taxonomy.os_aliases == {}


def test_load_taxonomy_normalizes_names() -> None:
    """Taxonomy names are case- and underscore-insensitive."""
    taxonomy = load_taxonomy(CATALOG_DIR / "taxonomy.yaml")
    assert taxonomy.canonical_os("ALPHA_OS") == "alpha os"
    assert taxonomy.canonical_os("alphaos") == "alpha-os"
    assert taxonomy.subfeatures_by_feature["link state"] == {"area adjacency"}


def test_load_taxonomy_errors(tmp_path: Path) -> None:
    """Missing and malformed taxonomy files are reported."""
    with pytest.raises(CatalogImportError, match="not found"):
        load_taxonomy(tmp_path / "missing.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump({"categories": {"routing": {"features": []}}}))
    with pytest.raises(CatalogImportError, match="expected a mapping"):
        load_taxonomy(bad)


def test_load_scope_reads_devices(tmp_path: Path) -> None:
    """Scope files list each device's features; other keys are ignored."""
    path = tmp_path / "scope.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "platform_metadata": [
                    {
                        "device_name": "r1",
                        "os_type": "alphaos",
                        "os_version": "1.0",
                        "features": ["peering"],
                        "errors": [],
                    }
                ]
            }
        )
    )
    scope = load_scope(path)
    assert scope.devices == (ScopedDevice("r1", "alphaos", ("peering",)),)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ({"devices": []}, "'platform_metadata' must be a list"),
        ({"platform_metadata": [{"os_type": "a"}]}, "'device_name'"),
        ({"platform_metadata": [{"device_name": "r1"}]}, "'os_type'"),
        (
            {
                "platform_metadata": [
                    {"device_name": "r1", "os_type": "a", "features": "x"}
                ]
            },
            "list of strings",
        ),
    ],
)
def test_load_scope_errors(
    tmp_path: Path, content: dict[str, object], message: str
) -> None:
    """Malformed scope files name the device and field."""
    path = tmp_path / "scope.yaml"
    path.write_text(yaml.safe_dump(content))
    with pytest.raises(CatalogImportError, match=message):
        load_scope(path)
    with pytest.raises(CatalogImportError, match="not found"):
        load_scope(tmp_path / "missing.yaml")


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def test_subfeature_match(catalog: Catalog) -> None:
    """A feature that names a subfeature selects only that subfeature's jobs."""
    plan = compute_import_plan(
        catalog, _scope(("r1", "alphaos", ["Peer_Sessions"])), _plan()
    )
    assert plan.matches[0].level is MatchLevel.SUBFEATURE
    assert plan.matches[0].jobs == (PEER_COUNT, PEERS_UP)


def test_feature_match_includes_feature_field_and_taxonomy(catalog: Catalog) -> None:
    """A feature selects its own entries and every subfeature under it."""
    plan = compute_import_plan(catalog, _scope(("r1", "alpha", ["peering"])), _plan())
    assert plan.matches[0].level is MatchLevel.FEATURE
    assert set(plan.matches[0].jobs) == {PEER_COUNT, PEERS_UP, RIB, ROUTES}


def test_category_match_needs_category_level(catalog: Catalog) -> None:
    """A category only matches when ``--match-level category`` allows it."""
    scope = _scope(("r1", "alpha-os", ["routing"]))
    narrow = compute_import_plan(catalog, scope, _plan())
    assert narrow.matches == ()
    assert [gap.feature for gap in narrow.gaps] == ["routing"]

    broad = compute_import_plan(
        catalog, scope, _plan(), ImportOptions(match_level=MatchLevel.CATEGORY)
    )
    assert broad.matches[0].level is MatchLevel.CATEGORY
    assert ADJACENCY in broad.matches[0].jobs


def test_match_level_caps_feature_matching(catalog: Catalog) -> None:
    """``subfeature`` level does not fall back to feature names."""
    plan = compute_import_plan(
        catalog,
        _scope(("r1", "alpha-os", ["peering"])),
        _plan(),
        ImportOptions(match_level=MatchLevel.SUBFEATURE),
    )
    assert plan.matches == ()
    assert plan.gaps[0].feature == "peering"


def test_os_aliases_match_both_sides(catalog: Catalog) -> None:
    """Scope and catalog OS names are compared through taxonomy aliases."""
    plan = compute_import_plan(
        catalog, _scope(("s1", "betaos", ["bundling", "pairing"])), _plan()
    )
    assert {job for match in plan.matches for job in match.jobs} == {
        BUNDLE,
        KEEPALIVE,
    }


def test_without_taxonomy_names_must_match_exactly(tmp_path: Path) -> None:
    """Without a taxonomy, only exact OS names and entry fields match."""
    taxonomy = tmp_path / "empty.yaml"
    taxonomy.write_text("{}\n")
    loaded = load_catalog(CATALOG_DIR, taxonomy=taxonomy)
    alias = compute_import_plan(loaded, _scope(("r1", "alphaos", ["peering"])), _plan())
    assert alias.matches == ()
    exact = compute_import_plan(
        loaded, _scope(("r1", "alpha-os", ["peering"])), _plan()
    )
    assert set(exact.matches[0].jobs) == {PEER_COUNT, PEERS_UP, RIB, ROUTES}


def test_other_os_entries_are_not_selected(catalog: Catalog) -> None:
    """A device only gets entries for its own OS."""
    plan = compute_import_plan(catalog, _scope(("s1", "beta-os", ["peering"])), _plan())
    assert plan.matches == ()
    assert plan.gaps[0].os == "beta-os"


def test_change_and_gate_need_opt_in(catalog: Catalog) -> None:
    """Default archetypes leave out change and gate jobs."""
    scope = _scope(("r1", "alpha-os", ["peer sessions"]))
    default = compute_import_plan(catalog, scope, _plan())
    assert RESET not in _jobs(default)
    assert GATE not in _jobs(default)

    opted_in = compute_import_plan(
        catalog,
        scope,
        _plan(),
        ImportOptions(archetypes=("change", "gate", "static-validation")),
    )
    assert {RESET, GATE} <= set(_jobs(opted_in))


def test_volatile_validation_is_selected_by_default(catalog: Catalog) -> None:
    """Volatile validation jobs are part of the default archetypes."""
    plan = compute_import_plan(
        catalog, _scope(("r1", "alpha", ["route tables"])), _plan()
    )
    assert RIB in _jobs(plan)


def test_always_include_adds_health_jobs(catalog: Catalog) -> None:
    """``always_include`` subfeatures are selected for every scoped OS."""
    plan = compute_import_plan(
        catalog, _scope(("r1", "alpha", []), ("s1", "beta", [])), _plan()
    )
    assert _jobs(plan) == [UPTIME]
    assert plan.new_test_cases[0].entry["target"] == {"os": ["alpha", "beta"]}


def test_features_filter_and_gaps(catalog: Catalog) -> None:
    """``features`` limits matching; unmatched features become gaps per OS."""
    scope = _scope(
        ("r1", "alpha", ["peering", "telemetry"]),
        ("r2", "alpha", ["telemetry"]),
    )
    plan = compute_import_plan(
        catalog, scope, _plan(), ImportOptions(features=("Telemetry",))
    )
    assert plan.matches == ()
    assert [(g.feature, g.devices) for g in plan.gaps] == [("telemetry", ("r1", "r2"))]


def test_selection_is_deterministic(catalog: Catalog) -> None:
    """Device and feature order in the scope do not change the plan."""
    one = _scope(
        ("r2", "alpha", ["link state", "peering"]), ("r1", "alpha", ["peering"])
    )
    two = _scope(
        ("r1", "alpha", ["peering"]), ("r2", "alpha", ["peering", "link state"])
    )
    assert compute_import_plan(catalog, one, _plan()).to_dict() == (
        compute_import_plan(catalog, two, _plan()).to_dict()
    )


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def test_new_test_cases_shape(no_always_catalog: Catalog) -> None:
    """New test cases carry title, job, tags and an OS target."""
    plan = compute_import_plan(
        no_always_catalog,
        _scope(
            ("r1", "alphaos", ["peer sessions"]), ("r2", "alpha", ["peer sessions"])
        ),
        _plan(),
        ImportOptions(tags=("baseline", "catalog")),
    )
    first = plan.new_test_cases[0]
    assert first.test_id == "CATALOG-IMPORT-PEER-SESSIONS-1"
    assert first.group_id == "catalog-import-peer-sessions"
    assert first.group_name == "peer sessions"
    assert first.entry == {
        "title": "Verify Peer Count",
        "job": PEER_COUNT,
        "tags": ["catalog", "peer sessions", "baseline"],
        "target": {"os": ["alpha", "alphaos"]},
    }


def test_device_target_mode(no_always_catalog: Catalog) -> None:
    """Device targeting lists only the devices that run the feature."""
    plan = compute_import_plan(
        no_always_catalog,
        _scope(("r1", "alpha", ["area adjacency"]), ("r2", "alpha", ["peering"])),
        _plan(),
        ImportOptions(target_mode=TargetMode.DEVICES),
    )
    targets = {tc.entry["job"]: tc.entry["target"] for tc in plan.new_test_cases}
    assert targets[ADJACENCY] == {"devices": ["r1"]}
    assert targets[PEERS_UP] == {"devices": ["r2"]}


def test_ids_continue_after_existing_counters(no_always_catalog: Catalog) -> None:
    """Allocated IDs follow the highest counter already in the plan."""
    existing = {
        "CATALOG-IMPORT-PEER-SESSIONS-7": TestCaseDefinition(
            test_id="CATALOG-IMPORT-PEER-SESSIONS-7", title="x", job="jobs/x.py"
        )
    }
    plan = compute_import_plan(
        no_always_catalog, _scope(("r1", "alpha", ["peer sessions"])), _plan(existing)
    )
    assert [tc.test_id for tc in plan.new_test_cases] == [
        "CATALOG-IMPORT-PEER-SESSIONS-8",
        "CATALOG-IMPORT-PEER-SESSIONS-9",
    ]


def test_existing_jobs_are_skipped_or_widened(no_always_catalog: Catalog) -> None:
    """Jobs already in the plan are not duplicated; new targets are reported."""
    existing = {
        "A": TestCaseDefinition(
            test_id="A",
            title="Peers",
            job=PEERS_UP,
            target=TargetDefinition(os=["alpha"]),
        ),
        "B": TestCaseDefinition(test_id="B", title="Count", job=PEER_COUNT),
    }
    scope = _scope(
        ("r1", "alpha", ["peer sessions"]), ("r2", "alphaos", ["peer sessions"])
    )
    plan = compute_import_plan(no_always_catalog, scope, _plan(existing))
    assert plan.new_test_cases == ()
    assert [(u.test_id, u.field, u.added) for u in plan.target_updates] == [
        ("A", "os", ("alphaos",))
    ]
    assert plan.skipped_jobs == (PEER_COUNT,)
    assert plan.has_changes


def test_existing_job_with_other_selector_is_left_alone(
    no_always_catalog: Catalog,
) -> None:
    """A test case targeted by groups is not widened in OS mode."""
    existing = {
        "A": TestCaseDefinition(
            test_id="A",
            title="Peers",
            job=PEERS_UP,
            target=TargetDefinition(groups=["core"]),
        )
    }
    plan = compute_import_plan(
        no_always_catalog, _scope(("r1", "alpha", ["peer sessions"])), _plan(existing)
    )
    assert plan.target_updates == ()
    assert PEERS_UP in plan.skipped_jobs


def test_reimport_after_apply_changes_nothing(no_always_catalog: Catalog) -> None:
    """Running the same import again on its own output plans no changes."""
    scope = _scope(("r1", "alpha", ["peering"]))
    first = compute_import_plan(no_always_catalog, scope, _plan())
    existing = {
        tc.test_id: TestCaseDefinition(
            test_id=tc.test_id,
            title=str(tc.entry["title"]),
            job=str(tc.entry["job"]),
            target=TargetDefinition(os=_target_values(tc.entry, "os")),
        )
        for tc in first.new_test_cases
    }
    second = compute_import_plan(no_always_catalog, scope, _plan(existing))
    assert not second.has_changes
    assert len(second.skipped_jobs) == len(first.new_test_cases)


def test_to_dict_is_json_serializable(catalog: Catalog) -> None:
    """The report form of a plan round-trips through JSON."""
    plan = compute_import_plan(
        catalog,
        _scope(("r1", "alpha", ["peering", "telemetry"])),
        _plan(),
        ImportOptions(phases=("pre",), parent_group="baseline"),
    )
    report = json.loads(json.dumps(plan.to_dict()))
    assert report["group"] == "catalog-import"
    assert report["phases"] == ["pre"]
    assert report["parent_group"] == "baseline"
    assert report["gaps"] == [
        {"feature": "telemetry", "os": "alpha", "devices": ["r1"]}
    ]
    assert report["matches"][0]["level"] == "feature"
    assert report["new_test_cases"][0]["id"].startswith("CATALOG-IMPORT-")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _write_cli_inputs(tmp_path: Path) -> tuple[Path, Path]:
    """Write a minimal test plan and a scope file, and return their paths."""
    plan_path = tmp_path / "test_plan"
    (plan_path / "groups").mkdir(parents=True)
    (plan_path / "test_cases.yaml").write_text(
        yaml.safe_dump(
            {"test_cases": {"1.0.0": {"title": "Ping", "job": "jobs/ping.py"}}}
        )
    )
    (plan_path / "groups" / "base.yaml").write_text(
        yaml.safe_dump(
            {
                "test_case_groups": {
                    "base": {"tests": ["1.0.0"]},
                    "baseline": {"groups": ["base"]},
                }
            }
        )
    )
    (plan_path / "scenarios.yaml").write_text(
        yaml.safe_dump(
            {"scenarios": {"s": {"phases": {"pre": {"test_case_groups": ["base"]}}}}}
        )
    )
    scope_path = tmp_path / "scope.yaml"
    scope_path.write_text(
        yaml.safe_dump(
            {
                "platform_metadata": [
                    {
                        "device_name": "r1",
                        "os_type": "alphaos",
                        "features": ["peering", "telemetry"],
                    }
                ]
            }
        )
    )
    return plan_path, scope_path


def _write_testbed(tmp_path: Path, devices: dict[str, str]) -> Path:
    """Write a testbed with the given device names and operating systems."""
    path = tmp_path / "testbed.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "devices": {
                    name: {
                        "os": os_name,
                        "connections": {
                            "cli": {"protocol": "ssh", "host": "192.0.2.1"}
                        },
                    }
                    for name, os_name in devices.items()
                }
            }
        )
    )
    return path


def _cli_args(plan_path: Path, scope_path: Path, *extra: str) -> list[str]:
    return [
        "import",
        "--catalog",
        str(CATALOG_DIR),
        "--scope",
        str(scope_path),
        "--plan",
        str(plan_path),
        *extra,
    ]


def test_cli_dry_run_reports_matches_and_gaps(tmp_path: Path) -> None:
    """A dry run prints matches, gaps and new test cases and writes nothing."""
    plan_path, scope_path = _write_cli_inputs(tmp_path)
    before = sorted(p.name for p in plan_path.rglob("*"))
    result = CliRunner().invoke(app, _cli_args(plan_path, scope_path, "--dry-run"))
    assert result.exit_code == 0, result.output
    assert "Matched 1 scoped feature(s)" in result.output
    assert "telemetry (alphaos): r1" in result.output
    assert "Verify Peers Up" in result.output
    assert "Dry run" in result.output
    assert sorted(p.name for p in plan_path.rglob("*")) == before


def test_cli_dry_run_json(tmp_path: Path) -> None:
    """``--format json`` prints the plan report as JSON."""
    plan_path, scope_path = _write_cli_inputs(tmp_path)
    result = CliRunner().invoke(
        app,
        _cli_args(
            plan_path,
            scope_path,
            "--dry-run",
            "--format",
            "json",
            "--target",
            "devices",
            "--testbed",
            str(_write_testbed(tmp_path, {"r1": "alpha-os"})),
            "--archetype",
            "static-validation",
        ),
    )
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["gaps"][0]["feature"] == "telemetry"
    jobs = {tc["job"] for tc in report["new_test_cases"]}
    assert RIB not in jobs
    assert all(tc["target"] == {"devices": ["r1"]} for tc in report["new_test_cases"])


def test_cli_reports_bad_catalog(tmp_path: Path) -> None:
    """A catalog error exits 1 with the error message."""
    plan_path, scope_path = _write_cli_inputs(tmp_path)
    args = _cli_args(plan_path, scope_path, "--dry-run")
    args[args.index("--catalog") + 1] = str(tmp_path / "missing")
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 1
    assert "Catalog not found" in result.output


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def _import(tmp_path: Path, *extra: str) -> Result:
    """Run a writing import from ``tmp_path`` against the default inputs."""
    plan_path = tmp_path / "test_plan"
    return CliRunner().invoke(
        app, _cli_args(plan_path, tmp_path / "scope.yaml", *extra)
    )


@pytest.fixture
def project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, importable_catalog: None
) -> Path:
    """A project directory with a plan and scope, used as the working directory."""
    _write_cli_inputs(tmp_path)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _load(path: Path) -> Any:  # noqa: ANN401
    return yaml.safe_load(path.read_text())


def test_import_writes_cases_groups_and_wiring(project: Path) -> None:
    """An import writes test cases and groups, and wires the group in."""
    result = _import(project, "--phase", "pre", "--parent-group", "baseline")
    assert result.exit_code == 0, result.output
    assert "Imported 5 test case(s)" in result.output

    plan_path = project / "test_plan"
    cases = _load(plan_path / "test_cases" / "catalog-import.yaml")["test_cases"]
    assert isinstance(cases, dict)
    assert {tc["job"] for tc in cases.values()} == {
        PEER_COUNT,
        PEERS_UP,
        RIB,
        ROUTES,
        UPTIME,
    }
    groups = _load(plan_path / "groups" / "catalog-import.yaml")["test_case_groups"]
    assert isinstance(groups, dict)
    assert groups["catalog-import"] == {
        "groups": [
            "catalog-import-device-health",
            "catalog-import-peer-sessions",
            "catalog-import-route-tables",
        ]
    }
    assert groups["catalog-import-peer-sessions"]["name"] == "peer sessions"
    base = _load(plan_path / "groups" / "base.yaml")["test_case_groups"]
    assert base["baseline"]["groups"] == ["base", "catalog-import"]
    scenarios = _load(plan_path / "scenarios.yaml")
    assert scenarios["scenarios"]["s"]["phases"]["pre"]["test_case_groups"] == [
        "base",
        "catalog-import",
    ]

    loaded = load_test_plan(plan_path)
    assert "catalog-import" in loaded.test_case_groups


def test_import_twice_changes_nothing(project: Path) -> None:
    """A second identical import reports nothing to do and writes nothing."""
    assert _import(project, "--phase", "pre").exit_code == 0
    files = {p: p.read_text() for p in (project / "test_plan").rglob("*.yaml")}
    result = _import(project, "--phase", "pre")
    assert result.exit_code == 0, result.output
    assert "up to date" in result.output
    assert {p: p.read_text() for p in (project / "test_plan").rglob("*.yaml")} == (
        files
    )


def test_import_extends_existing_groups_and_widens_targets(project: Path) -> None:
    """A later import adds to existing child groups and widens targets."""
    first = _import(
        project, "--features", "peering", "--archetype", "static-validation"
    )
    assert first.exit_code == 0, first.output
    assert "Imported 4 test case(s)" in first.output

    (project / "scope.yaml").write_text(
        yaml.safe_dump(
            {
                "platform_metadata": [
                    {
                        "device_name": "r1",
                        "os_type": "alphaos",
                        "features": ["peering"],
                    },
                    {"device_name": "r2", "os_type": "alpha", "features": ["peering"]},
                ]
            }
        )
    )
    result = _import(project)
    assert result.exit_code == 0, result.output
    assert "Imported 1 test case(s) and widened 4 target(s)" in result.output

    plan_path = project / "test_plan"
    cases = _load(plan_path / "test_cases" / "catalog-import.yaml")["test_cases"]
    assert isinstance(cases, dict)
    by_job = {tc["job"]: (test_id, tc) for test_id, tc in cases.items()}
    assert by_job[PEERS_UP][1]["target"] == {"os": ["alphaos", "alpha"]}
    assert by_job[RIB][0] == "CATALOG-IMPORT-ROUTE-TABLES-2"
    assert by_job[RIB][1]["target"] == {"os": ["alpha", "alphaos"]}
    groups = _load(plan_path / "groups" / "catalog-import.yaml")["test_case_groups"]
    assert isinstance(groups, dict)
    assert groups["catalog-import-route-tables"]["tests"] == [
        "CATALOG-IMPORT-ROUTE-TABLES-1",
        "CATALOG-IMPORT-ROUTE-TABLES-2",
    ]
    assert groups["catalog-import"]["groups"] == [
        "catalog-import-device-health",
        "catalog-import-peer-sessions",
        "catalog-import-route-tables",
    ]
    load_test_plan(plan_path)


def test_import_targets_testbed_os_names(project: Path) -> None:
    """With a testbed, OS targets use the testbed's name for each device."""
    testbed = _write_testbed(project, {"r1": "alpha-os"})
    result = _import(project, "--testbed", str(testbed), "--features", "peering")
    assert result.exit_code == 0, result.output
    cases = _load(project / "test_plan" / "test_cases" / "catalog-import.yaml")
    targets = {tc["target"]["os"][0] for tc in cases["test_cases"].values()}
    assert targets == {"alpha-os"}


def test_import_warns_on_devices_missing_from_testbed(project: Path) -> None:
    """OS targeting warns about scoped devices the testbed does not define."""
    _write_testbed(project, {"other": "alpha-os"})
    result = _import(project, "--dry-run")
    assert result.exit_code == 0, result.output
    assert "not in testbed" in result.output


def test_device_targeting_rejects_unknown_devices(project: Path) -> None:
    """Device targeting fails on scoped devices the testbed does not define."""
    _write_testbed(project, {"other": "alpha-os"})
    result = _import(project, "--target", "devices")
    assert result.exit_code == 1
    assert "not in testbed" in result.output
    assert not (project / "test_plan" / "test_cases").exists()


def test_import_checks_parent_and_scenarios_before_writing(project: Path) -> None:
    """A missing parent group or scenarios file fails before any file changes."""
    result = _import(project, "--parent-group", "nope")
    assert result.exit_code == 1
    assert "Parent group 'nope' not found" in result.output

    (project / "test_plan" / "scenarios.yaml").rename(project / "elsewhere.yaml")
    (project / "test_plan" / "groups" / "s.yaml").write_text(
        yaml.safe_dump(
            {"scenarios": {"s": {"phases": {"pre": {"test_case_groups": ["base"]}}}}}
        )
    )
    result = _import(project, "--phase", "pre")
    assert result.exit_code == 1
    assert "No scenarios.yaml" in result.output
    assert not (project / "test_plan" / "test_cases").exists()


def test_import_json_report_then_write(project: Path) -> None:
    """``--format json`` without ``--dry-run`` prints the report and writes."""
    result = _import(project, "--format", "json")
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["new_test_cases"]
    assert (project / "test_plan" / "test_cases" / "catalog-import.yaml").exists()


def test_import_into_single_file_plan_is_refused(project: Path) -> None:
    """Writing needs a plan directory, not a single plan file."""
    single = project / "plan.yaml"
    single.write_text(
        yaml.safe_dump(
            {
                "test_cases": {"1": {"title": "P", "job": "jobs/p.py"}},
                "test_case_groups": {"g": {"tests": ["1"]}},
                "scenarios": {"s": {"phases": {"p": {"test_case_groups": ["g"]}}}},
            }
        )
    )
    plan = compute_import_plan(
        load_catalog(CATALOG_DIR),
        _scope(("r1", "alpha", ["peering"])),
        load_test_plan(single),
    )
    with pytest.raises(CatalogImportError, match="must be a directory"):
        apply_import_plan(single, plan)


def test_apply_without_changes_writes_nothing(tmp_path: Path) -> None:
    """An empty plan is a no-op, even for a missing directory."""
    plan = compute_import_plan(load_catalog(CATALOG_DIR), _scope(), _plan())
    apply_import_plan(tmp_path / "missing", plan)
    assert not (tmp_path / "missing").exists()

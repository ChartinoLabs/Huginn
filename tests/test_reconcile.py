"""Unit tests for the reconcile module."""

import json
from pathlib import Path

import pytest
import yaml

from huginn.models import (
    Phase,
    Scenario,
    TargetDefinition,
    TestCaseDefinition,
    TestCaseGroup,
    TestPlan,
)
from huginn.output import Output
from huginn.reconcile import (
    FailingTestCase,
    ReconcileError,
    ReconcileInput,
    apply_reconcile_plan,
    compute_reconcile_plan,
    copy_parameter_files,
    find_latest_testing_results,
    parse_failures_from_run,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_json(path: Path, payload: object) -> Path:
    """Write a JSON file and return its path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _write_yaml_file(path: Path, data: dict) -> Path:
    """Write a YAML file and return its path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
    return path


def _build_run_json(
    *,
    scenario_id: str = "scenario-1",
    phase_id: str = "post-change",
    groups: list[dict] | None = None,
) -> dict:
    """Build a minimal run.json payload."""
    if groups is None:
        groups = [
            {
                "id": "connectivity",
                "name": "connectivity",
                "status": "partial",
                "test_cases": [
                    {
                        "test_id": "1.0.0",
                        "title": "Verify reachability",
                        "status": "passed",
                        "result_path": "test-cases/1.0.0/result.json",
                    },
                    {
                        "test_id": "2.0.0",
                        "title": "Verify OSPF neighbors",
                        "status": "failed",
                        "result_path": "test-cases/2.0.0/result.json",
                    },
                    {
                        "test_id": "3.0.0",
                        "title": "Verify BGP sessions",
                        "status": "failed",
                        "result_path": "test-cases/3.0.0/result.json",
                    },
                ],
            },
        ]
    return {
        "summary": {
            "status": "failed",
            "total": 3,
            "passed": 1,
            "failed": 2,
            "errored": 0,
            "not_applicable": 0,
            "skipped": 0,
            "blocked": 0,
        },
        "mode": "testing",
        "scenarios": [
            {
                "id": scenario_id,
                "name": scenario_id,
                "status": "failed",
                "phases": [
                    {
                        "id": phase_id,
                        "name": phase_id,
                        "status": "partial",
                        "test_case_groups": groups,
                    },
                ],
            },
        ],
    }


def _build_test_plan() -> TestPlan:
    """Build an in-memory TestPlan matching the default run.json fixture."""
    return TestPlan(
        test_cases={
            "1.0.0": TestCaseDefinition(
                test_id="1.0.0",
                title="Verify reachability",
                job="tests/verify_reachability.py",
            ),
            "2.0.0": TestCaseDefinition(
                test_id="2.0.0",
                title="Verify OSPF neighbors",
                job="tests/verify_ospf.py",
                tags=["ospf"],
            ),
            "3.0.0": TestCaseDefinition(
                test_id="3.0.0",
                title="Verify BGP sessions",
                job="tests/verify_bgp.py",
                tags=["bgp"],
                target=TargetDefinition(groups=["spine"]),
            ),
        },
        test_case_groups={
            "connectivity": TestCaseGroup(
                identifier="connectivity",
                tests=["1.0.0", "2.0.0", "3.0.0"],
            ),
        },
        scenarios={
            "scenario-1": Scenario(
                identifier="scenario-1",
                phases={
                    "pre-change": Phase(
                        identifier="pre-change",
                        test_case_groups=["connectivity"],
                    ),
                    "post-change": Phase(
                        identifier="post-change",
                        test_case_groups=["connectivity"],
                    ),
                },
            ),
        },
    )


def _build_plan_yaml_data() -> dict:
    """Build raw YAML data matching the default test plan."""
    return {
        "test_cases": {
            "1.0.0": {
                "title": "Verify reachability",
                "job": "tests/verify_reachability.py",
            },
            "2.0.0": {
                "title": "Verify OSPF neighbors",
                "job": "tests/verify_ospf.py",
                "tags": ["ospf"],
            },
            "3.0.0": {
                "title": "Verify BGP sessions",
                "job": "tests/verify_bgp.py",
                "tags": ["bgp"],
                "target": {"groups": ["spine"]},
            },
        },
        "test_case_groups": {
            "connectivity": {
                "tests": ["1.0.0", "2.0.0", "3.0.0"],
            },
        },
        "scenarios": {
            "scenario-1": {
                "phases": {
                    "pre-change": {
                        "test_case_groups": ["connectivity"],
                    },
                    "post-change": {
                        "test_case_groups": ["connectivity"],
                    },
                },
            },
        },
    }


@pytest.fixture
def output(tmp_path: Path) -> Output:
    """Build an Output instance that writes logs to tmp_path."""
    return Output(log_file=tmp_path / "huginn.log", log_level="DEBUG", show_logs=False)


# ---------------------------------------------------------------------------
# find_latest_testing_results
# ---------------------------------------------------------------------------


class TestFindLatestTestingResults:
    """Tests for result directory discovery."""

    def test_finds_latest_testing_directory(self, tmp_path: Path) -> None:
        """Return the most recent *-testing run.json."""
        older = tmp_path / "2026-Jan-01-00-00-00-testing"
        older.mkdir()
        _write_json(older / "run.json", {"scenarios": []})

        newer = tmp_path / "2026-Mar-19-12-00-00-testing"
        newer.mkdir()
        _write_json(newer / "run.json", {"scenarios": []})

        result = find_latest_testing_results(tmp_path)
        assert result == newer / "run.json"

    def test_sorts_by_timestamp_not_alphabetically(self, tmp_path: Path) -> None:
        """Months like Apr and Mar must sort chronologically, not alphabetically."""
        march = tmp_path / "2026-Mar-20-19-00-21-testing"
        march.mkdir()
        _write_json(march / "run.json", {"scenarios": []})

        april = tmp_path / "2026-Apr-04-13-56-56-testing"
        april.mkdir()
        _write_json(april / "run.json", {"scenarios": []})

        result = find_latest_testing_results(tmp_path)
        assert result == april / "run.json"

    def test_ignores_non_testing_directories(self, tmp_path: Path) -> None:
        """Skip directories that do not end with -testing."""
        learning = tmp_path / "2026-Mar-19-12-00-00-learning"
        learning.mkdir()
        _write_json(learning / "run.json", {"scenarios": []})

        testing = tmp_path / "2026-Mar-19-11-00-00-testing"
        testing.mkdir()
        _write_json(testing / "run.json", {"scenarios": []})

        result = find_latest_testing_results(tmp_path)
        assert result.parent.name == "2026-Mar-19-11-00-00-testing"

    def test_raises_when_no_results_directory(self, tmp_path: Path) -> None:
        """Raise when the results directory does not exist."""
        with pytest.raises(ReconcileError, match="does not exist"):
            find_latest_testing_results(tmp_path / "nonexistent")

    def test_raises_when_no_testing_runs(self, tmp_path: Path) -> None:
        """Raise when no testing run directories are found."""
        with pytest.raises(ReconcileError, match="No testing run directories"):
            find_latest_testing_results(tmp_path)

    def test_raises_when_run_json_missing(self, tmp_path: Path) -> None:
        """Raise when the latest directory has no run.json."""
        run_dir = tmp_path / "2026-Mar-19-12-00-00-testing"
        run_dir.mkdir()

        with pytest.raises(ReconcileError, match="run.json not found"):
            find_latest_testing_results(tmp_path)


# ---------------------------------------------------------------------------
# parse_failures_from_run
# ---------------------------------------------------------------------------


class TestParseFailuresFromRun:
    """Tests for extracting failures from run.json."""

    def test_extracts_failing_tests(self, tmp_path: Path) -> None:
        """Identify failed and errored tests from the target phase."""
        run_json = _write_json(tmp_path / "run.json", _build_run_json())

        result = parse_failures_from_run(run_json, "post-change")

        assert len(result.failing_tests) == 2
        failing_ids = {ft.test_id for ft in result.failing_tests}
        assert failing_ids == {"2.0.0", "3.0.0"}

    def test_tracks_passing_tests_by_group(self, tmp_path: Path) -> None:
        """Record passing test IDs per group."""
        run_json = _write_json(tmp_path / "run.json", _build_run_json())

        result = parse_failures_from_run(run_json, "post-change")

        assert "1.0.0" in result.passing_test_ids_by_group["connectivity"]

    def test_identifies_affected_groups(self, tmp_path: Path) -> None:
        """Track which groups contained failures."""
        run_json = _write_json(tmp_path / "run.json", _build_run_json())

        result = parse_failures_from_run(run_json, "post-change")

        assert result.affected_group_ids == {"connectivity"}

    def test_filters_by_scenario(self, tmp_path: Path) -> None:
        """Only process the specified scenario."""
        payload = _build_run_json(scenario_id="scenario-1")
        payload["scenarios"].append(
            {
                "id": "scenario-2",
                "name": "scenario-2",
                "status": "failed",
                "phases": [
                    {
                        "id": "post-change",
                        "name": "post-change",
                        "status": "failed",
                        "test_case_groups": [
                            {
                                "id": "other-group",
                                "name": "other-group",
                                "status": "failed",
                                "test_cases": [
                                    {
                                        "test_id": "9.0.0",
                                        "title": "Other test",
                                        "status": "failed",
                                        "result_path": "test-cases/x/result.json",
                                    },
                                ],
                            },
                        ],
                    },
                ],
            }
        )
        run_json = _write_json(tmp_path / "run.json", payload)

        result = parse_failures_from_run(
            run_json, "post-change", scenario_filter="scenario-1"
        )

        failing_ids = {ft.test_id for ft in result.failing_tests}
        assert "9.0.0" not in failing_ids
        assert result.scenarios_with_phase == ["scenario-1"]

    def test_raises_when_phase_not_found(self, tmp_path: Path) -> None:
        """Raise when the target phase does not exist in results."""
        run_json = _write_json(tmp_path / "run.json", _build_run_json())

        with pytest.raises(ReconcileError, match="Phase 'nonexistent' not found"):
            parse_failures_from_run(run_json, "nonexistent")

    def test_returns_empty_failures_when_all_pass(self, tmp_path: Path) -> None:
        """Return empty failures list when no tests failed."""
        groups = [
            {
                "id": "connectivity",
                "name": "connectivity",
                "status": "passed",
                "test_cases": [
                    {
                        "test_id": "1.0.0",
                        "title": "Test",
                        "status": "passed",
                        "result_path": "test-cases/x/result.json",
                    },
                ],
            },
        ]
        run_json = _write_json(tmp_path / "run.json", _build_run_json(groups=groups))

        result = parse_failures_from_run(run_json, "post-change")

        assert result.failing_tests == []

    def test_includes_errored_tests(self, tmp_path: Path) -> None:
        """Treat errored tests as failures."""
        groups = [
            {
                "id": "connectivity",
                "name": "connectivity",
                "status": "failed",
                "test_cases": [
                    {
                        "test_id": "1.0.0",
                        "title": "Test",
                        "status": "errored",
                        "result_path": "test-cases/x/result.json",
                    },
                ],
            },
        ]
        run_json = _write_json(tmp_path / "run.json", _build_run_json(groups=groups))

        result = parse_failures_from_run(run_json, "post-change")

        assert len(result.failing_tests) == 1
        assert result.failing_tests[0].test_id == "1.0.0"


# ---------------------------------------------------------------------------
# compute_reconcile_plan
# ---------------------------------------------------------------------------


class TestComputeReconcilePlan:
    """Tests for reconciliation plan computation."""

    def _default_input(self) -> ReconcileInput:
        """Build a ReconcileInput matching the default fixtures."""
        return ReconcileInput(
            failing_tests=[
                FailingTestCase(
                    test_id="2.0.0",
                    group_id="connectivity",
                    scenario_id="scenario-1",
                ),
                FailingTestCase(
                    test_id="3.0.0",
                    group_id="connectivity",
                    scenario_id="scenario-1",
                ),
            ],
            passing_test_ids_by_group={"connectivity": ["1.0.0"]},
            affected_group_ids={"connectivity"},
            phase_name="post-change",
            scenarios_with_phase=["scenario-1"],
        )

    def test_creates_new_test_cases(self) -> None:
        """Generate new test case definitions for failing tests."""
        plan = compute_reconcile_plan(
            self._default_input(), _build_test_plan(), "post-change", "scenario-1"
        )

        assert "2.0.0-scenario-1-post-change" in plan.new_test_cases
        assert "3.0.0-scenario-1-post-change" in plan.new_test_cases
        assert plan.new_test_cases["2.0.0-scenario-1-post-change"]["job"] == "tests/verify_ospf.py"
        assert plan.new_test_cases["2.0.0-scenario-1-post-change"]["title"] == (
            "Verify OSPF neighbors (scenario-1 post-change)"
        )

    def test_preserves_tags(self) -> None:
        """Carry over tags from the original test case."""
        plan = compute_reconcile_plan(
            self._default_input(), _build_test_plan(), "post-change", "scenario-1"
        )

        assert plan.new_test_cases["2.0.0-scenario-1-post-change"]["tags"] == ["ospf"]
        assert plan.new_test_cases["3.0.0-scenario-1-post-change"]["tags"] == ["bgp"]

    def test_preserves_target(self) -> None:
        """Carry over target from the original test case."""
        plan = compute_reconcile_plan(
            self._default_input(), _build_test_plan(), "post-change", "scenario-1"
        )

        assert "target" not in plan.new_test_cases["2.0.0-scenario-1-post-change"]
        assert plan.new_test_cases["3.0.0-scenario-1-post-change"]["target"] == {
            "groups": ["spine"]
        }

    def test_preserves_target_exclude_devices(self) -> None:
        """Carry over exclude_devices from the original test case."""
        test_plan = _build_test_plan()
        test_plan.test_cases["2.0.0"] = TestCaseDefinition(
            test_id="2.0.0",
            title="Verify OSPF neighbors",
            job="tests/verify_ospf.py",
            tags=["ospf"],
            target=TargetDefinition(exclude_devices=["TAC-R1"]),
        )

        plan = compute_reconcile_plan(self._default_input(), test_plan, "post-change", "scenario-1")

        assert plan.new_test_cases["2.0.0-scenario-1-post-change"]["target"] == {
            "exclude_devices": ["TAC-R1"]
        }

    def test_creates_new_groups(self) -> None:
        """Generate new groups that inherit from parent and exclude failing IDs."""
        plan = compute_reconcile_plan(
            self._default_input(), _build_test_plan(), "post-change", "scenario-1"
        )

        assert "connectivity-scenario-1-post-change" in plan.new_groups
        spec = plan.new_groups["connectivity-scenario-1-post-change"]
        assert spec.parent_group == "connectivity"
        assert set(spec.exclude_tests) == {"2.0.0", "3.0.0"}
        assert set(spec.tests) == {"2.0.0-scenario-1-post-change", "3.0.0-scenario-1-post-change"}

    def test_creates_phase_group_replacements(self) -> None:
        """Map old group references to new ones per scenario."""
        plan = compute_reconcile_plan(
            self._default_input(), _build_test_plan(), "post-change", "scenario-1"
        )

        assert plan.phase_group_replacements == {
            "scenario-1": {"connectivity": "connectivity-scenario-1-post-change"},
        }

    def test_creates_parameter_copies(self) -> None:
        """List parameter file copy pairs for failing tests."""
        plan = compute_reconcile_plan(
            self._default_input(), _build_test_plan(), "post-change", "scenario-1"
        )

        copy_map = dict(plan.parameter_copies)
        assert copy_map["2.0.0"] == "2.0.0-scenario-1-post-change"
        assert copy_map["3.0.0"] == "3.0.0-scenario-1-post-change"

    def test_skips_existing_test_case_ids(self) -> None:
        """Skip new IDs that already exist in the test plan."""
        test_plan = _build_test_plan()
        test_plan.test_cases["2.0.0-scenario-1-post-change"] = TestCaseDefinition(
            test_id="2.0.0-scenario-1-post-change",
            title="Already exists",
            job="tests/verify_ospf.py",
        )

        plan = compute_reconcile_plan(self._default_input(), test_plan, "post-change", "scenario-1")

        assert "2.0.0-scenario-1-post-change" not in plan.new_test_cases
        assert "2.0.0-scenario-1-post-change" in plan.skipped_existing

    def test_skips_existing_group_ids(self) -> None:
        """Skip new group IDs that already exist in the test plan."""
        test_plan = _build_test_plan()
        test_plan.test_case_groups["connectivity-scenario-1-post-change"] = TestCaseGroup(
            identifier="connectivity-scenario-1-post-change",
            tests=["1.0.0"],
        )

        plan = compute_reconcile_plan(self._default_input(), test_plan, "post-change", "scenario-1")

        assert "connectivity-scenario-1-post-change" not in plan.new_groups
        assert "connectivity-scenario-1-post-change" in plan.skipped_existing

    def test_deduplicates_failing_test_ids(self) -> None:
        """Handle the same test ID failing in multiple groups."""
        reconcile_input = ReconcileInput(
            failing_tests=[
                FailingTestCase("2.0.0", "group-a", "scenario-1"),
                FailingTestCase("2.0.0", "group-b", "scenario-1"),
            ],
            passing_test_ids_by_group={"group-a": [], "group-b": []},
            affected_group_ids={"group-a", "group-b"},
            phase_name="post-change",
            scenarios_with_phase=["scenario-1"],
        )
        test_plan = _build_test_plan()
        test_plan.test_case_groups["group-a"] = TestCaseGroup(
            identifier="group-a", tests=["2.0.0"]
        )
        test_plan.test_case_groups["group-b"] = TestCaseGroup(
            identifier="group-b", tests=["2.0.0"]
        )
        test_plan.scenarios["scenario-1"].phases["post-change"] = Phase(
            identifier="post-change",
            test_case_groups=["group-a", "group-b"],
        )

        plan = compute_reconcile_plan(reconcile_input, test_plan, "post-change", "scenario-1")

        assert len(plan.parameter_copies) == 1

    def test_raises_when_phase_not_in_plan(self) -> None:
        """Raise when the target phase exists in results but not in the plan."""
        reconcile_input = ReconcileInput(
            failing_tests=[FailingTestCase("1.0.0", "g", "scenario-1")],
            passing_test_ids_by_group={},
            affected_group_ids={"g"},
            phase_name="nonexistent",
            scenarios_with_phase=["scenario-1"],
        )

        with pytest.raises(ReconcileError, match="Phase 'nonexistent' not found"):
            compute_reconcile_plan(reconcile_input, _build_test_plan(), "nonexistent", "scenario-1")

    def test_deduplicates_id_when_original_equals_phase(self) -> None:
        """Avoid redundant repetition when original_id matches phase_name."""
        test_plan = _build_test_plan()
        test_plan.test_cases["post-change"] = TestCaseDefinition(
            test_id="post-change",
            title="Post-change check",
            job="tests/post_change.py",
        )
        test_plan.test_case_groups["post-change"] = TestCaseGroup(
            identifier="post-change",
            tests=["post-change"],
        )
        test_plan.scenarios["scenario-1"].phases["post-change"].test_case_groups.append(
            "post-change"
        )

        reconcile_input = ReconcileInput(
            failing_tests=[
                FailingTestCase("post-change", "post-change", "scenario-1"),
            ],
            passing_test_ids_by_group={"post-change": []},
            affected_group_ids={"post-change"},
            phase_name="post-change",
            scenarios_with_phase=["scenario-1"],
        )

        plan = compute_reconcile_plan(reconcile_input, test_plan, "post-change", "scenario-1")

        assert "scenario-1-post-change" in plan.new_test_cases
        assert "scenario-1-post-change" in plan.new_groups


# ---------------------------------------------------------------------------
# apply_reconcile_plan — single file
# ---------------------------------------------------------------------------


class TestApplySingleFile:
    """Tests for applying reconciliation to a single YAML file."""

    def test_adds_new_test_cases_and_groups(
        self, tmp_path: Path, output: Output
    ) -> None:
        """Write new test case and group definitions to the YAML file."""
        plan_path = _write_yaml_file(tmp_path / "plan.yaml", _build_plan_yaml_data())
        reconcile_input = ReconcileInput(
            failing_tests=[
                FailingTestCase("2.0.0", "connectivity", "scenario-1"),
            ],
            passing_test_ids_by_group={"connectivity": ["1.0.0", "3.0.0"]},
            affected_group_ids={"connectivity"},
            phase_name="post-change",
            scenarios_with_phase=["scenario-1"],
        )
        reconcile_plan = compute_reconcile_plan(
            reconcile_input, _build_test_plan(), "post-change", "scenario-1"
        )

        apply_reconcile_plan(
            plan_path=plan_path,
            reconcile_plan=reconcile_plan,
            phase_name="post-change",
            output=output,
        )

        reloaded = yaml.safe_load(plan_path.read_text())
        assert "2.0.0-scenario-1-post-change" in reloaded["test_cases"]
        new_group = reloaded["test_case_groups"]["connectivity-scenario-1-post-change"]
        assert new_group["groups"] == ["connectivity"]
        assert new_group["exclude_tests"] == ["2.0.0"]
        assert new_group["tests"] == ["2.0.0-scenario-1-post-change"]

    def test_updates_phase_group_references(
        self, tmp_path: Path, output: Output
    ) -> None:
        """Replace old group references with new ones in the phase."""
        plan_path = _write_yaml_file(tmp_path / "plan.yaml", _build_plan_yaml_data())
        reconcile_input = ReconcileInput(
            failing_tests=[
                FailingTestCase("2.0.0", "connectivity", "scenario-1"),
            ],
            passing_test_ids_by_group={"connectivity": ["1.0.0", "3.0.0"]},
            affected_group_ids={"connectivity"},
            phase_name="post-change",
            scenarios_with_phase=["scenario-1"],
        )
        reconcile_plan = compute_reconcile_plan(
            reconcile_input, _build_test_plan(), "post-change", "scenario-1"
        )

        apply_reconcile_plan(
            plan_path=plan_path,
            reconcile_plan=reconcile_plan,
            phase_name="post-change",
            output=output,
        )

        reloaded = yaml.safe_load(plan_path.read_text())
        post_change_groups = reloaded["scenarios"]["scenario-1"]["phases"][
            "post-change"
        ]["test_case_groups"]
        assert post_change_groups == ["connectivity-scenario-1-post-change"]

    def test_leaves_pre_change_phase_untouched(
        self, tmp_path: Path, output: Output
    ) -> None:
        """Do not modify group references in unaffected phases."""
        plan_path = _write_yaml_file(tmp_path / "plan.yaml", _build_plan_yaml_data())
        reconcile_input = ReconcileInput(
            failing_tests=[
                FailingTestCase("2.0.0", "connectivity", "scenario-1"),
            ],
            passing_test_ids_by_group={"connectivity": ["1.0.0", "3.0.0"]},
            affected_group_ids={"connectivity"},
            phase_name="post-change",
            scenarios_with_phase=["scenario-1"],
        )
        reconcile_plan = compute_reconcile_plan(
            reconcile_input, _build_test_plan(), "post-change", "scenario-1"
        )

        apply_reconcile_plan(
            plan_path=plan_path,
            reconcile_plan=reconcile_plan,
            phase_name="post-change",
            output=output,
        )

        reloaded = yaml.safe_load(plan_path.read_text())
        pre_change_groups = reloaded["scenarios"]["scenario-1"]["phases"]["pre-change"][
            "test_case_groups"
        ]
        assert pre_change_groups == ["connectivity"]


# ---------------------------------------------------------------------------
# apply_reconcile_plan — directory
# ---------------------------------------------------------------------------


class TestApplyDirectory:
    """Tests for applying reconciliation to a directory of YAML files."""

    def _setup_plan_directory(self, plan_dir: Path) -> None:
        """Create a multi-file test plan directory."""
        _write_yaml_file(
            plan_dir / "test_cases.yaml",
            {
                "test_cases": {
                    "1.0.0": {
                        "title": "Verify reachability",
                        "job": "tests/verify_reachability.py",
                    },
                    "2.0.0": {
                        "title": "Verify OSPF neighbors",
                        "job": "tests/verify_ospf.py",
                        "tags": ["ospf"],
                    },
                    "3.0.0": {
                        "title": "Verify BGP sessions",
                        "job": "tests/verify_bgp.py",
                        "tags": ["bgp"],
                        "target": {"groups": ["spine"]},
                    },
                },
            },
        )
        _write_yaml_file(
            plan_dir / "groups.yaml",
            {
                "test_case_groups": {
                    "connectivity": {
                        "tests": ["1.0.0", "2.0.0", "3.0.0"],
                    },
                },
            },
        )
        _write_yaml_file(
            plan_dir / "scenarios.yaml",
            {
                "scenarios": {
                    "scenario-1": {
                        "phases": {
                            "pre-change": {
                                "test_case_groups": ["connectivity"],
                            },
                            "post-change": {
                                "test_case_groups": ["connectivity"],
                            },
                        },
                    },
                },
            },
        )

    def test_creates_reconciled_file(self, tmp_path: Path, output: Output) -> None:
        """Write new definitions to a reconciled-{phase}.yaml file."""
        plan_dir = tmp_path / "plans"
        self._setup_plan_directory(plan_dir)

        reconcile_input = ReconcileInput(
            failing_tests=[
                FailingTestCase("2.0.0", "connectivity", "scenario-1"),
            ],
            passing_test_ids_by_group={"connectivity": ["1.0.0", "3.0.0"]},
            affected_group_ids={"connectivity"},
            phase_name="post-change",
            scenarios_with_phase=["scenario-1"],
        )
        reconcile_plan = compute_reconcile_plan(
            reconcile_input, _build_test_plan(), "post-change", "scenario-1"
        )

        apply_reconcile_plan(
            plan_path=plan_dir,
            reconcile_plan=reconcile_plan,
            phase_name="post-change",
            output=output,
        )

        reconciled = plan_dir / "reconciled-post-change.yaml"
        assert reconciled.is_file()
        data = yaml.safe_load(reconciled.read_text())
        assert "2.0.0-scenario-1-post-change" in data["test_cases"]
        new_group = data["test_case_groups"]["connectivity-scenario-1-post-change"]
        assert new_group["groups"] == ["connectivity"]
        assert new_group["exclude_tests"] == ["2.0.0"]
        assert new_group["tests"] == ["2.0.0-scenario-1-post-change"]

    def test_updates_scenario_file_in_place(
        self, tmp_path: Path, output: Output
    ) -> None:
        """Update the scenario file to reference new groups."""
        plan_dir = tmp_path / "plans"
        self._setup_plan_directory(plan_dir)

        reconcile_input = ReconcileInput(
            failing_tests=[
                FailingTestCase("2.0.0", "connectivity", "scenario-1"),
            ],
            passing_test_ids_by_group={"connectivity": ["1.0.0", "3.0.0"]},
            affected_group_ids={"connectivity"},
            phase_name="post-change",
            scenarios_with_phase=["scenario-1"],
        )
        reconcile_plan = compute_reconcile_plan(
            reconcile_input, _build_test_plan(), "post-change", "scenario-1"
        )

        apply_reconcile_plan(
            plan_path=plan_dir,
            reconcile_plan=reconcile_plan,
            phase_name="post-change",
            output=output,
        )

        scenario_data = yaml.safe_load((plan_dir / "scenarios.yaml").read_text())
        post_groups = scenario_data["scenarios"]["scenario-1"]["phases"]["post-change"][
            "test_case_groups"
        ]
        assert post_groups == ["connectivity-scenario-1-post-change"]

    def test_leaves_other_files_untouched(self, tmp_path: Path, output: Output) -> None:
        """Do not modify test_cases.yaml or groups.yaml."""
        plan_dir = tmp_path / "plans"
        self._setup_plan_directory(plan_dir)
        original_tc = (plan_dir / "test_cases.yaml").read_text()
        original_groups = (plan_dir / "groups.yaml").read_text()

        reconcile_input = ReconcileInput(
            failing_tests=[
                FailingTestCase("2.0.0", "connectivity", "scenario-1"),
            ],
            passing_test_ids_by_group={"connectivity": ["1.0.0", "3.0.0"]},
            affected_group_ids={"connectivity"},
            phase_name="post-change",
            scenarios_with_phase=["scenario-1"],
        )
        reconcile_plan = compute_reconcile_plan(
            reconcile_input, _build_test_plan(), "post-change", "scenario-1"
        )

        apply_reconcile_plan(
            plan_path=plan_dir,
            reconcile_plan=reconcile_plan,
            phase_name="post-change",
            output=output,
        )

        assert (plan_dir / "test_cases.yaml").read_text() == original_tc
        assert (plan_dir / "groups.yaml").read_text() == original_groups


# ---------------------------------------------------------------------------
# copy_parameter_files
# ---------------------------------------------------------------------------


class TestCopyParameterFiles:
    """Tests for parameter file copying."""

    def test_copies_parameter_files(self, tmp_path: Path, output: Output) -> None:
        """Copy source parameter files to new destinations."""
        params_dir = tmp_path / "parameters"
        _write_json(params_dir / "2.0.0.json", {"ospf_neighbors": 3})

        copied = copy_parameter_files(
            parameters_dir=params_dir,
            copies=[("2.0.0", "2.0.0-scenario-1-post-change")],
            output=output,
        )

        assert copied == 1
        dest = params_dir / "2.0.0-scenario-1-post-change.json"
        assert dest.is_file()
        assert json.loads(dest.read_text()) == {"ospf_neighbors": 3}

    def test_warns_on_missing_source(self, tmp_path: Path, output: Output) -> None:
        """Warn and skip when source parameter file does not exist."""
        params_dir = tmp_path / "parameters"
        params_dir.mkdir()

        copied = copy_parameter_files(
            parameters_dir=params_dir,
            copies=[("nonexistent", "nonexistent-scenario-1-post-change")],
            output=output,
        )

        assert copied == 0
        assert not (params_dir / "nonexistent-post-change.json").exists()

    def test_skips_existing_destination(self, tmp_path: Path, output: Output) -> None:
        """Skip copy when destination file already exists."""
        params_dir = tmp_path / "parameters"
        _write_json(params_dir / "2.0.0.json", {"original": True})
        _write_json(params_dir / "2.0.0-scenario-1-post-change.json", {"existing": True})

        copied = copy_parameter_files(
            parameters_dir=params_dir,
            copies=[("2.0.0", "2.0.0-scenario-1-post-change")],
            output=output,
        )

        assert copied == 0
        existing = json.loads((params_dir / "2.0.0-scenario-1-post-change.json").read_text())
        assert existing == {"existing": True}

    def test_handles_multiple_copies(self, tmp_path: Path, output: Output) -> None:
        """Process multiple parameter file copies."""
        params_dir = tmp_path / "parameters"
        _write_json(params_dir / "2.0.0.json", {"ospf": True})
        _write_json(params_dir / "3.0.0.json", {"bgp": True})

        copied = copy_parameter_files(
            parameters_dir=params_dir,
            copies=[
                ("2.0.0", "2.0.0-scenario-1-post-change"),
                ("3.0.0", "3.0.0-scenario-1-post-change"),
            ],
            output=output,
        )

        assert copied == 2
        assert (params_dir / "2.0.0-scenario-1-post-change.json").is_file()
        assert (params_dir / "3.0.0-scenario-1-post-change.json").is_file()

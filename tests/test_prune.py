"""Unit tests for the prune module."""

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from huginn.cli import app
from huginn.loaders import load_test_plan
from huginn.models import (
    Device,
    Phase,
    Scenario,
    TargetDefinition,
    Testbed,
    TestCaseDefinition,
    TestCaseGroup,
    TestPlan,
)
from huginn.prune import (
    NotApplicableTestCase,
    PruneError,
    PruneInput,
    _add_exclude_tests_to_group,
    _extract_all_devices,
    _remove_orphaned_test_cases,
    compute_prune_plan,
    find_latest_learning_results,
    parse_applicability_from_run,
)
from huginn.runner import resolve_targets

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_json(path: Path, payload: object) -> Path:
    """Write a JSON file and return its path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _build_run_json(
    *,
    scenario_id: str = "scenario-1",
    phase_id: str = "learning-phase",
    groups: list[dict] | None = None,
) -> dict:
    """Build a minimal run.json payload for learning mode."""
    if groups is None:
        groups = []
    return {
        "summary": {"status": "passed", "total": 0},
        "mode": "learning",
        "scenarios": [
            {
                "id": scenario_id,
                "name": scenario_id,
                "status": "passed",
                "phases": [
                    {
                        "id": phase_id,
                        "name": phase_id,
                        "status": "passed",
                        "test_case_groups": groups,
                    },
                ],
            },
        ],
    }


def _build_test_plan(
    *,
    test_cases: dict[str, TestCaseDefinition] | None = None,
    groups: dict[str, TestCaseGroup] | None = None,
) -> TestPlan:
    """Build an in-memory TestPlan with sensible defaults."""
    if test_cases is None:
        test_cases = {
            "TC-1": TestCaseDefinition(
                test_id="TC-1",
                title="Check reachability",
                job="jobs/reachability.py",
            ),
            "TC-2": TestCaseDefinition(
                test_id="TC-2",
                title="Check OSPF",
                job="jobs/ospf.py",
            ),
            "TC-3": TestCaseDefinition(
                test_id="TC-3",
                title="Check BGP",
                job="jobs/bgp.py",
            ),
        }
    if groups is None:
        groups = {
            "group-a": TestCaseGroup(
                identifier="group-a",
                tests=["TC-1", "TC-2", "TC-3"],
            ),
        }
    return TestPlan(
        test_cases=test_cases,
        test_case_groups=groups,
        scenarios={
            "scenario-1": Scenario(
                identifier="scenario-1",
                phases={
                    "phase-1": Phase(
                        identifier="phase-1",
                        test_case_groups=list(groups.keys()),
                    ),
                },
            ),
        },
    )


# ===========================================================================
# find_latest_learning_results
# ===========================================================================


class TestFindLatestLearningResults:
    """Tests for find_latest_learning_results."""

    def test_returns_correct_path_with_multiple_dirs(self, tmp_path: Path) -> None:
        """The most recent learning directory (by timestamp) is selected."""
        older = tmp_path / "2025-Jan-01-10-00-00-learning"
        newer = tmp_path / "2025-Feb-15-14-30-00-learning"
        older.mkdir()
        newer.mkdir()
        _write_json(older / "run.json", {"dummy": True})
        _write_json(newer / "run.json", {"dummy": True})

        result = find_latest_learning_results(tmp_path)

        assert result == newer / "run.json"

    def test_raises_when_no_learning_dirs_exist(self, tmp_path: Path) -> None:
        """PruneError is raised when no -learning directories are found."""
        # Create a non-learning directory to confirm it is ignored.
        (tmp_path / "2025-Jan-01-10-00-00-testing").mkdir()

        with pytest.raises(PruneError, match="No learning run directories found"):
            find_latest_learning_results(tmp_path)

    def test_raises_when_results_dir_missing(self, tmp_path: Path) -> None:
        """PruneError is raised when the results directory does not exist."""
        nonexistent = tmp_path / "does-not-exist"

        with pytest.raises(PruneError, match="Results directory does not exist"):
            find_latest_learning_results(nonexistent)

    def test_raises_when_run_json_missing(self, tmp_path: Path) -> None:
        """PruneError is raised when run.json is absent from the latest dir."""
        learning_dir = tmp_path / "2025-Mar-01-08-00-00-learning"
        learning_dir.mkdir()

        with pytest.raises(PruneError, match="run.json not found"):
            find_latest_learning_results(tmp_path)


# ===========================================================================
# parse_applicability_from_run
# ===========================================================================


class TestParseApplicabilityFromRun:
    """Tests for parse_applicability_from_run."""

    def test_classifies_partial_and_full_na(self, tmp_path: Path) -> None:
        """Tests with some applicable devices are partial; all-N/A are full."""
        run_dir = tmp_path / "run"
        run_dir.mkdir()

        # Partial N/A test: device-B is N/A, device-A is fine.
        partial_detail = {
            "command_executions": [
                {"device": "device-A", "command": "show ip route", "output": "..."},
                {"device": "device-B", "command": "show ip route", "output": "..."},
            ],
            "not_applicable_devices": {"device-B": "No OSPF support"},
        }
        _write_json(run_dir / "test-cases" / "TC-1" / "result.json", partial_detail)

        # Full N/A test: all devices are N/A.
        full_detail = {
            "command_executions": [
                {"device": "device-A", "command": "show bgp", "output": "..."},
            ],
            "not_applicable_devices": {"device-A": "No BGP configured"},
        }
        _write_json(run_dir / "test-cases" / "TC-2" / "result.json", full_detail)

        groups = [
            {
                "id": "group-a",
                "test_cases": [
                    {
                        "test_id": "TC-1",
                        "result_path": "test-cases/TC-1/result.json",
                    },
                    {
                        "test_id": "TC-2",
                        "result_path": "test-cases/TC-2/result.json",
                    },
                ],
            },
        ]
        run_json = _build_run_json(groups=groups)
        run_json_path = _write_json(run_dir / "run.json", run_json)

        result = parse_applicability_from_run(run_json_path)

        assert len(result.partial_tests) == 1
        assert result.partial_tests[0].test_id == "TC-1"
        assert result.partial_tests[0].applicable_devices == ["device-A"]

        assert len(result.full_tests) == 1
        assert result.full_tests[0].test_id == "TC-2"
        assert result.full_tests[0].applicable_devices == []

    def test_returns_empty_lists_when_no_na_tests(self, tmp_path: Path) -> None:
        """No N/A devices means both lists are empty."""
        run_dir = tmp_path / "run"
        run_dir.mkdir()

        detail = {
            "command_executions": [
                {"device": "device-A", "command": "show version", "output": "..."},
            ],
            "not_applicable_devices": {},
        }
        _write_json(run_dir / "test-cases" / "TC-1" / "result.json", detail)

        groups = [
            {
                "id": "group-a",
                "test_cases": [
                    {
                        "test_id": "TC-1",
                        "result_path": "test-cases/TC-1/result.json",
                    },
                ],
            },
        ]
        run_json = _build_run_json(groups=groups)
        run_json_path = _write_json(run_dir / "run.json", run_json)

        result = parse_applicability_from_run(run_json_path)

        assert result.partial_tests == []
        assert result.full_tests == []

    def test_deduplicates_test_ids_across_groups(self, tmp_path: Path) -> None:
        """A test_id appearing in multiple groups is only processed once."""
        run_dir = tmp_path / "run"
        run_dir.mkdir()

        detail = {
            "command_executions": [
                {"device": "device-A", "command": "show ip route", "output": "..."},
            ],
            "not_applicable_devices": {"device-A": "Not supported"},
        }
        _write_json(run_dir / "test-cases" / "TC-1" / "result.json", detail)

        shared_test_case = {
            "test_id": "TC-1",
            "result_path": "test-cases/TC-1/result.json",
        }
        groups = [
            {"id": "group-a", "test_cases": [shared_test_case]},
            {"id": "group-b", "test_cases": [shared_test_case]},
        ]
        run_json = _build_run_json(groups=groups)
        run_json_path = _write_json(run_dir / "run.json", run_json)

        result = parse_applicability_from_run(run_json_path)

        all_ids = [t.test_id for t in result.partial_tests + result.full_tests]
        assert all_ids == ["TC-1"]


# ===========================================================================
# compute_prune_plan
# ===========================================================================


class TestComputePrunePlan:
    """Tests for compute_prune_plan."""

    def test_partial_tests_get_exclude_devices_updates(self) -> None:
        """Partial N/A tests produce exclude_devices entries."""
        prune_input = PruneInput(
            partial_tests=[
                NotApplicableTestCase(
                    test_id="TC-1",
                    group_id="group-a",
                    scenario_id="scenario-1",
                    not_applicable_devices={"device-B": "No support"},
                    applicable_devices=["device-A"],
                ),
            ],
            full_tests=[],
        )
        plan = _build_test_plan()

        result = compute_prune_plan(prune_input, plan)

        assert "TC-1" in result.exclude_devices_updates
        assert "device-B" in result.exclude_devices_updates["TC-1"]

    def test_full_tests_get_exclude_from_groups(self) -> None:
        """Fully N/A tests produce exclude_from_groups entries."""
        prune_input = PruneInput(
            partial_tests=[],
            full_tests=[
                NotApplicableTestCase(
                    test_id="TC-2",
                    group_id="group-a",
                    scenario_id="scenario-1",
                    not_applicable_devices={"device-A": "N/A"},
                    applicable_devices=[],
                ),
            ],
        )
        plan = _build_test_plan()

        result = compute_prune_plan(prune_input, plan)

        assert "group-a" in result.exclude_from_groups
        assert "TC-2" in result.exclude_from_groups["group-a"]

    def test_already_pruned_tests_are_skipped(self) -> None:
        """Tests whose devices are already excluded are added to skipped."""
        test_cases = {
            "TC-1": TestCaseDefinition(
                test_id="TC-1",
                title="Already pruned",
                job="jobs/x.py",
                target=TargetDefinition(exclude_devices=["device-B"]),
            ),
        }
        groups = {
            "group-a": TestCaseGroup(
                identifier="group-a",
                tests=["TC-1"],
            ),
        }
        plan = _build_test_plan(test_cases=test_cases, groups=groups)

        prune_input = PruneInput(
            partial_tests=[
                NotApplicableTestCase(
                    test_id="TC-1",
                    group_id="group-a",
                    scenario_id="scenario-1",
                    not_applicable_devices={"device-B": "No support"},
                    applicable_devices=["device-A"],
                ),
            ],
            full_tests=[],
        )

        result = compute_prune_plan(prune_input, plan)

        assert "TC-1" in result.skipped_already_pruned
        assert "TC-1" not in result.exclude_devices_updates

    def test_already_excluded_full_test_is_skipped(self) -> None:
        """Full N/A tests already in exclude_tests are skipped."""
        groups = {
            "group-a": TestCaseGroup(
                identifier="group-a",
                tests=["TC-2"],
                exclude_tests=["TC-2"],
            ),
        }
        plan = _build_test_plan(groups=groups)

        prune_input = PruneInput(
            partial_tests=[],
            full_tests=[
                NotApplicableTestCase(
                    test_id="TC-2",
                    group_id="group-a",
                    scenario_id="scenario-1",
                    not_applicable_devices={"device-A": "N/A"},
                    applicable_devices=[],
                ),
            ],
        )

        result = compute_prune_plan(prune_input, plan)

        assert "TC-2" in result.skipped_already_pruned
        assert "group-a" not in result.exclude_from_groups

    def test_remove_orphans_true_detects_orphaned_test_cases(self) -> None:
        """When remove_orphans=True, tests excluded from ALL groups are orphaned."""
        test_cases = {
            "TC-1": TestCaseDefinition(
                test_id="TC-1", title="Only in one group", job="jobs/x.py"
            ),
        }
        groups = {
            "group-a": TestCaseGroup(
                identifier="group-a",
                tests=["TC-1"],
            ),
        }
        plan = _build_test_plan(test_cases=test_cases, groups=groups)

        prune_input = PruneInput(
            partial_tests=[],
            full_tests=[
                NotApplicableTestCase(
                    test_id="TC-1",
                    group_id="group-a",
                    scenario_id="scenario-1",
                    not_applicable_devices={"device-A": "N/A"},
                    applicable_devices=[],
                ),
            ],
        )

        result = compute_prune_plan(prune_input, plan, remove_orphans=True)

        assert "TC-1" in result.orphaned_test_cases

    def test_remove_orphans_false_leaves_orphaned_empty(self) -> None:
        """When remove_orphans=False (default), orphaned_test_cases stays empty."""
        test_cases = {
            "TC-1": TestCaseDefinition(
                test_id="TC-1", title="Only in one group", job="jobs/x.py"
            ),
        }
        groups = {
            "group-a": TestCaseGroup(
                identifier="group-a",
                tests=["TC-1"],
            ),
        }
        plan = _build_test_plan(test_cases=test_cases, groups=groups)

        prune_input = PruneInput(
            partial_tests=[],
            full_tests=[
                NotApplicableTestCase(
                    test_id="TC-1",
                    group_id="group-a",
                    scenario_id="scenario-1",
                    not_applicable_devices={"device-A": "N/A"},
                    applicable_devices=[],
                ),
            ],
        )

        result = compute_prune_plan(prune_input, plan, remove_orphans=False)

        assert result.orphaned_test_cases == []

    def test_partial_test_not_orphaned(self) -> None:
        """Partial N/A tests (exclude_devices only) are never orphaned.

        Orphan detection only applies to tests fully excluded from groups.
        A partial test retains its group membership and should not appear
        in orphaned_test_cases even with remove_orphans=True.
        """
        test_cases = {
            "TC-1": TestCaseDefinition(
                test_id="TC-1", title="Partial N/A", job="jobs/x.py"
            ),
            "TC-2": TestCaseDefinition(
                test_id="TC-2", title="Full N/A", job="jobs/y.py"
            ),
        }
        groups = {
            "group-a": TestCaseGroup(
                identifier="group-a",
                tests=["TC-1", "TC-2"],
            ),
        }
        plan = _build_test_plan(test_cases=test_cases, groups=groups)

        prune_input = PruneInput(
            partial_tests=[
                NotApplicableTestCase(
                    test_id="TC-1",
                    group_id="group-a",
                    scenario_id="scenario-1",
                    not_applicable_devices={"device-B": "N/A"},
                    applicable_devices=["device-A"],
                ),
            ],
            full_tests=[
                NotApplicableTestCase(
                    test_id="TC-2",
                    group_id="group-a",
                    scenario_id="scenario-1",
                    not_applicable_devices={"device-A": "N/A"},
                    applicable_devices=[],
                ),
            ],
        )

        result = compute_prune_plan(prune_input, plan, remove_orphans=True)

        # TC-1 is partial, so it stays referenced in the group.
        assert "TC-1" not in result.orphaned_test_cases
        # TC-2 is fully excluded from its only group, so it IS orphaned.
        assert "TC-2" in result.orphaned_test_cases

    def test_remove_orphans_finds_orphans_from_earlier_runs(self) -> None:
        """Orphans left by an earlier prune are found when nothing is pruned now."""
        test_cases = {
            "TC-1": TestCaseDefinition(test_id="TC-1", title="Kept", job="jobs/x.py"),
            "TC-2": TestCaseDefinition(
                test_id="TC-2", title="Pruned earlier", job="jobs/y.py"
            ),
        }
        groups = {"group-a": TestCaseGroup(identifier="group-a", tests=["TC-1"])}
        plan = _build_test_plan(test_cases=test_cases, groups=groups)

        result = compute_prune_plan(
            PruneInput(partial_tests=[], full_tests=[]), plan, remove_orphans=True
        )

        assert result.exclude_from_groups == {}
        assert result.orphaned_test_cases == ["TC-2"]

    def test_remove_orphans_includes_never_grouped_tests(self) -> None:
        """A test case that no group ever listed (e.g. a draft) is orphaned."""
        test_cases = {
            "TC-1": TestCaseDefinition(test_id="TC-1", title="Kept", job="jobs/x.py"),
            "TC-DRAFT": TestCaseDefinition(
                test_id="TC-DRAFT", title="Draft", job="jobs/draft.py"
            ),
        }
        groups = {"group-a": TestCaseGroup(identifier="group-a", tests=["TC-1"])}
        plan = _build_test_plan(test_cases=test_cases, groups=groups)

        result = compute_prune_plan(
            PruneInput(partial_tests=[], full_tests=[]), plan, remove_orphans=True
        )

        assert result.orphaned_test_cases == ["TC-DRAFT"]

    def test_nested_group_reference_keeps_test(self, tmp_path: Path) -> None:
        """A test inherited through nested groups is still referenced.

        The ``extra`` group is not referenced by any phase; a reference from
        any group still counts.
        """
        plan_path = tmp_path / "test_plan.yaml"
        plan_path.write_text(_NESTED_PLAN_YAML, encoding="utf-8")
        plan = load_test_plan(plan_path)
        # The loader flattens nested groups into ``tests``.
        assert plan.test_case_groups["composite"].tests == ["TC-1", "TC-2"]

        result = compute_prune_plan(
            PruneInput(partial_tests=[], full_tests=[]), plan, remove_orphans=True
        )

        assert result.orphaned_test_cases == []

    def test_exclude_tests_only_reference_is_orphaned(self, tmp_path: Path) -> None:
        """A test listed only in a composite group's exclude_tests is orphaned.

        This is the state a composite group is left in after a prune without
        ``--remove-orphans``.
        """
        plan_path = tmp_path / "test_plan.yaml"
        plan_path.write_text(_EXCLUDED_PLAN_YAML, encoding="utf-8")
        plan = load_test_plan(plan_path)

        result = compute_prune_plan(
            PruneInput(partial_tests=[], full_tests=[]), plan, remove_orphans=True
        )

        assert result.orphaned_test_cases == ["TC-2"]


_NESTED_PLAN_YAML = """\
test_cases:
  TC-1: {title: Base, job: jobs/x.py}
  TC-2: {title: Inherited, job: jobs/y.py}
test_case_groups:
  base:
    tests: [TC-1]
  extra:
    tests: [TC-2]
  composite:
    groups: [base, extra]
scenarios:
  scenario-1:
    phases:
      phase-1:
        test_case_groups: [composite]
"""

_EXCLUDED_PLAN_YAML = """\
test_cases:
  TC-1: {title: Kept, job: jobs/x.py}
  TC-2: {title: Excluded, job: jobs/y.py}
test_case_groups:
  base:
    tests: [TC-1]
  composite:
    groups: [base]
    exclude_tests: [TC-2]
scenarios:
  scenario-1:
    phases:
      phase-1:
        test_case_groups: [composite]
"""


# ===========================================================================
# _extract_all_devices
# ===========================================================================


class TestExtractAllDevices:
    """Tests for _extract_all_devices."""

    def test_extracts_from_command_executions(self) -> None:
        """Devices are extracted from command_executions entries."""
        detail = {
            "command_executions": [
                {"device": "router-1", "command": "show ip route", "output": "..."},
                {"device": "router-2", "command": "show ip route", "output": "..."},
            ],
            "not_applicable_devices": {},
        }

        result = _extract_all_devices(detail)

        assert result == ["router-1", "router-2"]

    def test_extracts_from_not_applicable_devices_when_no_executions(self) -> None:
        """Falls back to not_applicable_devices when no command_executions."""
        detail = {
            "command_executions": [],
            "not_applicable_devices": {"switch-1": "No support", "switch-2": "N/A"},
        }

        result = _extract_all_devices(detail)

        assert result == ["switch-1", "switch-2"]

    def test_deduplicates_devices(self) -> None:
        """Devices appearing in both sources are not duplicated."""
        detail = {
            "command_executions": [
                {"device": "router-1", "command": "show version", "output": "..."},
            ],
            "not_applicable_devices": {"router-1": "partial N/A"},
        }

        result = _extract_all_devices(detail)

        assert result == ["router-1"]

    def test_handles_non_dict_command_executions(self) -> None:
        """Non-dict entries in command_executions are skipped."""
        detail = {
            "command_executions": ["bad-entry", None, {"device": "router-1"}],
            "not_applicable_devices": {},
        }

        result = _extract_all_devices(detail)

        assert result == ["router-1"]


# ===========================================================================
# _add_exclude_tests_to_group
# ===========================================================================


class TestAddExcludeTestsToGroup:
    """Tests for _add_exclude_tests_to_group."""

    def test_adds_exclude_tests_to_composite_group(self) -> None:
        """Composite groups (with 'groups' key) get exclude_tests appended."""
        data = {
            "test_case_groups": {
                "parent-group": {
                    "groups": ["child-a", "child-b"],
                    "tests": ["TC-1", "TC-2"],
                },
            },
        }

        _add_exclude_tests_to_group(data, "parent-group", ["TC-1"])

        group = data["test_case_groups"]["parent-group"]
        assert group["exclude_tests"] == ["TC-1"]

    def test_removes_from_tests_list_in_leaf_group(self) -> None:
        """Leaf groups (no 'groups' key) have test IDs removed from tests list."""
        data = {
            "test_case_groups": {
                "leaf-group": {
                    "tests": ["TC-1", "TC-2", "TC-3"],
                },
            },
        }

        _add_exclude_tests_to_group(data, "leaf-group", ["TC-2"])

        group = data["test_case_groups"]["leaf-group"]
        assert "TC-2" not in group["tests"]
        assert group["tests"] == ["TC-1", "TC-3"]

    def test_idempotent_no_duplicates_in_composite(self) -> None:
        """Calling twice with the same test ID does not create duplicates."""
        data = {
            "test_case_groups": {
                "parent-group": {
                    "groups": ["child-a"],
                    "exclude_tests": ["TC-1"],
                },
            },
        }

        _add_exclude_tests_to_group(data, "parent-group", ["TC-1"])

        group = data["test_case_groups"]["parent-group"]
        assert group["exclude_tests"].count("TC-1") == 1

    def test_idempotent_already_removed_from_leaf(self) -> None:
        """Removing a test ID not in the leaf tests list does nothing."""
        data = {
            "test_case_groups": {
                "leaf-group": {
                    "tests": ["TC-1"],
                },
            },
        }

        _add_exclude_tests_to_group(data, "leaf-group", ["TC-99"])

        group = data["test_case_groups"]["leaf-group"]
        assert group["tests"] == ["TC-1"]

    def test_noop_when_group_not_found(self) -> None:
        """No error when the group_id does not exist in data."""
        data = {"test_case_groups": {}}

        _add_exclude_tests_to_group(data, "missing-group", ["TC-1"])
        # No exception raised.

    def test_appends_to_existing_exclude_tests(self) -> None:
        """New test IDs are appended to an existing exclude_tests list."""
        data = {
            "test_case_groups": {
                "parent-group": {
                    "groups": ["child-a"],
                    "exclude_tests": ["TC-1"],
                },
            },
        }

        _add_exclude_tests_to_group(data, "parent-group", ["TC-2"])

        group = data["test_case_groups"]["parent-group"]
        assert group["exclude_tests"] == ["TC-1", "TC-2"]


# ===========================================================================
# _remove_orphaned_test_cases
# ===========================================================================


class TestRemoveOrphanedTestCases:
    """Tests for _remove_orphaned_test_cases."""

    def test_removes_specified_test_ids(self) -> None:
        """Test case definitions are removed from the test_cases dict."""
        data = {
            "test_cases": {
                "TC-1": {"title": "Test 1", "job": "jobs/t1.py"},
                "TC-2": {"title": "Test 2", "job": "jobs/t2.py"},
                "TC-3": {"title": "Test 3", "job": "jobs/t3.py"},
            },
        }

        _remove_orphaned_test_cases(data, ["TC-1", "TC-3"])

        assert "TC-1" not in data["test_cases"]
        assert "TC-3" not in data["test_cases"]
        assert "TC-2" in data["test_cases"]

    def test_handles_missing_test_ids_gracefully(self) -> None:
        """No error when a test_id to remove does not exist."""
        data = {
            "test_cases": {
                "TC-1": {"title": "Test 1", "job": "jobs/t1.py"},
            },
        }

        _remove_orphaned_test_cases(data, ["TC-99", "TC-100"])

        assert "TC-1" in data["test_cases"]

    def test_noop_when_no_test_cases_key(self) -> None:
        """No error when data lacks a test_cases mapping."""
        data = {"other_key": "value"}

        _remove_orphaned_test_cases(data, ["TC-1"])
        # No exception raised.

    def test_noop_when_test_cases_not_dict(self) -> None:
        """No error when test_cases is not a dict."""
        data = {"test_cases": "not-a-dict"}

        _remove_orphaned_test_cases(data, ["TC-1"])
        # No exception raised.


# ===========================================================================
# huginn prune --remove-orphans (CLI)
# ===========================================================================

_CLI_PLAN_YAML = """\
test_cases:
  "3.0.0":
    title: Check OSPF
    job: jobs/ospf.py
  "4.0.0":
    title: Check BGP
    job: jobs/bgp.py
test_case_groups:
  routing:
    tests: ["3.0.0", "4.0.0"]
scenarios:
  scenario-1:
    phases:
      phase-1:
        test_case_groups: [routing]
"""


def _stage_prune_workspace(tmp_path: Path) -> Path:
    """Write a test plan plus learning results marking 4.0.0 fully N/A."""
    plan_path = tmp_path / "test_plan.yaml"
    plan_path.write_text(_CLI_PLAN_YAML, encoding="utf-8")

    run_dir = tmp_path / "results" / "2026-Apr-30-14-22-01-learning"
    _write_json(
        run_dir / "test-cases" / "4.0.0" / "result.json",
        {
            "command_executions": [{"device": "device-A", "command": "show bgp"}],
            "not_applicable_devices": {"device-A": "No BGP configured"},
        },
    )
    groups = [
        {
            "id": "routing",
            "test_cases": [
                {"test_id": "4.0.0", "result_path": "test-cases/4.0.0/result.json"}
            ],
        },
    ]
    _write_json(run_dir / "run.json", _build_run_json(groups=groups))
    return plan_path


def _invoke_prune(tmp_path: Path, plan_path: Path, *extra: str) -> str:
    """Run ``huginn prune`` and return its output as a single normalized line."""
    result = CliRunner().invoke(
        app,
        [
            "prune",
            "--plan",
            str(plan_path),
            "--results-dir",
            str(tmp_path / "results"),
            "--log-file",
            str(tmp_path / "huginn.log"),
            *extra,
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    return " ".join(re.sub(r"\x1b\[[0-9;]*m", "", result.output).split())


class TestPruneRemoveOrphansCli:
    """End-to-end tests for ``huginn prune --remove-orphans``."""

    def test_follow_up_run_removes_orphans(self, tmp_path: Path) -> None:
        """A later --remove-orphans run removes tests pruned by an earlier run."""
        plan_path = _stage_prune_workspace(tmp_path)
        _invoke_prune(tmp_path, plan_path)
        assert "4.0.0" in load_test_plan(plan_path).test_cases

        output = _invoke_prune(tmp_path, plan_path, "--remove-orphans")

        assert "Pruning already applied" not in output
        assert "1 test case definition(s) removed" in output
        assert set(load_test_plan(plan_path).test_cases) == {"3.0.0"}

    def test_same_run_removes_orphans(self, tmp_path: Path) -> None:
        """Pruning and orphan removal in one run still works."""
        plan_path = _stage_prune_workspace(tmp_path)

        _invoke_prune(tmp_path, plan_path, "--remove-orphans")

        loaded = load_test_plan(plan_path)
        assert set(loaded.test_cases) == {"3.0.0"}
        assert loaded.test_case_groups["routing"].tests == ["3.0.0"]

    def test_dry_run_lists_orphans_without_writing(self, tmp_path: Path) -> None:
        """--dry-run lists orphans, including never-grouped ones, and writes nothing."""
        plan_path = _stage_prune_workspace(tmp_path)
        # Add a draft test case that no group has ever referenced.
        draft = '  "9.9.9":\n    title: Draft\n    job: jobs/draft.py\n'
        text = plan_path.read_text(encoding="utf-8")
        plan_path.write_text(
            text.replace("test_case_groups:", f"{draft}test_case_groups:", 1),
            encoding="utf-8",
        )
        _invoke_prune(tmp_path, plan_path)
        before = plan_path.read_text(encoding="utf-8")

        output = _invoke_prune(tmp_path, plan_path, "--remove-orphans", "--dry-run")

        orphan_listing = output.split("Removing orphaned test case definitions")[1]
        orphan_listing = orphan_listing.split("Dry run complete")[0]
        assert "never-grouped" in orphan_listing
        assert "4.0.0" in orphan_listing
        assert "9.9.9" in orphan_listing
        assert "2 test case definition(s) would be removed" in output
        assert plan_path.read_text(encoding="utf-8") == before

    def test_second_remove_orphans_run_reports_no_changes(self, tmp_path: Path) -> None:
        """Running --remove-orphans again after cleanup changes nothing."""
        plan_path = _stage_prune_workspace(tmp_path)
        _invoke_prune(tmp_path, plan_path, "--remove-orphans")
        before = plan_path.read_text(encoding="utf-8")

        output = _invoke_prune(tmp_path, plan_path, "--remove-orphans")

        assert "Pruning already applied -- no changes needed" in output
        assert plan_path.read_text(encoding="utf-8") == before

    def test_removes_orphans_when_results_have_no_na_tests(
        self, tmp_path: Path
    ) -> None:
        """Orphans are removed even if the learning run found nothing N/A."""
        plan_path = _stage_prune_workspace(tmp_path)
        plan_path.write_text(
            _CLI_PLAN_YAML.replace('["3.0.0", "4.0.0"]', '["3.0.0"]'),
            encoding="utf-8",
        )
        run_dir = tmp_path / "results" / "2026-Apr-30-14-22-01-learning"
        _write_json(run_dir / "run.json", _build_run_json(groups=[]))

        output = _invoke_prune(tmp_path, plan_path, "--remove-orphans")

        assert "1 test case definition(s) removed" in output
        assert set(load_test_plan(plan_path).test_cases) == {"3.0.0"}


_NESTED_TARGET_PLAN_YAML = """\
test_cases:
  "5.0.0":
    title: Check interfaces
    job: jobs/interfaces.py
test_case_groups:
  nxos-checks:
    tests: ["5.0.0"]
    target:
      os: [nxos]
  fabric:
    groups: [nxos-checks]
scenarios:
  scenario-1:
    phases:
      phase-1:
        test_case_groups: [fabric]
"""


def test_prune_keeps_nested_group_target_for_partially_na_test(
    tmp_path: Path,
) -> None:
    """exclude_devices on a nested test combines with the child group's target."""
    plan_path = tmp_path / "test_plan.yaml"
    plan_path.write_text(_NESTED_TARGET_PLAN_YAML, encoding="utf-8")
    run_dir = tmp_path / "results" / "2026-Apr-30-14-22-01-learning"
    _write_json(
        run_dir / "test-cases" / "5.0.0" / "result.json",
        {
            "command_executions": [
                {"device": "nx-01", "command": "show interface"},
                {"device": "nx-02", "command": "show interface"},
            ],
            "not_applicable_devices": {"nx-02": "No interfaces configured"},
        },
    )
    groups = [
        {
            "id": "fabric",
            "test_cases": [
                {"test_id": "5.0.0", "result_path": "test-cases/5.0.0/result.json"}
            ],
        },
    ]
    _write_json(run_dir / "run.json", _build_run_json(groups=groups))

    _invoke_prune(tmp_path, plan_path)

    plan = load_test_plan(plan_path)
    test_case = plan.test_cases["5.0.0"]
    assert test_case.target == TargetDefinition(exclude_devices=["nx-02"])
    fabric = plan.test_case_groups["fabric"]
    assert fabric.tests == ["5.0.0"]
    testbed = Testbed(
        devices={
            name: Device(name=name, os=os_name)
            for name, os_name in (
                ("nx-01", "nxos"),
                ("nx-02", "nxos"),
                ("xe-01", "iosxe"),
            )
        }
    )
    targets = resolve_targets(
        testbed=testbed,
        phase=plan.scenarios["scenario-1"].phases["phase-1"],
        group=fabric,
        test_case=test_case,
    )
    assert [device.name for device in targets] == ["nx-01"]

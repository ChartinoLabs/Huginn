"""Unit tests for the prune module."""

import json
from pathlib import Path

import pytest

from huginn.models import (
    Phase,
    Scenario,
    TargetDefinition,
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

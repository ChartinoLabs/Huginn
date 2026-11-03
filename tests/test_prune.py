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
from huginn.output import Output
from huginn.prune import (
    NotApplicableTestCase,
    PruneEdit,
    PruneError,
    PruneInput,
    PrunePlan,
    _extract_all_devices,
    compute_prune_plan,
    find_latest_learning_results,
    parse_applicability_from_run,
    prepare_prune_edit,
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
        """Full N/A tests that no group lists any more are skipped."""
        groups = {
            "group-a": TestCaseGroup(
                identifier="group-a",
                tests=["TC-1"],
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
# prepare_prune_edit
# ===========================================================================

_EDIT_PLAN_YAML = """\
test_cases:
  TC-1: {title: One, job: jobs/one.py}
  TC-2: {title: Two, job: jobs/two.py}
  TC-3: {title: Three, job: jobs/three.py}
test_case_groups:
  leaf:
    tests: [TC-1, TC-2]
  other:
    tests: [TC-3]
  parent:
    tests: [TC-3]
    groups: [leaf]
    exclude_tests: [TC-2]
scenarios:
  s:
    phases:
      p:
        test_case_groups: [parent, other]
"""


def _edit_for(
    tmp_path: Path, prune_plan: PrunePlan, text: str = _EDIT_PLAN_YAML
) -> tuple[Path, PruneEdit]:
    """Write a single-file plan and prepare a prune edit for it."""
    plan_path = tmp_path / "test_plan.yaml"
    plan_path.write_text(text, encoding="utf-8")
    edit = prepare_prune_edit(
        plan_path=plan_path, prune_plan=prune_plan, output=Output()
    )
    return plan_path, edit


def _group_plan(**exclude_from_groups: list[str]) -> PrunePlan:
    """Build a PrunePlan that only removes tests from groups."""
    return PrunePlan(
        exclude_devices_updates={},
        exclude_from_groups=dict(exclude_from_groups),
        skipped_already_pruned=[],
    )


class TestPreparePruneEdit:
    """Tests for prepare_prune_edit."""

    def test_removes_tests_from_leaf_without_writing(self, tmp_path: Path) -> None:
        """Tests leave the leaf's list in memory; the file is untouched."""
        plan_path, edit = _edit_for(tmp_path, _group_plan(leaf=["TC-1"]))

        group = edit.documents[plan_path]["test_case_groups"]["leaf"]
        assert group["tests"] == ["TC-2"]
        assert edit.removed_groups == []
        assert plan_path.read_text(encoding="utf-8") == _EDIT_PLAN_YAML

    def test_emptied_child_is_removed_and_parent_tidied(self, tmp_path: Path) -> None:
        """The parent loses the child reference and its now-invalid exclude_tests."""
        plan_path, edit = _edit_for(tmp_path, _group_plan(leaf=["TC-1", "TC-2"]))

        groups = edit.documents[plan_path]["test_case_groups"]
        assert edit.removed_groups == ["leaf"]
        assert "leaf" not in groups
        assert dict(groups["parent"]) == {"tests": ["TC-3"]}
        assert "exclude_tests" not in groups["parent"]

    def test_cascade_reaches_phase(self, tmp_path: Path) -> None:
        """Emptying both of the parent's sources removes it from the phase."""
        plan_path, edit = _edit_for(
            tmp_path, _group_plan(leaf=["TC-1", "TC-2"], parent=["TC-3"])
        )

        assert edit.removed_groups == ["leaf", "parent"]
        phase = edit.documents[plan_path]["scenarios"]["s"]["phases"]["p"]
        assert phase["test_case_groups"] == ["other"]
        assert edit.removed_phases == []

    def test_invalid_result_raises_and_writes_nothing(self, tmp_path: Path) -> None:
        """Emptying every group fails validation before anything is written."""
        with pytest.raises(PruneError, match="no files were changed"):
            _edit_for(
                tmp_path,
                _group_plan(leaf=["TC-1", "TC-2"], parent=["TC-3"], other=["TC-3"]),
            )

        plan_path = tmp_path / "test_plan.yaml"
        assert plan_path.read_text(encoding="utf-8") == _EDIT_PLAN_YAML

    def test_error_message_names_the_real_plan_path(self, tmp_path: Path) -> None:
        """Validation errors refer to the plan, not the temporary copy."""
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        (plan_dir / "plan.yaml").write_text(_EDIT_PLAN_YAML, encoding="utf-8")
        # A second file that redefines a group the first one defines.
        (plan_dir / "dup.yaml").write_text(
            "test_case_groups:\n  other:\n    tests: [TC-3]\n", encoding="utf-8"
        )

        with pytest.raises(PruneError) as excinfo:
            prepare_prune_edit(
                plan_path=plan_dir, prune_plan=_group_plan(), output=Output()
            )

        assert str(plan_dir) in str(excinfo.value)
        assert "huginn-prune-" not in str(excinfo.value)

    def test_removes_orphaned_test_case_definitions(self, tmp_path: Path) -> None:
        """Orphaned definitions are deleted from test_cases."""
        prune_plan = PrunePlan(
            exclude_devices_updates={},
            exclude_from_groups={"leaf": ["TC-1"]},
            skipped_already_pruned=[],
            orphaned_test_cases=["TC-1", "TC-99"],
        )

        plan_path, edit = _edit_for(tmp_path, prune_plan)

        assert set(edit.documents[plan_path]["test_cases"]) == {"TC-2", "TC-3"}

    def test_sets_exclude_devices(self, tmp_path: Path) -> None:
        """Partially applicable tests get target.exclude_devices."""
        prune_plan = PrunePlan(
            exclude_devices_updates={"TC-3": ["dev-b"]},
            exclude_from_groups={},
            skipped_already_pruned=[],
        )

        plan_path, edit = _edit_for(tmp_path, prune_plan)

        test_case = edit.documents[plan_path]["test_cases"]["TC-3"]
        assert test_case["target"] == {"exclude_devices": ["dev-b"]}


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


# ===========================================================================
# huginn prune: removing groups that pruning empties (#349)
# ===========================================================================

_EMPTIED_GROUPS_YAML = """\
test_case_groups:
  catalog-import-vrf:
    name: vrf
    tests:
    - VRF-1
    - VRF-2
  catalog-import:
    groups:
    - catalog-import-vrf
"""

_EMPTIED_TEST_CASES_YAML = """\
test_cases:
  VRF-1:
    title: VRF one
    job: jobs.vrf.one
  VRF-2:
    title: VRF two
    job: jobs.vrf.two
"""

_EMPTIED_SCENARIOS_YAML = """\
test_cases:
  BASE-1:
    title: Baseline
    job: jobs.base.one
test_case_groups:
  baseline:
    tests:
    - BASE-1
scenarios:
  main:
    phases:
      learn:
        test_case_groups:
        - baseline
        - catalog-import
"""


def _stage_emptied_group_workspace(
    tmp_path: Path,
    *,
    scenarios_yaml: str = _EMPTIED_SCENARIOS_YAML,
    na_tests: tuple[str, ...] = ("VRF-1", "VRF-2"),
) -> Path:
    """Write a directory plan whose leaf group pruning will empty."""
    plan_dir = tmp_path / "test_plan"
    (plan_dir / "groups").mkdir(parents=True)
    (plan_dir / "test_cases").mkdir()
    (plan_dir / "groups" / "catalog-import.yaml").write_text(
        _EMPTIED_GROUPS_YAML, encoding="utf-8"
    )
    (plan_dir / "test_cases" / "catalog-import.yaml").write_text(
        _EMPTIED_TEST_CASES_YAML, encoding="utf-8"
    )
    (plan_dir / "scenarios.yaml").write_text(scenarios_yaml, encoding="utf-8")

    run_dir = tmp_path / "results" / "2026-Nov-03-09-39-30-learning"
    entries = []
    for test_id in na_tests:
        result_path = f"test-cases/{test_id}/result.json"
        _write_json(
            run_dir / result_path,
            {
                "command_executions": [],
                "not_applicable_devices": {"device-1": "Command not supported"},
            },
        )
        entries.append({"test_id": test_id, "result_path": result_path})
    groups = [{"id": "catalog-import", "test_cases": entries}]
    _write_json(run_dir / "run.json", _build_run_json(groups=groups))
    return plan_dir


def _plan_snapshot(plan_dir: Path) -> dict[str, str]:
    """Return the text of every YAML file in a plan directory."""
    return {
        str(path.relative_to(plan_dir)): path.read_text(encoding="utf-8")
        for path in sorted(plan_dir.rglob("*.yaml"))
    }


class TestPruneRemovesEmptiedGroups:
    """Groups, phases and scenarios that pruning empties are removed."""

    def test_emptied_leaf_and_composite_groups_are_removed(
        self, tmp_path: Path
    ) -> None:
        """The plan stays valid and both emptied groups disappear."""
        plan_dir = _stage_emptied_group_workspace(tmp_path)

        output = _invoke_prune(tmp_path, plan_dir)

        plan = load_test_plan(plan_dir)
        assert set(plan.test_case_groups) == {"baseline"}
        phase = plan.scenarios["main"].phases["learn"]
        assert phase.test_case_groups == ["baseline"]
        groups_text = (plan_dir / "groups" / "catalog-import.yaml").read_text(
            encoding="utf-8"
        )
        assert groups_text == "test_case_groups: {}\n"
        assert "exclude_tests" not in groups_text
        assert "Removing emptied test case groups:" in output
        assert "catalog-import-vrf" in output
        assert "2 group(s) removed" in output
        # Orphaned definitions stay without --remove-orphans.
        assert {"VRF-1", "VRF-2"} <= set(plan.test_cases)

    def test_composite_parent_gets_no_exclude_tests(self, tmp_path: Path) -> None:
        """Removing some tests from a child adds nothing to the parent."""
        plan_dir = _stage_emptied_group_workspace(tmp_path, na_tests=("VRF-1",))

        _invoke_prune(tmp_path, plan_dir)

        plan = load_test_plan(plan_dir)
        assert plan.test_case_groups["catalog-import-vrf"].tests == ["VRF-2"]
        assert plan.test_case_groups["catalog-import"].tests == ["VRF-2"]
        assert plan.test_case_groups["catalog-import"].exclude_tests == []

    def test_emptied_phase_and_scenario_are_removed(self, tmp_path: Path) -> None:
        """A phase with no groups left goes, and so does an empty scenario."""
        scenarios_yaml = _EMPTIED_SCENARIOS_YAML + (
            "  imported:\n"
            "    phases:\n"
            "      learn-import:\n"
            "        test_case_groups:\n"
            "        - catalog-import\n"
            "      after:\n"
            "        depends_on: [learn-import]\n"
            "        test_case_groups:\n"
            "        - catalog-import-vrf\n"
            "  partial:\n"
            "    phases:\n"
            "      first:\n"
            "        test_case_groups: [catalog-import]\n"
            "      second:\n"
            "        depends_on: [first]\n"
            "        test_case_groups: [baseline]\n"
        )
        plan_dir = _stage_emptied_group_workspace(
            tmp_path, scenarios_yaml=scenarios_yaml
        )

        output = _invoke_prune(tmp_path, plan_dir)

        plan = load_test_plan(plan_dir)
        assert set(plan.scenarios) == {"main", "partial"}
        partial = plan.scenarios["partial"]
        assert set(partial.phases) == {"second"}
        assert partial.phases["second"].depends_on == []
        assert "Removing emptied phases:" in output
        assert "first (scenario partial)" in output
        assert "Removing emptied scenarios:" in output
        assert "imported" in output

    def test_dry_run_reports_removals_without_writing(self, tmp_path: Path) -> None:
        """--dry-run lists the emptied groups and changes no file."""
        plan_dir = _stage_emptied_group_workspace(tmp_path)
        before = _plan_snapshot(plan_dir)

        output = _invoke_prune(tmp_path, plan_dir, "--dry-run")

        assert "Removing emptied test case groups:" in output
        assert "2 group(s) would be removed" in output
        assert _plan_snapshot(plan_dir) == before

    def test_invalid_result_writes_nothing(self, tmp_path: Path) -> None:
        """When nothing would be left to run, prune fails and writes nothing."""
        scenarios_yaml = (
            "scenarios:\n"
            "  main:\n"
            "    phases:\n"
            "      learn:\n"
            "        test_case_groups: [catalog-import]\n"
        )
        plan_dir = _stage_emptied_group_workspace(
            tmp_path, scenarios_yaml=scenarios_yaml
        )
        before = _plan_snapshot(plan_dir)

        result = CliRunner().invoke(
            app,
            [
                "prune",
                "--plan",
                str(plan_dir),
                "--results-dir",
                str(tmp_path / "results"),
                "--log-file",
                str(tmp_path / "huginn.log"),
            ],
        )

        assert result.exit_code == 1
        text = " ".join(re.sub(r"\x1b\[[0-9;]*m", "", result.output).split())
        assert "would leave an invalid test plan" in text
        assert "no files were changed" in text
        assert _plan_snapshot(plan_dir) == before

    def test_directly_listed_test_in_composite_is_removed(self, tmp_path: Path) -> None:
        """A test a composite lists in its own tests is removed, not excluded."""
        plan_path = tmp_path / "test_plan.yaml"
        plan_path.write_text(
            "test_cases:\n"
            "  A: {title: A, job: jobs.a}\n"
            "  B: {title: B, job: jobs.b}\n"
            "test_case_groups:\n"
            "  child:\n"
            "    tests: [B]\n"
            "  parent:\n"
            "    tests: [A]\n"
            "    groups: [child]\n"
            "scenarios:\n"
            "  s:\n"
            "    phases:\n"
            "      p:\n"
            "        test_case_groups: [parent]\n",
            encoding="utf-8",
        )
        run_dir = tmp_path / "results" / "2026-Apr-30-14-22-01-learning"
        _write_json(
            run_dir / "test-cases" / "A" / "result.json",
            {"command_executions": [], "not_applicable_devices": {"d1": "N/A"}},
        )
        groups = [
            {
                "id": "parent",
                "test_cases": [
                    {"test_id": "A", "result_path": "test-cases/A/result.json"}
                ],
            }
        ]
        _write_json(run_dir / "run.json", _build_run_json(groups=groups))

        _invoke_prune(tmp_path, plan_path)

        plan = load_test_plan(plan_path)
        assert plan.test_case_groups["parent"].tests == ["B"]
        assert plan.test_case_groups["parent"].exclude_tests == []


def test_remove_orphans_finds_test_pruned_from_nested_group(tmp_path: Path) -> None:
    """A pruned test inherited by a composite group is still an orphan."""
    plan_dir = _stage_emptied_group_workspace(tmp_path, na_tests=("VRF-1",))

    _invoke_prune(tmp_path, plan_dir, "--remove-orphans")

    plan = load_test_plan(plan_dir)
    assert "VRF-1" not in plan.test_cases
    assert plan.test_case_groups["catalog-import"].tests == ["VRF-2"]

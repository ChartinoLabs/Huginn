"""Unit tests for test plan tag filtering behavior."""

import huginn.models as models
from huginn.plan_filtering import (
    PlanFilterOptions,
    filter_test_plan,
    filter_test_plan_by_tags,
)


def _scenario_with_phases(**phases: models.Phase) -> dict[str, models.Scenario]:
    """Build a single-scenario test plan mapping."""
    return {
        "scenario-1": models.Scenario(
            name="scenario-1",
            phases=phases,
        )
    }


def test_filter_by_tags_matches_group_tags_when_test_case_has_no_tags() -> None:
    """Group tags are included in effective tag matching for a test case."""
    test_plan = models.TestPlan(
        scenarios=_scenario_with_phases(
            **{"phase-1": models.Phase(name="phase-1", test_case_groups=["routing"])}
        ),
        test_case_groups={
            "routing": models.TestCaseGroup(
                name="routing",
                tests=["1.0.0"],
                tags=["ospf"],
            )
        },
        test_cases={
            "1.0.0": models.TestCaseDefinition(
                test_id="1.0.0",
                title="Verify OSPF",
                job="jobs/verify_ospf.py",
                tags=[],
            )
        },
    )

    filtered = filter_test_plan_by_tags(test_plan, ["ospf"])

    assert list(filtered.test_case_groups.keys()) == ["routing"]
    assert filtered.test_case_groups["routing"].tests == ["1.0.0"]
    assert list(filtered.test_cases.keys()) == ["1.0.0"]


def test_filter_by_tags_uses_union_of_test_and_group_tags() -> None:
    """Test and group tags are treated as an additive union for filtering."""
    test_plan = models.TestPlan(
        scenarios=_scenario_with_phases(
            **{
                "phase-1": models.Phase(
                    name="phase-1",
                    test_case_groups=["core", "edge"],
                )
            }
        ),
        test_case_groups={
            "core": models.TestCaseGroup(
                name="core",
                tests=["1.0.0"],
                tags=["precheck"],
            ),
            "edge": models.TestCaseGroup(
                name="edge",
                tests=["1.0.0"],
                tags=["postcheck"],
            ),
        },
        test_cases={
            "1.0.0": models.TestCaseDefinition(
                test_id="1.0.0",
                title="Verify state",
                job="jobs/verify_state.py",
                tags=["routing"],
            )
        },
    )

    filtered = filter_test_plan_by_tags(test_plan, ["postcheck"])

    assert list(filtered.test_case_groups.keys()) == ["edge"]
    assert filtered.test_case_groups["edge"].tests == ["1.0.0"]
    assert filtered.scenarios["scenario-1"].phases["phase-1"].test_case_groups == [
        "edge"
    ]


def test_filter_by_tags_still_matches_plain_test_case_tags() -> None:
    """Existing test-case-only tag behavior is preserved."""
    test_plan = models.TestPlan(
        scenarios=_scenario_with_phases(
            **{"phase-1": models.Phase(name="phase-1", test_case_groups=["routing"])}
        ),
        test_case_groups={
            "routing": models.TestCaseGroup(name="routing", tests=["1.0.0"])
        },
        test_cases={
            "1.0.0": models.TestCaseDefinition(
                test_id="1.0.0",
                title="Verify OSPF",
                job="jobs/verify_ospf.py",
                tags=["ospf"],
            )
        },
    )

    filtered = filter_test_plan_by_tags(test_plan, ["ospf"])

    assert list(filtered.test_case_groups.keys()) == ["routing"]
    assert filtered.test_case_groups["routing"].tests == ["1.0.0"]


def test_filter_by_exclude_tags_removes_matching_tests() -> None:
    """Exclude tags remove tests with matching effective tags."""
    test_plan = models.TestPlan(
        scenarios=_scenario_with_phases(
            **{"phase-1": models.Phase(name="phase-1", test_case_groups=["routing"])}
        ),
        test_case_groups={
            "routing": models.TestCaseGroup(name="routing", tests=["1.0.0", "1.0.1"])
        },
        test_cases={
            "1.0.0": models.TestCaseDefinition(
                test_id="1.0.0",
                title="Fast test",
                job="jobs/fast.py",
                tags=["fast"],
            ),
            "1.0.1": models.TestCaseDefinition(
                test_id="1.0.1",
                title="Slow test",
                job="jobs/slow.py",
                tags=["slow"],
            ),
        },
    )

    filtered = filter_test_plan(
        test_plan,
        PlanFilterOptions(exclude_tags=["slow"]),
    )

    assert filtered.test_case_groups["routing"].tests == ["1.0.0"]


def test_filter_by_phase_group_and_test_id_combines_with_and_logic() -> None:
    """Phase/group/test-id filters combine to constrain execution nodes."""
    test_plan = models.TestPlan(
        scenarios=_scenario_with_phases(
            **{
                "pre": models.Phase(name="pre", test_case_groups=["core", "edge"]),
                "post": models.Phase(name="post", test_case_groups=["edge"]),
            }
        ),
        test_case_groups={
            "core": models.TestCaseGroup(name="core", tests=["1.0.0", "1.0.1"]),
            "edge": models.TestCaseGroup(name="edge", tests=["2.0.0"]),
        },
        test_cases={
            "1.0.0": models.TestCaseDefinition(
                test_id="1.0.0",
                title="Core 1",
                job="jobs/core1.py",
            ),
            "1.0.1": models.TestCaseDefinition(
                test_id="1.0.1",
                title="Core 2",
                job="jobs/core2.py",
            ),
            "2.0.0": models.TestCaseDefinition(
                test_id="2.0.0",
                title="Edge",
                job="jobs/edge.py",
            ),
        },
    )

    filtered = filter_test_plan(
        test_plan,
        PlanFilterOptions(
            scenarios=["scenario-1"],
            phases=["pre"],
            test_case_groups=["core"],
            test_ids=["1.0.1"],
        ),
    )

    assert list(filtered.scenarios.keys()) == ["scenario-1"]
    assert list(filtered.scenarios["scenario-1"].phases.keys()) == ["pre"]
    assert filtered.scenarios["scenario-1"].phases["pre"].test_case_groups == ["core"]
    assert filtered.test_case_groups["core"].tests == ["1.0.1"]
    assert list(filtered.test_cases.keys()) == ["1.0.1"]


def test_filter_by_tags_requires_all_requested_tags() -> None:
    """Include tags require full subset match against effective tags."""
    test_plan = models.TestPlan(
        scenarios=_scenario_with_phases(
            **{"phase-1": models.Phase(name="phase-1", test_case_groups=["routing"])}
        ),
        test_case_groups={
            "routing": models.TestCaseGroup(name="routing", tests=["1.0.0", "1.0.1"])
        },
        test_cases={
            "1.0.0": models.TestCaseDefinition(
                test_id="1.0.0",
                title="OSPF core",
                job="jobs/ospf_core.py",
                tags=["ospf", "critical"],
            ),
            "1.0.1": models.TestCaseDefinition(
                test_id="1.0.1",
                title="OSPF non-critical",
                job="jobs/ospf_noncritical.py",
                tags=["ospf"],
            ),
        },
    )

    filtered = filter_test_plan(
        test_plan,
        PlanFilterOptions(tags=["ospf", "critical"]),
    )

    assert filtered.test_case_groups["routing"].tests == ["1.0.0"]


# --- test_id_pattern filtering ---


def _plan_with_reconciled_ids() -> models.TestPlan:
    """Build a test plan with both original and reconciled test case IDs."""
    return models.TestPlan(
        scenarios=_scenario_with_phases(
            **{
                "phase-1": models.Phase(
                    name="phase-1",
                    test_case_groups=["validation"],
                ),
            }
        ),
        test_case_groups={
            "validation": models.TestCaseGroup(
                name="validation",
                tests=["1.0.0", "2.0.0", "1.0.0-post-shutdown", "2.0.0-post-shutdown"],
            ),
        },
        test_cases={
            "1.0.0": models.TestCaseDefinition(
                test_id="1.0.0",
                title="Verify reachability",
                job="jobs/verify_reachability.py",
            ),
            "2.0.0": models.TestCaseDefinition(
                test_id="2.0.0",
                title="Verify OSPF",
                job="jobs/verify_ospf.py",
            ),
            "1.0.0-post-shutdown": models.TestCaseDefinition(
                test_id="1.0.0-post-shutdown",
                title="Verify reachability (post-shutdown)",
                job="jobs/verify_reachability.py",
            ),
            "2.0.0-post-shutdown": models.TestCaseDefinition(
                test_id="2.0.0-post-shutdown",
                title="Verify OSPF (post-shutdown)",
                job="jobs/verify_ospf.py",
            ),
        },
    )


def test_filter_by_test_id_pattern_matches_suffix() -> None:
    """Filter test cases to only those matching the regex pattern."""
    filtered = filter_test_plan(
        _plan_with_reconciled_ids(),
        PlanFilterOptions(test_id_pattern=r"-post-shutdown$"),
    )

    assert set(filtered.test_cases.keys()) == {
        "1.0.0-post-shutdown",
        "2.0.0-post-shutdown",
    }
    assert filtered.test_case_groups["validation"].tests == [
        "1.0.0-post-shutdown",
        "2.0.0-post-shutdown",
    ]


def test_filter_by_test_id_pattern_excludes_non_matching() -> None:
    """Non-matching test case IDs are removed from groups."""
    filtered = filter_test_plan(
        _plan_with_reconciled_ids(),
        PlanFilterOptions(test_id_pattern=r"^1\."),
    )

    assert set(filtered.test_cases.keys()) == {"1.0.0", "1.0.0-post-shutdown"}


def test_filter_by_test_id_pattern_combined_with_test_ids() -> None:
    """Pattern and explicit test_ids filters are applied together (AND logic)."""
    filtered = filter_test_plan(
        _plan_with_reconciled_ids(),
        PlanFilterOptions(
            test_ids=["1.0.0-post-shutdown", "2.0.0-post-shutdown"],
            test_id_pattern=r"^1\.",
        ),
    )

    assert set(filtered.test_cases.keys()) == {"1.0.0-post-shutdown"}


def test_filter_by_test_id_pattern_no_match_prunes_group() -> None:
    """Groups with no remaining tests are pruned from the plan."""
    filtered = filter_test_plan(
        _plan_with_reconciled_ids(),
        PlanFilterOptions(test_id_pattern=r"nonexistent"),
    )

    assert filtered.test_case_groups == {}
    assert filtered.test_cases == {}
    assert filtered.scenarios == {}

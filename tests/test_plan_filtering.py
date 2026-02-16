"""Unit tests for test plan tag filtering behavior."""

import huginn.models as models
from huginn.plan_filtering import filter_test_plan_by_tags


def test_filter_by_tags_matches_group_tags_when_test_case_has_no_tags() -> None:
    """Group tags are included in effective tag matching for a test case."""
    test_plan = models.TestPlan(
        phases={"phase-1": models.Phase(name="phase-1", test_case_groups=["routing"])},
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
        phases={
            "phase-1": models.Phase(
                name="phase-1",
                test_case_groups=["core", "edge"],
            ),
        },
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
    assert filtered.phases["phase-1"].test_case_groups == ["edge"]


def test_filter_by_tags_still_matches_plain_test_case_tags() -> None:
    """Existing test-case-only tag behavior is preserved."""
    test_plan = models.TestPlan(
        phases={"phase-1": models.Phase(name="phase-1", test_case_groups=["routing"])},
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

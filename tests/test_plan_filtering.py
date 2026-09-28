"""Unit tests for test plan tag filtering behavior."""

from dataclasses import MISSING, fields, replace
from typing import TypeAlias

import pytest

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


def _shared_group_plan() -> models.TestPlan:
    """Build two scenarios whose two dependent phases share one group."""
    phases = {
        "pre": models.Phase(identifier="pre", test_case_groups=["core"]),
        "post": models.Phase(
            identifier="post", test_case_groups=["core"], depends_on=["pre"]
        ),
    }
    return models.TestPlan(
        scenarios={
            name: models.Scenario(
                identifier=name,
                phases={key: replace(phase) for key, phase in phases.items()},
            )
            for name in ("scenario-1", "scenario-2")
        },
        test_case_groups={
            "core": models.TestCaseGroup(
                identifier="core", name="Core", tests=["1.0.0", "2.0.0"]
            )
        },
        test_cases={
            test_id: models.TestCaseDefinition(
                test_id=test_id, title=test_id, job="jobs/check.py"
            )
            for test_id in ("1.0.0", "2.0.0")
        },
    )


def _phase_tests(
    test_plan: models.TestPlan, scenario: str, phase: str
) -> list[tuple[str, list[str]]]:
    """Return (group identifier, tests) pairs for one filtered phase."""
    groups = test_plan.scenarios[scenario].phases[phase].test_case_groups
    return [
        (
            test_plan.test_case_groups[key].identifier,
            test_plan.test_case_groups[key].tests,
        )
        for key in groups
    ]


def test_filter_by_test_contexts_keeps_only_exact_tuples() -> None:
    """Contexts select exact tuples rather than a scenario x phase x id product."""
    filtered = filter_test_plan(
        _shared_group_plan(),
        PlanFilterOptions(
            test_contexts=[
                ("scenario-1", "pre", "1.0.0"),
                ("scenario-2", "post", "2.0.0"),
            ]
        ),
    )

    assert list(filtered.scenarios["scenario-1"].phases) == ["pre"]
    assert list(filtered.scenarios["scenario-2"].phases) == ["post"]
    assert _phase_tests(filtered, "scenario-1", "pre") == [("core", ["1.0.0"])]
    assert _phase_tests(filtered, "scenario-2", "post") == [("core", ["2.0.0"])]
    assert list(filtered.test_cases) == ["1.0.0", "2.0.0"]


def test_filter_by_test_contexts_splits_shared_group_per_phase() -> None:
    """A group shared by two phases can keep different tests in each phase."""
    filtered = filter_test_plan(
        _shared_group_plan(),
        PlanFilterOptions(
            test_contexts=[
                ("scenario-1", "pre", "1.0.0"),
                ("scenario-1", "post", "2.0.0"),
                ("scenario-2", "pre", "1.0.0"),
            ]
        ),
    )

    assert _phase_tests(filtered, "scenario-1", "pre") == [("core", ["1.0.0"])]
    assert _phase_tests(filtered, "scenario-1", "post") == [("core", ["2.0.0"])]
    assert _phase_tests(filtered, "scenario-2", "pre") == [("core", ["1.0.0"])]
    # Identical subsets reuse one group entry; distinct subsets get their own
    # entry, all keeping the original group identifier and fields.
    assert len(filtered.test_case_groups) == 2
    for group in filtered.test_case_groups.values():
        assert group.identifier == "core"
        assert group.name == "Core"
    assert _shared_group_plan().test_case_groups["core"].tests == ["1.0.0", "2.0.0"]


def test_filter_by_test_contexts_combines_with_other_filters() -> None:
    """Contexts are ANDed with the scenario, phase, and test ID filters."""
    contexts = [
        ("scenario-1", "pre", "1.0.0"),
        ("scenario-1", "post", "2.0.0"),
        ("scenario-2", "post", "1.0.0"),
    ]

    by_phase = filter_test_plan(
        _shared_group_plan(),
        PlanFilterOptions(phases=["post"], test_contexts=contexts),
    )
    by_scenario_and_id = filter_test_plan(
        _shared_group_plan(),
        PlanFilterOptions(
            scenarios=["scenario-1"], test_ids=["1.0.0"], test_contexts=contexts
        ),
    )

    assert _phase_tests(by_phase, "scenario-1", "post") == [("core", ["2.0.0"])]
    assert _phase_tests(by_phase, "scenario-2", "post") == [("core", ["1.0.0"])]
    assert list(by_scenario_and_id.scenarios) == ["scenario-1"]
    assert list(by_scenario_and_id.scenarios["scenario-1"].phases) == ["pre"]
    assert list(by_scenario_and_id.test_cases) == ["1.0.0"]


def test_filter_by_test_contexts_drops_dependency_on_unselected_phase() -> None:
    """A selected phase no longer depends on a phase that was filtered out."""
    filtered = filter_test_plan(
        _shared_group_plan(),
        PlanFilterOptions(test_contexts=[("scenario-1", "post", "1.0.0")]),
    )

    assert list(filtered.scenarios) == ["scenario-1"]
    post = filtered.scenarios["scenario-1"].phases["post"]
    assert list(filtered.scenarios["scenario-1"].phases) == ["post"]
    assert post.depends_on == []


def test_filter_by_test_contexts_keeps_dependency_on_selected_phase() -> None:
    """Dependencies between two selected phases are preserved."""
    filtered = filter_test_plan(
        _shared_group_plan(),
        PlanFilterOptions(
            test_contexts=[
                ("scenario-1", "pre", "1.0.0"),
                ("scenario-1", "post", "2.0.0"),
            ]
        ),
    )

    assert filtered.scenarios["scenario-1"].phases["post"].depends_on == ["pre"]


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


# --- field preservation ---

PlanModel: TypeAlias = (
    models.TestPlan
    | models.Scenario
    | models.Phase
    | models.TestCaseGroup
    | models.TestCaseDefinition
)


def _fully_populated_plan() -> models.TestPlan:
    """Build a test plan where every model field has a non-default value."""
    target = models.TargetDefinition(
        devices=["leaf-01"],
        groups=["leaf"],
        os=["nxos"],
        exclude_devices=["leaf-02"],
    )
    return models.TestPlan(
        scenarios={
            "scenario-1": models.Scenario(
                identifier="scenario-1",
                name="Scenario One",
                phases={
                    "pre": models.Phase(
                        identifier="pre",
                        name="Pre-change",
                        test_case_groups=["core"],
                        target=target,
                        strategy=models.ExecutionStrategy(mode="serial", maximum=1),
                        preserve_cache=True,
                    ),
                    "post": models.Phase(
                        identifier="post",
                        name="Post-change",
                        test_case_groups=["core"],
                        depends_on=["pre"],
                        target=target,
                        strategy=models.ExecutionStrategy(mode="serial", maximum=1),
                        preserve_cache=True,
                    ),
                },
            )
        },
        test_case_groups={
            "core": models.TestCaseGroup(
                identifier="core",
                name="Core checks",
                tests=["1.0.0", "2.0.0"],
                tags=["core"],
                target=target,
                strategy=models.ExecutionStrategy(mode="parallel", maximum=2),
                exclude_tests=["3.0.0"],
            )
        },
        test_cases={
            "1.0.0": models.TestCaseDefinition(
                test_id="1.0.0",
                title="Verify OSPF",
                job="jobs/verify_ospf.py",
                tags=["ospf"],
                target=target,
                description="Checks OSPF neighbors",
                priority="high",
                category="routing",
                is_automated=False,
                metadata={"owner": "netops"},
            ),
            "2.0.0": models.TestCaseDefinition(
                test_id="2.0.0",
                title="Verify BGP",
                job="jobs/verify_bgp.py",
                tags=["bgp"],
            ),
        },
        name="Change plan",
        description="Validates a change window",
        defaults={"target": {"os": ["nxos"]}},
        data_model={"vrfs": ["blue"]},
    )


def _assert_non_default(obj: PlanModel) -> None:
    """Assert every field with a default is set to a non-default value."""
    for field in fields(obj):
        if field.default is not MISSING:
            default = field.default
        elif field.default_factory is not MISSING:
            default = field.default_factory()
        else:
            continue
        assert getattr(obj, field.name) != default, (
            f"{type(obj).__name__}.{field.name} should be non-default in the fixture"
        )


def _assert_fields_preserved(
    original: PlanModel, filtered: PlanModel, *, skip: set[str]
) -> None:
    """Assert every dataclass field except ``skip`` is unchanged."""
    for field in fields(original):
        if field.name in skip:
            continue
        assert getattr(filtered, field.name) == getattr(original, field.name), (
            f"{type(original).__name__}.{field.name} was not preserved"
        )


@pytest.mark.parametrize(
    "filters",
    [
        PlanFilterOptions(tags=["ospf"]),
        PlanFilterOptions(exclude_tags=["bgp"]),
        PlanFilterOptions(scenarios=["scenario-1"]),
        PlanFilterOptions(phases=["pre", "post"]),
        PlanFilterOptions(test_case_groups=["core"]),
        PlanFilterOptions(test_ids=["1.0.0"]),
        PlanFilterOptions(test_id_pattern=r"^1\."),
        PlanFilterOptions(
            test_contexts=[
                ("scenario-1", "pre", "1.0.0"),
                ("scenario-1", "post", "1.0.0"),
            ]
        ),
    ],
    ids=[
        "tags",
        "exclude_tags",
        "scenarios",
        "phases",
        "test_case_groups",
        "test_ids",
        "test_id_pattern",
        "test_contexts",
    ],
)
def test_filter_preserves_all_non_collection_fields(
    filters: PlanFilterOptions,
) -> None:
    """Filtering keeps every model field except the filtered collections."""
    test_plan = _fully_populated_plan()
    _assert_non_default(test_plan)
    for scenario in test_plan.scenarios.values():
        _assert_non_default(scenario)
    _assert_non_default(test_plan.scenarios["scenario-1"].phases["post"])
    for group in test_plan.test_case_groups.values():
        _assert_non_default(group)
    _assert_non_default(test_plan.test_cases["1.0.0"])

    filtered = filter_test_plan(test_plan, filters)

    _assert_fields_preserved(
        test_plan,
        filtered,
        skip={"scenarios", "test_case_groups", "test_cases"},
    )
    for scenario_name, scenario in filtered.scenarios.items():
        original_scenario = test_plan.scenarios[scenario_name]
        _assert_fields_preserved(original_scenario, scenario, skip={"phases"})
        for phase_name, phase in scenario.phases.items():
            _assert_fields_preserved(
                original_scenario.phases[phase_name],
                phase,
                skip={"test_case_groups"},
            )
    for group_name, group in filtered.test_case_groups.items():
        _assert_fields_preserved(
            test_plan.test_case_groups[group_name], group, skip={"tests"}
        )
    for test_id, test_case in filtered.test_cases.items():
        _assert_fields_preserved(test_plan.test_cases[test_id], test_case, skip=set())
    assert "1.0.0" in filtered.test_cases

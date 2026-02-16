"""Utilities for filtering test plans before validation/execution."""

from huginn.models import Phase, TestCaseDefinition, TestCaseGroup, TestPlan


def filter_test_plan_by_tags(test_plan: TestPlan, tags: list[str] | None) -> TestPlan:
    """Filter a test plan by test-case tags and prune empty nodes."""
    if tags is None:
        return test_plan

    tag_set = set(tags)
    filtered_groups = _filter_groups(test_plan, tag_set)
    filtered_test_cases = _filter_test_cases(test_plan, filtered_groups)
    filtered_phases = _filter_phases(test_plan, filtered_groups)

    _normalize_phase_dependencies(filtered_phases)
    return TestPlan(
        phases=filtered_phases,
        test_case_groups=filtered_groups,
        test_cases=filtered_test_cases,
    )


def _filter_test_cases(
    test_plan: TestPlan,
    filtered_groups: dict[str, TestCaseGroup],
) -> dict[str, TestCaseDefinition]:
    """Keep test case definitions that are still referenced by kept groups."""
    referenced_tests = {
        test_id for group in filtered_groups.values() for test_id in group.tests
    }
    return {
        test_id: test_case
        for test_id, test_case in test_plan.test_cases.items()
        if test_id in referenced_tests
    }


def _filter_groups(
    test_plan: TestPlan,
    tag_set: set[str],
) -> dict[str, TestCaseGroup]:
    """Filter groups to only include tests matching effective tags."""
    filtered_groups: dict[str, TestCaseGroup] = {}
    for group_name, group in test_plan.test_case_groups.items():
        kept_tests = [
            test_id
            for test_id in group.tests
            if _effective_tags_match(
                test_case=test_plan.test_cases[test_id],
                group=group,
                tag_set=tag_set,
            )
        ]
        if not kept_tests:
            continue
        filtered_groups[group_name] = TestCaseGroup(
            name=group.name,
            tests=kept_tests,
            tags=group.tags,
            target=group.target,
        )
    return filtered_groups


def _effective_tags_match(
    *,
    test_case: TestCaseDefinition,
    group: TestCaseGroup,
    tag_set: set[str],
) -> bool:
    """Return True when filter tags intersect test tags plus group tags."""
    effective_tags = set(test_case.tags)
    effective_tags.update(group.tags)
    return bool(effective_tags.intersection(tag_set))


def _filter_phases(
    test_plan: TestPlan,
    filtered_groups: dict[str, TestCaseGroup],
) -> dict[str, Phase]:
    """Filter phases to only include groups that remain after tag filtering."""
    filtered_phases: dict[str, Phase] = {}
    for phase_name, phase in test_plan.phases.items():
        kept_groups = [
            group_name
            for group_name in phase.test_case_groups
            if group_name in filtered_groups
        ]
        if not kept_groups:
            continue
        filtered_phases[phase_name] = Phase(
            name=phase.name,
            test_case_groups=kept_groups,
            depends_on=phase.depends_on,
            target=phase.target,
        )
    return filtered_phases


def _normalize_phase_dependencies(phases: dict[str, Phase]) -> None:
    """Remove phase dependencies that no longer exist after filtering."""
    existing = set(phases.keys())
    for phase in phases.values():
        phase.depends_on = [
            dependency for dependency in phase.depends_on if dependency in existing
        ]

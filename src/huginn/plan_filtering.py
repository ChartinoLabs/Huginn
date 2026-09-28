"""Utilities for filtering test plans before validation/execution."""

import re
from dataclasses import dataclass, replace

from huginn.models import Phase, Scenario, TestCaseDefinition, TestCaseGroup, TestPlan


@dataclass(frozen=True)
class PlanFilterOptions:
    """Include/exclude filters applied before validation and execution."""

    tags: list[str] | None = None
    exclude_tags: list[str] | None = None
    scenarios: list[str] | None = None
    phases: list[str] | None = None
    test_case_groups: list[str] | None = None
    test_ids: list[str] | None = None
    test_id_pattern: str | None = None
    # Exact (scenario, phase, test_id) execution contexts to keep. Unlike the
    # independent scenario/phase/test ID filters, a test is kept in a phase only
    # when its exact tuple is selected.
    test_contexts: list[tuple[str, str, str]] | None = None


def filter_test_plan_by_tags(test_plan: TestPlan, tags: list[str] | None) -> TestPlan:
    """Filter a test plan by test-case tags and prune empty nodes."""
    return filter_test_plan(test_plan, PlanFilterOptions(tags=tags))


def filter_test_plan(test_plan: TestPlan, filters: PlanFilterOptions) -> TestPlan:
    """Apply plan filters and prune empty scenarios/phases/groups/tests."""
    if _is_noop(filters):
        return test_plan

    include_tags = set(filters.tags or [])
    exclude_tags = set(filters.exclude_tags or [])
    scenario_filter = set(filters.scenarios or [])
    phase_filter = set(filters.phases or [])
    group_filter = set(filters.test_case_groups or [])
    test_filter = set(filters.test_ids or [])
    test_id_regex = _compile_test_id_pattern(filters.test_id_pattern)

    filtered_groups = _filter_groups(
        test_plan,
        include_tags=include_tags,
        exclude_tags=exclude_tags,
        group_filter=group_filter,
        test_filter=test_filter,
        test_id_regex=test_id_regex,
    )
    filtered_scenarios = _filter_scenarios(
        test_plan,
        filtered_groups,
        scenario_filter=scenario_filter,
        phase_filter=phase_filter,
    )
    if filters.test_contexts:
        filtered_scenarios, filtered_groups = _select_test_contexts(
            filtered_scenarios, filtered_groups, filters.test_contexts
        )
    filtered_test_cases = _filter_test_cases(test_plan, filtered_groups)

    _normalize_phase_dependencies(filtered_scenarios)
    return replace(
        test_plan,
        scenarios=filtered_scenarios,
        test_case_groups=filtered_groups,
        test_cases=filtered_test_cases,
    )


def _is_noop(filters: PlanFilterOptions) -> bool:
    """Return True when no filters were provided."""
    return not any(
        (
            filters.tags,
            filters.exclude_tags,
            filters.scenarios,
            filters.phases,
            filters.test_case_groups,
            filters.test_ids,
            filters.test_id_pattern,
            filters.test_contexts,
        )
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


def _compile_test_id_pattern(pattern: str | None) -> re.Pattern[str] | None:
    """Compile an optional test ID regex pattern."""
    if pattern is None:
        return None
    try:
        return re.compile(pattern)
    except re.error as error:
        raise ValueError(
            f"Invalid --test-id-pattern regex '{pattern}': {error}"
        ) from error


def _filter_groups(
    test_plan: TestPlan,
    *,
    include_tags: set[str],
    exclude_tags: set[str],
    group_filter: set[str],
    test_filter: set[str],
    test_id_regex: re.Pattern[str] | None = None,
) -> dict[str, TestCaseGroup]:
    """Filter groups to only include tests matching active filters."""
    filtered_groups: dict[str, TestCaseGroup] = {}
    for group_name, group in test_plan.test_case_groups.items():
        if group_filter and group_name not in group_filter:
            continue

        kept_tests = [
            test_id
            for test_id in group.tests
            if _test_matches_filters(
                test_case=test_plan.test_cases[test_id],
                group=group,
                include_tags=include_tags,
                exclude_tags=exclude_tags,
                test_filter=test_filter,
                test_id_regex=test_id_regex,
            )
        ]
        if not kept_tests:
            continue
        filtered_groups[group_name] = replace(group, tests=kept_tests)
    return filtered_groups


def _test_matches_filters(
    *,
    test_case: TestCaseDefinition,
    group: TestCaseGroup,
    include_tags: set[str],
    exclude_tags: set[str],
    test_filter: set[str],
    test_id_regex: re.Pattern[str] | None = None,
) -> bool:
    """Return True when a test case passes id/tag include and exclude filters."""
    if test_filter and test_case.test_id not in test_filter:
        return False

    if test_id_regex is not None and not test_id_regex.search(test_case.test_id):
        return False

    effective_tags = set(test_case.tags)
    effective_tags.update(group.tags)

    if include_tags and not include_tags.issubset(effective_tags):
        return False
    if exclude_tags and effective_tags.intersection(exclude_tags):
        return False
    return True


def _filter_scenarios(
    test_plan: TestPlan,
    filtered_groups: dict[str, TestCaseGroup],
    *,
    scenario_filter: set[str],
    phase_filter: set[str],
) -> dict[str, Scenario]:
    """Filter scenarios/phases to only include groups that remain after filtering."""
    filtered_scenarios: dict[str, Scenario] = {}
    for scenario_name, scenario in test_plan.scenarios.items():
        filtered_scenario = _filter_scenario(
            scenario_name=scenario_name,
            scenario=scenario,
            filtered_groups=filtered_groups,
            scenario_filter=scenario_filter,
            phase_filter=phase_filter,
        )
        if filtered_scenario is not None:
            filtered_scenarios[scenario_name] = filtered_scenario

    return filtered_scenarios


def _filter_scenario(
    *,
    scenario_name: str,
    scenario: Scenario,
    filtered_groups: dict[str, TestCaseGroup],
    scenario_filter: set[str],
    phase_filter: set[str],
) -> Scenario | None:
    """Filter one scenario and return it when any phases remain."""
    if scenario_filter and scenario_name not in scenario_filter:
        return None

    kept_phases = {
        phase_name: filtered_phase
        for phase_name, phase in scenario.phases.items()
        if (
            filtered_phase := _filter_phase(
                phase_name=phase_name,
                phase=phase,
                filtered_groups=filtered_groups,
                phase_filter=phase_filter,
            )
        )
        is not None
    }
    if not kept_phases:
        return None

    return replace(scenario, phases=kept_phases)


def _filter_phase(
    *,
    phase_name: str,
    phase: Phase,
    filtered_groups: dict[str, TestCaseGroup],
    phase_filter: set[str],
) -> Phase | None:
    """Filter one phase and return it when any groups remain."""
    if phase_filter and phase_name not in phase_filter:
        return None

    kept_groups = [
        group_name
        for group_name in phase.test_case_groups
        if group_name in filtered_groups
    ]
    if not kept_groups:
        return None

    return replace(phase, test_case_groups=kept_groups)


def _select_test_contexts(
    scenarios: dict[str, Scenario],
    groups: dict[str, TestCaseGroup],
    test_contexts: list[tuple[str, str, str]],
) -> tuple[dict[str, Scenario], dict[str, TestCaseGroup]]:
    """Keep only tests whose exact (scenario, phase, test_id) is selected.

    Groups are shared across phases, but a phase may need a different subset of a
    group's tests. Each distinct subset becomes its own entry in the returned
    group mapping: the first subset keeps the original key, later ones get a
    synthetic key. The group ``identifier`` is never changed, so results and
    reports still show the original group ID.
    """
    selected: dict[tuple[str, str], set[str]] = {}
    for scenario_name, phase_name, test_id in test_contexts:
        selected.setdefault((scenario_name, phase_name), set()).add(test_id)

    variants = _GroupVariants(groups)
    kept_scenarios: dict[str, Scenario] = {}
    for scenario_name, scenario in scenarios.items():
        kept_phases: dict[str, Phase] = {}
        for phase_name, phase in scenario.phases.items():
            test_ids = selected.get((scenario_name, phase_name), set())
            kept_groups = [
                key
                for group_name in phase.test_case_groups
                if (key := variants.key_for(group_name, test_ids)) is not None
            ]
            if kept_groups:
                kept_phases[phase_name] = replace(phase, test_case_groups=kept_groups)
        if kept_phases:
            kept_scenarios[scenario_name] = replace(scenario, phases=kept_phases)
    return kept_scenarios, variants.groups


class _GroupVariants:
    """Track per-phase subsets of shared groups under distinct mapping keys."""

    def __init__(self, source_groups: dict[str, TestCaseGroup]) -> None:
        self._source_groups = source_groups
        self._keys: dict[tuple[str, tuple[str, ...]], str] = {}
        self.groups: dict[str, TestCaseGroup] = {}

    def key_for(self, group_name: str, test_ids: set[str]) -> str | None:
        """Return the mapping key for a group narrowed to ``test_ids``."""
        source = self._source_groups[group_name]
        tests = tuple(test_id for test_id in source.tests if test_id in test_ids)
        if not tests:
            return None
        key = self._keys.get((group_name, tests))
        if key is None:
            key = self._unused_key(group_name)
            self._keys[(group_name, tests)] = key
            self.groups[key] = replace(source, tests=list(tests))
        return key

    def _unused_key(self, group_name: str) -> str:
        """Return ``group_name`` if free, else a synthetic key not already taken."""
        key = group_name
        suffix = 1
        while key in self.groups or (key != group_name and key in self._source_groups):
            key = f"{group_name}#{suffix}"
            suffix += 1
        return key


def _normalize_phase_dependencies(scenarios: dict[str, Scenario]) -> None:
    """Remove phase dependencies that no longer exist after filtering."""
    for scenario in scenarios.values():
        existing = set(scenario.phases.keys())
        for phase in scenario.phases.values():
            phase.depends_on = [
                dependency for dependency in phase.depends_on if dependency in existing
            ]

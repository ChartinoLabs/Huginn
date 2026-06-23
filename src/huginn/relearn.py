"""Parse failed test IDs from a testing run for selective re-learning."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

_FAILURE_STATUSES = frozenset({"failed", "errored"})


class RelearnError(ValueError):
    """Raised when relearn parsing cannot proceed."""


@dataclass(frozen=True)
class RelearnInput:
    """Parsed failure data for re-learning."""

    test_ids: list[str]
    scenario_ids: list[str]
    phase_ids: list[str]


def parse_failed_test_ids(
    run_json_path: Path,
    phase_filter: str | None = None,
    scenario_filter: str | None = None,
) -> RelearnInput:
    """Extract unique failed/errored test IDs from a testing run's run.json.

    Returns a RelearnInput containing deduplicated test IDs, affected scenario
    IDs, and affected phase IDs — all in the order they were first encountered.
    Optional scenario and phase filters narrow which results are considered.
    """
    raw = json.loads(run_json_path.read_text(encoding="utf-8"))
    scenarios = raw.get("scenarios", [])

    seen_tests: set[str] = set()
    seen_scenarios: set[str] = set()
    seen_phases: set[str] = set()
    failed_ids: list[str] = []
    scenario_ids: list[str] = []
    phase_ids: list[str] = []

    for scenario in scenarios:
        scenario_id = cast(str, scenario["id"])
        if scenario_filter is not None and scenario_id != scenario_filter:
            continue

        for phase in scenario.get("phases", []):
            phase_id = cast(str, phase["id"])
            if phase_filter is not None and phase_id != phase_filter:
                continue

            _collect_failures_from_phase(
                phase,
                scenario_id,
                phase_id,
                seen_tests,
                seen_scenarios,
                seen_phases,
                failed_ids,
                scenario_ids,
                phase_ids,
            )

    return RelearnInput(
        test_ids=failed_ids,
        scenario_ids=scenario_ids,
        phase_ids=phase_ids,
    )


def _collect_failures_from_phase(
    phase: dict[str, object],
    scenario_id: str,
    phase_id: str,
    seen_tests: set[str],
    seen_scenarios: set[str],
    seen_phases: set[str],
    failed_ids: list[str],
    scenario_ids: list[str],
    phase_ids: list[str],
) -> None:
    """Extract failures from a single phase's test case groups."""
    for group in cast(list[dict[str, object]], phase.get("test_case_groups", [])):
        for test_case in cast(list[dict[str, object]], group.get("test_cases", [])):
            test_id = cast(str, test_case["test_id"])
            if test_case["status"] not in _FAILURE_STATUSES:
                continue
            if test_id not in seen_tests:
                seen_tests.add(test_id)
                failed_ids.append(test_id)
            if scenario_id not in seen_scenarios:
                seen_scenarios.add(scenario_id)
                scenario_ids.append(scenario_id)
            if phase_id not in seen_phases:
                seen_phases.add(phase_id)
                phase_ids.append(phase_id)

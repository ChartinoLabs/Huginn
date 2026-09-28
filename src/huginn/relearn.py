"""Parse failed test IDs from a testing run for selective re-learning."""

import json
from dataclasses import dataclass, field
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
    # Exact (scenario, phase, test_id) contexts in which a test failed.
    contexts: list[tuple[str, str, str]] = field(default_factory=list)


def parse_failed_test_ids(
    run_json_path: Path,
    phase_filter: str | None = None,
    scenario_filter: str | None = None,
) -> RelearnInput:
    """Extract unique failed/errored test IDs from a testing run's run.json.

    Returns a RelearnInput containing the exact (scenario, phase, test_id)
    contexts that failed, plus the deduplicated test IDs, affected scenario IDs,
    and affected phase IDs -- all in the order they were first encountered.
    Optional scenario and phase filters narrow which results are considered.
    """
    raw = json.loads(run_json_path.read_text(encoding="utf-8"))
    contexts: dict[tuple[str, str, str], None] = {}

    for scenario in raw.get("scenarios", []):
        scenario_id = cast(str, scenario["id"])
        if scenario_filter is not None and scenario_id != scenario_filter:
            continue

        for phase in scenario.get("phases", []):
            for context in _failed_contexts_in_phase(phase, scenario_id, phase_filter):
                contexts.setdefault(context)

    return RelearnInput(
        test_ids=list(dict.fromkeys(test_id for _, _, test_id in contexts)),
        scenario_ids=list(dict.fromkeys(scenario_id for scenario_id, _, _ in contexts)),
        phase_ids=list(dict.fromkeys(phase_id for _, phase_id, _ in contexts)),
        contexts=list(contexts),
    )


def _failed_contexts_in_phase(
    phase: dict[str, object],
    scenario_id: str,
    phase_filter: str | None,
) -> list[tuple[str, str, str]]:
    """Return failed/errored (scenario, phase, test_id) contexts from one phase."""
    phase_id = cast(str, phase["id"])
    if phase_filter is not None and phase_id != phase_filter:
        return []
    return [
        (scenario_id, phase_id, cast(str, test_case["test_id"]))
        for group in cast(list[dict[str, object]], phase.get("test_case_groups", []))
        for test_case in cast(list[dict[str, object]], group.get("test_cases", []))
        if test_case["status"] in _FAILURE_STATUSES
    ]

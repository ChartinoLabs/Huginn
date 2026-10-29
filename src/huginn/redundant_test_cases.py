"""Detect test cases that are copies of each other."""

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict
from pathlib import Path

from huginn.models import TestCaseDefinition, TestPlan
from huginn.parameters import ParameterStoreError, load_test_case_parameters

REDUNDANT_TEST_CASE_WARNING_CODE = "redundant_test_case"


def find_redundant_test_cases(
    *,
    test_plan: TestPlan,
    targets_by_test_id: Mapping[str, Iterable[Sequence[str]]],
    parameters_dir: Path,
) -> list[list[str]]:
    """Return groups of test IDs that always produce the same result.

    Two test cases are copies when they share a job, test-level target,
    metadata and automation flag, resolve to the same devices everywhere the
    plan references them, and have the same learned parameters or none. Either
    one can then replace the other without changing any result.

    Learned parameters are compared because they are the only per-test-ID
    state. ``huginn reconcile`` deliberately creates test cases that differ
    from their originals only in learned parameters, so that a post-change
    phase can expect a different state, and those are not copies.

    ``targets_by_test_id`` maps each referenced test ID to the device names it
    resolves to at each reference. A test ID whose parameter file cannot be
    read is left out, since execution reports that error itself.
    """
    test_ids_by_key: dict[str, list[str]] = defaultdict(list)
    for test_id, targets in targets_by_test_id.items():
        key = _copy_key(
            case=test_plan.test_cases[test_id],
            targets=targets,
            parameters_dir=parameters_dir,
        )
        if key is not None:
            test_ids_by_key[key].append(test_id)
    return sorted(sorted(ids) for ids in test_ids_by_key.values() if len(ids) > 1)


def describe_redundant_test_cases(test_plan: TestPlan, test_ids: list[str]) -> str:
    """Build the warning message for one group of copied test cases."""
    job = test_plan.test_cases[test_ids[0]].job
    return (
        f"Test cases {', '.join(test_ids)} are copies: they run job {job} on the "
        "same devices with the same metadata and learned parameters, so they "
        "always produce the same result. Keep one and reference it from every "
        "phase or test case group that needs it."
    )


def _copy_key(
    *,
    case: TestCaseDefinition,
    targets: Iterable[Sequence[str]],
    parameters_dir: Path,
) -> str | None:
    """Serialize everything that decides a test case's result, or ``None``."""
    try:
        parameters = load_test_case_parameters(parameters_dir, case.test_id)
    except ParameterStoreError:
        return None
    return json.dumps(
        {
            "job": case.job,
            "target": asdict(case.target) if case.target is not None else None,
            "metadata": case.metadata,
            "is_automated": case.is_automated,
            "resolved_targets": sorted({tuple(sorted(names)) for names in targets}),
            "parameters": parameters,
        },
        sort_keys=True,
        default=str,
    )

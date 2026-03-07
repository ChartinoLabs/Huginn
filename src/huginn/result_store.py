"""Persist canonical Huginn results as JSON files."""

import json
import re
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from huginn.enums import ExecutionMode
from huginn.models import (
    ExecutedPhase,
    ExecutedTestCase,
    ExecutedTestCaseGroup,
    RunResult,
)

if TYPE_CHECKING:
    from huginn.validation import ValidationResult


class ResultWriteError(ValueError):
    """Raised when Huginn cannot persist canonical JSON results."""


def write_run_result(
    *,
    result: RunResult,
    results_dir: Path,
    mode: ExecutionMode | None = None,
) -> Path:
    """Write run JSON results under a timestamped results directory."""
    try:
        run_dir = _create_timestamped_run_dir(results_dir, mode=mode)
        test_case_paths = _write_test_case_results(result=result, run_dir=run_dir)
        payload = _build_run_summary_payload(
            result=result,
            test_case_paths=test_case_paths,
            mode=mode,
        )
        return _write_json(run_dir / "run.json", payload)
    except Exception as error:  # noqa: BLE001
        raise ResultWriteError(f"Failed to write run results: {error}") from error


def write_validation_result(*, result: "ValidationResult", results_dir: Path) -> Path:
    """Write validation JSON results under a timestamped results directory."""
    try:
        validate_dir = _create_timestamped_results_dir(results_dir, suffix="validate")
        return _write_json(validate_dir / "validate.json", asdict(result))
    except Exception as error:  # noqa: BLE001
        raise ResultWriteError(
            f"Failed to write validation results: {error}"
        ) from error


def _write_json(path: Path, payload: object) -> Path:
    """Write JSON payload to path, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _create_timestamped_run_dir(
    results_dir: Path,
    *,
    mode: ExecutionMode | None = None,
) -> Path:
    """Create a unique timestamped directory for one run."""
    suffix = mode.value if mode is not None else None
    return _create_timestamped_results_dir(results_dir, suffix=suffix)


def _create_timestamped_results_dir(
    results_dir: Path,
    *,
    suffix: str | None = None,
) -> Path:
    """Create a unique timestamped directory under results/."""
    base_name = datetime.now().strftime("%Y-%b-%d-%H-%M-%S")
    if suffix is not None:
        base_name = f"{base_name}-{suffix}"
    candidate = results_dir / base_name
    collision_suffix = 1

    while candidate.exists():
        candidate = results_dir / f"{base_name}-{collision_suffix:02d}"
        collision_suffix += 1

    candidate.mkdir(parents=True, exist_ok=False)
    return candidate


def _write_test_case_results(*, result: RunResult, run_dir: Path) -> dict[str, str]:
    """Write one JSON result file per executed test case."""
    written_paths: dict[str, str] = {}
    used_names: set[str] = set()

    for phase in result.phases:
        for group in phase.test_case_groups:
            for test_case in group.test_cases:
                directory_name = _unique_test_case_directory_name(
                    test_case.test_id,
                    used_names,
                )
                relative_path = Path("test-cases") / directory_name / "result.json"
                _write_json(run_dir / relative_path, asdict(test_case))
                written_paths[test_case.test_id] = relative_path.as_posix()

    return written_paths


def _unique_test_case_directory_name(test_id: str, used_names: set[str]) -> str:
    """Normalize a test case identifier into a unique directory name."""
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", test_id).strip(".-")
    candidate = normalized or "test-case"
    suffix = 1

    while candidate in used_names:
        candidate = f"{normalized or 'test-case'}-{suffix:02d}"
        suffix += 1

    used_names.add(candidate)
    return candidate


def _build_run_summary_payload(
    *,
    result: RunResult,
    test_case_paths: dict[str, str],
    mode: ExecutionMode | None,
) -> dict[str, Any]:
    """Build the compact top-level run payload."""
    payload: dict[str, Any] = {
        "summary": asdict(result.summary),
        "phases": [
            _build_phase_payload(phase, test_case_paths) for phase in result.phases
        ],
    }
    if mode is not None:
        payload["mode"] = mode.value
    return payload


def _build_phase_payload(
    phase: ExecutedPhase,
    test_case_paths: dict[str, str],
) -> dict[str, Any]:
    """Serialize one executed phase without inlining test details."""
    return {
        "name": phase.name,
        "status": phase.status,
        "test_case_groups": [
            _build_group_payload(group, test_case_paths)
            for group in phase.test_case_groups
        ],
    }


def _build_group_payload(
    group: ExecutedTestCaseGroup,
    test_case_paths: dict[str, str],
) -> dict[str, Any]:
    """Serialize one executed test case group without check payloads."""
    return {
        "name": group.name,
        "status": group.status,
        "test_cases": [
            _build_test_case_summary_payload(test_case, test_case_paths)
            for test_case in group.test_cases
        ],
    }


def _build_test_case_summary_payload(
    test_case: ExecutedTestCase,
    test_case_paths: dict[str, str],
) -> dict[str, Any]:
    """Serialize one executed test case summary with a pointer to full details."""
    payload: dict[str, Any] = {
        "test_id": test_case.test_id,
        "title": test_case.title,
        "status": test_case.status,
        "result_path": test_case_paths[test_case.test_id],
    }
    if test_case.error is not None:
        payload["error"] = test_case.error
    if test_case.error_code is not None:
        payload["error_code"] = test_case.error_code
    return payload

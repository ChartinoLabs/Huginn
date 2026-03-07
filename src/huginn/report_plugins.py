"""Report plugin interfaces and built-in plugin resolution."""

import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from huginn.enums import ExecutionMode
from huginn.models import (
    ExecutedPhase,
    ExecutedTestCase,
    ExecutedTestCaseGroup,
    RunReport,
)

if TYPE_CHECKING:
    from huginn.validation import ValidationReport


class ReportPluginError(ValueError):
    """Raised when a report plugin cannot be resolved or written."""


class ReportPlugin(Protocol):
    """Protocol for report plugins that persist run/validation artifacts."""

    @property
    def name(self) -> str:
        """Return plugin display name."""
        raise NotImplementedError

    def write_run_report(
        self,
        report: RunReport,
        results_dir: Path,
        *,
        mode: ExecutionMode | None = None,
    ) -> Path:
        """Persist a run report artifact and return its path."""
        raise NotImplementedError

    def write_validation_report(
        self,
        report: "ValidationReport",
        reports_dir: Path,
    ) -> Path:
        """Persist a validation report artifact and return its path."""
        raise NotImplementedError


@dataclass(frozen=True)
class JsonReportPlugin:
    """Built-in JSON report plugin for validation and run artifacts."""

    run_filename: str = "run.json"
    validation_filename: str = "validate.json"
    test_case_filename: str = "result.json"
    test_cases_directory: str = "test-cases"

    @property
    def name(self) -> str:
        """Return plugin identifier."""
        return "json"

    def write_run_report(
        self,
        report: RunReport,
        results_dir: Path,
        *,
        mode: ExecutionMode | None = None,
    ) -> Path:
        """Write run report JSON artifacts under a timestamped results directory."""
        run_dir = _create_timestamped_run_dir(results_dir, mode=mode)
        test_case_paths = _write_test_case_reports(
            report=report,
            run_dir=run_dir,
            test_cases_directory=self.test_cases_directory,
            test_case_filename=self.test_case_filename,
        )
        payload = _build_run_summary_payload(
            report=report,
            test_case_paths=test_case_paths,
            mode=mode,
        )
        return _write_json(run_dir / self.run_filename, payload)

    def write_validation_report(
        self,
        report: "ValidationReport",
        reports_dir: Path,
    ) -> Path:
        """Write validation report JSON artifact."""
        return _write_json(reports_dir / self.validation_filename, asdict(report))


def resolve_report_plugins(specs: list[str] | None) -> list[ReportPlugin]:
    """Resolve report plugin specs, defaulting to the built-in JSON plugin."""
    normalized_specs = _normalize_specs(specs)
    return [_parse_report_plugin_spec(spec) for spec in normalized_specs]


def write_run_reports(
    *,
    report: RunReport,
    results_dir: Path,
    plugins: Iterable[ReportPlugin],
    mode: ExecutionMode | None = None,
) -> list[Path]:
    """Write run report artifacts through configured plugins."""
    paths: list[Path] = []
    for plugin in plugins:
        try:
            paths.append(plugin.write_run_report(report, results_dir, mode=mode))
        except Exception as error:  # noqa: BLE001
            raise ReportPluginError(
                f"Report plugin '{plugin.name}' failed to write run report: {error}"
            ) from error
    return paths


def write_validation_reports(
    *,
    report: "ValidationReport",
    reports_dir: Path,
    plugins: Iterable[ReportPlugin],
) -> list[Path]:
    """Write validation report artifacts through configured plugins."""
    paths: list[Path] = []
    for plugin in plugins:
        try:
            paths.append(plugin.write_validation_report(report, reports_dir))
        except Exception as error:  # noqa: BLE001
            raise ReportPluginError(
                "Report plugin "
                f"'{plugin.name}' failed to write validation report: {error}"
            ) from error
    return paths


def _normalize_specs(specs: list[str] | None) -> list[str]:
    """Normalize plugin spec list and apply default plugin."""
    if not specs:
        return ["json"]

    normalized: list[str] = []
    seen: set[str] = set()
    for spec in specs:
        candidate = spec.strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)
    if not normalized:
        return ["json"]
    return normalized


def _parse_report_plugin_spec(spec: str) -> ReportPlugin:
    """Parse one report plugin spec string into a plugin instance."""
    if ":" in spec:
        raise ReportPluginError(
            "Report plugins currently support built-in names only. Use 'json'."
        )
    if spec == "json":
        return JsonReportPlugin()
    raise ReportPluginError(f"Unsupported report plugin '{spec}'. Supported: json")


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
    base_name = datetime.now().strftime("%Y-%b-%d-%H-%M-%S")
    if mode is not None:
        base_name = f"{base_name}-{mode.value}"
    candidate = results_dir / base_name
    suffix = 1

    while candidate.exists():
        candidate = results_dir / f"{base_name}-{suffix:02d}"
        suffix += 1

    candidate.mkdir(parents=True, exist_ok=False)
    return candidate


def _write_test_case_reports(
    *,
    report: RunReport,
    run_dir: Path,
    test_cases_directory: str,
    test_case_filename: str,
) -> dict[str, str]:
    """Write one JSON artifact per executed test case."""
    written_paths: dict[str, str] = {}
    used_names: set[str] = set()

    for phase in report.phases:
        for group in phase.test_case_groups:
            for test_case in group.test_cases:
                directory_name = _unique_test_case_directory_name(
                    test_case.test_id,
                    used_names,
                )
                relative_path = (
                    Path(test_cases_directory) / directory_name / test_case_filename
                )
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
    report: RunReport,
    test_case_paths: dict[str, str],
    mode: ExecutionMode | None,
) -> dict[str, Any]:
    """Build the compact top-level run payload."""
    payload: dict[str, Any] = {
        "summary": asdict(report.summary),
        "phases": [
            _build_phase_payload(phase, test_case_paths) for phase in report.phases
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

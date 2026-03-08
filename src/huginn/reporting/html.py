"""Built-in standard HTML reporting for Huginn run results."""

import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from jinja2 import Environment, Template
from markdown import markdown

from huginn.models import (
    ExecutedPhase,
    ExecutedTestCase,
    ExecutedTestCaseGroup,
    RunResult,
)
from huginn.result_store import _test_case_execution_key

_TEMPLATE_ENV = Environment(autoescape=True, trim_blocks=True, lstrip_blocks=True)
_RESOURCE_ROOT = files("huginn.reporting")


class ReportRenderError(ValueError):
    """Raised when the HTML report renderer cannot write report files."""


@dataclass(frozen=True)
class _TestCaseLocation:
    scenario_name: str
    phase_name: str
    group_name: str
    test_case: ExecutedTestCase


def write_standard_html_report(
    *,
    result: RunResult,
    reports_dir: Path,
    results_run_dir: Path,
    test_case_result_paths: dict[str, str],
) -> Path:
    """Write the built-in standard HTML report for one run."""
    report_dir = reports_dir / results_run_dir.name / "html"
    details_dir = report_dir / "test-cases"
    try:
        details_dir.mkdir(parents=True, exist_ok=True)
        _write_stylesheet(report_dir)

        detail_paths = _build_detail_paths(test_case_result_paths)
        locations = _collect_test_case_locations(result)

        for location in locations:
            detail_path = (
                report_dir / detail_paths[_test_case_execution_key(location.test_case)]
            )
            detail_path.parent.mkdir(parents=True, exist_ok=True)
            detail_path.write_text(
                _detail_template().render(
                    test_case=_build_test_case_view(location.test_case),
                    scenario_name=location.scenario_name,
                    phase_name=location.phase_name,
                    group_name=location.group_name,
                    metadata_sections=_build_metadata_views(location.test_case),
                    checks=_build_check_views(location.test_case),
                    commands=_build_command_views(location.test_case),
                ),
                encoding="utf-8",
            )

        dashboard_path = report_dir / "index.html"
        dashboard_path.write_text(
            _dashboard_template().render(
                stats=_build_dashboard_stats(result),
                scenarios=_build_scenario_views(result, detail_paths),
            ),
            encoding="utf-8",
        )
        _update_latest_symlink(reports_dir=reports_dir, report_dir=report_dir)
    except Exception as error:  # noqa: BLE001
        raise ReportRenderError(
            f"Failed to write standard HTML report: {error}"
        ) from error

    return dashboard_path


def _dashboard_template() -> Template:
    """Return the compiled dashboard HTML template."""
    return _TEMPLATE_ENV.from_string(_read_resource_text("templates/dashboard.html.j2"))


def _detail_template() -> Template:
    """Return the compiled test-case detail HTML template."""
    return _TEMPLATE_ENV.from_string(
        _read_resource_text("templates/test_case_detail.html.j2")
    )


def _write_stylesheet(report_dir: Path) -> None:
    """Write the shared stylesheet into the report output directory."""
    (report_dir / "styles.css").write_text(
        _read_resource_text("static/styles.css").strip() + "\n",
        encoding="utf-8",
    )


def _update_latest_symlink(*, reports_dir: Path, report_dir: Path) -> None:
    """Point reports/latest at the newest generated HTML report directory."""
    latest_path = reports_dir / "latest"
    if latest_path.is_symlink() or latest_path.is_file():
        latest_path.unlink()
    elif latest_path.exists():
        raise ReportRenderError(
            f"Cannot update latest report symlink because {latest_path} already exists"
        )

    latest_path.symlink_to(
        report_dir.relative_to(reports_dir),
        target_is_directory=True,
    )


def _read_resource_text(relative_path: str) -> str:
    """Read one packaged reporting resource as UTF-8 text."""
    return _RESOURCE_ROOT.joinpath(relative_path).read_text(encoding="utf-8")


def _build_dashboard_stats(result: RunResult) -> list[dict[str, int | str]]:
    """Build high-level run statistics for the dashboard top hat."""
    return [
        {"label": "Scenarios", "value": len(result.scenarios)},
        {
            "label": "Phases",
            "value": sum(len(scenario.phases) for scenario in result.scenarios),
        },
        {"label": "Test Cases", "value": result.summary.total},
        {"label": "Passing", "value": result.summary.passed},
        {"label": "Failing", "value": result.summary.failed},
        {"label": "Errored", "value": result.summary.errored},
        {"label": "Skipped", "value": result.summary.skipped},
        {"label": "Not Applicable", "value": result.summary.not_applicable},
        {"label": "Blocked", "value": result.summary.blocked},
    ]


def _build_scenario_views(
    result: RunResult,
    detail_paths: dict[str, str],
) -> list[dict[str, object]]:
    """Build scenario-focused view models for the dashboard."""
    scenario_views: list[dict[str, object]] = []
    for scenario in result.scenarios:
        scenario_statuses = [
            test_case.status
            for phase in scenario.phases
            for group in phase.test_case_groups
            for test_case in group.test_cases
        ]
        counts = _count_statuses(scenario_statuses)
        scenario_views.append(
            {
                "id": scenario.identifier,
                "name": scenario.display_name,
                "status": scenario.status,
                "status_class": _status_class(scenario.status),
                "chips": [
                    f"phases {len(scenario.phases)}",
                    f"total {len(scenario_statuses)}",
                    f"pass {counts['passed']}",
                    f"fail {counts['failed']}",
                    f"skip {counts['skipped']}",
                ],
                "phases": [
                    _build_phase_view(phase, detail_paths) for phase in scenario.phases
                ],
            }
        )
    return scenario_views


def _build_phase_view(
    phase: ExecutedPhase,
    detail_paths: dict[str, str],
) -> dict[str, object]:
    """Build one phase view for the dashboard."""
    phase_statuses = [
        test_case.status
        for group in phase.test_case_groups
        for test_case in group.test_cases
    ]
    counts = _count_statuses(phase_statuses)
    return {
        "id": phase.identifier,
        "name": phase.display_name,
        "status": phase.status,
        "status_class": _status_class(phase.status),
        "chips": [
            f"total {len(phase_statuses)}",
            f"pass {counts['passed']}",
            f"fail {counts['failed']}",
            f"skip {counts['skipped']}",
        ],
        "groups": [
            _build_group_view(group, detail_paths) for group in phase.test_case_groups
        ],
    }


def _build_group_view(
    group: ExecutedTestCaseGroup,
    detail_paths: dict[str, str],
) -> dict[str, object]:
    """Build one test-case-group view for the dashboard."""
    statuses = [test_case.status for test_case in group.test_cases]
    counts = _count_statuses(statuses)
    return {
        "id": group.identifier,
        "name": group.display_name,
        "status": group.status,
        "status_class": _status_class(group.status),
        "chips": [
            f"total {len(group.test_cases)}",
            f"pass {counts['passed']}",
            f"fail {counts['failed']}",
            f"skip {counts['skipped']}",
        ],
        "test_cases": [
            {
                **_build_test_case_view(test_case),
                "details_href": detail_paths[_test_case_execution_key(test_case)],
            }
            for test_case in group.test_cases
        ],
    }


def _collect_test_case_locations(result: RunResult) -> list[_TestCaseLocation]:
    """Collect phase and group location data for each test case."""
    return [
        _TestCaseLocation(
            scenario_name=scenario.display_name,
            phase_name=phase.display_name,
            group_name=group.display_name,
            test_case=test_case,
        )
        for scenario in result.scenarios
        for phase in scenario.phases
        for group in phase.test_case_groups
        for test_case in group.test_cases
    ]


def _build_test_case_view(test_case: ExecutedTestCase) -> dict[str, object]:
    """Build the shared view model for one test case."""
    return {
        "test_id": test_case.test_id,
        "title": test_case.title,
        "status": test_case.status,
        "status_class": _status_class(test_case.status),
        "command_count": len(test_case.command_executions),
        "check_count": len(test_case.checks),
        "metadata_count": len(test_case.metadata_sections),
        "commands": [
            {"device": command.device, "command": command.command}
            for command in test_case.command_executions
        ],
        "error": test_case.error,
        "error_code": test_case.error_code,
        "error_traceback": test_case.error_traceback,
    }


def _build_check_views(test_case: ExecutedTestCase) -> list[dict[str, str]]:
    """Build rendered check views for one test case."""
    return [
        {
            "status": check.status,
            "status_class": _status_class(check.status),
            "message": check.message,
        }
        for check in test_case.checks
    ]


def _build_metadata_views(test_case: ExecutedTestCase) -> list[dict[str, str]]:
    """Build rendered metadata views for one test case."""
    return [
        {
            "heading": section.heading,
            "content_html": _render_markdown(section.content),
        }
        for section in test_case.metadata_sections
    ]


def _build_command_views(test_case: ExecutedTestCase) -> list[dict[str, object]]:
    """Build rendered command views for one test case."""
    return [
        {
            "device": command.device,
            "command": command.command,
            "output": command.output,
            "parsed_pretty": _format_parsed_payload(command.parsed),
            "elapsed_ms": _format_elapsed_ms(command.elapsed_ms),
            "cached": command.cached,
        }
        for command in test_case.command_executions
    ]


def _build_detail_paths(test_case_result_paths: dict[str, str]) -> dict[str, str]:
    """Translate canonical JSON result paths into HTML detail page paths."""
    paths: dict[str, str] = {}
    for execution_key, result_path in test_case_result_paths.items():
        path_parts = Path(result_path).parts
        if len(path_parts) < 3:
            raise ReportRenderError(
                f"Unexpected test case result path layout: {result_path}"
            )
        paths[execution_key] = f"test-cases/{path_parts[1]}.html"
    return paths


def _count_statuses(statuses: list[str]) -> dict[str, int]:
    """Count status values for dashboard chips."""
    counts = {"passed": 0, "failed": 0, "skipped": 0}
    for status in statuses:
        if status == "passed":
            counts["passed"] += 1
        elif status in {"failed", "errored", "blocked"}:
            counts["failed"] += 1
        elif status in {"skipped", "not_applicable"}:
            counts["skipped"] += 1
    return counts


def _format_parsed_payload(payload: dict[str, object] | None) -> str | None:
    """Render structured parsed command output for HTML display."""
    if payload is None:
        return None
    return json.dumps(payload, indent=2, sort_keys=True)


def _format_elapsed_ms(elapsed_ms: float | None) -> str | None:
    """Format command execution timing for display."""
    if elapsed_ms is None:
        return None
    return f"{elapsed_ms:.2f}"


def _render_markdown(text: str) -> str:
    """Render report markdown into safe HTML fragments."""
    return markdown(
        text,
        extensions=["extra", "fenced_code", "tables", "nl2br"],
    )


def _status_class(status: str) -> str:
    """Return a CSS-safe status class name."""
    return status.replace("-", "_")

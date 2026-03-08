"""Built-in standard HTML reporting for Huginn run results."""

# ruff: noqa: E501

import json
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment

from huginn.models import ExecutedTestCase, RunResult

_TEMPLATE_ENV = Environment(autoescape=True, trim_blocks=True, lstrip_blocks=True)

_STYLESHEET = """
:root {
  --ink: #1c1b1a;
  --muted: #6f665d;
  --line: #d9d0c7;
  --surface: #fffaf4;
  --surface-strong: #f2e7db;
  --accent: #1e6b52;
  --accent-soft: #d9efe5;
  --pass: #1f7a4d;
  --fail: #b2412d;
  --error: #8b2d2d;
  --skip: #8a6a1f;
  --na: #5d5a96;
  --blocked: #5f4c86;
  --shadow: 0 12px 32px rgba(50, 38, 25, 0.12);
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: Georgia, "Iowan Old Style", "Palatino Linotype", serif;
  color: var(--ink);
  background:
    radial-gradient(circle at top right, rgba(223, 190, 143, 0.35), transparent 32%),
    linear-gradient(180deg, #f8efe6 0%, #f5f0ea 40%, #f8f5f1 100%);
}
a { color: var(--accent); }
.shell { width: min(1180px, calc(100% - 32px)); margin: 0 auto; padding: 24px 0 48px; }
.hero {
  padding: 28px;
  border-radius: 24px;
  background: linear-gradient(135deg, rgba(255,250,244,0.92), rgba(242,231,219,0.9));
  border: 1px solid rgba(146, 116, 84, 0.2);
  box-shadow: var(--shadow);
}
.eyebrow { margin: 0 0 8px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.12em; font-size: 12px; }
h1, h2, h3 { margin: 0; font-weight: 600; }
h1 { font-size: clamp(32px, 5vw, 52px); line-height: 1; }
.subtitle { margin: 10px 0 0; color: var(--muted); font-size: 17px; }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 14px; margin-top: 24px; }
.stat-card {
  padding: 16px 18px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.68);
  border: 1px solid rgba(146, 116, 84, 0.16);
}
.stat-label { display: block; color: var(--muted); font-size: 13px; text-transform: uppercase; letter-spacing: 0.08em; }
.stat-value { display: block; margin-top: 8px; font-size: 30px; }
.phase-list { margin-top: 24px; display: grid; gap: 16px; }
.phase {
  border: 1px solid rgba(146, 116, 84, 0.18);
  border-radius: 20px;
  background: rgba(255, 252, 248, 0.9);
  box-shadow: var(--shadow);
  overflow: hidden;
}
.phase > summary {
  list-style: none;
  cursor: pointer;
  padding: 18px 22px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.phase > summary::-webkit-details-marker { display: none; }
.phase-summary-title { display: flex; align-items: center; gap: 12px; }
.phase-body { padding: 0 18px 18px; }
.chip-row, .test-meta { display: flex; flex-wrap: wrap; gap: 8px; }
.chip, .badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-radius: 999px;
  font-size: 12px;
  border: 1px solid transparent;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.chip { background: var(--surface-strong); color: var(--muted); }
.badge-pass { background: rgba(31,122,77,0.12); color: var(--pass); border-color: rgba(31,122,77,0.2); }
.badge-failed { background: rgba(178,65,45,0.12); color: var(--fail); border-color: rgba(178,65,45,0.2); }
.badge-errored { background: rgba(139,45,45,0.12); color: var(--error); border-color: rgba(139,45,45,0.2); }
.badge-skipped { background: rgba(138,106,31,0.14); color: var(--skip); border-color: rgba(138,106,31,0.22); }
.badge-not_applicable { background: rgba(93,90,150,0.12); color: var(--na); border-color: rgba(93,90,150,0.2); }
.badge-blocked { background: rgba(95,76,134,0.12); color: var(--blocked); border-color: rgba(95,76,134,0.2); }
.test-card {
  margin-top: 14px;
  padding: 18px;
  border-radius: 18px;
  background: white;
  border: 1px solid rgba(146, 116, 84, 0.16);
}
.test-card-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
}
.test-title { font-size: 22px; }
.test-id { margin-top: 5px; color: var(--muted); font-size: 14px; }
.command-list { margin: 14px 0 0; padding-left: 18px; }
.command-list li { margin-top: 5px; }
.section-grid { display: grid; gap: 16px; margin-top: 24px; }
.panel {
  padding: 18px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.82);
  border: 1px solid rgba(146, 116, 84, 0.16);
}
.results-list { display: grid; gap: 12px; }
.result-item, .command-card {
  padding: 14px 16px;
  border: 1px solid rgba(146, 116, 84, 0.16);
  border-radius: 16px;
  background: white;
}
.result-item p, .metadata-block p { margin: 10px 0 0; white-space: pre-wrap; }
.metadata-list, .command-stack { display: grid; gap: 12px; }
.metadata-block { padding: 14px 16px; border-radius: 16px; background: white; border: 1px solid rgba(146, 116, 84, 0.16); }
pre {
  margin: 12px 0 0;
  padding: 14px;
  overflow-x: auto;
  background: #201d1b;
  color: #f8f5f1;
  border-radius: 14px;
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
  font-size: 13px;
  line-height: 1.5;
}
.back-link { display: inline-block; margin-top: 18px; }
@media (max-width: 700px) {
  .shell { width: min(100% - 20px, 1180px); }
  .hero { padding: 20px; border-radius: 20px; }
  .phase > summary, .test-card-header { display: block; }
  .test-card-header .badge { margin-top: 12px; }
}
"""

_DASHBOARD_TEMPLATE = _TEMPLATE_ENV.from_string(
    """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Huginn Test Report</title>
    <link rel="stylesheet" href="styles.css">
  </head>
  <body>
    <main class="shell">
      <section class="hero">
        <p class="eyebrow">Huginn Standard HTML Report</p>
        <h1>Run Dashboard</h1>
        <p class="subtitle">A user-facing summary of the canonical JSON results for this run.</p>
        <div class="stats">
          {% for stat in stats %}
          <article class="stat-card">
            <span class="stat-label">{{ stat.label }}</span>
            <span class="stat-value">{{ stat.value }}</span>
          </article>
          {% endfor %}
        </div>
      </section>

      <section class="phase-list">
        {% for phase in phases %}
        <details class="phase" {% if loop.first %}open{% endif %}>
          <summary>
            <div class="phase-summary-title">
              <h2>{{ phase.name }}</h2>
              <span class="badge badge-{{ phase.status_class }}">{{ phase.status }}</span>
            </div>
            <div class="chip-row">
              {% for chip in phase.chips %}
              <span class="chip">{{ chip }}</span>
              {% endfor %}
            </div>
          </summary>
          <div class="phase-body">
            {% for test_case in phase.test_cases %}
            <article class="test-card">
              <div class="test-card-header">
                <div>
                  <h3 class="test-title">{{ test_case.title }}</h3>
                  <div class="test-id">{{ test_case.test_id }}{% if test_case.group_name %} - {{ test_case.group_name }}{% endif %}</div>
                </div>
                <span class="badge badge-{{ test_case.status_class }}">{{ test_case.status }}</span>
              </div>
              <div class="test-meta">
                <span class="chip">{{ test_case.command_count }} command{% if test_case.command_count != 1 %}s{% endif %}</span>
                <span class="chip">{{ test_case.check_count }} result{% if test_case.check_count != 1 %}s{% endif %}</span>
              </div>
              {% if test_case.commands %}
              <ul class="command-list">
                {% for command in test_case.commands %}
                <li><strong>{{ command.device }}</strong>: <code>{{ command.command }}</code></li>
                {% endfor %}
              </ul>
              {% else %}
              <p class="subtitle">No command executions were recorded for this test case.</p>
              {% endif %}
              <p><a href="{{ test_case.details_href }}">View Details</a></p>
            </article>
            {% endfor %}
          </div>
        </details>
        {% endfor %}
      </section>
    </main>
  </body>
</html>
"""
)

_DETAIL_TEMPLATE = _TEMPLATE_ENV.from_string(
    """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{ test_case.title }} - Huginn Test Report</title>
    <link rel="stylesheet" href="../styles.css">
  </head>
  <body>
    <main class="shell">
      <section class="hero">
        <p class="eyebrow">Huginn Test Case Report</p>
        <h1>{{ test_case.title }}</h1>
        <p class="subtitle">{{ test_case.test_id }} - {{ phase_name }}{% if group_name %} - {{ group_name }}{% endif %}</p>
        <div class="chip-row" style="margin-top: 18px;">
          <span class="badge badge-{{ test_case.status_class }}">{{ test_case.status }}</span>
          <span class="chip">{{ test_case.command_count }} command{% if test_case.command_count != 1 %}s{% endif %}</span>
          <span class="chip">{{ test_case.check_count }} result{% if test_case.check_count != 1 %}s{% endif %}</span>
          <span class="chip">{{ test_case.metadata_count }} metadata section{% if test_case.metadata_count != 1 %}s{% endif %}</span>
        </div>
        <a class="back-link" href="../index.html">Back to dashboard</a>
      </section>

      <section class="section-grid">
        <article class="panel">
          <h2>Metadata</h2>
          {% if metadata_sections %}
          <div class="metadata-list">
            {% for section in metadata_sections %}
            <section class="metadata-block">
              <h3>{{ section.heading }}</h3>
              <p>{{ section.content }}</p>
            </section>
            {% endfor %}
          </div>
          {% else %}
          <p class="subtitle">This test case did not emit structured metadata.</p>
          {% endif %}
        </article>

        <article class="panel">
          <h2>Results</h2>
          {% if checks %}
          <div class="results-list">
            {% for check in checks %}
            <section class="result-item">
              <span class="badge badge-{{ check.status_class }}">{{ check.status }}</span>
              <p>{{ check.message }}</p>
            </section>
            {% endfor %}
          </div>
          {% else %}
          <p class="subtitle">No check results were recorded.</p>
          {% endif %}
        </article>

        <article class="panel">
          <h2>Command Executions</h2>
          {% if commands %}
          <div class="command-stack">
            {% for command in commands %}
            <section class="command-card">
              <div class="test-meta">
                <span class="chip">Device: {{ command.device }}</span>
                <span class="chip">Command: {{ command.command }}</span>
                {% if command.elapsed_ms is not none %}<span class="chip">{{ command.elapsed_ms }} ms</span>{% endif %}
                {% if command.cached is not none %}<span class="chip">Cached: {{ command.cached }}</span>{% endif %}
              </div>
              <h3 style="margin-top: 14px;">Raw Output</h3>
              <pre>{{ command.output }}</pre>
              <h3 style="margin-top: 14px;">Parsed Output</h3>
              {% if command.parsed_pretty %}
              <pre>{{ command.parsed_pretty }}</pre>
              {% else %}
              <p class="subtitle">No structured parsed output was recorded.</p>
              {% endif %}
            </section>
            {% endfor %}
          </div>
          {% else %}
          <p class="subtitle">No command executions were recorded for this test case.</p>
          {% endif %}
        </article>

        {% if test_case.error %}
        <article class="panel">
          <h2>Error Details</h2>
          <section class="result-item">
            <span class="badge badge-{{ test_case.status_class }}">{{ test_case.status }}</span>
            <p>{{ test_case.error }}</p>
            {% if test_case.error_code %}<p><strong>Error Code:</strong> {{ test_case.error_code }}</p>{% endif %}
            {% if test_case.error_traceback %}<pre>{{ test_case.error_traceback }}</pre>{% endif %}
          </section>
        </article>
        {% endif %}
      </section>
    </main>
  </body>
</html>
"""
)


class ReportRenderError(ValueError):
    """Raised when the HTML report renderer cannot write report files."""


@dataclass(frozen=True)
class _TestCaseLocation:
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
        (report_dir / "styles.css").write_text(_STYLESHEET.strip(), encoding="utf-8")

        detail_paths = _build_detail_paths(test_case_result_paths)
        locations = _collect_test_case_locations(result)

        for location in locations:
            detail_path = report_dir / detail_paths[location.test_case.test_id]
            detail_path.parent.mkdir(parents=True, exist_ok=True)
            detail_path.write_text(
                _DETAIL_TEMPLATE.render(
                    test_case=_build_test_case_view(location.test_case),
                    phase_name=location.phase_name,
                    group_name=location.group_name,
                    metadata_sections=location.test_case.metadata_sections,
                    checks=_build_check_views(location.test_case),
                    commands=_build_command_views(location.test_case),
                ),
                encoding="utf-8",
            )

        dashboard_path = report_dir / "index.html"
        dashboard_path.write_text(
            _DASHBOARD_TEMPLATE.render(
                stats=_build_dashboard_stats(result),
                phases=_build_phase_views(result, detail_paths),
            ),
            encoding="utf-8",
        )
    except Exception as error:  # noqa: BLE001
        raise ReportRenderError(
            f"Failed to write standard HTML report: {error}"
        ) from error

    return dashboard_path


def _build_dashboard_stats(result: RunResult) -> list[dict[str, int | str]]:
    """Build high-level run statistics for the dashboard top hat."""
    return [
        {"label": "Phases", "value": len(result.phases)},
        {"label": "Test Cases", "value": result.summary.total},
        {"label": "Passing", "value": result.summary.passed},
        {"label": "Failing", "value": result.summary.failed},
        {"label": "Errored", "value": result.summary.errored},
        {"label": "Skipped", "value": result.summary.skipped},
        {"label": "Not Applicable", "value": result.summary.not_applicable},
        {"label": "Blocked", "value": result.summary.blocked},
    ]


def _build_phase_views(
    result: RunResult,
    detail_paths: dict[str, str],
) -> list[dict[str, object]]:
    """Build phase-focused view models for the dashboard."""
    phase_views: list[dict[str, object]] = []
    for phase in result.phases:
        phase_statuses = [
            test_case.status
            for group in phase.test_case_groups
            for test_case in group.test_cases
        ]
        test_cases = [
            {
                **_build_test_case_view(test_case),
                "group_name": group.name,
                "details_href": detail_paths[test_case.test_id],
            }
            for group in phase.test_case_groups
            for test_case in group.test_cases
        ]
        counts = _count_statuses(phase_statuses)
        phase_views.append(
            {
                "name": phase.name,
                "status": phase.status,
                "status_class": _status_class(phase.status),
                "chips": [
                    f"total {len(test_cases)}",
                    f"pass {counts['passed']}",
                    f"fail {counts['failed']}",
                    f"skip {counts['skipped']}",
                ],
                "test_cases": test_cases,
            }
        )
    return phase_views


def _collect_test_case_locations(result: RunResult) -> list[_TestCaseLocation]:
    """Collect phase and group location data for each test case."""
    return [
        _TestCaseLocation(
            phase_name=phase.name,
            group_name=group.name,
            test_case=test_case,
        )
        for phase in result.phases
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


def _build_command_views(test_case: ExecutedTestCase) -> list[dict[str, object]]:
    """Build rendered command views for one test case."""
    return [
        {
            "device": command.device,
            "command": command.command,
            "output": command.output,
            "parsed_pretty": _format_parsed_payload(command.parsed),
            "elapsed_ms": command.elapsed_ms,
            "cached": command.cached,
        }
        for command in test_case.command_executions
    ]


def _build_detail_paths(test_case_result_paths: dict[str, str]) -> dict[str, str]:
    """Translate canonical JSON result paths into HTML detail page paths."""
    paths: dict[str, str] = {}
    for test_id, result_path in test_case_result_paths.items():
        path_parts = Path(result_path).parts
        if len(path_parts) < 3:
            raise ReportRenderError(
                f"Unexpected test case result path layout: {result_path}"
            )
        paths[test_id] = f"test-cases/{path_parts[1]}.html"
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


def _status_class(status: str) -> str:
    """Return a CSS-safe status class name."""
    return status.replace("-", "_")

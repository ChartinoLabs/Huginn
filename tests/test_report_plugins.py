"""Unit tests for report plugin resolution and JSON writing."""

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from huginn.models import RunSummary
from huginn.report_plugins import ReportPluginError, resolve_report_plugins
from huginn.validation import ValidationReport

if TYPE_CHECKING:
    from huginn.models import RunReport


def test_resolve_report_plugins_defaults_to_json() -> None:
    """No explicit specs resolves the built-in JSON report plugin."""
    plugins = resolve_report_plugins(None)

    assert len(plugins) == 1
    assert plugins[0].name == "json"


def test_resolve_report_plugins_rejects_unsupported_plugin() -> None:
    """Unsupported plugin names fail with ReportPluginError."""
    with pytest.raises(ReportPluginError, match="Unsupported report plugin"):
        resolve_report_plugins(["html"])


def test_json_report_plugin_writes_validate_report(tmp_path: Path) -> None:
    """Built-in JSON plugin writes validate.json artifact."""
    plugin = resolve_report_plugins(["json"])[0]
    report = ValidationReport(
        valid=True,
        phase_order=["phase-1"],
        required_brokers=["ssh"],
        test_cases=[],
        warnings=[],
        errors=[],
    )

    report_path = plugin.write_validation_report(report, tmp_path / "reports")

    assert report_path.name == "validate.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["valid"] is True


def test_json_report_plugin_writes_run_report(tmp_path: Path) -> None:
    """Built-in JSON plugin writes run.json artifact."""
    plugin = resolve_report_plugins(["json"])[0]
    report = _build_minimal_run_report()

    report_path = plugin.write_run_report(report, tmp_path / "reports")

    assert report_path.name == "run.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["summary"]["status"] == "passed"


def _build_minimal_run_report() -> "RunReport":
    """Build minimal run report object for plugin tests."""
    from huginn.models import RunReport

    return RunReport(
        summary=RunSummary(
            status="passed",
            total=0,
            passed=0,
            failed=0,
            errored=0,
            not_applicable=0,
            skipped=0,
            blocked=0,
        ),
        phases=[],
    )

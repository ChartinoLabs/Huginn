"""Unit tests for report plugin resolution and JSON writing."""

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from huginn.enums import ExecutionMode
from huginn.models import (
    CheckResult,
    ExecutedPhase,
    ExecutedTestCase,
    ExecutedTestCaseGroup,
    RunSummary,
)
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
    """Built-in JSON plugin writes timestamped run artifacts."""
    plugin = resolve_report_plugins(["json"])[0]
    report = _build_run_report_with_test_case()

    report_path = plugin.write_run_report(
        report,
        tmp_path / "results",
        mode=ExecutionMode.TESTING,
    )

    assert report_path.name == "run.json"
    assert report_path.parent.parent == tmp_path / "results"
    assert report_path.parent.name.endswith("-testing")
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["mode"] == "testing"
    assert payload["summary"]["status"] == "passed"
    test_case = payload["phases"][0]["test_case_groups"][0]["test_cases"][0]
    assert test_case["test_id"] == "test-1"
    assert test_case["result_path"] == "test-cases/test-1/result.json"
    assert "checks" not in test_case

    test_case_payload = json.loads(
        (report_path.parent / test_case["result_path"]).read_text(encoding="utf-8")
    )
    assert test_case_payload["checks"][0]["message"] == "all good"


def _build_run_report_with_test_case() -> "RunReport":
    """Build a run report that includes one executed test case."""
    from huginn.models import RunReport

    return RunReport(
        summary=RunSummary(
            status="passed",
            total=1,
            passed=1,
            failed=0,
            errored=0,
            not_applicable=0,
            skipped=0,
            blocked=0,
        ),
        phases=[
            ExecutedPhase(
                name="phase-1",
                status="passed",
                test_case_groups=[
                    ExecutedTestCaseGroup(
                        name="group-1",
                        status="passed",
                        test_cases=[
                            ExecutedTestCase(
                                test_id="test-1",
                                title="Test 1",
                                status="passed",
                                checks=[
                                    CheckResult(
                                        status="passed",
                                        message="all good",
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )
        ],
    )

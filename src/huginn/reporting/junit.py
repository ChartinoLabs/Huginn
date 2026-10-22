"""Built-in JUnit XML reporting for Huginn run results.

The report follows the Jenkins/Surefire JUnit schema. Each test case group in
each phase of each scenario becomes one ``<testsuite>``, and each test case
one ``<testcase>``. JUnit knows only pass, failure, error and skipped, so the
Huginn status a test case collapsed from is kept in the ``type`` attribute of
its ``<failure>`` or ``<skipped>`` element and in its ``<system-out>``.
"""

import logging
import re

# Only builds XML from Huginn's own results; nothing untrusted is parsed.
import xml.etree.ElementTree as ET  # nosec B405
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from huginn.enums import ResultStatus
from huginn.models import (
    CheckResult,
    ExecutedTestCase,
    ExecutedTestCaseGroup,
    RunResult,
)
from huginn.reporting.protocol import ReportRenderError

logger = logging.getLogger(__name__)

DEFAULT_REPORT_NAME = "junit.xml"
_CONFIG_KEYS = frozenset({"path"})
_FAILURE_STATUSES = frozenset(
    {ResultStatus.FAILED.value, ResultStatus.LOST_APPLICABILITY.value}
)
_SKIPPED_STATUSES = frozenset(
    {
        ResultStatus.SKIPPED.value,
        ResultStatus.NOT_APPLICABLE.value,
        ResultStatus.BLOCKED.value,
    }
)
# Characters XML 1.0 forbids, such as ANSI escapes in command output.
_INVALID_XML_CHARS = re.compile("[^\u0009\u000a\u000d -퟿-�\U00010000-\U0010ffff]")


@dataclass
class _Counts:
    """JUnit outcome counters for one suite or the whole run."""

    tests: int = 0
    failures: int = 0
    errors: int = 0
    skipped: int = 0

    def add(self, other: "_Counts") -> None:
        """Add another set of counters to this one."""
        self.tests += other.tests
        self.failures += other.failures
        self.errors += other.errors
        self.skipped += other.skipped


def write_junit_report(
    *,
    result: RunResult,
    output_path: Path,
) -> Path:
    """Write a JUnit XML report for one run to ``output_path``."""
    root = build_junit_tree(result)
    ET.indent(root)
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        ET.ElementTree(root).write(output_path, encoding="utf-8", xml_declaration=True)
    except OSError as error:
        raise ReportRenderError(
            f"Failed to write JUnit report to {output_path}: {error}"
        ) from error
    return output_path


def build_junit_tree(result: RunResult) -> ET.Element:
    """Build the ``<testsuites>`` element for one run."""
    root = ET.Element("testsuites", {"name": "huginn"})
    totals = _Counts()
    for scenario in result.scenarios:
        for phase in scenario.phases:
            for group in phase.test_case_groups:
                suite_name = (
                    f"{scenario.identifier}.{phase.identifier}.{group.identifier}"
                )
                suite, counts = _build_suite(suite_name, group, result.started_at)
                root.append(suite)
                totals.add(counts)
    _set_counts(root, totals, include_skipped=False)
    if result.elapsed_seconds is not None:
        root.set("time", _format_time(result.elapsed_seconds))
    return root


def _build_suite(
    name: str,
    group: ExecutedTestCaseGroup,
    timestamp: str | None,
) -> tuple[ET.Element, _Counts]:
    """Build one ``<testsuite>`` for a group within a scenario and phase."""
    suite = ET.Element("testsuite", {"name": _xml_text(name)})
    counts = _Counts()
    elapsed = 0.0
    for test_case in group.test_cases:
        suite.append(_build_test_case(name, test_case))
        counts.add(_count_test_case(test_case.status))
        elapsed += test_case.elapsed_seconds or 0.0
    _set_counts(suite, counts, include_skipped=True)
    suite.set("time", _format_time(elapsed))
    if timestamp is not None:
        suite.set("timestamp", timestamp)
    return suite, counts


def _build_test_case(classname: str, test_case: ExecutedTestCase) -> ET.Element:
    """Build one ``<testcase>`` with its outcome element and output."""
    element = ET.Element(
        "testcase",
        {"classname": _xml_text(classname), "name": _xml_text(test_case.test_id)},
    )
    if test_case.elapsed_seconds is not None:
        element.set("time", _format_time(test_case.elapsed_seconds))
    outcome = _build_outcome(test_case)
    if outcome is not None:
        element.append(outcome)
    ET.SubElement(element, "system-out").text = _xml_text(_system_out(test_case))
    return element


def _build_outcome(test_case: ExecutedTestCase) -> ET.Element | None:
    """Build the ``<failure>``, ``<error>`` or ``<skipped>`` element, if any."""
    status = test_case.status
    if status == ResultStatus.ERRORED.value:
        return _outcome_element(
            "error",
            type_=test_case.error_code or status,
            message=test_case.error or status,
            body=test_case.error_traceback or test_case.error,
        )
    if status in _FAILURE_STATUSES:
        failing = [check for check in test_case.checks if check.status == status]
        return _outcome_element(
            "failure",
            type_=status,
            message=failing[0].message if failing else status,
            body=_format_checks(failing, indent=""),
        )
    if status in _SKIPPED_STATUSES:
        return _outcome_element(
            "skipped",
            type_=_skipped_type(test_case),
            message=_skipped_message(test_case),
            body=None,
        )
    return None


def _outcome_element(
    tag: str,
    *,
    type_: str,
    message: str,
    body: str | None,
) -> ET.Element:
    """Build an outcome element with a type, a message and an optional body."""
    element = ET.Element(tag, {"type": _xml_text(type_), "message": _xml_text(message)})
    if body:
        element.text = _xml_text(body)
    return element


def _skipped_type(test_case: ExecutedTestCase) -> str:
    """Return the Huginn status and kind a skipped outcome collapsed from."""
    kind = test_case.skip_kind or test_case.block_kind
    return f"{test_case.status}:{kind}" if kind else test_case.status


def _skipped_message(test_case: ExecutedTestCase) -> str:
    """Return the reason a test case is reported as skipped."""
    if test_case.error:
        return test_case.error
    if test_case.not_applicable_devices:
        return "; ".join(
            f"{device}: {reason}"
            for device, reason in test_case.not_applicable_devices.items()
        )
    return test_case.status


def _system_out(test_case: ExecutedTestCase) -> str:
    """Return the readable details JUnit has no structured place for."""
    lines = [f"Title: {test_case.title}", f"Status: {test_case.status}"]
    if test_case.checks:
        lines.append("Checks:")
        lines.append(_format_checks(test_case.checks, indent="  "))
    if test_case.not_applicable_devices:
        lines.append("Not applicable devices:")
        lines.extend(
            f"  {device}: {reason}"
            for device, reason in test_case.not_applicable_devices.items()
        )
    return "\n".join(lines)


def _format_checks(checks: list[CheckResult], *, indent: str) -> str:
    """Format checks one per line with their status."""
    return "\n".join(f"{indent}[{check.status}] {check.message}" for check in checks)


def _count_test_case(status: str) -> _Counts:
    """Return the JUnit counters for one test case status."""
    return _Counts(
        tests=1,
        failures=int(status in _FAILURE_STATUSES),
        errors=int(status == ResultStatus.ERRORED.value),
        skipped=int(status in _SKIPPED_STATUSES),
    )


def _set_counts(element: ET.Element, counts: _Counts, *, include_skipped: bool) -> None:
    """Set the count attributes the schema allows on ``element``."""
    element.set("tests", str(counts.tests))
    element.set("failures", str(counts.failures))
    element.set("errors", str(counts.errors))
    if include_skipped:
        element.set("skipped", str(counts.skipped))


def _format_time(seconds: float) -> str:
    """Format seconds as the schema's time type, with millisecond precision."""
    return f"{max(seconds, 0.0):.3f}"


def _xml_text(value: str) -> str:
    """Remove characters that XML 1.0 cannot represent."""
    return _INVALID_XML_CHARS.sub("", value)


def _resolve_output_path(
    config: dict[str, Any],
    *,
    run_dir: Path,
    project_root: Path,
) -> Path:
    """Return the report path from ``config``, or the default in ``run_dir``."""
    unknown = sorted(set(config) - _CONFIG_KEYS)
    if unknown:
        logger.warning(
            "Ignoring unknown key(s) in [tool.huginn.plugins.config.junit]: %s",
            ", ".join(unknown),
        )
    path = config.get("path")
    if path is None:
        return run_dir / DEFAULT_REPORT_NAME
    if not isinstance(path, str) or not path:
        raise ReportRenderError(
            "[tool.huginn.plugins.config.junit] key 'path' must be a non-empty "
            f"string, got {path!r}."
        )
    output_path = Path(path)
    return output_path if output_path.is_absolute() else project_root / output_path


class JUnitReporterPlugin:
    """Built-in JUnit XML report renderer exposed as a ReporterPlugin."""

    @property
    def name(self) -> str:
        """Return the plugin identifier."""
        return "junit"

    async def generate_report(
        self,
        *,
        result: RunResult,
        run_dir: Path,
        reports_dir: Path,
        test_case_result_paths: dict[str, str],
        config: dict[str, Any],
    ) -> Path | None:
        """Write the JUnit XML report, by default to ``<run_dir>/junit.xml``.

        A relative ``path`` option is resolved against the project root, the
        directory that holds ``reports/``.
        """
        output_path = _resolve_output_path(
            config, run_dir=run_dir, project_root=reports_dir.parent
        )
        return write_junit_report(result=result, output_path=output_path)

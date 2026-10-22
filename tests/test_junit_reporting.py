"""Unit tests for JUnit XML reporting."""

import asyncio
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import xmlschema

from huginn.enums import BlockKind, ResultStatus, SkipKind
from huginn.models import (
    CheckResult,
    ExecutedPhase,
    ExecutedScenario,
    ExecutedTestCase,
    ExecutedTestCaseGroup,
    RunResult,
    RunSummary,
)
from huginn.reporting.junit import (
    JUnitReporterPlugin,
    build_junit_tree,
    write_junit_report,
)
from huginn.reporting.protocol import ReporterPlugin, ReportRenderError

JUNIT_XSD = Path(__file__).parent / "fixtures" / "junit" / "junit-10.xsd"


def test_plugin_satisfies_reporter_protocol() -> None:
    """The JUnit reporter is a ReporterPlugin named junit."""
    plugin = JUnitReporterPlugin()
    assert isinstance(plugin, ReporterPlugin)
    assert plugin.name == "junit"


def test_suites_are_one_per_scenario_phase_and_group() -> None:
    """Each group in each phase and scenario becomes one qualified testsuite."""
    result = _run_result(
        [
            _test_case("1.0.0", ResultStatus.PASSED, group="group-a"),
            _test_case("1.0.1", ResultStatus.PASSED, group="group-b"),
        ]
    )

    root = build_junit_tree(result)

    assert [suite.get("name") for suite in root.findall("testsuite")] == [
        "scenario-1.pre-change.group-a",
        "scenario-1.pre-change.group-b",
    ]
    case = root.find("testsuite/testcase")
    assert case is not None
    assert case.get("classname") == "scenario-1.pre-change.group-a"
    assert case.get("name") == "1.0.0"


@pytest.mark.parametrize(
    "status",
    [ResultStatus.PASSED, ResultStatus.INFO],
)
def test_passing_statuses_have_no_outcome_element(status: ResultStatus) -> None:
    """Passed and info test cases have no failure, error or skipped child."""
    case = _single_case(_test_case("1.0.0", status))

    assert _outcome_tags(case) == []


@pytest.mark.parametrize(
    "status",
    [ResultStatus.FAILED, ResultStatus.LOST_APPLICABILITY],
)
def test_failing_statuses_map_to_failure(status: ResultStatus) -> None:
    """Failed and lost-applicability test cases list their failing checks."""
    test_case = _test_case(
        "1.0.0",
        status,
        checks=[
            CheckResult(status=ResultStatus.PASSED.value, message="leaf-01: ok"),
            CheckResult(status=status.value, message="leaf-02: version drifted"),
        ],
    )

    failure = _only_outcome(_single_case(test_case), "failure")

    assert failure.get("type") == status.value
    assert failure.get("message") == "leaf-02: version drifted"
    assert failure.text == f"[{status.value}] leaf-02: version drifted"


def test_errored_maps_to_error_with_code_and_traceback() -> None:
    """Errored test cases carry the error code, message and traceback."""
    test_case = _test_case(
        "1.0.0",
        ResultStatus.ERRORED,
        error="boom",
        error_code="execution_error",
        error_traceback="Traceback (most recent call last):\nRuntimeError: boom",
    )

    error = _only_outcome(_single_case(test_case), "error")

    assert error.get("type") == "execution_error"
    assert error.get("message") == "boom"
    assert error.text == "Traceback (most recent call last):\nRuntimeError: boom"


@pytest.mark.parametrize(
    ("test_case", "expected_type", "expected_message"),
    [
        (
            ExecutedTestCase(
                scenario="scenario-1",
                phase="pre-change",
                group="group-a",
                test_id="1.0.0",
                title="Verify NTP",
                status=ResultStatus.SKIPPED.value,
                error="Skipped by change-window",
                skip_kind=SkipKind.HOOK.value,
            ),
            "skipped:hook",
            "Skipped by change-window",
        ),
        (
            ExecutedTestCase(
                scenario="scenario-1",
                phase="pre-change",
                group="group-a",
                test_id="1.0.0",
                title="Verify NTP",
                status=ResultStatus.BLOCKED.value,
                error="Blocked because phase 'change' failed",
                block_kind=BlockKind.DEPENDENCY_FAILED.value,
            ),
            "blocked:dependency_failed",
            "Blocked because phase 'change' failed",
        ),
        (
            ExecutedTestCase(
                scenario="scenario-1",
                phase="pre-change",
                group="group-a",
                test_id="1.0.0",
                title="Verify NTP",
                status=ResultStatus.NOT_APPLICABLE.value,
                not_applicable_devices={"leaf-01": "ntp not supported"},
            ),
            "not_applicable",
            "leaf-01: ntp not supported",
        ),
    ],
    ids=["skipped", "blocked", "not_applicable"],
)
def test_non_running_statuses_map_to_skipped(
    test_case: ExecutedTestCase,
    expected_type: str,
    expected_message: str,
) -> None:
    """Skipped, blocked and not-applicable keep their Huginn status in type."""
    skipped = _only_outcome(_single_case(test_case), "skipped")

    assert skipped.get("type") == expected_type
    assert skipped.get("message") == expected_message


def test_every_result_status_is_mapped() -> None:
    """Every ResultStatus value produces a deterministic JUnit outcome."""
    expected = {
        ResultStatus.PASSED: [],
        ResultStatus.INFO: [],
        ResultStatus.FAILED: ["failure"],
        ResultStatus.LOST_APPLICABILITY: ["failure"],
        ResultStatus.ERRORED: ["error"],
        ResultStatus.SKIPPED: ["skipped"],
        ResultStatus.NOT_APPLICABLE: ["skipped"],
        ResultStatus.BLOCKED: ["skipped"],
    }
    assert set(expected) == set(ResultStatus)

    for status, tags in expected.items():
        case = _single_case(_test_case("1.0.0", status))
        assert _outcome_tags(case) == tags, status


def test_counts_and_times_roll_up_to_suites_and_run() -> None:
    """Suite and run counters and times are totals of their test cases."""
    result = _run_result(
        [
            _test_case("1.0.0", ResultStatus.PASSED, elapsed_seconds=1.25),
            _test_case("1.0.1", ResultStatus.FAILED, elapsed_seconds=0.5),
            _test_case("1.0.2", ResultStatus.ERRORED),
            _test_case("1.0.3", ResultStatus.BLOCKED),
        ],
        elapsed_seconds=4.0,
    )

    root = build_junit_tree(result)
    suite = root.find("testsuite")
    assert suite is not None

    assert (suite.get("tests"), suite.get("failures"), suite.get("errors")) == (
        "4",
        "1",
        "1",
    )
    assert suite.get("skipped") == "1"
    assert suite.get("time") == "1.750"
    assert suite.get("timestamp") == "2026-10-22T09:00:00+00:00"
    assert (root.get("tests"), root.get("failures"), root.get("errors")) == (
        "4",
        "1",
        "1",
    )
    assert root.get("time") == "4.000"
    times = [case.get("time") for case in suite.findall("testcase")]
    assert times == ["1.250", "0.500", None, None]


def test_system_out_keeps_status_checks_and_not_applicable_devices() -> None:
    """system-out records what JUnit has no structured place for."""
    test_case = _test_case(
        "1.0.0",
        ResultStatus.PASSED,
        checks=[CheckResult(status=ResultStatus.PASSED.value, message="leaf-01: ok")],
        not_applicable_devices={"leaf-02": "ntp not supported"},
    )

    system_out = _single_case(test_case).find("system-out")

    assert system_out is not None
    assert system_out.text == (
        "Title: Verify 1.0.0\n"
        "Status: passed\n"
        "Checks:\n"
        "  [passed] leaf-01: ok\n"
        "Not applicable devices:\n"
        "  leaf-02: ntp not supported"
    )


def test_characters_invalid_in_xml_are_removed(tmp_path: Path) -> None:
    """Control characters such as ANSI escapes do not break the XML."""
    test_case = _test_case(
        "1.0.0",
        ResultStatus.ERRORED,
        error="\x1b[31mboom\x1b[0m",
        error_code="execution_error",
    )

    path = write_junit_report(
        result=_run_result([test_case]), output_path=tmp_path / "junit.xml"
    )

    error = ET.parse(path).getroot().find("testsuite/testcase/error")
    assert error is not None
    assert error.get("message") == "[31mboom[0m"


def test_report_validates_against_jenkins_junit_schema(tmp_path: Path) -> None:
    """A report with every status validates against the Jenkins JUnit XSD."""
    result = _run_result(
        [
            _test_case(f"1.0.{index}", status)
            for index, status in enumerate(ResultStatus)
        ]
    )

    path = write_junit_report(result=result, output_path=tmp_path / "junit.xml")

    _assert_valid(path)


def test_empty_run_validates_against_jenkins_junit_schema(tmp_path: Path) -> None:
    """A run with no test cases still writes a valid, empty report."""
    path = write_junit_report(
        result=_run_result([]), output_path=tmp_path / "junit.xml"
    )

    root = ET.parse(path).getroot()
    assert root.get("tests") == "0"
    _assert_valid(path)


def test_plugin_writes_junit_xml_in_run_dir_by_default(tmp_path: Path) -> None:
    """Without a path option, the report is results/<run>/junit.xml."""
    run_dir = tmp_path / "results" / "2026-Oct-22-09-00-00-testing"
    run_dir.mkdir(parents=True)

    path = _generate(tmp_path, run_dir, config={})

    assert path == run_dir / "junit.xml"
    assert path.is_file()


def test_plugin_resolves_relative_path_against_project_root(tmp_path: Path) -> None:
    """A relative path option is resolved against the project root."""
    run_dir = tmp_path / "results" / "2026-Oct-22-09-00-00-testing"

    path = _generate(tmp_path, run_dir, config={"path": "ci/junit/results.xml"})

    assert path == tmp_path / "ci" / "junit" / "results.xml"
    assert path.is_file()


def test_plugin_accepts_absolute_path(tmp_path: Path) -> None:
    """An absolute path option is used as is."""
    target = tmp_path / "elsewhere" / "huginn.xml"

    path = _generate(
        tmp_path, tmp_path / "results" / "run", config={"path": str(target)}
    )

    assert path == target
    assert path.is_file()


@pytest.mark.parametrize("value", ["", 42])
def test_plugin_rejects_invalid_path_option(tmp_path: Path, value: object) -> None:
    """A path option that is not a non-empty string fails the report."""
    with pytest.raises(ReportRenderError, match="key 'path' must be a non-empty"):
        _generate(tmp_path, tmp_path / "results" / "run", config={"path": value})


def test_plugin_warns_on_unknown_options(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unknown options are reported and otherwise ignored."""
    run_dir = tmp_path / "results" / "run"

    path = _generate(tmp_path, run_dir, config={"output": "junit.xml"})

    assert path == run_dir / "junit.xml"
    assert "Ignoring unknown key(s) in [tool.huginn.plugins.config.junit]: output" in (
        caplog.text
    )


def test_unwritable_output_raises_report_render_error(tmp_path: Path) -> None:
    """A path that cannot be written raises ReportRenderError."""
    blocker = tmp_path / "blocker"
    blocker.write_text("", encoding="utf-8")

    with pytest.raises(ReportRenderError, match="Failed to write JUnit report"):
        write_junit_report(result=_run_result([]), output_path=blocker / "junit.xml")


def _generate(tmp_path: Path, run_dir: Path, *, config: dict[str, object]) -> Path:
    """Run the plugin against a one-test result and return the report path."""
    path = asyncio.run(
        JUnitReporterPlugin().generate_report(
            result=_run_result([_test_case("1.0.0", ResultStatus.PASSED)]),
            run_dir=run_dir,
            reports_dir=tmp_path / "reports",
            test_case_result_paths={},
            config=config,
        )
    )
    assert path is not None
    return path


def _assert_valid(path: Path) -> None:
    """Assert that ``path`` validates against the Jenkins JUnit schema."""
    xmlschema.XMLSchema(JUNIT_XSD).validate(path)


def _single_case(test_case: ExecutedTestCase) -> ET.Element:
    """Return the testcase element built for one test case."""
    case = build_junit_tree(_run_result([test_case])).find("testsuite/testcase")
    assert case is not None
    return case


def _outcome_tags(case: ET.Element) -> list[str]:
    """Return the outcome child tags of a testcase element."""
    return [child.tag for child in case if child.tag in {"failure", "error", "skipped"}]


def _only_outcome(case: ET.Element, tag: str) -> ET.Element:
    """Return the single outcome element, asserting it is ``tag``."""
    assert _outcome_tags(case) == [tag]
    outcome = case.find(tag)
    assert outcome is not None
    return outcome


def _test_case(
    test_id: str,
    status: ResultStatus,
    *,
    group: str = "group-a",
    checks: list[CheckResult] | None = None,
    not_applicable_devices: dict[str, str] | None = None,
    error: str | None = None,
    error_code: str | None = None,
    error_traceback: str | None = None,
    elapsed_seconds: float | None = None,
) -> ExecutedTestCase:
    """Build an executed test case in scenario-1, phase pre-change."""
    return ExecutedTestCase(
        scenario="scenario-1",
        phase="pre-change",
        group=group,
        test_id=test_id,
        title=f"Verify {test_id}",
        status=status.value,
        checks=checks or [],
        not_applicable_devices=not_applicable_devices or {},
        error=error,
        error_code=error_code,
        error_traceback=error_traceback,
        elapsed_seconds=elapsed_seconds,
    )


def _run_result(
    test_cases: list[ExecutedTestCase],
    *,
    elapsed_seconds: float | None = 2.5,
) -> RunResult:
    """Build a run result with the test cases grouped by their group IDs."""
    groups: dict[str, list[ExecutedTestCase]] = {}
    for test_case in test_cases:
        groups.setdefault(test_case.group, []).append(test_case)
    phase = ExecutedPhase(
        identifier="pre-change",
        status=ResultStatus.PASSED.value,
        test_case_groups=[
            ExecutedTestCaseGroup(
                identifier=group_id,
                status=ResultStatus.PASSED.value,
                test_cases=cases,
            )
            for group_id, cases in groups.items()
        ],
    )
    return RunResult(
        summary=RunSummary(
            status=ResultStatus.PASSED.value,
            total=len(test_cases),
            passed=0,
            failed=0,
            errored=0,
            not_applicable=0,
            skipped=0,
            blocked=0,
        ),
        scenarios=[
            ExecutedScenario(
                identifier="scenario-1",
                status=ResultStatus.PASSED.value,
                phases=[phase],
            )
        ],
        mode="testing",
        started_at="2026-10-22T09:00:00+00:00",
        elapsed_seconds=elapsed_seconds,
    )

"""Tests for the JUnit XML report written by the junit reporter during a run."""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from .conftest import (
    invoke_cli,
    phase_cases,
    phases_by_name as _phases_by_name,
    run_outcome_plan as _run,
    stage_outcome_plan as _stage_plan,
    stage_runner_fixture,
)


def test_testing_run_writes_junit_report_next_to_run_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A testing run writes results/<run>/junit.xml with one case per test."""
    _stage_plan(
        tmp_path,
        {
            "first": {"test": "failed-1"},
            "dependent": {"test": "passed-2", "depends_on": ["first"]},
        },
    )

    assert _run(tmp_path, monkeypatch) == 1

    root = _load_junit(tmp_path)
    cases = {case.get("name"): case for case in root.iter("testcase")}
    assert set(cases) == {"failed-1", "passed-2"}
    assert cases["failed-1"].get("classname") == "scenario-1.first.first-group"
    assert cases["failed-1"].find("failure") is not None
    skipped = cases["passed-2"].find("skipped")
    assert skipped is not None
    assert skipped.get("type") == "blocked:dependency_failed"
    assert (root.get("tests"), root.get("failures")) == ("2", "1")


def test_run_records_per_test_case_elapsed_seconds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A test case that ran records its elapsed time in run.json and JUnit."""
    _stage_plan(
        tmp_path,
        {
            "first": {"test": "failed-1"},
            "dependent": {"test": "passed-2", "depends_on": ["first"]},
        },
    )

    _run(tmp_path, monkeypatch)

    phases = _phases_by_name(tmp_path)
    ran = phase_cases(phases["first"])[0]
    blocked = phase_cases(phases["dependent"])[0]
    assert ran["elapsed_seconds"] >= 0
    assert blocked["elapsed_seconds"] is None
    cases = {case.get("name"): case for case in _load_junit(tmp_path).iter("testcase")}
    assert cases["failed-1"].get("time") is not None
    assert cases["passed-2"].get("time") is None


def test_learning_run_writes_junit_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A learning run writes a JUnit report as well."""
    stage_runner_fixture(tmp_path, "learning_testing_parameters")
    monkeypatch.chdir(tmp_path)

    result = invoke_cli(tmp_path, "run", "--mode", "learning")

    assert result.exit_code == 0
    root = _load_junit(tmp_path)
    assert root.get("tests") == "1"
    assert root.get("failures") == "0"


def test_junit_report_follows_configured_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The path option in [tool.huginn.plugins.config.junit] moves the report."""
    _stage_plan(tmp_path, {"first": {"test": "passed-1"}})
    (tmp_path / "pyproject.toml").write_text(
        '[tool.huginn.plugins.config.junit]\npath = "ci/huginn-junit.xml"\n',
        encoding="utf-8",
    )

    assert _run(tmp_path, monkeypatch) == 0

    assert (tmp_path / "ci" / "huginn-junit.xml").is_file()
    assert not list((tmp_path / "results").glob("*/junit.xml"))


def test_reporters_list_without_junit_writes_no_junit_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Leaving junit out of the reporters list disables it."""
    _stage_plan(tmp_path, {"first": {"test": "passed-1"}})
    (tmp_path / "pyproject.toml").write_text(
        '[tool.huginn.plugins]\nreporters = ["html"]\n', encoding="utf-8"
    )

    assert _run(tmp_path, monkeypatch) == 0

    assert not list((tmp_path / "results").glob("*/junit.xml"))
    assert (tmp_path / "reports" / "latest" / "index.html").exists()


def _load_junit(tmp_path: Path) -> ET.Element:
    """Parse the newest run's junit.xml."""
    reports = sorted((tmp_path / "results").glob("*/junit.xml"))
    assert reports, "expected a junit.xml artifact under results/"
    return ET.parse(reports[-1]).getroot()

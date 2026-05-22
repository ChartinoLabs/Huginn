"""Tests for CLI filtering options: --phase, --test-case-group, --test-id, --tags, --exclude-tags."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from huginn.cli import app

from .conftest import first_test_case, load_report, stage_runner_fixture


def test_run_filters_test_cases_by_tags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run command executes only test cases matching requested tags."""
    stage_runner_fixture(tmp_path, "tag_filtering")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "--mode",
            "testing",
            "--testbed",
            str(tmp_path / "testbed.yaml"),
            "--plan",
            str(tmp_path / "test_plan.yaml"),
            "--tags",
            "ospf",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert not (tmp_path / "unexpected.tag.execution").exists()
    report_data = load_report(tmp_path)
    assert report_data["summary"]["total"] == 1
    checks = first_test_case(report_data)["checks"]
    assert checks[0]["message"] == "ran:ospf"


def test_run_with_unmatched_tags_produces_empty_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unmatched tag filters prune all test cases and phases."""
    stage_runner_fixture(tmp_path, "tag_filtering")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "--mode",
            "testing",
            "--testbed",
            str(tmp_path / "testbed.yaml"),
            "--plan",
            str(tmp_path / "test_plan.yaml"),
            "--tags",
            "isis",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    report_data = load_report(tmp_path)
    assert report_data["summary"]["total"] == 0
    assert report_data["scenarios"] == []


def test_run_filters_by_phase_option(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase filter runs only selected phase execution nodes."""
    stage_runner_fixture(tmp_path, "cli_filtering")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "--mode",
            "testing",
            "--testbed",
            str(tmp_path / "testbed.yaml"),
            "--plan",
            str(tmp_path / "test_plan.yaml"),
            "--scenario",
            "scenario-1",
            "--phase",
            "post-change",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    report = load_report(tmp_path)
    assert [phase["name"] for phase in report["scenarios"][0]["phases"]] == [
        "post-change"
    ]
    assert report["summary"]["total"] == 1


def test_run_filters_by_test_case_group_option(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Group filter keeps matching group and prunes others."""
    stage_runner_fixture(tmp_path, "cli_filtering")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "--mode",
            "testing",
            "--testbed",
            str(tmp_path / "testbed.yaml"),
            "--plan",
            str(tmp_path / "test_plan.yaml"),
            "--test-case-group",
            "pre-checks",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    report = load_report(tmp_path)
    executed_groups = [
        group["name"]
        for phase in report["scenarios"][0]["phases"]
        for group in phase["test_case_groups"]
    ]
    assert executed_groups == ["pre-checks"]
    assert report["summary"]["total"] == 2


def test_run_filters_by_test_id_option(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test-id filter runs only selected test case ids."""
    stage_runner_fixture(tmp_path, "cli_filtering")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "--mode",
            "testing",
            "--testbed",
            str(tmp_path / "testbed.yaml"),
            "--plan",
            str(tmp_path / "test_plan.yaml"),
            "--test-id",
            "1.0.1",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    report = load_report(tmp_path)
    executed_ids = [
        case["test_id"]
        for phase in report["scenarios"][0]["phases"]
        for group in phase["test_case_groups"]
        for case in group["test_cases"]
    ]
    assert executed_ids == ["1.0.1"]


def test_run_filters_by_exclude_tags_option(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exclude-tags filter removes matching tests from execution."""
    stage_runner_fixture(tmp_path, "cli_filtering")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "--mode",
            "testing",
            "--testbed",
            str(tmp_path / "testbed.yaml"),
            "--plan",
            str(tmp_path / "test_plan.yaml"),
            "--exclude-tags",
            "slow",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    report = load_report(tmp_path)
    executed_ids = [
        case["test_id"]
        for phase in report["scenarios"][0]["phases"]
        for group in phase["test_case_groups"]
        for case in group["test_cases"]
    ]
    assert set(executed_ids) == {"1.0.0", "2.0.0"}


def test_run_filters_by_comma_separated_tags_with_all_match_semantics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Comma-separated tags are parsed and all requested tags must match."""
    stage_runner_fixture(tmp_path, "cli_filtering")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "--mode",
            "testing",
            "--testbed",
            str(tmp_path / "testbed.yaml"),
            "--plan",
            str(tmp_path / "test_plan.yaml"),
            "--tags",
            "ospf,post",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    report = load_report(tmp_path)
    executed_ids = [
        case["test_id"]
        for phase in report["scenarios"][0]["phases"]
        for group in phase["test_case_groups"]
        for case in group["test_cases"]
    ]
    assert executed_ids == ["2.0.0"]

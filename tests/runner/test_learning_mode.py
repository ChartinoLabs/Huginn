"""Tests for learning mode: parameter persistence, deduplication, and skipping."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from huginn.cli import app

from .conftest import first_test_case, load_report, stage_runner_fixture


def test_run_learning_mode_persists_parameters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Learning mode writes learned parameters for the executing test case."""
    stage_runner_fixture(tmp_path, "learning_testing_parameters")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "--mode",
            "learning",
            "--testbed",
            str(tmp_path / "testbed.yaml"),
            "--plan",
            str(tmp_path / "test_plan.yaml"),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    parameter_path = tmp_path / "parameters" / "1.0.0.json"
    assert parameter_path.exists()
    saved = json.loads(parameter_path.read_text(encoding="utf-8"))
    assert saved == {
        "target_count": 1,
        "target_names": ["leaf-01"],
    }


def test_run_learning_mode_writes_html_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Learning mode writes the standard HTML report alongside run results."""
    stage_runner_fixture(tmp_path, "learning_testing_parameters")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "--mode",
            "learning",
            "--testbed",
            str(tmp_path / "testbed.yaml"),
            "--plan",
            str(tmp_path / "test_plan.yaml"),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert (tmp_path / "reports" / "latest" / "index.html").exists()
    assert "Run report written to reports/latest/" in result.stdout


def test_run_learning_mode_deduplicates_reused_test_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Learning mode executes a reused test id once across scenarios."""
    stage_runner_fixture(tmp_path, "duplicate_learning_parameters")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "--mode",
            "learning",
            "--testbed",
            str(tmp_path / "testbed.yaml"),
            "--plan",
            str(tmp_path / "test_plan.yaml"),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert result.stdout.count("Starting test: 1.0.0") == 1
    assert (
        "Skipping test: 1.0.0 (Learn shared parameters once) already learned "
        "earlier in this run" in result.stdout
    )
    invocation_counter = json.loads(
        (tmp_path / "learning-invocations.json").read_text(encoding="utf-8")
    )
    assert invocation_counter == {"count": 1}

    report_data = load_report(tmp_path)
    scenarios = report_data["scenarios"]
    assert [scenario["id"] for scenario in scenarios] == ["scenario-1", "scenario-2"]
    assert first_test_case(report_data)["status"] == "passed"
    second_test_case = scenarios[1]["phases"][0]["test_case_groups"][0]["test_cases"][0]
    assert second_test_case["status"] == "passed"


def test_run_learning_mode_skips_non_learning_testcases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Learning mode skips tests that do not inherit LearningTestCase."""
    stage_runner_fixture(tmp_path, "passed")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "--mode",
            "learning",
            "--testbed",
            str(tmp_path / "testbed.yaml"),
            "--plan",
            str(tmp_path / "test_plan.yaml"),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 1
    report_data = load_report(tmp_path)
    test_case = first_test_case(report_data)
    assert test_case["status"] == "skipped"
    assert "inherit LearningTestCase" in test_case["error"]
    assert report_data["summary"]["skipped"] == 1


def test_run_testing_mode_loads_learned_parameters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Testing mode loads previously learned parameters and validates state."""
    stage_runner_fixture(tmp_path, "learning_testing_parameters")
    monkeypatch.chdir(tmp_path)

    parameters_dir = tmp_path / "parameters"
    parameters_dir.mkdir(parents=True, exist_ok=True)
    (parameters_dir / "1.0.0.json").write_text(
        json.dumps({"target_count": 1, "target_names": ["leaf-01"]}),
        encoding="utf-8",
    )

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
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    report_data = load_report(tmp_path)
    checks = first_test_case(report_data)["checks"]
    assert checks[0]["message"] == "parameters matched"


def test_run_testing_mode_errors_when_parameters_are_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Testing mode surfaces missing learned parameter files as execution errors."""
    stage_runner_fixture(tmp_path, "learning_testing_parameters")
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
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 1
    report_data = load_report(tmp_path)
    test_case = first_test_case(report_data)
    assert test_case["status"] == "errored"
    assert "No learned parameters found" in test_case["error"]

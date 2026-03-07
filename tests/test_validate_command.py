"""Integration tests for the CLI validate command."""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from huginn.cli import app


def test_validate_generates_report_for_valid_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validate command writes a passing report for valid inputs."""
    _stage_runner_fixture(tmp_path, "target_selectors")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "validate",
            "--testbed",
            str(tmp_path / "testbed.yaml"),
            "--plan",
            str(tmp_path / "test_plan.yaml"),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    report = _load_validate_report(tmp_path)
    assert report["valid"] is True
    assert report["phase_order"] == ["phase-1"]
    assert report["required_brokers"] == ["ssh"]


def test_validate_reports_errors_for_invalid_target_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validate command fails when target references unknown device name."""
    _stage_runner_fixture(tmp_path, "unknown_target")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "validate",
            "--testbed",
            str(tmp_path / "testbed.yaml"),
            "--plan",
            str(tmp_path / "test_plan.yaml"),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 3
    report = _load_validate_report(tmp_path)
    assert report["valid"] is False
    assert report["errors"][0]["code"] == "validation_error"
    assert any(
        "Unknown target device 'leaf-42'" in error["message"]
        for error in report["errors"]
    )


def test_validate_filters_test_cases_by_tags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validate command applies tag filter before reporting cases."""
    _stage_runner_fixture(tmp_path, "tag_filtering")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "validate",
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
    report = _load_validate_report(tmp_path)
    assert report["valid"] is True
    assert [case["test_id"] for case in report["test_cases"]] == ["1.0.0"]


def test_validate_with_unmatched_tags_has_empty_execution_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unmatched tags produce a valid but empty validation report."""
    _stage_runner_fixture(tmp_path, "tag_filtering")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "validate",
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
    report = _load_validate_report(tmp_path)
    assert report["valid"] is True
    assert report["phase_order"] == []
    assert report["test_cases"] == []


def test_validate_supports_file_inventory_plugin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validate command resolves testbed via file inventory plugin."""
    _stage_runner_fixture(tmp_path, "tag_filtering")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "validate",
            "--inventory-plugin",
            "file:testbed.yaml",
            "--plan",
            str(tmp_path / "test_plan.yaml"),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    report = _load_validate_report(tmp_path)
    assert report["valid"] is True


def test_validate_reports_inventory_plugin_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validate command reports unsupported inventory plugin errors."""
    _stage_runner_fixture(tmp_path, "tag_filtering")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "validate",
            "--inventory-plugin",
            "unknown:foo",
            "--plan",
            str(tmp_path / "test_plan.yaml"),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 3
    report = _load_validate_report(tmp_path)
    assert report["valid"] is False
    assert report["errors"][0]["code"] == "configuration_error"


def test_validate_rejects_unsupported_report_plugin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unsupported report plugin names fail argument validation."""
    _stage_runner_fixture(tmp_path, "tag_filtering")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "validate",
            "--testbed",
            str(tmp_path / "testbed.yaml"),
            "--plan",
            str(tmp_path / "test_plan.yaml"),
            "--report-plugin",
            "html",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 2


def test_validate_filters_by_phase_and_test_case_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validate command applies phase and group filters before planning."""
    _stage_runner_fixture(tmp_path, "cli_filtering")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "validate",
            "--testbed",
            str(tmp_path / "testbed.yaml"),
            "--plan",
            str(tmp_path / "test_plan.yaml"),
            "--phase",
            "pre-change",
            "--test-case-group",
            "pre-checks",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    report = _load_validate_report(tmp_path)
    assert report["phase_order"] == ["pre-change"]
    assert {case["test_id"] for case in report["test_cases"]} == {"1.0.0", "1.0.1"}


def test_validate_filters_by_test_id_and_exclude_tags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validate command supports test-id and exclude-tags filters."""
    _stage_runner_fixture(tmp_path, "cli_filtering")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "validate",
            "--testbed",
            str(tmp_path / "testbed.yaml"),
            "--plan",
            str(tmp_path / "test_plan.yaml"),
            "--test-id",
            "1.0.1",
            "--exclude-tags",
            "slow",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    report = _load_validate_report(tmp_path)
    assert report["phase_order"] == []
    assert report["test_cases"] == []


def _stage_runner_fixture(tmp_path: Path, fixture_name: str) -> None:
    """Copy a first-slice fixture scenario into a temporary directory."""
    fixture_root = Path(__file__).resolve().parent / "fixtures" / "first_slice_runner"
    source = fixture_root / fixture_name
    for source_path in source.rglob("*"):
        if source_path.is_dir():
            continue
        destination = tmp_path / source_path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)


def _load_validate_report(tmp_path: Path) -> dict[str, Any]:
    """Load generated validate report payload."""
    validate_reports = sorted((tmp_path / "results").glob("*-validate/validate.json"))
    assert validate_reports, "expected a validate.json artifact under results/"
    report_path = validate_reports[-1]
    return json.loads(report_path.read_text(encoding="utf-8"))

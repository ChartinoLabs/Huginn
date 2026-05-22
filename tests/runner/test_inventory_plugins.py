"""Tests for inventory plugin resolution and error handling."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from huginn.cli import app

from .conftest import load_report, stage_runner_fixture


def test_run_supports_file_inventory_plugin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run command resolves testbed via built-in file inventory plugin."""
    stage_runner_fixture(tmp_path, "passed")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "--mode",
            "testing",
            "--inventory-plugin",
            "file:testbed.yaml",
            "--plan",
            str(tmp_path / "test_plan.yaml"),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    report_data = load_report(tmp_path)
    assert report_data["summary"]["status"] == "passed"


def test_run_inventory_plugin_errors_map_to_configuration_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unsupported inventory plugins exit with configuration error code."""
    stage_runner_fixture(tmp_path, "passed")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "--mode",
            "testing",
            "--inventory-plugin",
            "unknown:foo",
            "--plan",
            str(tmp_path / "test_plan.yaml"),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 2
    assert "configuration_error" in result.stderr
    assert "Traceback (most recent call last)" in result.stderr

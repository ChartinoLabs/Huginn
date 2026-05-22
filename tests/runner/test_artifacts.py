"""Tests for artifacts directory creation and custom output/results directories."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from huginn.cli import app

from .conftest import stage_runner_fixture


def test_run_creates_artifacts_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI run creates an artifacts directory inside the run results directory."""
    stage_runner_fixture(tmp_path, "passed")
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

    assert result.exit_code == 0
    run_dirs = sorted((tmp_path / "results").glob("*-testing"))
    assert run_dirs, "expected a timestamped run directory under results/"
    artifacts_dir = run_dirs[-1] / "artifacts"
    assert artifacts_dir.exists()
    assert artifacts_dir.is_dir()


def test_run_uses_custom_output_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI --output-dir overrides the default artifacts location."""
    stage_runner_fixture(tmp_path, "passed")
    monkeypatch.chdir(tmp_path)
    custom_output = tmp_path / "custom-artifacts"

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
            "--output-dir",
            str(custom_output),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert custom_output.exists()
    assert custom_output.is_dir()


def test_run_uses_custom_results_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI --results-dir overrides the default results location."""
    stage_runner_fixture(tmp_path, "passed")
    monkeypatch.chdir(tmp_path)
    custom_results = tmp_path / "custom-results"

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
            "--results-dir",
            str(custom_results),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    run_dirs = sorted(custom_results.glob("*-testing"))
    assert run_dirs, "expected a timestamped run directory under custom results dir"

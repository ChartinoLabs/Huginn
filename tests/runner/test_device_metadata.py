"""Integration tests for passing testbed device metadata to jobs."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from huginn.cli import app

from .conftest import load_report, stage_runner_fixture


def test_run_passes_read_only_device_metadata_to_every_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every job reads `device.metadata`, expanded and read-only."""
    stage_runner_fixture(tmp_path, "device_metadata")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HUGINN_TEST_SITE", "dc2")

    result = CliRunner().invoke(
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

    assert result.exit_code == 0, result.output
    metadata = {"role": "spine", "site": "dc2", "uplinks": ["leaf-01", "leaf-02"]}
    expected = [
        f"spine-01={json.dumps(metadata, sort_keys=True)}",
        "read-only",
        "Learned parameters saved successfully",
    ]
    report = load_report(tmp_path)
    checks = {
        test_case["test_id"]: [check["message"] for check in test_case["checks"]]
        for scenario in report["scenarios"]
        for phase in scenario["phases"]
        for group in phase["test_case_groups"]
        for test_case in group["test_cases"]
    }
    # The second job sees the original value: the first job could not mutate it.
    assert checks == {"1.0.0": expected, "1.1.0": expected}

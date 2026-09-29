"""Tests for runtime broker planning, connection and teardown during a run."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from huginn.cli import app
from huginn.enums import BrokerType

from .conftest import (
    _FakeRuntimeBroker,
    first_test_case,
    load_report,
    stage_runner_fixture,
)


def test_runner_plans_brokers_from_job_declarations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runner uses job-declared broker requirements from validation planning."""
    stage_runner_fixture(tmp_path, "job_declared_netconf")
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
    assert _FakeRuntimeBroker.last_required_brokers == {BrokerType.NETCONF}
    report_data = load_report(tmp_path)
    checks = first_test_case(report_data)["checks"]
    assert checks[0]["message"] == "get:leaf-01:/interfaces"


def test_runner_disconnects_once_per_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runner tears down runtime broker once after all test cases."""
    stage_runner_fixture(tmp_path, "connection_reuse")
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
    assert _FakeRuntimeBroker.connect_invocations == 1
    assert _FakeRuntimeBroker.disconnect_invocations == 1

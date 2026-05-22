"""Tests for execution strategy: parallel/serial group and phase concurrency."""

from pathlib import Path
from time import perf_counter

import pytest
from typer.testing import CliRunner

from huginn.cli import app

from .conftest import load_report, stage_runner_fixture


def _run_execution_strategy_fixture(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    plan_name: str,
) -> float:
    """Run one execution-strategy fixture plan and return elapsed seconds."""
    stage_runner_fixture(tmp_path, "execution_strategy")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    start = perf_counter()
    result = runner.invoke(
        app,
        [
            "run",
            "--mode",
            "testing",
            "--testbed",
            str(tmp_path / "testbed.yaml"),
            "--plan",
            str(tmp_path / plan_name),
        ],
        catch_exceptions=False,
    )
    elapsed = perf_counter() - start

    assert result.exit_code == 0
    return elapsed


def test_run_executes_test_cases_in_group_in_parallel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test cases in a group execute concurrently rather than serially."""
    stage_runner_fixture(tmp_path, "parallel_group_execution")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    start = perf_counter()
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
    elapsed = perf_counter() - start

    assert result.exit_code == 0
    report = load_report(tmp_path)
    executed_ids = [
        case["test_id"]
        for phase in report["scenarios"][0]["phases"]
        for group in phase["test_case_groups"]
        for case in group["test_cases"]
    ]
    assert executed_ids == ["1.0.0", "1.0.1"]
    assert elapsed < 0.65


def test_run_honors_group_serial_strategy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Group serial strategy executes test cases one-at-a-time."""
    elapsed = _run_execution_strategy_fixture(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        plan_name="plan_group_serial.yaml",
    )

    assert elapsed >= 0.55


def test_run_honors_group_parallel_maximum_strategy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Group parallel.maximum limits test case concurrency."""
    elapsed = _run_execution_strategy_fixture(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        plan_name="plan_group_parallel_maximum_one.yaml",
    )

    assert elapsed >= 0.55


def test_run_group_parallel_default_is_unbounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Group default parallel strategy runs test cases concurrently."""
    elapsed = _run_execution_strategy_fixture(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        plan_name="plan_group_parallel_default.yaml",
    )

    assert elapsed < 0.65


def test_run_honors_phase_serial_strategy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase serial strategy executes groups one-at-a-time."""
    elapsed = _run_execution_strategy_fixture(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        plan_name="plan_phase_serial.yaml",
    )

    assert elapsed >= 0.55


def test_run_honors_phase_parallel_strategy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase parallel strategy executes groups concurrently."""
    parallel_elapsed = _run_execution_strategy_fixture(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        plan_name="plan_phase_parallel.yaml",
    )
    serial_elapsed = _run_execution_strategy_fixture(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        plan_name="plan_phase_serial.yaml",
    )

    assert parallel_elapsed < serial_elapsed


def test_run_honors_phase_parallel_maximum_strategy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase parallel.maximum limits group concurrency."""
    elapsed = _run_execution_strategy_fixture(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        plan_name="plan_phase_parallel_maximum_one.yaml",
    )

    assert elapsed >= 0.55

"""Shared test infrastructure for runner integration tests."""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner, Result

from huginn.cli import app
from huginn.enums import BrokerType
from huginn.models import Device


class _FakeCommandResult:
    def __init__(self, output: str) -> None:
        self.output = output


class _FakeRuntimeBroker:
    last_required_brokers: set[BrokerType] = set()
    connect_invocations: int = 0
    disconnect_invocations: int = 0
    clear_cache_invocations: int = 0

    def __init__(
        self,
        *,
        required_brokers: set[BrokerType] | None = None,
        **_kwargs: object,
    ) -> None:
        self._planned_brokers = required_brokers or {BrokerType.SSH}

    async def connect_targets(
        self,
        targets: list[Device],
        required_brokers: set[BrokerType],
    ) -> None:
        _FakeRuntimeBroker.connect_invocations += 1
        _FakeRuntimeBroker.last_required_brokers = set(required_brokers)
        self._connected = {target.name for target in targets}

    async def disconnect_targets(self) -> None:
        _FakeRuntimeBroker.disconnect_invocations += 1
        self._connected = set()

    async def execute(self, target: Device, command: str) -> _FakeCommandResult:
        assert command
        return _FakeCommandResult(output=f"ok:{target.name}")

    async def get(
        self,
        target: Device,
        path: str,
        **kwargs: object,
    ) -> _FakeCommandResult:
        assert path
        return _FakeCommandResult(output=f"get:{target.name}:{path}")

    async def edit(
        self,
        target: Device,
        config: str,
        **kwargs: object,
    ) -> _FakeCommandResult:
        assert config
        return _FakeCommandResult(output=f"edit:{target.name}")

    def clear_cache(self) -> None:
        _FakeRuntimeBroker.clear_cache_invocations += 1

    def for_protocol(self, protocol: str) -> "_FakeRuntimeBrokerClient":
        return _FakeRuntimeBrokerClient(runtime=self, protocol=protocol)


class _FakeRuntimeBrokerClient:
    def __init__(self, runtime: _FakeRuntimeBroker, protocol: str) -> None:
        self._runtime = runtime
        self._protocol = protocol

    async def execute(self, target: Device, command: str) -> _FakeCommandResult:
        return await self._runtime.execute(target, f"{self._protocol}:{command}")

    async def get(
        self,
        target: Device,
        path: str,
        **kwargs: object,
    ) -> _FakeCommandResult:
        return await self._runtime.get(target, path, **kwargs)

    async def edit(
        self,
        target: Device,
        config: str,
        **kwargs: object,
    ) -> _FakeCommandResult:
        return await self._runtime.edit(target, config, **kwargs)


@pytest.fixture(autouse=True)
def patch_runtime_broker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use a fake runtime broker to avoid network dependencies in tests."""
    _FakeRuntimeBroker.last_required_brokers = set()
    _FakeRuntimeBroker.connect_invocations = 0
    _FakeRuntimeBroker.disconnect_invocations = 0
    _FakeRuntimeBroker.clear_cache_invocations = 0
    monkeypatch.setattr("huginn.runner.RuntimeBroker", _FakeRuntimeBroker)


def stage_runner_fixture(tmp_path: Path, fixture_name: str) -> None:
    """Copy a fixture scenario into the temp execution directory."""
    fixture_root = Path(__file__).resolve().parent.parent / "fixtures" / "runner"
    source = fixture_root / fixture_name
    for source_path in source.rglob("*"):
        if source_path.is_dir():
            continue
        destination = tmp_path / source_path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)


def load_report(tmp_path: Path) -> dict[str, Any]:
    """Load the generated run report and hydrate per-test-case details."""
    run_reports = sorted((tmp_path / "results").glob("*/run.json"))
    assert run_reports, "expected a run.json artifact under results/"

    report_path = run_reports[-1]
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    for scenario in payload["scenarios"]:
        for phase in scenario["phases"]:
            for group in phase["test_case_groups"]:
                hydrated_cases: list[dict[str, Any]] = []
                for test_case in group["test_cases"]:
                    hydrated_case = dict(test_case)
                    result_path = hydrated_case.pop("result_path")
                    test_case_payload = json.loads(
                        (report_path.parent / result_path).read_text(encoding="utf-8")
                    )
                    hydrated_cases.append({**hydrated_case, **test_case_payload})
                group["test_cases"] = hydrated_cases

    return payload


def first_test_case(report_data: dict[str, Any]) -> dict[str, Any]:
    """Return the first hydrated test case from a loaded run report."""
    return report_data["scenarios"][0]["phases"][0]["test_case_groups"][0][
        "test_cases"
    ][0]


# Outcome plan harness: one single-test phase per entry, built on the
# phase_blocking fixture whose job sets its outcome from the test ID prefix.
OUTCOME_JOB = "jobs/test_verify_outcome.py"


def stage_outcome_plan(tmp_path: Path, phases: dict[str, dict[str, Any]]) -> None:
    """Stage the fixture with one single-test group per phase.

    ``phases`` maps each phase name to its test ID and optional
    ``depends_on``. The test ID prefix sets the test's outcome.
    """
    stage_runner_fixture(tmp_path, "phase_blocking")
    plan = {
        "test_cases": {
            spec["test"]: {"title": spec["test"], "job": OUTCOME_JOB}
            for spec in phases.values()
        },
        "test_case_groups": {
            f"{name}-group": {"tests": [spec["test"]]} for name, spec in phases.items()
        },
        "scenarios": {
            "scenario-1": {
                "phases": {
                    name: {
                        "test_case_groups": [f"{name}-group"],
                        "depends_on": spec.get("depends_on", []),
                    }
                    for name, spec in phases.items()
                }
            }
        },
    }
    (tmp_path / "test_plan.yaml").write_text(yaml.safe_dump(plan), encoding="utf-8")


def run_outcome_plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> int:
    """Run the staged plan in testing mode and return the exit code."""
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
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
    return result.exit_code


def phases_by_name(tmp_path: Path) -> dict[str, dict[str, Any]]:
    """Return the report's phases for the only scenario, keyed by phase ID."""
    report = load_report(tmp_path)
    return {phase["id"]: phase for phase in report["scenarios"][0]["phases"]}


# Learning plan harness: one group per phase, built on the
# learning_phase_blocking fixture, where a change job cannot run in learning mode.
LEARN_STATE_JOB = "jobs/test_learn_state.py"
CHANGE_JOB = "jobs/test_apply_change.py"
NOT_LEARNED = "Blocked because phase '{}' was not run in learning mode"


def stage_learning_plan(tmp_path: Path, phases: dict[str, dict[str, Any]]) -> None:
    """Stage the fixture with one group per phase.

    ``phases`` maps each phase name to its ``tests`` (test ID to job path),
    optional ``depends_on`` and optional group ``target``.
    """
    stage_runner_fixture(tmp_path, "learning_phase_blocking")
    groups: dict[str, Any] = {}
    for name, spec in phases.items():
        group: dict[str, Any] = {"tests": list(spec["tests"])}
        if "target" in spec:
            group["target"] = spec["target"]
        groups[f"{name}-group"] = group
    plan = {
        "test_cases": {
            test_id: {"title": test_id, "job": job}
            for spec in phases.values()
            for test_id, job in spec["tests"].items()
        },
        "test_case_groups": groups,
        "scenarios": {
            "scenario-1": {
                "phases": {
                    name: {
                        "test_case_groups": [f"{name}-group"],
                        "depends_on": spec.get("depends_on", []),
                    }
                    for name, spec in phases.items()
                }
            }
        },
    }
    (tmp_path / "test_plan.yaml").write_text(yaml.safe_dump(plan), encoding="utf-8")


def change_plan() -> dict[str, dict[str, Any]]:
    """Return a pre-change, change and post-change phase chain."""
    return {
        "pre": {"tests": {"pre-1": LEARN_STATE_JOB}},
        "shut": {"tests": {"shut-1": CHANGE_JOB}, "depends_on": ["pre"]},
        "post": {"tests": {"post-1": LEARN_STATE_JOB}, "depends_on": ["shut"]},
    }


def invoke_cli(tmp_path: Path, *args: str) -> Result:
    """Invoke the CLI against the staged plan and testbed."""
    return CliRunner().invoke(
        app,
        [
            *args,
            "--testbed",
            str(tmp_path / "testbed.yaml"),
            "--plan",
            str(tmp_path / "test_plan.yaml"),
        ],
        catch_exceptions=False,
    )


def phase_cases(phase: dict[str, Any]) -> list[dict[str, Any]]:
    """Return every test case in a phase."""
    return [case for group in phase["test_case_groups"] for case in group["test_cases"]]

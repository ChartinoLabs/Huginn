"""Shared test infrastructure for runner integration tests."""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from huginn.enums import BrokerType
from huginn.models import Device


class _FakeCommandResult:
    def __init__(self, output: str) -> None:
        self.output = output


class _FakeRuntimeBroker:
    last_required_brokers: set[BrokerType] = set()
    connect_invocations: int = 0
    disconnect_invocations: int = 0

    def __init__(
        self,
        *,
        required_brokers: set[BrokerType] | None = None,
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
        pass

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
    monkeypatch.setattr("huginn.runner.RuntimeBroker", _FakeRuntimeBroker)


def stage_runner_fixture(tmp_path: Path, fixture_name: str) -> None:
    """Copy a fixture scenario into the temp execution directory."""
    fixture_root = (
        Path(__file__).resolve().parent.parent / "fixtures" / "first_slice_runner"
    )
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

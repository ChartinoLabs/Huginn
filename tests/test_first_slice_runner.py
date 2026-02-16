"""Integration tests for the first end-to-end runner slice."""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

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


def test_run_executes_single_test_case_and_writes_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI run executes one test and writes a JSON report."""
    _stage_runner_fixture(tmp_path, "passed")
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
    report_data = _load_report(tmp_path)
    assert report_data["summary"]["status"] == "passed"
    assert report_data["summary"]["passed"] == 1


def test_run_returns_non_zero_for_failed_test_case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI run returns exit code 1 when a test fails."""
    _stage_runner_fixture(tmp_path, "failed")
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
    report_data = _load_report(tmp_path)
    assert report_data["summary"]["status"] == "failed"
    assert report_data["summary"]["failed"] == 1


def test_cleanup_runs_when_test_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cleanup is executed even when test raises an exception."""
    _stage_runner_fixture(tmp_path, "errored")
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
    assert (tmp_path / "cleanup.marker").exists()
    assert _FakeRuntimeBroker.disconnect_invocations == 1
    report_data = _load_report(tmp_path)
    assert report_data["summary"]["status"] == "errored"
    assert report_data["summary"]["errored"] == 1


def test_run_honors_test_case_device_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runner resolves test-case targets and executes only matching devices."""
    _stage_runner_fixture(tmp_path, "targeted")
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
    report_data = _load_report(tmp_path)
    checks = report_data["phases"][0]["test_case_groups"][0]["test_cases"][0]["checks"]
    assert len(checks) == 1
    assert checks[0]["message"] == "ok:leaf-01"


def test_run_errors_when_test_target_device_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown test-case target devices are reported as execution errors."""
    _stage_runner_fixture(tmp_path, "unknown_target")
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
    report_data = _load_report(tmp_path)
    test_case = report_data["phases"][0]["test_case_groups"][0]["test_cases"][0]
    assert test_case["status"] == "errored"
    assert test_case["error_code"] == "validation_error"
    assert "Unknown target device 'leaf-42'" in test_case["error"]


def test_runner_plans_brokers_from_job_declarations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runner uses job-declared broker requirements from validation planning."""
    _stage_runner_fixture(tmp_path, "job_declared_netconf")
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
    report_data = _load_report(tmp_path)
    checks = report_data["phases"][0]["test_case_groups"][0]["test_cases"][0]["checks"]
    assert checks[0]["message"] == "get:leaf-01:/interfaces"


def test_phase_with_failed_dependency_is_marked_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Downstream phases are blocked when dependency phase fails."""
    _stage_runner_fixture(tmp_path, "phase_dependency_blocked")
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
    assert not (tmp_path / "phase2.executed").exists()

    report_data = _load_report(tmp_path)
    assert report_data["summary"]["failed"] == 1
    assert report_data["summary"]["blocked"] == 1

    phase_1 = report_data["phases"][0]
    phase_2 = report_data["phases"][1]
    assert phase_1["status"] == "failed"
    assert phase_2["status"] == "blocked"

    blocked_case = phase_2["test_case_groups"][0]["test_cases"][0]
    assert blocked_case["status"] == "blocked"


def test_runner_disconnects_once_per_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runner tears down runtime broker once after all test cases."""
    _stage_runner_fixture(tmp_path, "connection_reuse")
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
    assert _FakeRuntimeBroker.connect_invocations == 2
    assert _FakeRuntimeBroker.disconnect_invocations == 1


def test_run_applies_group_and_os_target_selectors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Group and OS selectors filter target set with AND semantics."""
    _stage_runner_fixture(tmp_path, "target_selectors")
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
    report_data = _load_report(tmp_path)
    checks = report_data["phases"][0]["test_case_groups"][0]["test_cases"][0]["checks"]
    assert len(checks) == 1
    assert checks[0]["message"] == "selected:leaf-02"


def test_run_skips_test_case_when_no_targets_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No matched targets marks test as skipped instead of errored."""
    _stage_runner_fixture(tmp_path, "target_no_match")
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
    assert not (tmp_path / "unexpected.execution").exists()
    report_data = _load_report(tmp_path)
    test_case = report_data["phases"][0]["test_case_groups"][0]["test_cases"][0]
    assert test_case["status"] == "skipped"
    assert test_case["error_code"] is None
    assert "No devices matched target selectors" in test_case["error"]


def test_run_applies_phase_group_test_target_intersection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase/group/test-case targets are intersected deterministically."""
    _stage_runner_fixture(tmp_path, "hierarchical_targets")
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
    report_data = _load_report(tmp_path)
    checks = report_data["phases"][0]["test_case_groups"][0]["test_cases"][0]["checks"]
    assert len(checks) == 1
    assert checks[0]["message"] == "selected:leaf-02"


def test_run_skips_when_hierarchical_target_intersection_is_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty target set after phase/group/test intersections is skipped."""
    _stage_runner_fixture(tmp_path, "hierarchical_no_match")
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
    assert not (tmp_path / "hierarchy.unexpected").exists()
    report_data = _load_report(tmp_path)
    test_case = report_data["phases"][0]["test_case_groups"][0]["test_cases"][0]
    assert test_case["status"] == "skipped"


def test_run_filters_test_cases_by_tags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run command executes only test cases matching requested tags."""
    _stage_runner_fixture(tmp_path, "tag_filtering")
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
    report_data = _load_report(tmp_path)
    assert report_data["summary"]["total"] == 1
    checks = report_data["phases"][0]["test_case_groups"][0]["test_cases"][0]["checks"]
    assert checks[0]["message"] == "ran:ospf"


def test_run_with_unmatched_tags_produces_empty_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unmatched tag filters prune all test cases and phases."""
    _stage_runner_fixture(tmp_path, "tag_filtering")
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
    report_data = _load_report(tmp_path)
    assert report_data["summary"]["total"] == 0
    assert report_data["phases"] == []


def test_run_supports_file_inventory_plugin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run command resolves testbed via built-in file inventory plugin."""
    _stage_runner_fixture(tmp_path, "passed")
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
    report_data = _load_report(tmp_path)
    assert report_data["summary"]["status"] == "passed"


def test_run_inventory_plugin_errors_map_to_configuration_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unsupported inventory plugins exit with configuration error code."""
    _stage_runner_fixture(tmp_path, "passed")
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
    assert "configuration_error" in result.stdout


def test_run_learning_mode_persists_parameters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Learning mode writes learned parameters for the executing test case."""
    _stage_runner_fixture(tmp_path, "learning_testing_parameters")
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


def test_run_testing_mode_loads_learned_parameters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Testing mode loads previously learned parameters and validates state."""
    _stage_runner_fixture(tmp_path, "learning_testing_parameters")
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
    report_data = _load_report(tmp_path)
    checks = report_data["phases"][0]["test_case_groups"][0]["test_cases"][0]["checks"]
    assert checks[0]["message"] == "parameters matched"


def test_run_testing_mode_errors_when_parameters_are_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Testing mode surfaces missing learned parameter files as execution errors."""
    _stage_runner_fixture(tmp_path, "learning_testing_parameters")
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
    report_data = _load_report(tmp_path)
    test_case = report_data["phases"][0]["test_case_groups"][0]["test_cases"][0]
    assert test_case["status"] == "errored"
    assert "No learned parameters found" in test_case["error"]


def _stage_runner_fixture(tmp_path: Path, fixture_name: str) -> None:
    """Copy a fixture scenario into the temp execution directory."""
    fixture_root = Path(__file__).resolve().parent / "fixtures" / "first_slice_runner"
    source = fixture_root / fixture_name
    for source_path in source.rglob("*"):
        if source_path.is_dir():
            continue
        destination = tmp_path / source_path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)


def _load_report(tmp_path: Path) -> dict[str, Any]:
    """Load the generated run report from the default reports directory."""
    report_path = tmp_path / "reports" / "run.json"
    return json.loads(report_path.read_text(encoding="utf-8"))

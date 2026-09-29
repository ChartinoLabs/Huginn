"""Hook plugin harness shared by the hook integration tests."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml
from typer.testing import CliRunner, Result

from huginn.cli import app
from huginn.plugin_registry import HOOK_GROUP

from ..conftest import load_report, stage_runner_fixture

OUTCOME = "jobs/test_outcome.py"
LEARN = "jobs/test_learn.py"

# Hooks registered for the current test, in entry-point order.
REGISTERED: list[tuple[str, type]] = []


class _FakeEntryPoint:
    """Simulates an importlib.metadata entry point."""

    def __init__(self, name: str, cls: type) -> None:
        self.name = name
        self._cls = cls

    def load(self) -> type:
        return self._cls


@pytest.fixture
def fake_hook_entry_points() -> Iterator[None]:
    """Serve ``REGISTERED`` as the installed ``huginn.hooks`` entry points."""
    REGISTERED.clear()
    from huginn import plugin_registry

    real_entry_points = plugin_registry.entry_points

    def _entry_points(*, group: str) -> object:
        if group == HOOK_GROUP:
            return [_FakeEntryPoint(name, cls) for name, cls in REGISTERED]
        return real_entry_points(group=group)

    with patch("huginn.plugin_registry.entry_points", side_effect=_entry_points):
        yield


def register(name: str, cls: type) -> None:
    """Install a hook plugin under the entry point ``name``."""
    REGISTERED.append((name, cls))


def stage_plan(
    tmp_path: Path,
    phases: dict[str, dict[str, Any]],
    *,
    pyproject: str | None = None,
) -> None:
    """Stage a plan where each phase has the given groups of test IDs.

    ``phases`` maps phase ID to ``groups`` (group ID to test IDs), optional
    ``depends_on`` and optional ``strategy``. Every test uses the outcome job.
    """
    stage_runner_fixture(tmp_path, "hook_dispatch")
    groups = {
        group_id: {"tests": list(test_ids)}
        for spec in phases.values()
        for group_id, test_ids in spec["groups"].items()
    }
    test_ids = [test_id for group in groups.values() for test_id in group["tests"]]
    plan = {
        "test_cases": {
            test_id: {"title": f"Title {test_id}", "job": OUTCOME, "tags": ["t"]}
            for test_id in test_ids
        },
        "test_case_groups": groups,
        "scenarios": {
            "scenario-1": {
                "phases": {
                    phase_id: {
                        "test_case_groups": list(spec["groups"]),
                        "depends_on": spec.get("depends_on", []),
                        **(
                            {"strategy": spec["strategy"]} if "strategy" in spec else {}
                        ),
                    }
                    for phase_id, spec in phases.items()
                }
            }
        },
    }
    (tmp_path / "test_plan.yaml").write_text(
        yaml.safe_dump(plan, sort_keys=False), encoding="utf-8"
    )
    if pyproject is not None:
        (tmp_path / "pyproject.toml").write_text(pyproject, encoding="utf-8")


def one_phase(*test_ids: str) -> dict[str, dict[str, Any]]:
    """Return a plan with one phase holding one group of ``test_ids``."""
    return {"phase-1": {"groups": {"group-1": list(test_ids)}}}


def run_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *args: str) -> Result:
    """Run the staged plan in testing mode unless ``args`` says otherwise."""
    monkeypatch.chdir(tmp_path)
    return CliRunner().invoke(
        app,
        [
            *(args or ("run", "--mode", "testing")),
            "--testbed",
            str(tmp_path / "testbed.yaml"),
            "--plan",
            str(tmp_path / "test_plan.yaml"),
        ],
        catch_exceptions=False,
    )


def cases(tmp_path: Path) -> dict[str, dict[str, Any]]:
    """Return the report's test cases keyed by test ID."""
    report = load_report(tmp_path)
    return {
        case["test_id"]: case
        for scenario in report["scenarios"]
        for phase in scenario["phases"]
        for group in phase["test_case_groups"]
        for case in group["test_cases"]
    }


def ran(tmp_path: Path, test_id: str) -> list[str]:
    """Return the job steps that ran for ``test_id``."""
    markers = tmp_path / "executed" / test_id
    return sorted(path.name for path in markers.iterdir()) if markers.exists() else []


def stage_serial_group(tmp_path: Path) -> None:
    """Make every group in the staged plan run its tests serially."""
    plan_path = tmp_path / "test_plan.yaml"
    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    for group in plan["test_case_groups"].values():
        group["strategy"] = {"serial": {}}
    plan_path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")


def use_learning_job(tmp_path: Path) -> None:
    """Point every test case in the staged plan at the learning job."""
    plan_path = tmp_path / "test_plan.yaml"
    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    for test_case in plan["test_cases"].values():
        test_case["job"] = LEARN
    plan_path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")


def write_failed_testing_run(tmp_path: Path, test_id: str) -> None:
    """Write a testing run.json in which only ``test_id`` failed."""
    run_json = tmp_path / "results" / "2020-Jan-01-00-00-00-testing" / "run.json"
    run_json.parent.mkdir(parents=True)
    test_case = {"test_id": test_id, "title": test_id, "status": "failed"}
    phase = {
        "id": "phase-1",
        "status": "failed",
        "test_case_groups": [
            {"id": "group-1", "status": "failed", "test_cases": [test_case]}
        ],
    }
    scenario = {"id": "scenario-1", "status": "failed", "phases": [phase]}
    run_json.write_text(
        json.dumps({"mode": "testing", "scenarios": [scenario]}), encoding="utf-8"
    )

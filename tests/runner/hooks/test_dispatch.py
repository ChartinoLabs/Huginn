"""Tests for dispatching hook plugins during `huginn run` and `huginn relearn`."""

from pathlib import Path
from typing import Any

import pytest

from huginn.hooks import HookEvent, HookSignal, HookSkip

from .conftest import (
    OUTCOME,
    cases as _cases,
    one_phase as _one_phase,
    ran as _ran,
    register as _register,
    run_cli as _run,
    stage_plan as _stage_plan,
    stage_serial_group as _stage_serial_group,
    use_learning_job as _use_learning_job,
    write_failed_testing_run as _write_failed_testing_run,
)


class _RecordingHook:
    """Record every event with a copy of its context, minus ``output``.

    ``skips`` maps (event, item ID) to what ``on_event`` returns for it. The
    item ID is the test ID, group ID or phase ID of the event.
    """

    hook_name = "recorder"
    events: list[tuple[str, dict[str, Any]]] = []
    outputs: list[object] = []
    skips: dict[tuple[HookEvent, str], object] = {}

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    @property
    def name(self) -> str:
        return self.hook_name

    def subscriptions(self) -> set[HookEvent]:
        return set(HookEvent)

    async def on_event(self, event: HookEvent, context: dict[str, Any]) -> object:
        self.outputs.append(context["output"])
        recorded = {key: value for key, value in context.items() if key != "output"}
        self.events.append((event.value, recorded))
        item = context.get("test_id") if event == HookEvent.TEST_CASE_START else None
        item = item or context.get("group") or context.get("phase")
        return self.skips.get((event, str(item)))


class _SecondSkipper:
    """Skip every test case whose ID starts with ``both``."""

    @property
    def name(self) -> str:
        return "second"

    def subscriptions(self) -> set[HookEvent]:
        return {HookEvent.TEST_CASE_START}

    async def on_event(self, event: HookEvent, context: dict[str, Any]) -> object:
        if str(context["test_id"]).startswith("both"):
            return HookSkip("Change freeze")
        return None


class _BrokenHook:
    """Raise on every event."""

    @property
    def name(self) -> str:
        return "broken"

    def subscriptions(self) -> set[HookEvent]:
        return {HookEvent.RUN_START, HookEvent.TEST_CASE_START}

    async def on_event(self, event: HookEvent, context: dict[str, Any]) -> object:
        raise RuntimeError("hook exploded")


@pytest.fixture(autouse=True)
def reset_recording_hook(fake_hook_entry_points: None) -> None:
    """Install the fake entry points and clear what the recorder saw."""
    _RecordingHook.events = []
    _RecordingHook.outputs = []
    _RecordingHook.skips = {}


def _events() -> list[str]:
    """Return the recorded event names in order."""
    return [event for event, _ in _RecordingHook.events]


def _payload(event: str, **match: object) -> dict[str, Any]:
    """Return the first recorded payload of ``event`` matching ``match``."""
    for name, payload in _RecordingHook.events:
        if name == event and all(payload.get(k) == v for k, v in match.items()):
            return payload
    raise AssertionError(f"no {event} event matching {match}")


def test_events_are_dispatched_in_lifecycle_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A simple plan dispatches every event, each start before its end."""
    _register("recorder", _RecordingHook)
    _stage_plan(tmp_path, _one_phase("passed-1", "failed-1", "errored-1"))
    _stage_serial_group(tmp_path)

    result = _run(tmp_path, monkeypatch)

    assert result.exit_code == 1, result.stdout
    assert _events() == [
        "run_start",
        "scenario_start",
        "phase_start",
        "group_start",
        "test_case_start",
        "test_case_end",
        "test_case_start",
        "test_case_end",
        "on_failure",
        "test_case_start",
        "test_case_end",
        "on_error",
        "group_end",
        "phase_end",
        "scenario_end",
        "run_end",
    ]


def test_event_payloads_carry_ids_statuses_and_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each payload holds the documented plain-data keys."""
    _register("recorder", _RecordingHook)
    _stage_plan(tmp_path, _one_phase("passed-1", "lost-1"))

    _run(tmp_path, monkeypatch)

    run_start = _payload("run_start")
    assert run_start == {
        "plan": str(tmp_path / "test_plan.yaml"),
        "scenarios": ["scenario-1"],
        "test_ids": ["passed-1", "lost-1"],
        "mode": "testing",
    }
    assert _payload("scenario_start") == {
        "scenario": "scenario-1",
        "name": None,
        "description": None,
        "phases": ["phase-1"],
        "mode": "testing",
    }
    assert _payload("phase_start")["groups"] == ["group-1"]
    assert _payload("group_start")["test_ids"] == ["passed-1", "lost-1"]
    assert _payload("test_case_start", test_id="passed-1") == {
        "scenario": "scenario-1",
        "phase": "phase-1",
        "group": "group-1",
        "test_id": "passed-1",
        "title": "Title passed-1",
        "job": OUTCOME,
        "tags": ["t"],
        "metadata": None,
        "targets": ["spine-01"],
        "mode": "testing",
    }
    test_case_end = _payload("test_case_end", test_id="lost-1")
    assert test_case_end["status"] == "lost_applicability"
    assert test_case_end["checks"] == [
        {"status": "lost_applicability", "message": "outcome lost_applicability"}
    ]
    assert _payload("on_failure") == test_case_end
    group_end = _payload("group_end")
    assert group_end["status"] == "lost_applicability"
    assert group_end["counts"] == {"passed": 1, "lost_applicability": 1}
    assert _payload("phase_end")["counts"] == {"passed": 1, "lost_applicability": 1}
    assert _payload("scenario_end") == {
        "scenario": "scenario-1",
        "status": "lost_applicability",
        "mode": "testing",
    }
    run_end = _payload("run_end")
    assert run_end["status"] == "lost_applicability"
    assert run_end["summary"]["total"] == 2
    assert run_end["error"] is None
    assert Path(run_end["run_dir"]).parent == tmp_path / "results"
    assert all(output is not None for output in _RecordingHook.outputs)


def test_payload_mutation_does_not_change_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hook that mutates its context cannot change the plan or results."""

    class _Mutator:
        @property
        def name(self) -> str:
            return "mutator"

        def subscriptions(self) -> set[HookEvent]:
            return {HookEvent.GROUP_START, HookEvent.TEST_CASE_END}

        async def on_event(self, event: HookEvent, context: dict[str, Any]) -> None:
            for value in context.values():
                if isinstance(value, list):
                    value.clear()
            context["status"] = "passed"

    _register("mutator", _Mutator)
    _stage_plan(tmp_path, _one_phase("failed-1", "passed-1"))

    result = _run(tmp_path, monkeypatch)

    assert result.exit_code == 1
    cases = _cases(tmp_path)
    assert cases["failed-1"]["status"] == "failed"
    assert cases["passed-1"]["status"] == "passed"


def test_config_filter_limits_active_hooks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only hooks named in ``[tool.huginn.plugins] hooks`` are called."""
    _register("recorder", _RecordingHook)
    _register("broken", _BrokenHook)
    _stage_plan(
        tmp_path,
        _one_phase("passed-1"),
        pyproject='[tool.huginn.plugins]\nhooks = ["recorder"]\n',
    )

    result = _run(tmp_path, monkeypatch)

    assert result.exit_code == 0, result.stdout
    assert "hook exploded" not in result.stdout
    assert "run_start" in _events()


def test_empty_hooks_list_disables_every_hook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``hooks = []`` loads no hook plugin."""
    _register("recorder", _RecordingHook)
    _stage_plan(
        tmp_path,
        _one_phase("passed-1"),
        pyproject="[tool.huginn.plugins]\nhooks = []\n",
    )

    result = _run(tmp_path, monkeypatch)

    assert result.exit_code == 0, result.stdout
    assert _events() == []


def test_hook_options_reach_the_plugin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``[tool.huginn.plugins.config.<name>]`` is passed as ``config``."""
    configs: list[dict[str, Any]] = []

    class _Configured(_RecordingHook):
        def __init__(self, config: dict[str, Any] | None = None) -> None:
            super().__init__(config)
            configs.append(self.config)

    _register("recorder", _Configured)
    _stage_plan(
        tmp_path,
        _one_phase("passed-1"),
        pyproject='[tool.huginn.plugins.config.recorder]\ncalendar = "lab"\n',
    )

    _run(tmp_path, monkeypatch)

    assert configs == [{"calendar": "lab"}]


def test_raising_hook_warns_and_run_completes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hook that raises prints a warning naming it and the event."""
    _register("broken", _BrokenHook)
    _register("recorder", _RecordingHook)
    _stage_plan(tmp_path, _one_phase("passed-1"))

    result = _run(tmp_path, monkeypatch)

    assert result.exit_code == 0, result.stdout
    stdout = " ".join(result.stdout.split())
    assert "WARNING [hook_error]: Hook 'broken' raised during 'run_start'" in stdout
    assert "raised during 'test_case_start'" in stdout
    assert "RuntimeError: hook exploded" in stdout
    assert _cases(tmp_path)["passed-1"]["status"] == "passed"
    assert _events()[-1] == "run_end"
    log = (tmp_path / "huginn.log").read_text(encoding="utf-8")
    assert "Hook 'broken' raised during 'run_start'" in log


def test_raising_hook_does_not_change_a_failing_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exit code still reflects the test results."""
    _register("broken", _BrokenHook)
    _stage_plan(tmp_path, _one_phase("failed-1"))

    result = _run(tmp_path, monkeypatch)

    assert result.exit_code == 1


@pytest.mark.parametrize(
    ("returned", "reason"),
    [
        (HookSignal.SKIP, "Skipped by hook 'recorder'"),
        (HookSkip("Change freeze"), "Change freeze"),
        (HookSkip(""), "Skipped by hook 'recorder'"),
    ],
)
def test_test_case_skip_records_reason_and_does_not_run_the_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    returned: object,
    reason: str,
) -> None:
    """A skip on ``test_case_start`` records SKIPPED and runs no job step."""
    _register("recorder", _RecordingHook)
    _RecordingHook.skips = {(HookEvent.TEST_CASE_START, "passed-1"): returned}
    _stage_plan(tmp_path, _one_phase("passed-1", "passed-2"))

    result = _run(tmp_path, monkeypatch)

    assert result.exit_code == 0, result.stdout
    cases = _cases(tmp_path)
    assert cases["passed-1"]["status"] == "skipped"
    assert cases["passed-1"]["error"] == reason
    assert cases["passed-1"]["skip_kind"] == "hook"
    assert cases["passed-2"]["status"] == "passed"
    assert _ran(tmp_path, "passed-1") == []
    assert _ran(tmp_path, "passed-2") == ["cleanup", "setup", "test"]
    end = _payload("test_case_end", test_id="passed-1")
    assert end["status"] == "skipped"
    assert end["error"] == reason


def test_skip_reason_appears_in_html_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The HTML detail page shows the hook's skip reason."""
    _register("recorder", _RecordingHook)
    _RecordingHook.skips = {
        (HookEvent.TEST_CASE_START, "passed-1"): HookSkip("Change freeze")
    }
    _stage_plan(tmp_path, _one_phase("passed-1"))

    _run(tmp_path, monkeypatch)

    pages = list((tmp_path / "reports" / "latest").rglob("*.html"))
    assert any("Change freeze" in page.read_text(encoding="utf-8") for page in pages)


def test_group_skip_records_every_test_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A skip on ``group_start`` records the group's test cases SKIPPED."""
    _register("recorder", _RecordingHook)
    _RecordingHook.skips = {(HookEvent.GROUP_START, "group-1"): HookSkip("No window")}
    _stage_plan(
        tmp_path,
        {
            "phase-1": {
                "groups": {"group-1": ["failed-1", "passed-1"], "group-2": ["passed-2"]}
            }
        },
    )

    result = _run(tmp_path, monkeypatch)

    assert result.exit_code == 0, result.stdout
    cases = _cases(tmp_path)
    for test_id in ("failed-1", "passed-1"):
        assert cases[test_id]["status"] == "skipped"
        assert cases[test_id]["error"] == "No window"
        assert cases[test_id]["skip_kind"] == "hook"
        assert _ran(tmp_path, test_id) == []
    assert cases["passed-2"]["status"] == "passed"
    assert _payload("group_end", group="group-1")["status"] == "skipped"
    started = [p["test_id"] for e, p in _RecordingHook.events if e == "test_case_start"]
    assert started == ["passed-2"]


def test_phase_skip_records_every_test_case_and_does_not_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hook-skipped phase records SKIPPED and its dependents still run."""
    _register("recorder", _RecordingHook)
    _RecordingHook.skips = {(HookEvent.PHASE_START, "change"): HookSignal.SKIP}
    _stage_plan(
        tmp_path,
        {
            "change": {"groups": {"group-1": ["failed-1"], "group-2": ["passed-1"]}},
            "post": {"groups": {"group-3": ["passed-2"]}, "depends_on": ["change"]},
        },
    )

    result = _run(tmp_path, monkeypatch)

    assert result.exit_code == 0, result.stdout
    cases = _cases(tmp_path)
    for test_id in ("failed-1", "passed-1"):
        assert cases[test_id]["status"] == "skipped"
        assert cases[test_id]["error"] == "Skipped by hook 'recorder'"
        assert cases[test_id]["skip_kind"] == "hook"
    assert cases["passed-2"]["status"] == "passed"
    assert _payload("phase_end", phase="change")["status"] == "skipped"
    groups_started = [
        p["group"] for e, p in _RecordingHook.events if e == "group_start"
    ]
    assert groups_started == ["group-3"]


def test_hook_skipped_phase_does_not_block_in_learning_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hook skip is not mistaken for a learning-mode skip that blocks."""
    _register("recorder", _RecordingHook)
    _RecordingHook.skips = {(HookEvent.PHASE_START, "pre"): HookSignal.SKIP}
    _stage_plan(
        tmp_path,
        {
            "pre": {"groups": {"group-1": ["learn-1"]}},
            "post": {"groups": {"group-2": ["learn-2"]}, "depends_on": ["pre"]},
        },
    )
    _use_learning_job(tmp_path)

    result = _run(tmp_path, monkeypatch, "run", "--mode", "learning")

    assert result.exit_code == 0, result.stdout
    cases = _cases(tmp_path)
    assert cases["learn-1"]["status"] == "skipped"
    assert cases["learn-2"]["status"] == "passed"


def test_every_skipping_hook_reason_is_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When several hooks skip one test case, all their reasons are kept."""
    _register("recorder", _RecordingHook)
    _register("second", _SecondSkipper)
    _RecordingHook.skips = {(HookEvent.TEST_CASE_START, "both-1"): HookSignal.SKIP}
    _stage_plan(tmp_path, _one_phase("both-1"))

    _run(tmp_path, monkeypatch)

    case = _cases(tmp_path)["both-1"]
    assert case["status"] == "skipped"
    assert case["error"] == "Skipped by hook 'recorder'; Change freeze"


def test_skip_on_non_influencing_event_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A SKIP returned from an ``*_end`` event has no effect."""
    _register("recorder", _RecordingHook)
    _RecordingHook.skips = {(HookEvent.GROUP_END, "group-1"): HookSignal.SKIP}
    _stage_plan(tmp_path, _one_phase("passed-1"))

    result = _run(tmp_path, monkeypatch)

    assert result.exit_code == 0
    assert _cases(tmp_path)["passed-1"]["status"] == "passed"


def test_parallel_groups_and_tests_dispatch_safely(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Parallel siblings each dispatch start before end without crashing."""
    _register("recorder", _RecordingHook)
    _stage_plan(
        tmp_path,
        {
            "phase-1": {
                "groups": {
                    "group-1": ["passed-1", "passed-2", "failed-1"],
                    "group-2": ["passed-3", "errored-1"],
                },
                "strategy": {"parallel": {}},
            }
        },
    )

    result = _run(tmp_path, monkeypatch)

    assert result.exit_code == 1, result.stdout
    events = _RecordingHook.events
    for test_id in ("passed-1", "passed-2", "failed-1", "passed-3", "errored-1"):
        indexes = [
            index
            for index, (event, payload) in enumerate(events)
            if payload.get("test_id") == test_id and event.startswith("test_case_")
        ]
        assert [events[i][0] for i in indexes] == ["test_case_start", "test_case_end"]
    for group_id in ("group-1", "group-2"):
        names = [
            e for e, p in events if p.get("group") == group_id and "test_id" not in p
        ]
        assert names == ["group_start", "group_end"]
    assert _events().count("on_failure") == 1
    assert _events().count("on_error") == 1


def test_blocked_phase_dispatches_no_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A phase blocked by a failed dependency dispatches nothing for its items."""
    _register("recorder", _RecordingHook)
    _stage_plan(
        tmp_path,
        {
            "pre": {"groups": {"group-1": ["failed-1"]}},
            "post": {"groups": {"group-2": ["passed-1"]}, "depends_on": ["pre"]},
        },
    )

    _run(tmp_path, monkeypatch)

    phases = [p["phase"] for e, p in _RecordingHook.events if e == "phase_start"]
    assert phases == ["pre"]
    assert _cases(tmp_path)["passed-1"]["status"] == "blocked"


def test_relearn_dispatches_hooks_in_learning_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`huginn relearn` runs the plan with hooks, in learning mode."""
    _register("recorder", _RecordingHook)
    _stage_plan(tmp_path, _one_phase("learn-1", "learn-2"))
    _use_learning_job(tmp_path)
    _write_failed_testing_run(tmp_path, "learn-2")

    result = _run(tmp_path, monkeypatch, "relearn")

    assert result.exit_code == 0, result.stdout
    assert _payload("run_start")["mode"] == "learning"
    started = [p["test_id"] for e, p in _RecordingHook.events if e == "test_case_start"]
    assert started == ["learn-2"]
    assert _events()[-1] == "run_end"


def test_run_end_fires_when_the_run_aborts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run-level error still dispatches ``run_end`` with status errored."""
    _register("recorder", _RecordingHook)
    _stage_plan(
        tmp_path,
        {
            "a": {"groups": {"group-1": ["passed-1"]}, "depends_on": ["b"]},
            "b": {"groups": {"group-2": ["passed-2"]}, "depends_on": ["a"]},
        },
    )

    result = _run(tmp_path, monkeypatch)

    assert result.exit_code != 0
    run_end = _payload("run_end")
    assert run_end["status"] == "errored"
    assert run_end["summary"] is None
    assert "Unable to resolve phase dependencies" in run_end["error"]
    assert "on_error" not in _events()


def test_no_hooks_installed_dispatches_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no hook plugins, the run behaves as before."""
    _stage_plan(tmp_path, _one_phase("passed-1", "failed-1"))

    result = _run(tmp_path, monkeypatch)

    assert result.exit_code == 1
    assert "hook_error" not in result.stdout
    assert "Hook plugins active" not in (tmp_path / "huginn.log").read_text()
    cases = _cases(tmp_path)
    assert cases["passed-1"]["status"] == "passed"
    assert cases["failed-1"]["status"] == "failed"

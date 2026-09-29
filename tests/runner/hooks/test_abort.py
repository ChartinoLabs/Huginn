"""Tests for hook plugins that abort a run with ``HookAbort``."""

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from huginn.hooks import HookAbort, HookEvent, HookSkip

from ..conftest import _FakeRuntimeBroker, load_report
from .conftest import (
    cases,
    one_phase,
    ran,
    register,
    run_cli,
    stage_plan,
    stage_serial_group,
    use_learning_job,
    write_failed_testing_run,
)


class _Aborter:
    """Record every event and return ``returns[(event, item)]`` for it.

    The item is the test ID, group ID, phase ID or scenario ID of the event,
    or ``""`` for ``run_start`` and ``run_end``.
    """

    hook_name = "testbed-lock"
    events: list[tuple[str, str]] = []
    payloads: list[tuple[str, dict[str, Any]]] = []
    returns: dict[tuple[HookEvent, str], object] = {}

    @property
    def name(self) -> str:
        return self.hook_name

    def subscriptions(self) -> set[HookEvent]:
        return set(HookEvent)

    async def on_event(self, event: HookEvent, context: dict[str, Any]) -> object:
        item = _item(event, context)
        self.events.append((event.value, item))
        recorded = {key: value for key, value in context.items() if key != "output"}
        self.payloads.append((event.value, recorded))
        return self.returns.get((event, item))


class _SecondHook(_Aborter):
    """A second hook, called after ``_Aborter`` for the same events."""

    hook_name = "second"
    events: list[tuple[str, str]] = []
    payloads: list[tuple[str, dict[str, Any]]] = []
    returns: dict[tuple[HookEvent, str], object] = {}


def _item(event: HookEvent, context: dict[str, Any]) -> str:
    """Return the ID of the item an event is about."""
    if event.value.startswith(("test_case_", "on_")):
        return str(context["test_id"])
    for key in ("group", "phase", "scenario"):
        if key in context:
            return str(context[key])
    return ""


@pytest.fixture(autouse=True)
def reset_hooks(fake_hook_entry_points: None) -> None:
    """Install the fake entry points and clear what the hooks recorded."""
    for cls in (_Aborter, _SecondHook):
        cls.events = []
        cls.payloads = []
        cls.returns = {}


def _run_json(tmp_path: Path) -> dict[str, Any]:
    """Return the latest run.json."""
    return load_report(tmp_path)


def _two_phases() -> dict[str, dict[str, Any]]:
    """Return a plan with two independent serial phases of two test cases."""
    return {
        "pre": {"groups": {"group-1": ["passed-1", "passed-2"]}},
        "post": {"groups": {"group-2": ["passed-3", "passed-4"]}},
    }


def test_abort_at_run_start_connects_no_device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An abort on ``run_start`` blocks everything and connects nothing."""
    register("testbed-lock", _Aborter)
    _Aborter.returns = {
        (HookEvent.RUN_START, ""): HookAbort("Testbed 'lab-1' is locked by alice")
    }
    stage_plan(tmp_path, _two_phases())

    result = run_cli(tmp_path, monkeypatch)

    assert result.exit_code == 1, result.stdout
    assert _FakeRuntimeBroker.connect_invocations == 0
    reason = "Run aborted by hook 'testbed-lock': Testbed 'lab-1' is locked by alice"
    for case in cases(tmp_path).values():
        assert case["status"] == "blocked"
        assert case["block_kind"] == "hook_abort"
        assert case["error"] == reason
    assert [event for event, _ in _Aborter.events] == ["run_start", "run_end"]
    for test_id in ("passed-1", "passed-2", "passed-3", "passed-4"):
        assert ran(tmp_path, test_id) == []


def test_run_json_records_the_abort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """run.json has a top-level ``aborted`` field; it is absent otherwise."""
    register("testbed-lock", _Aborter)
    _Aborter.returns = {(HookEvent.PHASE_START, "pre"): HookAbort("Locked")}
    stage_plan(tmp_path, _two_phases())

    run_cli(tmp_path, monkeypatch)

    report = _run_json(tmp_path)
    assert report["aborted"] == {
        "hook": "testbed-lock",
        "event": "phase_start",
        "reason": "Locked",
    }
    assert report["summary"]["blocked"] == 4
    assert report["summary"]["learning_mode_blocked"] == 0


def test_run_json_has_no_aborted_field_for_a_normal_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run that no hook aborted writes no ``aborted`` key."""
    register("testbed-lock", _Aborter)
    stage_plan(tmp_path, one_phase("passed-1"))

    result = run_cli(tmp_path, monkeypatch)

    assert result.exit_code == 0, result.stdout
    assert "aborted" not in _run_json(tmp_path)
    assert _Aborter.payloads[-1][1]["aborted"] is None


def test_cli_prints_the_abort_and_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CLI names the hook, the reason and the event, and exits 1."""
    register("testbed-lock", _Aborter)
    _Aborter.returns = {(HookEvent.RUN_START, ""): HookAbort("Locked by alice")}
    stage_plan(tmp_path, one_phase("passed-1"))

    result = run_cli(tmp_path, monkeypatch)

    assert result.exit_code == 1
    output = " ".join(result.output.split())
    assert (
        "ERROR [hook_abort]: Run aborted by hook 'testbed-lock': Locked by alice "
        "(event 'run_start')"
    ) in output


def test_abort_of_a_learning_run_fails_the_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HOOK_ABORT blocks are not learning-mode blocks: a learning run fails."""
    register("testbed-lock", _Aborter)
    _Aborter.returns = {(HookEvent.RUN_START, ""): HookAbort("Locked")}
    stage_plan(tmp_path, one_phase("learn-1"))
    use_learning_job(tmp_path)

    result = run_cli(tmp_path, monkeypatch, "run", "--mode", "learning")

    assert result.exit_code == 1, result.stdout
    assert _run_json(tmp_path)["summary"]["learning_mode_blocked"] == 0


def test_abort_at_phase_start_blocks_it_and_every_later_phase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``phase_start`` abort: that phase and later ones never run."""
    register("testbed-lock", _Aborter)
    _Aborter.returns = {(HookEvent.PHASE_START, "post"): HookAbort("Window closed")}
    stage_plan(
        tmp_path,
        {
            "pre": {"groups": {"group-1": ["passed-1"]}},
            "post": {"groups": {"group-2": ["passed-2"]}},
            "later": {"groups": {"group-3": ["passed-3"]}},
        },
    )

    result = run_cli(tmp_path, monkeypatch)

    assert result.exit_code == 1
    status = {test_id: case["status"] for test_id, case in cases(tmp_path).items()}
    assert status == {
        "passed-1": "passed",
        "passed-2": "blocked",
        "passed-3": "blocked",
    }
    assert ran(tmp_path, "passed-2") == []
    assert ("phase_end", "post") in _Aborter.events
    assert ("phase_start", "later") not in _Aborter.events
    assert ("group_start", "group-2") not in _Aborter.events
    assert _Aborter.events[-2:] == [("scenario_end", "scenario-1"), ("run_end", "")]
    phases = _run_json(tmp_path)["scenarios"][0]["phases"]
    assert [phase["status"] for phase in phases] == ["passed", "blocked", "blocked"]


def test_abort_at_test_case_start_blocks_it_and_later_test_cases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``test_case_start`` abort: the test case and later ones never run."""
    register("testbed-lock", _Aborter)
    _Aborter.returns = {(HookEvent.TEST_CASE_START, "passed-2"): HookAbort("Stop")}
    stage_plan(tmp_path, _two_phases())
    stage_serial_group(tmp_path)

    run_cli(tmp_path, monkeypatch)

    status = {test_id: case["status"] for test_id, case in cases(tmp_path).items()}
    assert status == {
        "passed-1": "passed",
        "passed-2": "blocked",
        "passed-3": "blocked",
        "passed-4": "blocked",
    }
    assert ran(tmp_path, "passed-2") == []
    assert ("test_case_end", "passed-2") in _Aborter.events
    assert ("test_case_start", "passed-3") not in _Aborter.events
    assert ("group_end", "group-1") in _Aborter.events
    assert ("phase_end", "pre") in _Aborter.events
    assert ("phase_start", "post") not in _Aborter.events
    end = next(p for e, p in _Aborter.payloads if e == "test_case_end")
    assert end["test_id"] == "passed-1"
    blocked_end = [p for e, p in _Aborter.payloads if e == "test_case_end"][1]
    assert blocked_end["status"] == "blocked"
    assert blocked_end["block_kind"] == "hook_abort"


def test_abort_at_group_start_blocks_the_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``group_start`` abort: its test cases never start; ``group_end`` fires."""
    register("testbed-lock", _Aborter)
    _Aborter.returns = {(HookEvent.GROUP_START, "group-1"): HookAbort("Stop")}
    stage_plan(tmp_path, one_phase("passed-1"))

    run_cli(tmp_path, monkeypatch)

    assert cases(tmp_path)["passed-1"]["status"] == "blocked"
    assert ("test_case_start", "passed-1") not in _Aborter.events
    group_end = next(p for e, p in _Aborter.payloads if e == "group_end")
    assert group_end["status"] == "blocked"
    phase = _run_json(tmp_path)["scenarios"][0]["phases"][0]
    assert phase["status"] == "blocked"


def test_fail_fast_abort_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An ``on_failure`` abort keeps the failed result and blocks the rest."""
    register("testbed-lock", _Aborter)
    _Aborter.returns = {(HookEvent.ON_FAILURE, "failed-1"): HookAbort("Fail fast")}
    stage_plan(
        tmp_path,
        {
            "pre": {"groups": {"group-1": ["passed-1", "failed-1", "passed-2"]}},
            "post": {"groups": {"group-2": ["passed-3"]}},
        },
    )
    stage_serial_group(tmp_path)

    result = run_cli(tmp_path, monkeypatch)

    assert result.exit_code == 1
    all_cases = cases(tmp_path)
    assert all_cases["failed-1"]["status"] == "failed"
    assert all_cases["passed-1"]["status"] == "passed"
    assert all_cases["passed-2"]["status"] == "blocked"
    assert all_cases["passed-3"]["status"] == "blocked"
    assert all_cases["passed-3"]["error"] == (
        "Run aborted by hook 'testbed-lock': Fail fast"
    )
    assert _run_json(tmp_path)["aborted"]["event"] == "on_failure"


def test_parallel_siblings_finish_and_later_items_are_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Running siblings finish; queued siblings and later groups do not start."""
    register("testbed-lock", _Aborter)
    _Aborter.returns = {(HookEvent.ON_ERROR, "errored-1"): HookAbort("Fail fast")}
    # Two slots: slow-1 starts and sleeps, errored-1 starts, errors and aborts
    # while slow-1 is still running, and passed-1 waits for a free slot.
    parallel = {"parallel": {"maximum": 2}}
    stage_plan(
        tmp_path,
        {
            "pre": {
                "groups": {
                    "group-1": ["slow-1", "errored-1", "passed-1"],
                    "group-2": ["passed-2"],
                },
                "strategy": {"serial": {}},
            },
            "post": {"groups": {"group-3": ["passed-3"]}},
        },
    )
    plan_path = tmp_path / "test_plan.yaml"
    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    plan["test_case_groups"]["group-1"]["strategy"] = parallel
    plan_path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")

    run_cli(tmp_path, monkeypatch)

    status = {test_id: case["status"] for test_id, case in cases(tmp_path).items()}
    assert status == {
        "slow-1": "passed",
        "errored-1": "errored",
        "passed-1": "blocked",
        "passed-2": "blocked",
        "passed-3": "blocked",
    }
    assert ran(tmp_path, "slow-1") == ["cleanup", "setup", "test"]
    assert ran(tmp_path, "passed-1") == []
    abort_index = _Aborter.events.index(("on_error", "errored-1"))
    assert _Aborter.events.index(("test_case_end", "slow-1")) > abort_index
    assert ("test_case_start", "passed-1") not in _Aborter.events
    assert ("group_start", "group-2") not in _Aborter.events
    assert _Aborter.events[-1] == ("run_end", "")


def test_run_end_payload_carries_the_abort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``run_end`` fires after an abort, with the abort in its payload."""
    register("testbed-lock", _Aborter)
    _Aborter.returns = {(HookEvent.SCENARIO_START, "scenario-1"): HookAbort("Stop")}
    stage_plan(tmp_path, one_phase("passed-1"))

    run_cli(tmp_path, monkeypatch)

    event, payload = _Aborter.payloads[-1]
    assert event == "run_end"
    assert payload["status"] == "blocked"
    assert payload["summary"]["blocked"] == 1
    assert payload["error"] is None
    assert payload["aborted"] == {
        "hook": "testbed-lock",
        "event": "scenario_start",
        "reason": "Stop",
    }
    assert ("scenario_end", "scenario-1") in _Aborter.events
    assert ("phase_start", "phase-1") not in _Aborter.events


def test_first_abort_wins_and_later_hooks_still_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first hook's abort is recorded; the second hook is still called."""
    register("testbed-lock", _Aborter)
    register("second", _SecondHook)
    _Aborter.returns = {(HookEvent.RUN_START, ""): HookAbort("First")}
    _SecondHook.returns = {(HookEvent.RUN_START, ""): HookAbort("Second")}
    stage_plan(tmp_path, one_phase("passed-1"))

    run_cli(tmp_path, monkeypatch)

    assert _run_json(tmp_path)["aborted"]["reason"] == "First"
    assert ("run_start", "") in _SecondHook.events
    assert cases(tmp_path)["passed-1"]["error"] == (
        "Run aborted by hook 'testbed-lock': First"
    )


@pytest.mark.parametrize(
    "event", [HookEvent.TEST_CASE_START, HookEvent.GROUP_START, HookEvent.PHASE_START]
)
def test_abort_takes_precedence_over_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, event: HookEvent
) -> None:
    """When one hook skips an item and another aborts, the item is BLOCKED."""
    register("skipper", _SecondHook)
    register("testbed-lock", _Aborter)
    item = {
        HookEvent.TEST_CASE_START: "passed-1",
        HookEvent.GROUP_START: "group-1",
        HookEvent.PHASE_START: "phase-1",
    }[event]
    _SecondHook.returns = {(event, item): HookSkip("Change freeze")}
    _Aborter.returns = {(event, item): HookAbort("Locked")}
    stage_plan(tmp_path, one_phase("passed-1"))

    result = run_cli(tmp_path, monkeypatch)

    assert result.exit_code == 1
    case = cases(tmp_path)["passed-1"]
    assert case["status"] == "blocked"
    assert case["block_kind"] == "hook_abort"
    assert case["skip_kind"] is None


def test_abort_from_run_end_is_ignored_with_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``run_end`` cannot abort: the result stands and a warning is printed."""
    register("testbed-lock", _Aborter)
    _Aborter.returns = {(HookEvent.RUN_END, ""): HookAbort("Too late")}
    stage_plan(tmp_path, one_phase("passed-1"))

    result = run_cli(tmp_path, monkeypatch)

    assert result.exit_code == 0, result.stdout
    output = " ".join(result.output.split())
    assert (
        "WARNING [hook_abort_ignored]: Hook 'testbed-lock' returned HookAbort "
        "from 'run_end'"
    ) in output
    assert "aborted" not in _run_json(tmp_path)


def test_abort_from_run_end_after_an_error_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The error path of ``run_end`` also ignores an abort."""
    register("testbed-lock", _Aborter)
    _Aborter.returns = {(HookEvent.RUN_END, ""): HookAbort("Too late")}
    stage_plan(
        tmp_path,
        {
            "a": {"groups": {"group-1": ["passed-1"]}, "depends_on": ["b"]},
            "b": {"groups": {"group-2": ["passed-2"]}, "depends_on": ["a"]},
        },
    )

    result = run_cli(tmp_path, monkeypatch)

    assert result.exit_code != 0
    assert _Aborter.events[-1] == ("run_end", "")
    assert "hook_abort_ignored" in " ".join(result.output.split())


def test_html_report_shows_the_abort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dashboard shows a banner with the abort reason and event."""
    register("testbed-lock", _Aborter)
    _Aborter.returns = {(HookEvent.RUN_START, ""): HookAbort("Locked by alice")}
    stage_plan(tmp_path, one_phase("passed-1"))

    run_cli(tmp_path, monkeypatch)

    dashboard = (tmp_path / "reports" / "latest" / "index.html").read_text(
        encoding="utf-8"
    )
    assert "abort-banner" in dashboard
    assert "Run aborted by hook &#39;testbed-lock&#39;: Locked by alice" in dashboard
    assert "<code>run_start</code>" in dashboard


def test_relearn_honours_an_abort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`huginn relearn` blocks and exits 1 when a hook aborts it."""
    register("testbed-lock", _Aborter)
    _Aborter.returns = {(HookEvent.RUN_START, ""): HookAbort("Locked")}
    stage_plan(tmp_path, one_phase("learn-1", "learn-2"))
    use_learning_job(tmp_path)
    write_failed_testing_run(tmp_path, "learn-2")

    result = run_cli(tmp_path, monkeypatch, "relearn")

    assert result.exit_code == 1, result.stdout
    assert _FakeRuntimeBroker.connect_invocations == 0
    assert "ERROR [hook_abort]" in " ".join(result.output.split())
    run_json = sorted((tmp_path / "results").glob("*-learning/run.json"))[-1]
    payload = json.loads(run_json.read_text(encoding="utf-8"))
    assert payload["aborted"]["hook"] == "testbed-lock"
    assert payload["summary"]["blocked"] == 1
    assert ran(tmp_path, "learn-2") == []

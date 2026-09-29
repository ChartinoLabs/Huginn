"""Run the use-case hook plugins from docs/reference/hooks.md through the runner.

Each test extracts one plugin's code from the page, installs it as a hook
plugin, and runs a plan through `huginn run`, as a project would.
"""

import asyncio
import json
import os
import re
import socket
import threading
import time
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml
from aiohttp import web

from huginn import __version__
from huginn.hooks import HookEvent

from ..conftest import _FakeRuntimeBroker, load_report
from .conftest import (
    cases,
    cases as _cases,
    one_phase,
    one_phase as _one_phase,
    register,
    register as _register,
    run_cli,
    run_cli as _run,
    stage_plan,
    stage_plan as _stage_plan,
)

_PAGE = Path(__file__).resolve().parents[3] / "docs" / "reference" / "hooks.md"


@pytest.fixture(autouse=True)
def install_fake_entry_points(fake_hook_entry_points: None) -> None:
    """Serve registered hooks as installed entry points in every test."""


def _example(module: str, class_name: str) -> type:
    """Load ``class_name`` from the page's ``# acme_hooks/<module>.py`` block."""
    return _class_from_block(rf"# acme_hooks/{module}\.py\n", class_name)


def _class_from_block(first_line: str, class_name: str) -> type:
    """Execute the page's Python block that starts with ``first_line``."""
    text = _PAGE.read_text(encoding="utf-8")
    match = re.search(rf"```python\n({first_line}.*?)```", text, flags=re.S)
    assert match, f"no Python block starting with {first_line!r} in {_PAGE}"
    namespace: dict[str, Any] = {"__name__": "acme_hooks"}
    exec(compile(match.group(1), str(_PAGE), "exec"), namespace)  # noqa: S102
    return namespace[class_name]


def test_fail_fast_example_stops_at_the_first_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fail-fast snippet in "Aborting the run" blocks what follows a failure."""
    fail_fast = _class_from_block(
        r"from typing import Any\n\nfrom huginn.hooks import HookAbort", "FailFastHook"
    )
    register("fail-fast", fail_fast)
    stage_plan(
        tmp_path,
        {
            "pre": {"groups": {"group-1": ["failed-1"]}},
            "post": {"groups": {"group-2": ["passed-1"]}},
        },
    )

    result = run_cli(tmp_path, monkeypatch)

    assert result.exit_code == 1
    assert load_report(tmp_path)["aborted"] == {
        "hook": "fail-fast",
        "event": "on_failure",
        "reason": "Stopping after failed-1 failed",
    }
    assert cases(tmp_path)["passed-1"]["status"] == "blocked"


def _pyproject(name: str, options: Mapping[str, object]) -> str:
    """Return a pyproject.toml that configures the hook ``name``."""
    lines = [f"[tool.huginn.plugins.config.{name}]"]
    lines += [f"{key} = {json.dumps(value)}" for key, value in options.items()]
    return "\n".join(lines) + "\n"


class _Receiver:
    """An aiohttp app on localhost, in its own thread, that records posts."""

    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []
        self.status = 200
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}/hook"

    def __enter__(self) -> "_Receiver":
        self._thread.start()
        assert self._ready.wait(5), "webhook receiver did not start"
        return self

    def __exit__(self, *_exc: object) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(5)

    def _serve(self) -> None:
        asyncio.set_event_loop(self._loop)
        app = web.Application()
        app.router.add_post("/hook", self._handle)
        runner = web.AppRunner(app)
        self._loop.run_until_complete(runner.setup())
        site = web.TCPSite(runner, "127.0.0.1", self.port)
        self._loop.run_until_complete(site.start())
        self._ready.set()
        self._loop.run_forever()
        self._loop.run_until_complete(runner.cleanup())
        self._loop.close()

    async def _handle(self, request: web.Request) -> web.Response:
        self.posts.append(
            {
                "json": await request.json(),
                "authorization": request.headers.get("Authorization"),
            }
        )
        return web.json_response({"ok": True}, status=self.status)


@pytest.fixture
def receiver() -> Iterator[_Receiver]:
    """Serve a local webhook endpoint for the duration of a test."""
    with _Receiver() as server:
        yield server


def test_run_notify_example_posts_start_phase_and_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, receiver: _Receiver
) -> None:
    """The run-notify example posts run start, each phase end and run end."""
    register("run-notify", _example("run_notify", "RunNotifyHook"))
    monkeypatch.setenv("NOTIFY_TOKEN", "s3cret")
    stage_plan(
        tmp_path,
        {
            "pre": {"groups": {"group-1": ["passed-1", "failed-1"]}},
            "post": {"groups": {"group-2": ["passed-2"]}},
        },
        pyproject=_pyproject(
            "run-notify", {"url": receiver.url, "token_env": "NOTIFY_TOKEN"}
        ),
    )

    result = run_cli(tmp_path, monkeypatch)

    assert result.exit_code == 1, result.stdout
    assert "hook_error" not in result.stdout
    bodies = [post["json"] for post in receiver.posts]
    assert [body["event"] for body in bodies] == [
        "run_start",
        "phase_end",
        "phase_end",
        "run_end",
    ]
    assert {post["authorization"] for post in receiver.posts} == {"Bearer s3cret"}
    start, pre, post, end = bodies
    assert start["data"]["test_count"] == 3
    assert start["data"]["scenarios"] == ["scenario-1"]
    assert start["data"]["plan"].endswith("test_plan.yaml")
    assert pre["data"]["counts"] == {"passed": 1, "failed": 1}
    assert pre["text"] == "Phase scenario-1/pre failed: passed=1 failed=1"
    assert post["data"]["status"] == "passed"
    assert end["data"]["status"] == "failed"
    assert end["data"]["summary"]["total"] == 3
    assert end["data"]["elapsed_seconds"] > 0
    assert end["data"]["aborted"] is None
    assert end["text"].startswith("Huginn run failed in ")


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ({"format": "webex", "room_id": "room-42"}, {"roomId", "markdown"}),
        ({"format": "slack"}, {"text"}),
    ],
)
def test_run_notify_example_webex_and_slack_payloads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    receiver: _Receiver,
    options: dict[str, str],
    expected: set[str],
) -> None:
    """The ``format`` option reshapes every post for Webex or Slack."""
    register("run-notify", _example("run_notify", "RunNotifyHook"))
    monkeypatch.setenv("SLACK_URL", receiver.url)
    stage_plan(
        tmp_path,
        one_phase("passed-1"),
        pyproject=_pyproject("run-notify", {"url_env": "SLACK_URL", **options}),
    )

    run_cli(tmp_path, monkeypatch)

    assert len(receiver.posts) == 3
    for post in receiver.posts:
        body = post["json"]
        assert set(body) == expected
        if "roomId" in body:
            assert body["roomId"] == "room-42"
    assert receiver.posts[0]["authorization"] is None


def test_run_notify_example_failure_does_not_fail_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, receiver: _Receiver
) -> None:
    """A webhook that rejects every post prints warnings; the run passes."""
    register("run-notify", _example("run_notify", "RunNotifyHook"))
    receiver.status = 500
    stage_plan(
        tmp_path,
        one_phase("passed-1"),
        pyproject=_pyproject("run-notify", {"url": receiver.url}),
    )

    result = run_cli(tmp_path, monkeypatch)

    assert result.exit_code == 0, result.stdout
    assert "WARNING [hook_error]: Hook 'run-notify' raised" in " ".join(
        result.stdout.split()
    )
    assert cases(tmp_path)["passed-1"]["status"] == "passed"


def test_run_notify_example_reports_an_abort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, receiver: _Receiver
) -> None:
    """The run_end post names the hook that aborted the run."""
    lock_dir = tmp_path / "locks"
    _hold_lease(lock_dir, "test_plan", ttl=600)
    register("testbed-lock", _example("testbed_lock", "TestbedLockHook"))
    register("run-notify", _example("run_notify", "RunNotifyHook"))
    stage_plan(
        tmp_path,
        one_phase("passed-1"),
        pyproject=_pyproject("run-notify", {"url": receiver.url})
        + _pyproject("testbed-lock", {"lock_dir": str(lock_dir)}),
    )

    run_cli(tmp_path, monkeypatch)

    end = receiver.posts[-1]["json"]
    assert end["event"] == "run_end"
    assert end["data"]["aborted"]["hook"] == "testbed-lock"
    assert (
        "(aborted by hook 'testbed-lock': Testbed 'test_plan' is locked"
        in (end["text"])
    )


def _hold_lease(lock_dir: Path, key: str, *, ttl: float) -> dict[str, Any]:
    """Write a lease for ``key`` held by another run, expiring in ``ttl``."""
    lock_dir.mkdir(parents=True, exist_ok=True)
    now = time.time()
    lease = {
        "user": "alice",
        "host": "lab-host-2",
        "pid": 4242,
        "acquired_at": now - 60,
        "expires_at": now + ttl,
    }
    (lock_dir / f"{key}.lease").write_text(json.dumps(lease), encoding="utf-8")
    return lease


def test_testbed_lock_example_second_run_aborts_while_the_first_holds_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two runs back to back: the second aborts and connects no device."""
    lock_class = _example("testbed_lock", "TestbedLockHook")
    lock_dir = tmp_path / "locks"
    config = {"lock_dir": str(lock_dir), "key": "lab-1", "ttl_seconds": 600}
    holder = lock_class(config=config)
    holder.owner = {**holder.owner, "pid": os.getpid() + 1}
    started = holder.on_event(HookEvent.RUN_START, {"plan": "plan.yaml"})
    assert asyncio.run(started) is None
    register("testbed-lock", lock_class)
    stage_plan(
        tmp_path, one_phase("passed-1"), pyproject=_pyproject("testbed-lock", config)
    )

    result = run_cli(tmp_path, monkeypatch)

    assert result.exit_code == 1, result.stdout
    assert _FakeRuntimeBroker.connect_invocations == 0
    case = cases(tmp_path)["passed-1"]
    assert case["status"] == "blocked"
    assert case["block_kind"] == "hook_abort"
    assert re.fullmatch(
        r"Run aborted by hook 'testbed-lock': Testbed 'lab-1' is locked by "
        r"\S+@\S+ since \d\d:\d\d \(expires \d\d:\d\d\)",
        case["error"],
    )
    assert load_report(tmp_path)["aborted"]["event"] == "run_start"
    assert "ERROR [hook_abort]" in " ".join(result.output.split())
    lease = json.loads((lock_dir / "lab-1.lease").read_text(encoding="utf-8"))
    assert lease["pid"] == os.getpid() + 1, "the aborted run released the lease"


def test_testbed_lock_example_releases_the_lease_after_a_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A normal run takes, renews and releases the lease; the next run can too."""
    lock_dir = tmp_path / "locks"
    register("testbed-lock", _example("testbed_lock", "TestbedLockHook"))
    stage_plan(
        tmp_path,
        {
            "pre": {"groups": {"group-1": ["passed-1"]}},
            "post": {"groups": {"group-2": ["passed-2"]}},
        },
        pyproject=_pyproject("testbed-lock", {"lock_dir": str(lock_dir)}),
    )

    first = run_cli(tmp_path, monkeypatch)
    second = run_cli(tmp_path, monkeypatch)

    assert first.exit_code == 0, first.stdout
    assert second.exit_code == 0, second.stdout
    assert "hook_error" not in first.stdout + second.stdout
    assert list(lock_dir.iterdir()) == []
    assert _FakeRuntimeBroker.connect_invocations == 2


def test_testbed_lock_example_takes_over_an_expired_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lease whose TTL has passed, from a run that crashed, is taken over."""
    lock_dir = tmp_path / "locks"
    _hold_lease(lock_dir, "test_plan", ttl=-5)
    register("testbed-lock", _example("testbed_lock", "TestbedLockHook"))
    stage_plan(
        tmp_path,
        one_phase("passed-1"),
        pyproject=_pyproject("testbed-lock", {"lock_dir": str(lock_dir)}),
    )

    result = run_cli(tmp_path, monkeypatch)

    assert result.exit_code == 0, result.stdout
    assert cases(tmp_path)["passed-1"]["status"] == "passed"
    assert list(lock_dir.iterdir()) == []


def test_testbed_lock_example_does_not_release_a_lease_it_lost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run whose lease was taken over aborts at the next phase_start."""
    lock_dir = tmp_path / "locks"
    lock_class: Any = _example("testbed_lock", "TestbedLockHook")

    class _Stolen(lock_class):
        """Lose the lease to another run right after taking it."""

        async def on_event(self, event: HookEvent, context: dict[str, Any]) -> object:
            result = await super().on_event(event, context)
            if event == HookEvent.RUN_START and result is None:
                _hold_lease(lock_dir, "test_plan", ttl=600)
            return result

    register("testbed-lock", _Stolen)
    stage_plan(
        tmp_path,
        one_phase("passed-1"),
        pyproject=_pyproject("testbed-lock", {"lock_dir": str(lock_dir)}),
    )

    result = run_cli(tmp_path, monkeypatch)

    assert result.exit_code == 1
    assert cases(tmp_path)["passed-1"]["error"] == (
        "Run aborted by hook 'testbed-lock': Lost the lease on testbed 'test_plan'"
    )
    lease = json.loads((lock_dir / "test_plan.lease").read_text(encoding="utf-8"))
    assert lease["user"] == "alice"


@pytest.mark.parametrize("expired", [False, True])
def test_testbed_lock_example_backend_admits_one_of_many_racing_runs(
    tmp_path: Path, expired: bool
) -> None:
    """Many threads racing for one free or expired lease: exactly one wins."""
    hook_class = _example("testbed_lock", "TestbedLockHook")
    backend = hook_class.__init__.__globals__["FileLeaseBackend"](tmp_path)
    if expired:
        _hold_lease(tmp_path, "lab-1", ttl=-5)
    barrier = threading.Barrier(16)
    winners: list[int] = []

    def contend(pid: int) -> None:
        owner = {"user": "u", "host": "h", "pid": pid}
        barrier.wait()
        if backend.acquire("lab-1", owner, 600) is None:
            winners.append(pid)

    threads = [threading.Thread(target=contend, args=(i,)) for i in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(winners) == 1, winners
    lease = json.loads((tmp_path / "lab-1.lease").read_text(encoding="utf-8"))
    assert lease["pid"] == winners[0]


def test_job_telemetry_example_sends_one_record_per_test_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, receiver: _Receiver
) -> None:
    """The telemetry example posts one batch and appends the same JSONL records."""
    register("job-telemetry", _example("job_telemetry", "JobTelemetryHook"))
    monkeypatch.setenv("TELEMETRY_TOKEN", "t0ken")
    jsonl = tmp_path / "results" / "telemetry.jsonl"
    stage_plan(
        tmp_path,
        {
            "pre": {"groups": {"group-1": ["passed-1", "failed-1", "errored-1"]}},
            "post": {"groups": {"group-2": ["passed-1"]}},
        },
        pyproject=_pyproject(
            "job-telemetry",
            {
                "url": receiver.url,
                "token_env": "TELEMETRY_TOKEN",
                "jsonl_path": str(jsonl),
            },
        ),
    )

    result = run_cli(tmp_path, monkeypatch)

    assert result.exit_code == 1
    assert "hook_error" not in result.stdout
    assert len(receiver.posts) == 1
    assert receiver.posts[0]["authorization"] == "Bearer t0ken"
    batch = receiver.posts[0]["json"]
    assert batch["run_status"] == "errored"
    records = batch["records"]
    by_context = {(r["phase"], r["test_id"]): r for r in records}
    assert set(by_context) == {
        ("pre", "passed-1"),
        ("pre", "failed-1"),
        ("pre", "errored-1"),
        ("post", "passed-1"),
    }
    errored = by_context[("pre", "errored-1")]
    assert errored["status"] == "errored"
    assert errored["error_code"] == "execution_error"
    assert errored["job"] == "jobs/test_outcome.py"
    assert errored["tags"] == ["t"]
    assert errored["target_count"] == 1
    assert errored["title"] == "Title errored-1"
    assert errored["mode"] == "testing"
    assert errored["duration_seconds"] >= 0
    assert "checks" not in errored
    assert "error" not in errored
    assert {r["huginn_version"] for r in records} == {__version__}
    assert len({r["run_id"] for r in records}) == 1
    assert batch["run_id"] == records[0]["run_id"]
    lines = jsonl.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == records


def test_job_telemetry_example_includes_checks_only_when_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``include_checks`` adds each test case's checks to its record."""
    register("job-telemetry", _example("job_telemetry", "JobTelemetryHook"))
    jsonl = tmp_path / "telemetry.jsonl"
    stage_plan(
        tmp_path,
        one_phase("failed-1"),
        pyproject=_pyproject(
            "job-telemetry", {"jsonl_path": str(jsonl), "include_checks": True}
        ),
    )

    run_cli(tmp_path, monkeypatch)

    (record,) = [json.loads(line) for line in jsonl.read_text().splitlines()]
    assert record["checks"] == [{"status": "failed", "message": "outcome failed"}]


def _documented_example_hook() -> type:
    """Load the example plugin class from the hook reference page."""
    page = Path(__file__).resolve().parents[3] / "docs" / "reference" / "hooks.md"
    text = page.read_text(encoding="utf-8")
    source = text.split("```python\n", 1)[1].split("```", 1)[0]
    namespace: dict[str, Any] = {}
    exec(compile(source, str(page), "exec"), namespace)  # noqa: S102
    return namespace["ChangeWindowHook"]


@pytest.mark.parametrize("allow", [False, True])
def test_documented_example_hook_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, allow: bool
) -> None:
    """The example in docs/reference/hooks.md skips and reports as documented."""
    _register("change-window", _documented_example_hook())
    pyproject = (
        "[tool.huginn.plugins.config.change-window]\nallow_disruptive = true\n"
        if allow
        else None
    )
    _stage_plan(tmp_path, _one_phase("passed-1", "failed-1"), pyproject=pyproject)
    plan_path = tmp_path / "test_plan.yaml"
    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    plan["test_cases"]["passed-1"]["tags"] = ["disruptive"]
    plan_path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")

    result = _run(tmp_path, monkeypatch)

    cases = _cases(tmp_path)
    expected = "passed" if allow else "skipped"
    assert cases["passed-1"]["status"] == expected
    if not allow:
        assert cases["passed-1"]["error"] == "Outside the change window"
    assert "change-window: failed-1 failed" in " ".join(result.stdout.split())

# Hook Plugins

A hook plugin runs your code at fixed points of a `huginn run` or `huginn relearn`: when the run starts and ends, around each scenario, phase, group and test case, and when a test case fails or errors. A hook can skip a phase, group or test case before it runs, for example to enforce a change window, or stop the whole run, for example when another run holds the testbed. This page covers the protocol, the events and their payloads, skipping and aborting, how errors in a hook are handled, and complete plugins for common [use cases](#use-cases).

To select installed hooks and pass them options, see [Configuration - Hooks](configuration.md#hooks).

## Commands that dispatch hooks

`huginn run` and `huginn relearn` load the active hook plugins once per run and dispatch events to them. `huginn execute` runs single commands rather than a test plan, so it dispatches no events. The other commands do not run jobs.

With no hook plugin installed, or with `hooks = []`, no event is dispatched and no payload is built.

## Writing a hook plugin

A hook plugin is a class that implements the `HookPlugin` protocol from `huginn.hooks`:

| Member                           | Description                                                                                                                                                                              |
| -------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`                           | Property. The name used in log messages, warnings and generic skip reasons. Use the entry point name.                                                                                    |
| `subscriptions()`                | Returns the set of `HookEvent` values the hook receives. Other events are not delivered.                                                                                                 |
| `async on_event(event, context)` | Called for each subscribed event. `context` is a dict described in [Event payloads](#event-payloads). The return value matters only for [skipping and aborting](#skipping-and-aborting). |

The class needs no base class. Huginn instantiates it once per run. When the project sets options for it in `[tool.huginn.plugins.config.<name>]`, Huginn calls `cls(config=<options>)`; otherwise it calls `cls()`. Accept `config` as an optional keyword argument to support both.

### Complete example

This plugin skips test cases tagged `disruptive` unless the project allows them, and prints a line for every failed test case:

```python
# acme_hooks/change_window.py
from typing import Any

from huginn.hooks import HookEvent, HookSkip


class ChangeWindowHook:
    """Skip disruptive test cases outside a change window."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.allow_disruptive = bool((config or {}).get("allow_disruptive", False))

    @property
    def name(self) -> str:
        return "change-window"

    def subscriptions(self) -> set[HookEvent]:
        return {HookEvent.TEST_CASE_START, HookEvent.ON_FAILURE}

    async def on_event(
        self, event: HookEvent, context: dict[str, Any]
    ) -> HookSkip | None:
        if event == HookEvent.TEST_CASE_START:
            if "disruptive" in context["tags"] and not self.allow_disruptive:
                return HookSkip("Outside the change window")
            return None
        output = context["output"]
        if output is not None:
            output.status(f"change-window: {context['test_id']} {context['status']}")
        return None
```

Register the class in the `huginn.hooks` entry point group of the package that provides it:

```toml
# pyproject.toml of acme-hooks
[project]
name = "acme-hooks"
version = "1.0.0"
dependencies = ["huginn-framework"]

[project.entry-points."huginn.hooks"]
change-window = "acme_hooks.change_window:ChangeWindowHook"
```

After `pip install acme-hooks` (or `uv add acme-hooks`) in the project's environment, every run loads the hook. To pass it options, add a table to the project's `pyproject.toml`:

```toml
[tool.huginn.plugins.config.change-window]
allow_disruptive = true
```

## Events

`huginn.hooks.HookEvent` defines these events, dispatched in this order for a plan with one scenario, phase, group and test case:

| Event             | Dispatched                                                                                   | Can skip | Can abort |
| ----------------- | -------------------------------------------------------------------------------------------- | -------- | --------- |
| `run_start`       | After the testbed and plan are loaded, filtered and planned, before connections are primed   | No       | Yes       |
| `scenario_start`  | Before a scenario's first phase                                                              | No       | Yes       |
| `phase_start`     | Before a phase runs, once its dependencies have finished and none of them blocks it          | Yes      | Yes       |
| `group_start`     | Before a group's test cases run                                                              | Yes      | Yes       |
| `test_case_start` | Before a test case's job runs                                                                | Yes      | Yes       |
| `test_case_end`   | After a test case finishes, including a test case a hook skipped                             | No       | Yes       |
| `on_failure`      | After `test_case_end`, when the test case is `failed` or `lost_applicability`                | No       | Yes       |
| `on_error`        | After `test_case_end`, when the test case is `errored`                                       | No       | Yes       |
| `group_end`       | After all of a group's test cases finish, or after a hook skipped the group                  | No       | Yes       |
| `phase_end`       | After all of a phase's groups finish, or after a hook skipped the phase                      | No       | Yes       |
| `scenario_end`    | After a scenario's last phase                                                                | No       | Yes       |
| `run_end`         | After results and reports are written, or when the run stops with an error after `run_start` | No       | No        |

Every `*_start` event is followed by its `*_end` event for the same item, including when a hook skipped the item or aborted the run on that `*_start` event. A skipped phase or group dispatches no events for the groups and test cases inside it. After a hook aborts the run, no new `*_start` event fires. See [Aborting the run](#aborting-the-run).

A test case that appears in several phases dispatches `test_case_start` and `test_case_end` in each of them. In learning mode Huginn runs its job only once and reuses the result in later phases, but the events still fire for every phase.

### Failures and errors

`on_failure` fires for `failed` and `lost_applicability` test cases, the two statuses in which the job ran and found a deviation. `on_error` fires for `errored` test cases, including a job that raised, a target selector that names an unknown device, and a job that could not be imported.

Neither fires for `blocked` test cases. A blocked test case never ran: its phase is blocked because a phase it depends on failed, errored or was not run in learning mode, and that phase's test cases already dispatched `on_failure` or `on_error`. A blocked phase dispatches no events at all, not even `phase_start`. The `run_end` summary counts blocked test cases.

Neither fires for errors of the run itself, such as a broker that fails to connect or phase dependencies that cannot be resolved. When such an error stops the run after `run_start`, `run_end` fires with `status` set to `errored` and the message in `error`. An error while loading the testbed or plan happens before hooks are loaded, so no event fires.

### Ordering and concurrency

Hooks subscribed to the same event are called one at a time, in the order Huginn discovers their entry points. Each hook call is awaited before the runner continues with that item, so a `*_start` hook finishes before the item runs.

Groups in a phase, and test cases in a group, run concurrently unless the [execution strategy](test-plan.md#group-execution-strategy) is `serial`. For one item the order is always the same: `start`, then `end`. Across concurrent siblings, events interleave in whatever order the items reach them, so `test_case_start` for one test case can come between `test_case_start` and `test_case_end` of another. Scenarios, and phases within a scenario, always run one at a time.

All hooks run in the run's event loop. A hook that blocks, for example with a synchronous HTTP call, stalls every concurrent test case. Use async I/O, or `asyncio.to_thread()` for blocking work. If a hook keeps state across events, remember that concurrent test cases can interleave at every `await`.

## Event payloads

`context` is a new dict for each call. Every value in it is plain data: strings, lists, dicts, numbers and `None`, copied from runner state. Changing it has no effect on the run.

Every event has these two keys:

| Key      | Type             | Description                                                                                                                          |
| -------- | ---------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `mode`   | `str`            | `"learning"` or `"testing"`. `huginn relearn` runs in `"learning"`.                                                                  |
| `output` | `Output \| None` | The run's console output, for messages such as `output.status("...")` or `output.warning("...")`. `None` when the run has no output. |

The other keys depend on the event.

### `run_start`

| Key         | Type        | Description                                                 |
| ----------- | ----------- | ----------------------------------------------------------- |
| `plan`      | `str`       | Path of the test plan file or directory                     |
| `scenarios` | `list[str]` | Scenario IDs that will run, after filtering                 |
| `test_ids`  | `list[str]` | Test case IDs that will run, after filtering, in plan order |

### `run_end`

| Key               | Type            | Description                                                                                                                                                                                                             |
| ----------------- | --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `status`          | `str`           | The run status, as in `run.json`. `errored` when the run stopped with an error, `blocked` when a hook aborted it before any test case ran.                                                                              |
| `summary`         | `dict \| None`  | The summary counts from `run.json`: `status`, `total`, `passed`, `failed`, `errored`, `not_applicable`, `skipped`, `blocked`, `lost_applicability`, `learning_mode_blocked`. `None` when the run stopped with an error. |
| `elapsed_seconds` | `float \| None` | Run duration. `None` when the run stopped with an error.                                                                                                                                                                |
| `run_dir`         | `str`           | The run's directory under the results directory                                                                                                                                                                         |
| `error`           | `str \| None`   | The error that stopped the run, or `None`                                                                                                                                                                               |
| `aborted`         | `dict \| None`  | The hook abort that stopped the run, `{"hook": ..., "event": ..., "reason": ...}` as in `run.json`, or `None`                                                                                                           |

### `scenario_start`

| Key           | Type          | Description                   |
| ------------- | ------------- | ----------------------------- |
| `scenario`    | `str`         | Scenario ID                   |
| `name`        | `str \| None` | Scenario `name` from the plan |
| `description` | `str \| None` | Scenario `description`        |
| `phases`      | `list[str]`   | Phase IDs, in declared order  |

### `scenario_end`

| Key        | Type  | Description                                      |
| ---------- | ----- | ------------------------------------------------ |
| `scenario` | `str` | Scenario ID                                      |
| `status`   | `str` | The scenario's status, rolled up from its phases |

### `phase_start`

| Key           | Type          | Description                  |
| ------------- | ------------- | ---------------------------- |
| `scenario`    | `str`         | Scenario ID                  |
| `phase`       | `str`         | Phase ID                     |
| `name`        | `str \| None` | Phase `name` from the plan   |
| `description` | `str \| None` | Phase `description`          |
| `depends_on`  | `list[str]`   | Phase IDs this phase needs   |
| `groups`      | `list[str]`   | Group IDs, in declared order |

### `phase_end`

| Key        | Type             | Description                                                                                                                   |
| ---------- | ---------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `scenario` | `str`            | Scenario ID                                                                                                                   |
| `phase`    | `str`            | Phase ID                                                                                                                      |
| `status`   | `str`            | The phase's status, `skipped` when a hook skipped it                                                                          |
| `counts`   | `dict[str, int]` | Number of the phase's test cases per status, for example `{"passed": 3, "failed": 1}`. Statuses with no test case are absent. |

### `group_start`

| Key           | Type          | Description                                             |
| ------------- | ------------- | ------------------------------------------------------- |
| `scenario`    | `str`         | Scenario ID                                             |
| `phase`       | `str`         | Phase ID                                                |
| `group`       | `str`         | Group ID                                                |
| `name`        | `str \| None` | Group `name` from the plan                              |
| `description` | `str \| None` | Group `description`                                     |
| `test_ids`    | `list[str]`   | Test case IDs in the group, after filtering and nesting |

### `group_end`

| Key        | Type             | Description                                          |
| ---------- | ---------------- | ---------------------------------------------------- |
| `scenario` | `str`            | Scenario ID                                          |
| `phase`    | `str`            | Phase ID                                             |
| `group`    | `str`            | Group ID                                             |
| `status`   | `str`            | The group's status, `skipped` when a hook skipped it |
| `counts`   | `dict[str, int]` | Number of the group's test cases per status          |

### `test_case_start`

| Key        | Type           | Description                                                                                        |
| ---------- | -------------- | -------------------------------------------------------------------------------------------------- |
| `scenario` | `str`          | Scenario ID                                                                                        |
| `phase`    | `str`          | Phase ID                                                                                           |
| `group`    | `str`          | Group ID                                                                                           |
| `test_id`  | `str`          | Test case ID                                                                                       |
| `title`    | `str`          | Test case `title`                                                                                  |
| `job`      | `str`          | Test case `job`, as written in the plan                                                            |
| `tags`     | `list[str]`    | Test case `tags`                                                                                   |
| `metadata` | `dict \| None` | Test case `metadata`                                                                               |
| `targets`  | `list[str]`    | Names of the devices the test case targets. Empty when no device matches or a selector is invalid. |

### `test_case_end`, `on_failure` and `on_error`

The three events share one payload:

| Key          | Type          | Description                                                                                |
| ------------ | ------------- | ------------------------------------------------------------------------------------------ |
| `scenario`   | `str`         | Scenario ID                                                                                |
| `phase`      | `str`         | Phase ID                                                                                   |
| `group`      | `str`         | Group ID                                                                                   |
| `test_id`    | `str`         | Test case ID                                                                               |
| `title`      | `str`         | Test case `title`                                                                          |
| `status`     | `str`         | The test case's status, as in `run.json`                                                   |
| `error`      | `str \| None` | The error message, or the skip reason for a skipped test case                              |
| `error_code` | `str \| None` | The error category for an errored test case, for example `execution_error`                 |
| `skip_kind`  | `str \| None` | Why a skipped test case was skipped, for example `hook` or `no_matching_targets`           |
| `block_kind` | `str \| None` | `hook_abort` for a test case blocked by an abort on its own `test_case_start`, else `None` |
| `checks`     | `list[dict]`  | The test case's checks, each `{"status": ..., "message": ...}`                             |

## Skipping and aborting

### Skipping items

On `phase_start`, `group_start` and `test_case_start`, a hook can skip the item by returning one of these values from `on_event`:

| Return value                    | Effect                                                                       |
| ------------------------------- | ---------------------------------------------------------------------------- |
| `HookSkip("reason")`            | Skip the item and record `reason`                                            |
| `HookSignal.SKIP`               | Skip the item and record `Skipped by hook '<name>'`, using the hook's `name` |
| `None` or `HookSignal.CONTINUE` | Run the item                                                                 |

Both `HookSkip` and `HookSignal` are in `huginn.hooks`. `HookSkip("")` records the generic reason. On every other event a skip is ignored.

Every subscribed hook is called even after one has skipped the item. When several hooks skip it, the recorded reason joins their reasons with `; `, in hook order, for example `Skipped by hook 'maintenance'; Outside the change window`.

#### What a skip records

A skipped test case does not run: its job's `setup()`, `test()` and `cleanup()` are not called. Skipping a group or phase records every test case in it the same way, and dispatches no events for them. The test cases are recorded with:

- `status` `skipped`
- `error` set to the skip reason, shown in `run.json`, the test case's `result.json` and the HTML report
- `skip_kind` `hook` in `result.json`

A skip does not make the run fail. A phase a hook skipped does not block the phases that depend on it, in either mode: unlike a job skipped because it cannot run in learning mode, a hook skip is a deliberate decision. See [Test Plan Specification - Failure Blocking](test-plan.md#failure-blocking) for how phases block their dependents.

### Aborting the run

On any event except `run_end`, a hook can stop the whole run by returning `HookAbort("reason")` from `huginn.hooks`. Use it when the run must not continue at all, for example because another run holds the testbed, or to stop at the first failure.

This hook stops the run at the first failed test case:

```python
from typing import Any

from huginn.hooks import HookAbort, HookEvent


class FailFastHook:
    @property
    def name(self) -> str:
        return "fail-fast"

    def subscriptions(self) -> set[HookEvent]:
        return {HookEvent.ON_FAILURE}

    async def on_event(self, event: HookEvent, context: dict[str, Any]) -> HookAbort:
        return HookAbort(f"Stopping after {context['test_id']} {context['status']}")
```

What happens next:

- The item of a `*_start` event that aborts does not run. The result of the item of a `*_end`, `on_failure` or `on_error` event stands.
- Test cases that are already running, in parallel with the one that aborted, finish normally. Huginn does not cancel a job during a device operation.
- Nothing new starts: no test case, group, phase or scenario.
- Every test case that has not started is recorded `blocked` with `block_kind` `hook_abort` and the reason `Run aborted by hook '<name>': <reason>`.
- The `*_end` events of the items that already started still fire, then `run_end`. So do the other hooks for the event that aborted.
- Results and reports are written as usual.

A hook that aborts on `run_start` stops the run before any connection is primed, so no device is connected.

#### What an abort records

`run.json` has a top-level `aborted` field, which is absent when no hook aborted the run:

```json
{
  "summary": {
    "status": "failed",
    "total": 12,
    "passed": 4,
    "failed": 1,
    "errored": 0,
    "not_applicable": 0,
    "skipped": 0,
    "blocked": 7,
    "lost_applicability": 0,
    "learning_mode_blocked": 0
  },
  "aborted": {
    "hook": "fail-fast",
    "event": "on_failure",
    "reason": "Stopping after OSPF-002 failed"
  },
  "scenarios": ["..."]
}
```

The same dict is in the `run_end` payload's `aborted` key. The CLI prints a line such as:

```
ERROR [hook_abort]: Run aborted by hook 'testbed-lock': Testbed 'lab-1' is locked by alice@lab-host since 10:02 (event 'run_start')
```

The HTML report shows the reason and the event in a banner above the summary.

An aborted run always exits with code 1, in both modes. Blocked test cases fail the run, and unlike test cases blocked because a phase was not run in learning mode, `hook_abort` blocks also fail a learning run or `huginn relearn`. The run's `status` is `blocked` when no test case ran at all, and otherwise rolls up the test cases that did run.

#### Several hooks

The first hook to return `HookAbort` wins: its hook name, event and reason are recorded. Later hooks for the same event are still called, and later aborts are ignored.

On `phase_start`, `group_start` and `test_case_start`, an abort takes precedence over a skip: when one hook skips the item and another aborts, the item is recorded `blocked`, not `skipped`.

A `HookAbort` returned from `run_end` is ignored, and Huginn prints a `hook_abort_ignored` warning, because the run is already over.

## Errors in a hook

A hook that raises from `on_event` does not stop the run. Huginn prints a warning that names the hook, the event and the exception, and writes it with its traceback to the log:

```
WARNING [hook_error]: Hook 'change-window' raised during 'test_case_start': KeyError: 'calendar'; continuing execution
```

The other hooks for the event are still called, and the item runs as if the failing hook had returned `None`. The warning does not change the run's status or exit code. A hook that should stop the run on an error must catch it and return `HookAbort`.

A hook class that raises while being instantiated is left out of the run with a warning in the log.

## Use cases

Each plugin below is complete and runnable. They are tested against the real runner: the test suite extracts the code from this page, installs it as a hook plugin and runs a plan through `huginn run`. Adapt the names and options to your project. They share one package, `acme-hooks`, whose `pyproject.toml` registers all three:

```toml
# pyproject.toml of acme-hooks
[project]
name = "acme-hooks"
version = "1.0.0"
dependencies = ["huginn-framework"]

[project.entry-points."huginn.hooks"]
run-notify = "acme_hooks.run_notify:RunNotifyHook"
testbed-lock = "acme_hooks.testbed_lock:TestbedLockHook"
job-telemetry = "acme_hooks.job_telemetry:JobTelemetryHook"
```

Huginn does not expand `${VAR}` references in `[tool.huginn.plugins.config]`, unlike the testbed. So that a secret never has to be written in `pyproject.toml`, the plugins below take the name of an environment variable, such as `token_env`, and read the secret from `os.environ` when they need it.

### Run notifications

This plugin posts a message to a webhook when the run starts, after each phase, and when the run ends, including when it stops with an error or a hook aborts it. It uses `aiohttp`, which Huginn already depends on, so posting never blocks the event loop:

```python
# acme_hooks/run_notify.py
"""Post run and phase notifications to a webhook."""

import os
from typing import Any

import aiohttp

from huginn.hooks import HookEvent


class RunNotifyHook:
    """Post a message at run start, after each phase and at run end."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        config = config or {}
        self.url = config.get("url") or os.environ[config["url_env"]]
        self.token_env = config.get("token_env")
        self.format = config.get("format", "generic")
        self.room_id = config.get("room_id")
        self.timeout = aiohttp.ClientTimeout(total=config.get("timeout_seconds", 10))

    @property
    def name(self) -> str:
        return "run-notify"

    def subscriptions(self) -> set[HookEvent]:
        return {HookEvent.RUN_START, HookEvent.PHASE_END, HookEvent.RUN_END}

    async def on_event(self, event: HookEvent, context: dict[str, Any]) -> None:
        if event == HookEvent.RUN_START:
            data = {
                "plan": context["plan"],
                "scenarios": context["scenarios"],
                "test_count": len(context["test_ids"]),
            }
            text = (
                f"Huginn {context['mode']} run started: {data['plan']}, "
                f"{data['test_count']} test case(s) in "
                f"{', '.join(data['scenarios']) or 'no scenario'}"
            )
        elif event == HookEvent.PHASE_END:
            data = {
                key: context[key] for key in ("scenario", "phase", "status", "counts")
            }
            text = (
                f"Phase {data['scenario']}/{data['phase']} {data['status']}: "
                f"{_counts(data['counts'])}"
            )
        else:
            data = {
                key: context[key]
                for key in ("status", "summary", "elapsed_seconds", "error", "aborted")
            }
            text = _run_end_text(data)
        await self._post(self._body(event, text, data))

    def _body(
        self, event: HookEvent, text: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Shape the message for the receiving service."""
        if self.format == "webex":
            return {"roomId": self.room_id, "markdown": text}
        if self.format == "slack":
            return {"text": text}
        return {"source": "huginn", "event": event.value, "text": text, "data": data}

    async def _post(self, body: dict[str, Any]) -> None:
        headers = {}
        if self.token_env:
            token = os.environ.get(self.token_env)
            if not token:
                raise RuntimeError(f"environment variable {self.token_env} is not set")
            headers["Authorization"] = f"Bearer {token}"
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.post(self.url, json=body, headers=headers) as response:
                response.raise_for_status()


def _counts(counts: dict[str, int] | None) -> str:
    """Format status counts, for example ``passed=3 failed=1``."""
    shown = {k: v for k, v in (counts or {}).items() if v and k != "status"}
    return " ".join(f"{status}={count}" for status, count in shown.items()) or "none"


def _run_end_text(data: dict[str, Any]) -> str:
    """Describe how the run ended."""
    text = f"Huginn run {data['status']}"
    if data["elapsed_seconds"] is not None:
        text += f" in {data['elapsed_seconds']:.1f}s"
    if data["summary"] is not None:
        text += f": {_counts(data['summary'])}"
    if data["aborted"] is not None:
        aborted = data["aborted"]
        text += f" (aborted by hook '{aborted['hook']}': {aborted['reason']})"
    if data["error"] is not None:
        text += f" (error: {data['error']})"
    return text
```

Configure it in the project's `pyproject.toml`:

```toml
[tool.huginn.plugins.config.run-notify]
url = "https://hooks.example.net/huginn"
token_env = "NOTIFY_TOKEN"
timeout_seconds = 10
```

| Option            | Default   | Description                                                                                    |
| ----------------- | --------- | ---------------------------------------------------------------------------------------------- |
| `url`             | -         | The webhook URL. Required unless `url_env` is set.                                             |
| `url_env`         | -         | Name of an environment variable that holds the URL, for URLs that embed a secret               |
| `token_env`       | -         | Name of an environment variable that holds a bearer token, sent as `Authorization: Bearer ...` |
| `format`          | `generic` | The message shape: `generic`, `webex` or `slack`                                               |
| `room_id`         | -         | The Webex room ID, for `format = "webex"`                                                      |
| `timeout_seconds` | `10`      | How long one post may take                                                                     |

In the `generic` format, each post is a JSON object with `source`, `event`, `text` and `data`, where `data` holds the plan, scenarios and test count, the phase's status and counts, or the run's status, summary, elapsed time, error and abort.

#### Webex and Slack

The `format` option reshapes the body for two common services:

- Webex, through the [Messages API](https://developer.webex.com/docs/api/v1/messages/create-a-message): `url` is `https://webexapis.com/v1/messages`, `token_env` names a variable holding a bot token, and `room_id` is the room to post in. The body is `{"roomId": ..., "markdown": text}`.
- Slack, through an [incoming webhook](https://api.slack.com/messaging/webhooks): the webhook URL is itself the secret, so set `url_env` instead of `url`, and leave `token_env` unset. The body is `{"text": text}`. For richer messages, return a `blocks` list from `_body` alongside `text`.

```toml
[tool.huginn.plugins.config.run-notify]
url = "https://webexapis.com/v1/messages"
token_env = "WEBEX_BOT_TOKEN"
format = "webex"
room_id = "Y2lzY29zcGFyazovL3VzL1JPT00vNGQ5YTM5"
```

#### What it does and caveats

- A notification that fails, because the service is down, rejects the token or times out, does not fail the run. The post raises, and Huginn prints a `hook_error` warning and continues, as described in [Errors in a hook](#errors-in-a-hook).
- Each post is awaited before the run continues, so a slow service delays the next phase by up to `timeout_seconds`. Keep it short.
- A missing `url_env` variable stops the plugin from being created, which Huginn logs as a warning; the run continues without notifications.
- `test_ids` can be long, so `run_start` sends only the count.

### Testbed lock

This plugin makes sure that only one run at a time uses a testbed. On `run_start` it takes a lease, a lock with an expiry time. When another run already holds an unexpired lease, it returns `HookAbort`, so the run stops before any device is connected. It releases the lease on `run_end`, but only when this run holds it, and it renews the lease on every `phase_start` so that a long run keeps it.

The lease backend is pluggable. The one shown, `FileLeaseBackend`, keeps each lease as a JSON file in a directory that every host running Huginn against the testbed can reach, such as an NFS share:

```python
# acme_hooks/testbed_lock.py
"""Hold a lease on a testbed for the duration of a run."""

import asyncio
import getpass
import json
import os
import socket
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from huginn.hooks import HookAbort, HookEvent

Lease = dict[str, Any]


class LeaseBackend(Protocol):
    """Where leases are kept. Every method is called from a worker thread."""

    def acquire(self, key: str, owner: Lease, ttl: float) -> Lease | None:
        """Take the lease and return None, or return the current holder's lease."""
        ...

    def refresh(self, key: str, owner: Lease, ttl: float) -> bool:
        """Extend the lease if ``owner`` holds it; return False if it does not."""
        ...

    def release(self, key: str, owner: Lease) -> None:
        """Remove the lease if ``owner`` holds it."""
        ...


class FileLeaseBackend:
    """Keep each lease as ``<directory>/<key>.lease``, a JSON file."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    def acquire(self, key: str, owner: Lease, ttl: float) -> Lease | None:
        path = self.directory / f"{key}.lease"
        guard = self.directory / f"{key}.takeover"
        for _ in range(3):
            if _create(path, _lease(owner, ttl)):
                return None
            current = _read(path)
            if current is not None and current["expires_at"] > time.time():
                return current
            # The lease expired. Only the run that creates the guard file may
            # replace it, and only if nobody replaced it first.
            if current is not None and _create(guard, _lease(owner, 30)):
                try:
                    if _read(path) == current:
                        _replace(path, _lease(owner, ttl))
                        return None
                finally:
                    guard.unlink(missing_ok=True)
            else:
                taker = _read(guard)
                if taker is not None and taker["expires_at"] <= time.time():
                    guard.unlink(missing_ok=True)  # left by a run that crashed
        return _read(path) or _read(guard) or _lease({"user": "?", "host": "?"}, 0)

    def refresh(self, key: str, owner: Lease, ttl: float) -> bool:
        path = self.directory / f"{key}.lease"
        current = _read(path)
        if current is None or not _same_owner(current, owner):
            return False
        _replace(path, _lease(owner, ttl, acquired_at=current["acquired_at"]))
        return True

    def release(self, key: str, owner: Lease) -> None:
        path = self.directory / f"{key}.lease"
        current = _read(path)
        if current is not None and _same_owner(current, owner):
            path.unlink(missing_ok=True)


class TestbedLockHook:
    """Abort the run when another run holds the testbed's lease."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        backend: LeaseBackend | None = None,
    ) -> None:
        config = config or {}
        self.key = config.get("key")
        self.ttl = float(config.get("ttl_seconds", 3600))
        self.backend = backend or FileLeaseBackend(Path(config["lock_dir"]))
        self.owner = {
            "user": getpass.getuser(),
            "host": socket.gethostname(),
            "pid": os.getpid(),
        }
        self.held: str | None = None

    @property
    def name(self) -> str:
        return "testbed-lock"

    def subscriptions(self) -> set[HookEvent]:
        return {HookEvent.RUN_START, HookEvent.PHASE_START, HookEvent.RUN_END}

    async def on_event(
        self, event: HookEvent, context: dict[str, Any]
    ) -> HookAbort | None:
        if event == HookEvent.RUN_START:
            key = self.key or Path(context["plan"]).stem
            holder = await asyncio.to_thread(
                self.backend.acquire, key, self.owner, self.ttl
            )
            if holder is not None:
                return HookAbort(
                    f"Testbed '{key}' is locked by {holder['user']}@{holder['host']} "
                    f"since {_clock(holder['acquired_at'])} "
                    f"(expires {_clock(holder['expires_at'])})"
                )
            self.held = key
        elif self.held is None:
            return None
        elif event == HookEvent.PHASE_START:
            renewed = await asyncio.to_thread(
                self.backend.refresh, self.held, self.owner, self.ttl
            )
            if not renewed:
                lost, self.held = self.held, None
                return HookAbort(f"Lost the lease on testbed '{lost}'")
        else:
            await asyncio.to_thread(self.backend.release, self.held, self.owner)
            self.held = None
        return None


def _lease(owner: Lease, ttl: float, acquired_at: float | None = None) -> Lease:
    now = time.time()
    return {**owner, "acquired_at": acquired_at or now, "expires_at": now + ttl}


def _same_owner(lease: Lease, owner: Lease) -> bool:
    return all(lease.get(key) == value for key, value in owner.items())


def _create(path: Path, lease: Lease) -> bool:
    """Create ``path`` holding ``lease``; return False if it already exists.

    The lease is written to a temporary file first and then hard-linked into
    place. ``os.link`` fails atomically when ``path`` exists, and ``path``
    never exists without its full content.
    """
    temporary = _write_temporary(path, lease)
    try:
        os.link(temporary, path)
    except FileExistsError:
        return False
    finally:
        temporary.unlink()
    return True


def _replace(path: Path, lease: Lease) -> None:
    """Overwrite ``path`` atomically with ``lease``."""
    os.replace(_write_temporary(path, lease), path)


def _write_temporary(path: Path, lease: Lease) -> Path:
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(lease), encoding="utf-8")
    return temporary


def _read(path: Path) -> Lease | None:
    """Return the lease in ``path``, or None if it is missing or unreadable."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _clock(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%H:%M")
```

Configure it in the project's `pyproject.toml`:

```toml
[tool.huginn.plugins.config.testbed-lock]
lock_dir = "/mnt/lab-share/huginn-locks"
key = "lab-1"
ttl_seconds = 3600
```

| Option        | Default                         | Description                                                          |
| ------------- | ------------------------------- | -------------------------------------------------------------------- |
| `lock_dir`    | -                               | Directory that holds the lease files. Required for the file backend. |
| `key`         | The plan file or directory name | The lease's name. Runs with the same key exclude each other.         |
| `ttl_seconds` | `3600`                          | How long a lease lasts without being renewed                         |

A run that finds the testbed locked stops with:

```
ERROR [hook_abort]: Run aborted by hook 'testbed-lock': Testbed 'lab-1' is locked by alice@lab-host-2 since 10:02 (expires 11:02) (event 'run_start')
```

#### What it does and caveats

- The owner is the user, the host name and the process ID, so two runs by the same user on the same host still exclude each other.
- The lease expires after `ttl_seconds`, so a run that crashed, or a host that lost power, cannot hold the testbed for ever. A run renews it on every `phase_start`, so pick a TTL longer than your longest phase. A run whose lease expired and was taken over aborts at its next `phase_start` with `Lost the lease on testbed '<key>'`. For phases that run for hours, renew from a background task started on `run_start` instead.
- A run that is stopped with Ctrl+C before `run_end` leaves its lease until it expires. Delete the lease file to free the testbed sooner.
- Expiry compares wall-clock times written by different hosts, so keep their clocks in sync, for example with NTP.

#### How atomic it is

- Taking a free lease writes it to a temporary file and hard-links that file to the lease's name with `os.link`, which fails if the name exists, in one atomic step. This is the classic lock-file technique: it works on a local file system and on NFS, and a lease file never exists without its content. Creating the lease file directly with `os.open(..., O_CREAT | O_EXCL)` is atomic too, but another run can read the file between its creation and the write of its content, and mistake it for a broken lease. File-sync tools such as Dropbox or OneDrive do not give either guarantee; do not use this backend on them.
- Taking over an expired lease is guarded by a second file created the same way, so two runs cannot both take over one expired lease. Renewing and releasing read the lease and then write or delete it in two steps. They check the owner first, so a run never removes another run's lease on purpose, but a run whose own lease expired and was taken over in the moment between the two steps can still remove the new holder's lease. A TTL longer than any phase makes this practically impossible.

For a hard guarantee, keep leases in a service with atomic compare-and-set, and pass it as `backend`, for example from a subclass whose `__init__` calls `super().__init__(config, backend=RedisLeaseBackend(...))`:

| Backend           | Acquire                                                                    | Refresh and release                                                                              |
| ----------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| Redis             | `SET <key> <owner-json> NX PX <ttl-ms>`, atomic on one Redis server        | A Lua script that runs `PEXPIRE` or `DEL` only when the value still equals the owner             |
| SQL database      | `INSERT` a row with a unique key, or `UPDATE ... WHERE expires_at < now()` | `UPDATE` or `DELETE ... WHERE key = ? AND owner = ?`, each a single atomic statement             |
| HTTP lock service | `POST /leases/<key>` returning 409 with the holder when it is taken        | `PUT` or `DELETE /leases/<key>` with the owner, returning 409 when the caller no longer holds it |

Redis replication is asynchronous, so a lease on a replicated Redis can be lost in a failover; use a single primary for locks.

### Job telemetry

This plugin records one record per test case, pairing `test_case_start` with `test_case_end`, and sends them all in one batch when the run ends. Use it to find slow or flaky jobs across many runs:

```python
# acme_hooks/job_telemetry.py
"""Send one telemetry record per test case at the end of the run."""

import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import aiohttp

import huginn
from huginn.hooks import HookEvent


class JobTelemetryHook:
    """Collect a record per test case and send them at run end."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        config = config or {}
        self.url = config.get("url")
        self.token_env = config.get("token_env")
        self.jsonl_path = config.get("jsonl_path")
        self.include_checks = bool(config.get("include_checks", False))
        self.timeout = aiohttp.ClientTimeout(total=config.get("timeout_seconds", 30))
        self.run_id = uuid.uuid4().hex
        self.started: dict[tuple[str, str, str, str], tuple[float, dict]] = {}
        self.records: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return "job-telemetry"

    def subscriptions(self) -> set[HookEvent]:
        return {HookEvent.TEST_CASE_START, HookEvent.TEST_CASE_END, HookEvent.RUN_END}

    async def on_event(self, event: HookEvent, context: dict[str, Any]) -> None:
        if event == HookEvent.TEST_CASE_START:
            start = {
                "job": context["job"],
                "tags": context["tags"],
                "target_count": len(context["targets"]),
            }
            self.started[_key(context)] = (time.monotonic(), start)
        elif event == HookEvent.TEST_CASE_END:
            self.records.append(self._record(context))
        else:
            await self._send(context)

    def _record(self, context: dict[str, Any]) -> dict[str, Any]:
        started_at, start = self.started.pop(_key(context), (None, {}))
        record = {
            "run_id": self.run_id,
            "huginn_version": huginn.__version__,
            "mode": context["mode"],
            "scenario": context["scenario"],
            "phase": context["phase"],
            "group": context["group"],
            "test_id": context["test_id"],
            "title": context["title"],
            "job": start.get("job"),
            "tags": start.get("tags", []),
            "target_count": start.get("target_count"),
            "status": context["status"],
            "error_code": context["error_code"],
            "duration_seconds": (
                None if started_at is None else time.monotonic() - started_at
            ),
        }
        if self.include_checks:
            record["checks"] = context["checks"]
        return record

    async def _send(self, context: dict[str, Any]) -> None:
        records, self.records = self.records, []
        if self.jsonl_path:
            await asyncio.to_thread(_append_jsonl, Path(self.jsonl_path), records)
        if self.url and records:
            batch = {
                "run_id": self.run_id,
                "huginn_version": huginn.__version__,
                "run_status": context["status"],
                "records": records,
            }
            headers = {}
            if self.token_env:
                headers["Authorization"] = f"Bearer {os.environ[self.token_env]}"
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(
                    self.url, json=batch, headers=headers
                ) as response:
                    response.raise_for_status()


def _key(context: dict[str, Any]) -> tuple[str, str, str, str]:
    return (context["scenario"], context["phase"], context["group"], context["test_id"])


def _append_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
```

Configure it in the project's `pyproject.toml`:

```toml
[tool.huginn.plugins.config.job-telemetry]
url = "https://telemetry.example.net/v1/huginn/records"
token_env = "TELEMETRY_TOKEN"
jsonl_path = "results/telemetry.jsonl"
```

| Option            | Default | Description                                                                                    |
| ----------------- | ------- | ---------------------------------------------------------------------------------------------- |
| `url`             | -       | Where the batch is posted as JSON. No post is made when unset.                                 |
| `token_env`       | -       | Name of an environment variable that holds a bearer token                                      |
| `jsonl_path`      | -       | A file that each record is appended to, one JSON object per line. Nothing is written if unset. |
| `include_checks`  | `false` | Add each test case's `checks`, with their status and message, to its record                    |
| `timeout_seconds` | `30`    | How long the post may take                                                                     |

A record looks like this:

```json
{
  "run_id": "5f0c1c9e8a2b4d0f9a7e6b3c2d1e0f98",
  "huginn_version": "0.4.0",
  "mode": "testing",
  "scenario": "link-shutdown-r1r2",
  "phase": "post-change",
  "group": "ospf",
  "test_id": "OSPF-002",
  "title": "Verify OSPF neighbors",
  "job": "catalog.iosxe.ospf.verify_neighbors",
  "tags": ["ospf", "routing"],
  "target_count": 4,
  "status": "failed",
  "error_code": null,
  "duration_seconds": 3.42
}
```

#### What it does and caveats

- Records are keyed by scenario, phase, group and test ID, because a test case can appear in several phases and runs concurrently with its siblings. The run ID is new for every run.
- `job` is the test case's `job` exactly as written in the plan. A job from a central catalog, referenced by package, is identified by its module path, for example `catalog.iosxe.ospf.verify_neighbors`, so records from many projects that use the same catalog job group together. A local job is a path such as `jobs/verify_ospf.py`.
- The records hold no device output and no credentials. They also leave out the test case's `error`, and `checks` unless `include_checks` is set, because check and error messages can quote device data such as addresses and configuration. Review them before sending them outside your network.
- A test case that was blocked before it started, by a failed dependency or by an abort, dispatches no events, so it has no record. A test case blocked by an abort on its own `test_case_start` has a record with status `blocked`.
- Records are kept in memory until `run_end`. A run that is killed before `run_end` sends nothing. A post that fails prints a `hook_error` warning and does not fail the run; the JSONL file is written first, so it still has the records.

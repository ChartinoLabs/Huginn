# Hook Plugins

A hook plugin runs your code at fixed points of a `huginn run` or `huginn relearn`: when the run starts and ends, around each scenario, phase, group and test case, and when a test case fails or errors. A hook can skip a phase, group or test case before it runs, for example to enforce a change window. This page covers the protocol, the events and their payloads, the skip API, and how errors in a hook are handled.

To select installed hooks and pass them options, see [Configuration - Hooks](configuration.md#hooks).

## Commands that dispatch hooks

`huginn run` and `huginn relearn` load the active hook plugins once per run and dispatch events to them. `huginn execute` runs single commands rather than a test plan, so it dispatches no events. The other commands do not run jobs.

With no hook plugin installed, or with `hooks = []`, no event is dispatched and no payload is built.

## Writing a hook plugin

A hook plugin is a class that implements the `HookPlugin` protocol from `huginn.hooks`:

| Member                           | Description                                                                                                                                                          |
| -------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`                           | Property. The name used in log messages, warnings and generic skip reasons. Use the entry point name.                                                                |
| `subscriptions()`                | Returns the set of `HookEvent` values the hook receives. Other events are not delivered.                                                                             |
| `async on_event(event, context)` | Called for each subscribed event. `context` is a dict described in [Event payloads](#event-payloads). The return value matters only for [skipping](#skipping-items). |

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

| Event             | Dispatched                                                                                   | Can skip |
| ----------------- | -------------------------------------------------------------------------------------------- | -------- |
| `run_start`       | After the testbed and plan are loaded, filtered and planned, before connections are primed   | No       |
| `scenario_start`  | Before a scenario's first phase                                                              | No       |
| `phase_start`     | Before a phase runs, once its dependencies have finished and none of them blocks it          | Yes      |
| `group_start`     | Before a group's test cases run                                                              | Yes      |
| `test_case_start` | Before a test case's job runs                                                                | Yes      |
| `test_case_end`   | After a test case finishes, including a test case a hook skipped                             | No       |
| `on_failure`      | After `test_case_end`, when the test case is `failed` or `lost_applicability`                | No       |
| `on_error`        | After `test_case_end`, when the test case is `errored`                                       | No       |
| `group_end`       | After all of a group's test cases finish, or after a hook skipped the group                  | No       |
| `phase_end`       | After all of a phase's groups finish, or after a hook skipped the phase                      | No       |
| `scenario_end`    | After a scenario's last phase                                                                | No       |
| `run_end`         | After results and reports are written, or when the run stops with an error after `run_start` | No       |

Every `*_start` event is followed by its `*_end` event for the same item, including when a hook skipped the item. A skipped phase or group dispatches no events for the groups and test cases inside it.

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
| `status`          | `str`           | The run status, as in `run.json`. `errored` when the run stopped with an error.                                                                                                                                         |
| `summary`         | `dict \| None`  | The summary counts from `run.json`: `status`, `total`, `passed`, `failed`, `errored`, `not_applicable`, `skipped`, `blocked`, `lost_applicability`, `learning_mode_blocked`. `None` when the run stopped with an error. |
| `elapsed_seconds` | `float \| None` | Run duration. `None` when the run stopped with an error.                                                                                                                                                                |
| `run_dir`         | `str`           | The run's directory under the results directory                                                                                                                                                                         |
| `error`           | `str \| None`   | The error that stopped the run, or `None`                                                                                                                                                                               |

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

| Key          | Type          | Description                                                                      |
| ------------ | ------------- | -------------------------------------------------------------------------------- |
| `scenario`   | `str`         | Scenario ID                                                                      |
| `phase`      | `str`         | Phase ID                                                                         |
| `group`      | `str`         | Group ID                                                                         |
| `test_id`    | `str`         | Test case ID                                                                     |
| `title`      | `str`         | Test case `title`                                                                |
| `status`     | `str`         | The test case's status, as in `run.json`                                         |
| `error`      | `str \| None` | The error message, or the skip reason for a skipped test case                    |
| `error_code` | `str \| None` | The error category for an errored test case, for example `execution_error`       |
| `skip_kind`  | `str \| None` | Why a skipped test case was skipped, for example `hook` or `no_matching_targets` |
| `block_kind` | `str \| None` | Always `None`, because blocked test cases dispatch no events                     |
| `checks`     | `list[dict]`  | The test case's checks, each `{"status": ..., "message": ...}`                   |

## Skipping items

On `phase_start`, `group_start` and `test_case_start`, a hook can skip the item by returning one of these values from `on_event`:

| Return value                    | Effect                                                                       |
| ------------------------------- | ---------------------------------------------------------------------------- |
| `HookSkip("reason")`            | Skip the item and record `reason`                                            |
| `HookSignal.SKIP`               | Skip the item and record `Skipped by hook '<name>'`, using the hook's `name` |
| `None` or `HookSignal.CONTINUE` | Run the item                                                                 |

Both `HookSkip` and `HookSignal` are in `huginn.hooks`. `HookSkip("")` records the generic reason. The return value of every other event is ignored.

Every subscribed hook is called even after one has skipped the item. When several hooks skip it, the recorded reason joins their reasons with `; `, in hook order, for example `Skipped by hook 'maintenance'; Outside the change window`.

### What a skip records

A skipped test case does not run: its job's `setup()`, `test()` and `cleanup()` are not called. Skipping a group or phase records every test case in it the same way, and dispatches no events for them. The test cases are recorded with:

- `status` `skipped`
- `error` set to the skip reason, shown in `run.json`, the test case's `result.json` and the HTML report
- `skip_kind` `hook` in `result.json`

A skip does not make the run fail. A phase a hook skipped does not block the phases that depend on it, in either mode: unlike a job skipped because it cannot run in learning mode, a hook skip is a deliberate decision. See [Test Plan Specification - Failure Blocking](test-plan.md#failure-blocking) for how phases block their dependents.

## Errors in a hook

A hook that raises from `on_event` does not stop the run. Huginn prints a warning that names the hook, the event and the exception, and writes it with its traceback to the log:

```
WARNING [hook_error]: Hook 'change-window' raised during 'test_case_start': KeyError: 'calendar'; continuing execution
```

The other hooks for the event are still called, and the item runs as if the failing hook had returned `None`. The warning does not change the run's status or exit code.

A hook class that raises while being instantiated is left out of the run with a warning in the log.

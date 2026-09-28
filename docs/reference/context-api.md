# Context API

The framework passes a `Context` object to every test method (`setup()`, `test()`, `cleanup()`). It gives the job its target devices, the connection broker, the result collector and the learned parameters for the current test case.

## Context fields

`Context` is a dataclass defined in `huginn.context` and exported as `huginn.Context`.

| Field             | Type                           | Description                                                                                                             |
| ----------------- | ------------------------------ | ----------------------------------------------------------------------------------------------------------------------- |
| `test_id`         | `str`                          | Test case identifier from the test plan, for example `"1.0.0"`.                                                         |
| `test_title`      | `str`                          | Test case title from the test plan.                                                                                     |
| `mode`            | `ExecutionMode`                | `ExecutionMode.LEARNING` or `ExecutionMode.TESTING`.                                                                    |
| `testbed`         | `Testbed`                      | The full loaded testbed, including devices this test does not target.                                                   |
| `targets`         | `list[Device]`                 | Devices this test case targets after target resolution.                                                                 |
| `broker`          | `Any`                          | A `RuntimeBroker` at runtime. All device operations go through it. See [Connection broker API](#connection-broker-api). |
| `parameters`      | `ParameterManager`             | Loads and saves learned parameters for this test case.                                                                  |
| `results`         | `ResultCollector`              | Records checks, command executions and metadata for the report.                                                         |
| `output_dir`      | `Path`                         | Run-scoped directory for test artifacts (`<run>/artifacts` by default).                                                 |
| `scenario`        | `str`                          | Identifier of the scenario being executed.                                                                              |
| `phase`           | `str`                          | Identifier of the phase being executed.                                                                                 |
| `test_case_group` | `str`                          | Identifier of the test case group being executed.                                                                       |
| `output`          | `Output \| None`               | Console and log output helper. Defaults to `None`. See [Output and Logging](../design/output-logging.md).               |
| `data_model`      | `Mapping[str, object] \| None` | Merged, read-only data model, or `None` when none is configured. See [Data model access](#data-model-access).           |

## Target devices

`context.targets` and `context.testbed` hold plain dataclasses from `huginn.models`. They describe devices but do not execute commands; use `context.broker` for that.

### Testbed

| Field         | Type                        | Description                                                         |
| ------------- | --------------------------- | ------------------------------------------------------------------- |
| `devices`     | `dict[str, Device]`         | All testbed devices, keyed by device name.                          |
| `credentials` | `dict[str, dict[str, str]]` | Shared credential definitions from the testbed `credentials` block. |

`Testbed` has no lookup helpers. Index `devices` directly or filter it yourself.

### Device

| Field         | Type                              | Description                                                              |
| ------------- | --------------------------------- | ------------------------------------------------------------------------ |
| `name`        | `str`                             | Device name (the key in the testbed `devices` mapping).                  |
| `os`          | `str`                             | Operating system identifier, for example `"iosxe"` or `"nxos"`.          |
| `groups`      | `list[str]`                       | Groups the device belongs to.                                            |
| `credentials` | `dict[str, dict[str, str]]`       | Resolved credentials available to this device, keyed by credential name. |
| `connections` | `dict[str, ConnectionDefinition]` | Connection definitions, keyed by connection name.                        |

### ConnectionDefinition

| Field        | Type                 | Description                                                    |
| ------------ | -------------------- | -------------------------------------------------------------- |
| `name`       | `str`                | Connection name (the key in the device `connections` mapping). |
| `protocol`   | `ConnectionProtocol` | `ssh`, `http`, `https`, `rest` or `netconf`.                   |
| `host`       | `str`                | Hostname or IP address.                                        |
| `port`       | `int`                | Port number.                                                   |
| `credential` | `str \| None`        | Credential name. `None` uses the `default` credential.         |
| `options`    | `dict[str, object]`  | Broker-specific connection options.                            |

`Device` is not exported from the top-level `huginn` package. Import it from `huginn.models` when you need it for type hints:

```python
from huginn import Context
from huginn.models import Device


def spine_devices(context: Context) -> list[Device]:
    return [device for device in context.targets if "spine" in device.groups]


def describe_targets(context: Context) -> None:
    for device in context.targets:
        ssh = device.connections.get("ssh")
        host = ssh.host if ssh is not None else "no ssh connection"
        print(f"Testing {device.name} ({device.os}) at {host}")

    # Any device in the testbed, including ones this test does not target
    border = context.testbed.devices.get("border-leaf-01")
    nxos_devices = [d for d in context.testbed.devices.values() if d.os == "nxos"]
    print(border, len(nxos_devices))
```

## Recording results

`context.results` is a `ResultCollector`. The test case status is derived from the checks it collects.

| Method                  | Signature                                                                                                                      | Description                                                                                                                                                                    |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `add_result`            | `add_result(status: ResultStatus, message: str) -> None`                                                                       | Record one check.                                                                                                                                                              |
| `add_command_execution` | `add_command_execution(*, device: str, command: str, output: str \| object, parsed: dict[str, object] \| None = None) -> None` | Record a command and its output for the report. Pass the `CommandResult` itself as `output` to also record `elapsed_ms`, `cached` and (when `parsed` is omitted) `structured`. |
| `add_metadata_section`  | `add_metadata_section(heading: str, content: str) -> None`                                                                     | Add a rendered metadata section to the test case report.                                                                                                                       |
| `derive_status`         | `derive_status() -> ResultStatus`                                                                                              | Compute the test case status from the checks recorded so far.                                                                                                                  |

`ResultCollector` also exposes the collected data as attributes: `checks`, `command_executions`, `metadata_sections` and `not_applicable_devices` (a `dict[str, str]` of device name to reason). `LearningTestCase` fills `not_applicable_devices` for you; `huginn prune` reads it from the run results.

The authoring convention is to pass `status` and `message` positionally:

```python
from huginn import Context, ResultStatus


async def check_ospf(context: Context) -> None:
    for device in context.targets:
        result = await context.broker.execute(device, "show ip ospf neighbor")
        context.results.add_command_execution(
            device=device.name,
            command="show ip ospf neighbor",
            output=result,
        )
        if "FULL" in result.output:
            context.results.add_result(
                ResultStatus.PASSED,
                f"{device.name}: OSPF neighbor 10.1.1.1 is in FULL state",
            )
        else:
            context.results.add_result(
                ResultStatus.FAILED,
                f"{device.name}: OSPF neighbor 10.1.1.1 is not in FULL state",
            )

    context.results.add_result(
        ResultStatus.INFO,
        f"Checked OSPF neighbors on {len(context.targets)} devices",
    )
```

There is no `skip()` helper. Record a skip with `add_result(ResultStatus.SKIPPED, "...")`.

### ResultStatus enum

| Status           | Meaning                                                                                                  | Counts as failure?                                |
| ---------------- | -------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| `PASSED`         | The check succeeded.                                                                                     | No                                                |
| `FAILED`         | The check did not match expected state.                                                                  | Yes                                               |
| `ERRORED`        | An exception or error occurred.                                                                          | Yes                                               |
| `NOT_APPLICABLE` | The check did not apply to the target at runtime.                                                        | No                                                |
| `SKIPPED`        | The test case was intentionally not executed.                                                            | No                                                |
| `BLOCKED`        | The test case did not run because a phase it depends on did not pass. Set by the framework, not by jobs. | No; the dependency that blocked it already failed |
| `INFO`           | Informational note. Ignored when deriving status.                                                        | No                                                |

A test case's status is derived from its checks in this order: any `ERRORED` gives `ERRORED`; otherwise any `FAILED` gives `FAILED`; otherwise, ignoring `INFO` checks, all `NOT_APPLICABLE` gives `NOT_APPLICABLE` and all `SKIPPED` gives `SKIPPED`; anything else gives `PASSED`. The run status is derived from the test case statuses in the same order. `huginn run` exits with code 1 whenever the run status is not `passed`, including a run where every test case is `NOT_APPLICABLE` or `SKIPPED`.

A `LOST_APPLICABILITY` status is planned but not implemented; see [Command support regression detection](#command-support-regression-detection).

## Connection broker API

All device operations go through `context.broker`, a `RuntimeBroker`. It holds the connections the framework opened at the start of the run, serializes operations per device and connection, and caches `execute()` and `get()` results.

### Declaring required brokers

A job declares which brokers it needs with the `required_brokers` class attribute. The default is `{BrokerType.SSH}`. The framework connects every target through each declared broker before the run starts.

```python
from huginn import Context, LearningTestCase
from huginn.enums import BrokerType


class VerifyInterfaceCounters(LearningTestCase[dict[str, object]]):
    required_brokers = {BrokerType.SSH, BrokerType.NETCONF}

    async def gather_state(self, context: Context) -> dict[str, object]:
        return {"devices": {}}

    async def compare_state(
        self,
        *,
        expected: dict[str, object],
        current: dict[str, object],
        context: Context,
    ) -> None:
        return None
```

### Broker methods

| Method                     | Signature                                                                                        | Cached | Description                                                                                                            |
| -------------------------- | ------------------------------------------------------------------------------------------------ | ------ | ---------------------------------------------------------------------------------------------------------------------- |
| `execute`                  | `execute(target, command, *, broker=None, use_cache=True, bust_cache=False) -> CommandResult`    | Yes    | Run a CLI command.                                                                                                     |
| `get`                      | `get(target, path, *, broker=None, use_cache=True, bust_cache=False, **kwargs) -> CommandResult` | Yes    | Read-style operation: HTTP GET, NETCONF get or get-config, or a show command over SSH.                                 |
| `edit`                     | `edit(target, config: str, *, broker=None, **kwargs) -> CommandResult`                           | No     | Write-style operation: HTTP POST/PUT/PATCH/DELETE, NETCONF edit-config, or newline-separated config commands over SSH. |
| `send_interactive`         | `send_interactive(target, interact_events, *, broker=None) -> CommandResult`                     | No     | Run a prompt-driven command sequence. SSH only.                                                                        |
| `for_protocol`             | `for_protocol(protocol) -> RuntimeBrokerClient`                                                  | -      | Return a client pinned to one broker type.                                                                             |
| `clear_cache`              | `clear_cache() -> None`                                                                          | -      | Drop every cached result.                                                                                              |
| `invalidate_execute_cache` | `invalidate_execute_cache(*, target, command, broker=None) -> None`                              | -      | Drop the cached result of one `execute()` call.                                                                        |
| `invalidate_get_cache`     | `invalidate_get_cache(*, target, path, broker=None, **kwargs) -> None`                           | -      | Drop the cached result of one `get()` call.                                                                            |

`target` is always a `Device`. `broker` is a `BrokerType` or its string value (`"ssh"`, `"http"`, `"netconf"`). When `broker` is omitted and the device is connected through exactly one broker, that broker is used. When the device is connected through several brokers, `broker=` is required, or the call raises `RuntimeBrokerError`.

Extra `**kwargs` on `get()` and `edit()` are passed to the underlying broker:

- HTTP `get()`: `params`, `headers`.
- HTTP `edit()`: `path` (required), `method` (default `"POST"`), `params`, `headers`.
- NETCONF `get()`: `source` (`"running"`, `"candidate"`, `"startup"`; omitted means `get`), `filter_type` (`"subtree"` or `"xpath"`).
- NETCONF `edit()`: `target` datastore (default `"running"`).

### CommandResult

Every broker operation returns a `CommandResult` (`huginn.brokers.protocol.CommandResult`), not a string. Read the raw text from `.output`.

| Field        | Type                     | Default | Description                                                                                                                                                       |
| ------------ | ------------------------ | ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `output`     | `str`                    | -       | Raw text output or response body.                                                                                                                                 |
| `structured` | `dict[str, Any] \| None` | `None`  | Parsed payload when the broker produces one, for example a JSON HTTP response.                                                                                    |
| `elapsed_ms` | `float`                  | `0.0`   | Time the operation took, in milliseconds.                                                                                                                         |
| `cached`     | `bool`                   | `False` | Whether the broker reported the result as cached. The built-in brokers always set `False`, and a `RuntimeBroker` cache hit returns the original object unchanged. |

`ParameterManager.save()` only accepts JSON-serializable data, so store extracted values (such as `result.output` or parsed fields) in parameters, never the `CommandResult` itself.

### CLI operations

```python
from huginn import Context


async def collect_cli(context: Context) -> None:
    device = context.targets[0]

    # Cached for the rest of the phase by default
    version = await context.broker.execute(device, "show version")
    print(version.output)

    # Bypass the cache when the read must reflect a change made in this job
    clock = await context.broker.execute(device, "show clock", use_cache=False)
    print(clock.output)

    # Apply configuration; lines are newline-separated and never cached
    await context.broker.edit(
        device,
        "interface Loopback0\n ip address 10.0.0.1 255.255.255.255",
    )

    # Answer a confirmation prompt
    await context.broker.send_interactive(
        device,
        [
            (
                "clear counters",
                'Clear "show interface" counters on all interfaces [confirm]',
            ),
            ("", "#"),
        ],
    )
```

### REST and NETCONF operations

For devices with an HTTP or NETCONF connection, and a job that declares the matching broker:

```python
from huginn import Context
from huginn.enums import BrokerType


async def collect_api(context: Context) -> None:
    device = context.targets[0]

    # HTTP GET (cached by default); JSON bodies are parsed into .structured
    interfaces = await context.broker.get(
        device, "/restconf/data/ietf-interfaces:interfaces", broker=BrokerType.HTTP
    )
    print(interfaces.structured)

    # HTTP write; path is required, method defaults to POST
    await context.broker.edit(
        device,
        '{"vlan": {"id": 100, "name": "users"}}',
        broker=BrokerType.HTTP,
        path="/api/v1/vlans",
        method="PUT",
    )

    # NETCONF get-config against the running datastore
    running = await context.broker.get(
        device,
        "<native xmlns='http://cisco.com/ns/yang/Cisco-IOS-XE-native'><hostname/></native>",
        broker=BrokerType.NETCONF,
        source="running",
    )
    print(running.output)
```

### Protocol-pinned clients

`for_protocol()` returns a `RuntimeBrokerClient` bound to one broker type, so you don't have to repeat `broker=` on every call. It exposes `execute(target, command, *, use_cache=True, bust_cache=False)`, `get(target, path, **kwargs)` and `edit(target, config, **kwargs)`. `get()` also accepts `use_cache` and `bust_cache` as keywords. Asking for a broker the run did not plan raises `RuntimeBrokerError`.

```python
from huginn import Context


async def collect_netconf(context: Context) -> None:
    netconf = context.broker.for_protocol("netconf")
    for device in context.targets:
        result = await netconf.get(
            device,
            "<interfaces xmlns='urn:ietf:params:xml:ns:yang:ietf-interfaces'/>",
            bust_cache=True,
        )
        print(device.name, len(result.output))
```

### Caching

- `execute()` and `get()` results are cached per device, broker, command or path, and `get()` keyword arguments. Concurrent identical calls share one in-flight request.
- `use_cache=False` runs the operation without reading or writing the cache.
- `bust_cache=True` drops the cached entry, runs the operation and caches the new result.
- `invalidate_execute_cache()` and `invalidate_get_cache()` drop one entry without running anything; `clear_cache()` drops them all.
- The framework clears the whole cache at the start of each phase, unless the phase sets `preserve_cache: true`. See [Test Plan Schema - Phases](test-plan.md#phases).

### Connection errors

`RuntimeBroker` has no connection-status methods. Connections are opened before the run starts, and a failure there stops the run with a broker error. At runtime, calling an operation on a device that has no connection raises `RuntimeBrokerError` (`huginn.runtime_broker.RuntimeBrokerError`), for example `Device 'leaf-01' is not connected`. Errors raised by the underlying broker during `execute()`, `get()` and `edit()` are re-raised as `RuntimeBrokerError`.

## Learning and testing modes

Huginn runs jobs in two modes. In learning mode, a job captures current state and saves it as learned parameters. In testing mode, it loads those parameters and compares them against current state.

### ParameterManager

`context.parameters` stores one JSON file per test case under the parameters directory.

| Method | Signature                                           | Description                                                                                                                          |
| ------ | --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `save` | `async save(payload: Mapping[str, object]) -> None` | Write `payload` as JSON. Raises `ParameterStoreError` if it is not JSON-serializable or cannot be written.                           |
| `load` | `async load() -> dict[str, object]`                 | Read the learned parameters. Raises `ParameterStoreError` if none exist for this test case, or the file is not a valid JSON mapping. |

`ParameterStoreError` lives in `huginn.parameters`. Both methods are coroutines, so always `await` them.

### LearningTestCase base class

Jobs that follow the learning and testing flow inherit from `LearningTestCase` and implement `gather_state()` and `compare_state()`. `compare_state()` is async and keyword-only.

```python
from typing import TypedDict

from huginn import CommandSupportResult, Context, LearningTestCase, ResultStatus
from huginn.utils.commands import is_command_unsupported


class OspfParameters(TypedDict):
    devices: dict[str, dict[str, str]]


class VerifyOspfNeighbors(LearningTestCase[OspfParameters]):
    command = "show ip ospf neighbor"

    async def check_command_support(self, context: Context) -> CommandSupportResult:
        applicable = []
        not_applicable: dict[str, str] = {}
        for device in context.targets:
            result = await context.broker.execute(device, self.command)
            if is_command_unsupported(result.output):
                not_applicable[device.name] = (
                    f"Device does not support '{self.command}'"
                )
                continue
            applicable.append(device)
        return CommandSupportResult(
            applicable=applicable, not_applicable=not_applicable
        )

    async def gather_state(self, context: Context) -> OspfParameters:
        devices: dict[str, dict[str, str]] = {}
        for device in context.targets:
            result = await context.broker.execute(device, self.command)
            context.results.add_command_execution(
                device=device.name, command=self.command, output=result
            )
            devices[device.name] = {"raw": result.output}
        return {"devices": devices}

    async def compare_state(
        self,
        *,
        expected: OspfParameters,
        current: OspfParameters,
        context: Context,
    ) -> None:
        for device in context.targets:
            learned = expected["devices"].get(device.name)
            if learned == current["devices"].get(device.name):
                context.results.add_result(
                    ResultStatus.PASSED, f"{device.name}: OSPF neighbors match"
                )
            else:
                context.results.add_result(
                    ResultStatus.FAILED, f"{device.name}: OSPF neighbors changed"
                )
```

`LearningTestCase` provides no-op `setup()` and `cleanup()`, a default `check_command_support()` that accepts every target, and implements `test()` as:

1. Call `check_command_support(context)`.
2. Record a `NOT_APPLICABLE` check (`"<device>: <reason>"`) for each target not in `applicable`, and copy `not_applicable` into `context.results.not_applicable_devices`.
3. If no target is applicable, record an `INFO` check (`No supported targets after command support check`) and return.
4. Narrow `context.targets` to the applicable devices.
5. Call `gather_state(context)`. If the result is a mapping with a `devices` mapping, every applicable target missing from it is added to `not_applicable_devices`.
6. If the derived status is already `ERRORED`, return without saving or comparing.
7. In learning mode, save the state with `context.parameters.save(...)`, record a `PASSED` check (`Learned parameters saved successfully`) unless every check so far is `NOT_APPLICABLE`, and return.
8. In testing mode, load the expected state with `context.parameters.load()`, render the `DESCRIPTION`, `SETUP`, `PROCEDURE` and `PASS_FAIL_CRITERIA` class attributes as metadata sections, and call `compare_state(expected=..., current=..., context=...)`.

The runner calls `setup()`, then `test()`, then `cleanup()`, so `check_command_support()` runs inside `test()` after `setup()`. A plain `TestCase` has no command support hook; its `test()` does whatever you write.

When running `huginn run --mode learning`, only jobs inheriting `LearningTestCase` are executed. Jobs inheriting `TestCase` directly are reported as `SKIPPED` in learning mode.

### Custom mode handling

A job that subclasses `TestCase` directly can branch on `context.mode` itself:

```python
from huginn import Context, ExecutionMode, ResultStatus, TestCase


class VerifyNtpAssociations(TestCase):
    async def setup(self, context: Context) -> None:
        return None

    async def test(self, context: Context) -> None:
        current: dict[str, object] = {}
        for device in context.targets:
            result = await context.broker.execute(device, "show ntp associations")
            current[device.name] = result.output

        if context.mode == ExecutionMode.LEARNING:
            await context.parameters.save({"devices": current})
            context.results.add_result(
                ResultStatus.PASSED, "Learned parameters saved successfully"
            )
            return

        expected = await context.parameters.load()
        if expected.get("devices") == current:
            context.results.add_result(ResultStatus.PASSED, "NTP associations match")
        else:
            context.results.add_result(ResultStatus.FAILED, "NTP associations changed")

    async def cleanup(self, context: Context) -> None:
        return None
```

Because this class does not inherit `LearningTestCase`, its learning branch never runs under `huginn run --mode learning`; the job is skipped instead.

## Data model access

`context.data_model` holds the data model configured by `data_model.path` in the test plan or by `--data-model`, merged into one mapping. It is `None` when neither is set. See [Test Plan Specification - Data Model](test-plan.md#data-model) for how it is loaded and merged.

Every job in a run shares the same object, so it is read-only. Its mappings and lists behave like plain `dict` and `list` for reads, iteration, `isinstance()` checks and `json.dumps()`, but any change raises `TypeError`. Use `copy.deepcopy()` to get a mutable copy:

```python
import copy

if context.data_model is not None:
    fabric = context.data_model["fabric"]
    leafs = copy.deepcopy(fabric["leafs"])
    leafs.append("leaf-03")
```

## Command support checking

`check_command_support()` is a `LearningTestCase` method that lets a job drop targets that do not support the command it needs, so they are reported as `NOT_APPLICABLE` instead of failing.

### CommandSupportResult

`CommandSupportResult` is exported as `huginn.CommandSupportResult`.

| Field            | Type             | Description                                     |
| ---------------- | ---------------- | ----------------------------------------------- |
| `applicable`     | `list[Device]`   | Targets that support the required command(s).   |
| `not_applicable` | `dict[str, str]` | Device name to the reason it is not applicable. |

A target that is not in `applicable` and has no entry in `not_applicable` is reported with the reason `Command not supported on this device`. See [LearningTestCase base class](#learningtestcase-base-class) for how the result is applied.

### Command support regression detection

Planned; see [#254](https://github.com/ChartinoLabs/Huginn/issues/254). The intent is that a device which supported the command when parameters were learned, but no longer does during testing, is reported as a failing `LOST_APPLICABILITY` status. Today such a device is reported as `NOT_APPLICABLE`.

## Async patterns

All test methods are async. Use `asyncio.gather` to query targets concurrently; the broker already serializes operations per device and connection. Huginn supports Python 3.10, so avoid `asyncio.TaskGroup` in jobs that must run there.

### Parallel device operations

```python
import asyncio

from huginn import Context
from huginn.models import Device


async def gather_versions(context: Context) -> dict[str, str]:
    async def get_version(device: Device) -> tuple[str, str]:
        result = await context.broker.execute(device, "show version")
        return device.name, result.output

    pairs = await asyncio.gather(*(get_version(device) for device in context.targets))
    return dict(pairs)
```

### Semaphore for rate limiting

```python
import asyncio

from huginn import Context
from huginn.models import Device


async def gather_versions_rate_limited(context: Context) -> dict[str, str]:
    semaphore = asyncio.Semaphore(10)

    async def get_version(device: Device) -> tuple[str, str]:
        async with semaphore:
            result = await context.broker.execute(device, "show version")
            return device.name, result.output

    pairs = await asyncio.gather(*(get_version(device) for device in context.targets))
    return dict(pairs)
```

## Error handling

### Graceful failure

Catch errors per device and record them, so the remaining devices are still checked:

```python
from huginn import Context, ResultStatus
from huginn.runtime_broker import RuntimeBrokerError


async def check_each_device(context: Context) -> None:
    for device in context.targets:
        try:
            result = await context.broker.execute(device, "show ip ospf neighbor")
        except RuntimeBrokerError as error:
            context.results.add_result(ResultStatus.ERRORED, f"{device.name}: {error}")
            continue
        context.results.add_result(
            ResultStatus.PASSED,
            f"{device.name}: collected {len(result.output.splitlines())} lines",
        )
```

### Critical failures

An exception raised from `setup()` or `test()` aborts the test case. The runner still calls `cleanup()`, and records the test case as `ERRORED` with the exception message and traceback.

```python
from huginn import Context, LearningTestCase


class VerifyBgpNeighbors(LearningTestCase[dict[str, object]]):
    async def setup(self, context: Context) -> None:
        if not any(device.os == "iosxe" for device in context.targets):
            raise RuntimeError("VerifyBgpNeighbors requires at least one IOS-XE target")

    async def gather_state(self, context: Context) -> dict[str, object]:
        return {"devices": {}}

    async def compare_state(
        self,
        *,
        expected: dict[str, object],
        current: dict[str, object],
        context: Context,
    ) -> None:
        return None
```

## See also

- [Concepts - Glossary](../concepts/glossary.md) - formal term definitions including Command Support
- [Design - Architecture](../design/architecture.md) - Context and broker internals
- [Design - Connection Broker](../design/connection-broker.md) - broker protocol and built-in brokers
- [Reference - Testbed Schema](testbed.md) - device definitions behind `Device` and `ConnectionDefinition`
- [Reference - Test Plan Schema](test-plan.md) - test organization, targeting and `preserve_cache`
- [Authoring Jobs](../authoring/index.md) - practical guides for writing jobs using this API

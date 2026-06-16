# Context API

The `Context` object is passed to every test method and provides access to framework services.

## Context fields

```python
class Context:
    # Identification
    test_id: str              # "1.0.0"
    test_title: str           # "Verify OSPF Neighbor State"

    # Execution mode
    mode: ExecutionMode       # ExecutionMode.LEARNING or ExecutionMode.TESTING

    # Infrastructure access
    testbed: TestbedAdapter   # Full testbed metadata
    targets: list[DeviceAdapter]  # Devices this test targets

    # Connection broker (primary interface for command execution)
    broker: ConnectionBroker  # Execute commands, check connectivity, access cache

    # Results
    results: ResultCollector  # Record test outcomes

    # Parameters (learned state)
    parameters: ParameterManager  # Save/load learned parameters

    # Data model (external source of truth)
    data_model: dict | None   # Merged data model, or None if not configured

    # Configuration
    config: FrameworkConfig   # Framework settings
```

## Accessing target devices

```python
async def test(self, context: Context) -> None:
    # Iterate over target devices
    for device in context.targets:
        print(f"Testing {device.name} ({device.os})")

    # Access specific device from full testbed
    spine = context.testbed.get_device("spine-01")

    # Get devices by group
    leafs = context.testbed.get_devices_by_group("leaf")

    # Get devices by OS
    nxos_devices = context.testbed.get_devices_by_os("nxos")
```

## Device adapter properties

The `DeviceAdapter` provides device metadata (but not command execution):

```python
device.name        # "spine-01"
device.hostname    # "spine-01.lab.local"
device.os          # "nxos"
device.groups      # ["spine", "datacenter-1"]
device.metadata    # {"vendor": "cisco", "model": "N9K-C9336C"}
```

## Recording results

```python
from huginn import ResultStatus

async def test(self, context: Context) -> None:
    # Record a passing check
    context.results.add_result(
        status=ResultStatus.PASSED,
        message="OSPF neighbor 10.1.1.1 is in FULL state"
    )

    # Record a failing check
    context.results.add_result(
        status=ResultStatus.FAILED,
        message="OSPF neighbor 10.1.1.2 is in INIT state, expected FULL"
    )

    # Record informational message (doesn't affect pass/fail)
    context.results.add_result(
        status=ResultStatus.INFO,
        message="Found 5 OSPF neighbors on device spine-01"
    )

    # Execute command through broker and record for reporting
    output = await context.broker.execute(device, "show ip ospf neighbor")
    context.results.add_command_execution(
        device=device.name,
        command="show ip ospf neighbor",
        output=output,
        parsed=parsed_data  # Optional: structured data
    )
```

### ResultStatus enum

| Status               | Meaning                                                              | Contributes to failure? |
| -------------------- | -------------------------------------------------------------------- | ----------------------- |
| `PASSED`             | Check succeeded                                                      | No                      |
| `FAILED`             | Check failed                                                         | Yes                     |
| `NOT_APPLICABLE`     | Check did not apply to the target at runtime                         | No                      |
| `LOST_APPLICABILITY` | Previously supported the command, now doesn't (has prior parameters) | Yes                     |
| `SKIPPED`            | Check was skipped                                                    | No                      |
| `ERRORED`            | Check encountered an error                                           | Yes                     |
| `INFO`               | Informational (no impact on overall status)                          | No                      |

## Connection broker API

All command execution goes through the Connection Broker via `context.broker`. This enables connection pooling and command caching.

### CLI operations

```python
# Execute a command (cached by default)
output = await context.broker.execute(device, "show ip route")

# Execute without caching (for commands that must be fresh)
output = await context.broker.execute(device, "show clock", use_cache=False)

# Execute configuration commands (never cached)
await context.broker.configure(device, [
    "interface loopback0",
    "ip address 10.0.0.1 255.255.255.255"
])
```

### REST API operations

For devices with REST API connections:

```python
# GET request (cached by default)
data = await context.broker.get(device, "/api/v1/interfaces")

# GET without caching
data = await context.broker.get(device, "/api/v1/interfaces", use_cache=False)

# POST request (never cached)
response = await context.broker.post(device, "/api/v1/config", data={"vlan": 100})
```

### Connection status

```python
# Check if a specific device is connected
if context.broker.is_connected(device.name):
    # Device is ready for commands

# Get status of all connections
status = context.broker.get_connection_status()
# Returns: {"spine-01": "connected", "leaf-01": "connected", ...}
```

## Learning and testing modes

Huginn supports dual execution modes for "golden state" validation.

### Learning mode

Capture current infrastructure state as the expected baseline:

```python
from huginn import ExecutionMode, ResultStatus

async def test(self, context: Context) -> None:
    if context.mode == ExecutionMode.LEARNING:
        state = await self.gather_state(context)
        await context.parameters.save(state)
        context.results.add_result(
            status=ResultStatus.PASSED,
            message="Learned parameters saved successfully"
        )
```

### Testing mode

Compare current state against previously learned parameters:

```python
from huginn import ExecutionMode

async def test(self, context: Context) -> None:
    if context.mode == ExecutionMode.TESTING:
        expected = await context.parameters.load()
        current = await self.gather_state(context)
        self.compare_state(expected, current, context)
```

### LearningTestCase base class

For tests that follow the learning/testing flow, inherit from `LearningTestCase`:

```python
from huginn import Context, LearningTestCase


class VerifyOSPFNeighbors(LearningTestCase):
    async def gather_state(self, context: Context) -> dict:
        # Gather current state for all targets
        ...

    async def compare_state(
        self,
        *,
        expected: dict,
        current: dict,
        context: Context,
    ) -> None:
        # Compare expected vs current and record results
        ...
```

`LearningTestCase` provides default no-op `setup()`/`cleanup()` and implements `test()` as:

1. Call `gather_state(context)`
2. Call `check_command_support(context)` (override optional)
3. Record skipped results for unsupported targets
4. If no targets are applicable, record skip and return
5. If `context.mode == LEARNING`, save with `context.parameters.save(...)`
6. Otherwise load expected state with `context.parameters.load()`
7. Call `compare_state(expected=..., current=..., context=...)`

When running `huginn run --mode learning`, only tests inheriting `LearningTestCase` are executed. Tests inheriting `TestCase` directly are skipped by design in learning mode.

## Data model access

When a data model is configured, tests can derive expected state from the external source of truth instead of using file-based parameters.

```python
async def test(self, context: Context) -> None:
    if context.data_model is None:
        expected = await context.parameters.load()
    else:
        expected = self.derive_expected_state(context.data_model)
```

A robust pattern that handles both modes and optional data model:

```python
from huginn import TestCase, Context, ExecutionMode, ResultStatus

class VerifyBGPNeighbors(TestCase):
    """Verify BGP neighbors match expected state."""

    async def setup(self, context: Context) -> None:
        for device in context.targets:
            if not context.broker.is_connected(device.name):
                raise RuntimeError(f"Device {device.name} is not connected")

    async def test(self, context: Context) -> None:
        current_state = await self.gather_bgp_state(context)

        if context.mode == ExecutionMode.LEARNING:
            await context.parameters.save(current_state)
            context.results.add_result(
                status=ResultStatus.PASSED,
                message=f"Learned BGP state for {len(current_state)} devices"
            )
        elif context.data_model is not None:
            expected = self.derive_expected_bgp_state(context.data_model)
            if expected is None:
                context.results.skip("BGP not configured in data model")
                return
            self.compare_bgp_state(expected, current_state, context)
        else:
            expected = await context.parameters.load()
            self.compare_bgp_state(expected, current_state, context)

    async def cleanup(self, context: Context) -> None:
        pass
```

## Command support checking

The `check_command_support()` method provides a structured way for tests to introspect their targets and filter out devices that do not support the required command(s).

### CommandSupportResult

```python
from dataclasses import dataclass, field
from huginn import DeviceAdapter

@dataclass
class CommandSupportResult:
    applicable: list[DeviceAdapter] = field(default_factory=list)
    not_applicable: dict[str, str] = field(default_factory=dict)
```

### Execution flow

When a test implements `check_command_support()`, the framework:

1. Calls `check_command_support(context)` with all originally assigned targets
2. Records unsupported devices with `NOT_APPLICABLE` status and their reasons
3. Updates `context.targets` to contain only supported devices
4. Proceeds with `setup()` -> `test()` -> `cleanup()` using filtered targets
5. If no devices support the command, skips `setup()` and `test()` entirely

### Command support regression detection

When running in testing mode with file-based parameters, the framework detects devices that supported the required command(s) when parameters were learned but no longer support them. This is recorded as `LOST_APPLICABILITY` rather than `NOT_APPLICABLE`.

| Status             | Meaning                                              | Contributes to failure? |
| ------------------ | ---------------------------------------------------- | ----------------------- |
| NOT_APPLICABLE     | Never supported the command (no prior parameters)    | No                      |
| LOST_APPLICABILITY | Previously supported, now doesn't (has prior params) | Yes                     |

## Async patterns

All test methods are async, enabling efficient parallel operations.

### Parallel device operations

```python
import asyncio

async def gather_state(self, context: Context) -> dict:
    async def get_device_state(device):
        output = await context.broker.execute(device, "show version")
        return device.name, output

    async with asyncio.TaskGroup() as tg:
        tasks = [
            tg.create_task(get_device_state(device))
            for device in context.targets
        ]

    return {name: output for name, output in [t.result() for t in tasks]}
```

### Semaphore for rate limiting

```python
async def gather_state_rate_limited(self, context: Context) -> dict:
    semaphore = asyncio.Semaphore(10)

    async def get_device_state(device):
        async with semaphore:
            output = await context.broker.execute(device, "show version")
            return device.name, output

    async with asyncio.TaskGroup() as tg:
        tasks = [
            tg.create_task(get_device_state(device))
            for device in context.targets
        ]

    return dict(t.result() for t in tasks)
```

## Error handling

### Graceful failure

Record failures without raising exceptions to continue checking other devices:

```python
async def test(self, context: Context) -> None:
    for device in context.targets:
        try:
            output = await context.broker.execute(device, "show ip ospf neighbor")
            context.results.add_result(status=ResultStatus.PASSED, message="...")
        except Exception as e:
            context.results.add_result(
                status=ResultStatus.ERRORED,
                message=f"{device.name}: {e}"
            )
```

### Critical failures

Raise exceptions to abort the test entirely:

```python
async def setup(self, context: Context) -> None:
    disconnected = [
        d.name for d in context.targets
        if not context.broker.is_connected(d.name)
    ]
    if disconnected:
        raise RuntimeError(f"Devices not connected: {disconnected}")
```

## See also

- [Concepts - Glossary](../concepts/glossary.md) - formal term definitions including Command Support
- [Design - Architecture](../design/architecture.md) - Context and adapter internals
- [Reference - Testbed Schema](testbed.md) - device definitions referenced by DeviceAdapter
- [Reference - Test Plan Schema](test-plan.md) - test organization and targeting
- [Authoring Jobs](../authoring/index.md) - practical guides for writing jobs using this API

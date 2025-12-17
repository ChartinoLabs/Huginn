# Test Authoring Guide

This document describes how to write tests for Huginn, including the base class structure, async patterns, and best practices.

## Overview

Huginn tests are Python classes that inherit from the `TestCase` abstract base class. Each test implements three async methods:

- `setup()`: Verify prerequisites and prepare test state
- `test()`: Execute the actual test logic
- `cleanup()`: Clean up test-specific state (not connections - the framework manages those)

**Important**: Tests do not manage device connections. The framework's Connection Broker establishes connections to all testbed devices at test plan start and maintains them throughout execution. Tests execute commands through `context.broker`.

## The TestCase Base Class

```python
from abc import ABC, abstractmethod
from huginn import Context

class TestCase(ABC):
    """Abstract base class for all Huginn tests."""

    @abstractmethod
    async def setup(self, context: Context) -> None:
        """Prepare for test execution.

        Called before test(). Use this to verify prerequisites like
        device connectivity (already established by framework) or
        set up test-specific state. If this method raises an exception,
        test() is skipped but cleanup() still runs.

        Note: Do NOT connect to devices here - the Connection Broker
        handles connection lifecycle at the test plan level.
        """
        ...

    @abstractmethod
    async def test(self, context: Context) -> None:
        """Execute the test logic.

        This is where the main test logic lives. Use context.broker
        to execute commands and context.results to record outcomes.
        """
        ...

    @abstractmethod
    async def cleanup(self, context: Context) -> None:
        """Clean up after test execution.

        Always called, even if setup() or test() fails. Use this to
        restore device state if modified, or clean up test artifacts.

        Note: Do NOT disconnect from devices here - the Connection
        Broker handles disconnection at test plan end.
        """
        ...
```

## Minimal Test Example

```python
# tests/verify_connectivity.py
from huginn import TestCase, Context, ResultStatus

class VerifyConnectivity(TestCase):
    """Verify connectivity to all target devices."""

    async def setup(self, context: Context) -> None:
        # Connections already established by framework - just verify
        pass

    async def test(self, context: Context) -> None:
        for device in context.targets:
            if context.broker.is_connected(device.name):
                context.results.add_result(
                    status=ResultStatus.PASSED,
                    message=f"Device {device.name} is connected"
                )
            else:
                context.results.add_result(
                    status=ResultStatus.FAILED,
                    message=f"Device {device.name} is not connected"
                )

    async def cleanup(self, context: Context) -> None:
        # No cleanup needed - framework manages connections
        pass
```

## The Context Object

The `Context` object is passed to every test method and provides access to framework services:

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

### Accessing Target Devices

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

### Recording Results

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

Result statuses (`ResultStatus` enum):

- `PASSED`: Check succeeded
- `FAILED`: Check failed
- `SKIPPED`: Check was skipped
- `ERRORED`: Check encountered an error
- `INFO`: Informational (no impact on overall status)

## Learning and Testing Modes

Huginn supports dual execution modes for "golden state" validation:

### Learning Mode

Capture current infrastructure state as the expected baseline:

```python
from huginn import ExecutionMode, ResultStatus

async def test(self, context: Context) -> None:
    if context.mode == ExecutionMode.LEARNING:
        # Gather current state
        state = await self.gather_state(context)

        # Save as expected parameters
        await context.parameters.save(state)

        context.results.add_result(
            status=ResultStatus.PASSED,
            message="Learned parameters saved successfully"
        )
```

### Testing Mode

Compare current state against previously learned parameters:

```python
from huginn import ExecutionMode

async def test(self, context: Context) -> None:
    if context.mode == ExecutionMode.TESTING:
        # Load expected state
        expected = await context.parameters.load()

        # Gather current state
        current = await self.gather_state(context)

        # Compare and record results
        self.compare_state(expected, current, context)
```

## Data Model-Driven Tests

When a data model is configured, tests can derive expected state from the external source of truth instead of using file-based parameters. This pattern supports Infrastructure as Code approaches.

### Accessing the Data Model

```python
async def test(self, context: Context) -> None:
    # Check if data model is available
    if context.data_model is None:
        # No data model configured - fall back to file-based parameters
        expected = await context.parameters.load()
    else:
        # Data model available - derive expected state from it
        expected = self.derive_expected_state(context.data_model)
```

### Skipping When Not Applicable

Use the data model to determine if a test is applicable:

```python
async def test(self, context: Context) -> None:
    if context.data_model is None:
        expected = await context.parameters.load()
    else:
        # Check if OSPF is configured in the data model
        ospf_config = context.data_model.get("routing", {}).get("ospf")
        if ospf_config is None:
            context.results.skip("OSPF not configured in data model")
            return

        expected = ospf_config.get("neighbors", [])

    current = await self.gather_ospf_state(context)
    self.compare_state(expected, current, context)
```

### Data Model with Learning Mode Fallback

A robust pattern that works with or without a data model:

```python
from huginn import TestCase, Context, ExecutionMode, ResultStatus

class VerifyBGPNeighbors(TestCase):
    """Verify BGP neighbors match expected state from data model or learned parameters."""

    async def setup(self, context: Context) -> None:
        for device in context.targets:
            if not context.broker.is_connected(device.name):
                raise RuntimeError(f"Device {device.name} is not connected")

    async def test(self, context: Context) -> None:
        current_state = await self.gather_bgp_state(context)

        if context.mode == ExecutionMode.LEARNING:
            # Learning mode always saves to parameters file
            await context.parameters.save(current_state)
            context.results.add_result(
                status=ResultStatus.PASSED,
                message=f"Learned BGP state for {len(current_state)} devices"
            )
        elif context.data_model is not None:
            # Data model available - derive expected state
            expected = self.derive_expected_bgp_state(context.data_model)
            if expected is None:
                context.results.skip("BGP not configured in data model")
                return
            self.compare_bgp_state(expected, current_state, context)
        else:
            # No data model - use file-based parameters
            expected = await context.parameters.load()
            self.compare_bgp_state(expected, current_state, context)

    async def cleanup(self, context: Context) -> None:
        pass

    def derive_expected_bgp_state(self, data_model: dict) -> dict | None:
        """Extract expected BGP neighbor state from data model."""
        bgp_config = data_model.get("routing", {}).get("bgp")
        if bgp_config is None:
            return None

        expected = {}
        for device_name, device_bgp in bgp_config.get("devices", {}).items():
            expected[device_name] = {
                neighbor["ip"]: {"state": "Established", "asn": neighbor["asn"]}
                for neighbor in device_bgp.get("neighbors", [])
            }
        return expected

    async def gather_bgp_state(self, context: Context) -> dict:
        # ... implementation ...
        pass

    def compare_bgp_state(self, expected: dict, current: dict, context: Context) -> None:
        # ... implementation ...
        pass
```

## Learning and Testing Modes (File-Based Parameters)

### Combined Pattern

A complete test handling both modes:

```python
from huginn import TestCase, Context, ExecutionMode, ResultStatus
import muninn  # Separate parser package

class VerifyOSPFNeighbors(TestCase):
    """Verify OSPF neighbors match expected state."""

    async def setup(self, context: Context) -> None:
        # Verify target devices are connected (framework manages connections)
        for device in context.targets:
            if not context.broker.is_connected(device.name):
                raise RuntimeError(f"Device {device.name} is not connected")

    async def test(self, context: Context) -> None:
        # Gather current state (same for both modes)
        current_state = await self.gather_ospf_state(context)

        if context.mode == ExecutionMode.LEARNING:
            await context.parameters.save(current_state)
            context.results.add_result(
                status=ResultStatus.PASSED,
                message=f"Learned OSPF state for {len(current_state)} devices"
            )
        else:
            expected_state = await context.parameters.load()
            self.compare_ospf_state(expected_state, current_state, context)

    async def cleanup(self, context: Context) -> None:
        # No connection teardown needed - framework manages connections
        pass

    async def gather_ospf_state(self, context: Context) -> dict:
        """Gather OSPF neighbor state from all targets."""
        state = {}
        for device in context.targets:
            # Execute through broker (enables caching)
            output = await context.broker.execute(device, "show ip ospf neighbor")
            # Parse output using Muninn
            parsed = muninn.parse(device.os, "show ip ospf neighbor", output)
            state[device.name] = parsed

            context.results.add_command_execution(
                device=device.name,
                command="show ip ospf neighbor",
                output=output,
                parsed=parsed
            )
        return state

    def compare_ospf_state(
        self,
        expected: dict,
        current: dict,
        context: Context
    ) -> None:
        """Compare expected vs current OSPF state."""
        for device_name, expected_neighbors in expected.items():
            current_neighbors = current.get(device_name, {})

            for neighbor_id, expected_data in expected_neighbors.items():
                current_data = current_neighbors.get(neighbor_id)

                if current_data is None:
                    context.results.add_result(
                        status=ResultStatus.FAILED,
                        message=f"{device_name}: Neighbor {neighbor_id} not found"
                    )
                    continue

                if current_data["state"] == expected_data["state"]:
                    context.results.add_result(
                        status=ResultStatus.PASSED,
                        message=f"{device_name}: Neighbor {neighbor_id} is {current_data['state']}"
                    )
                else:
                    context.results.add_result(
                        status=ResultStatus.FAILED,
                        message=(
                            f"{device_name}: Neighbor {neighbor_id} is "
                            f"{current_data['state']}, expected {expected_data['state']}"
                        )
                    )
```

## Async Patterns

All test methods are async. This enables efficient parallel operations.

### Parallel Device Operations

Execute commands across multiple devices concurrently through the broker:

```python
import asyncio

async def gather_state(self, context: Context) -> dict:
    """Gather state from all devices in parallel."""

    async def get_device_state(device):
        output = await context.broker.execute(device, "show version")
        return device.name, output

    # Execute all commands concurrently
    async with asyncio.TaskGroup() as tg:
        tasks = [
            tg.create_task(get_device_state(device))
            for device in context.targets
        ]

    # Collect results
    return {name: output for name, output in [t.result() for t in tasks]}
```

Note: Even when executing in parallel, the broker's caching applies. If the same command on the same device is requested concurrently, only one execution occurs.

### Structured Concurrency with TaskGroup

Python 3.11+ `TaskGroup` provides clean error handling:

```python
async def gather_multi_command_state(self, context: Context) -> dict:
    """Gather multiple commands per device."""

    async def get_device_data(device):
        version = await context.broker.execute(device, "show version")
        interfaces = await context.broker.execute(device, "show ip interface brief")
        return device.name, {"version": version, "interfaces": interfaces}

    async with asyncio.TaskGroup() as tg:
        tasks = [
            tg.create_task(get_device_data(device))
            for device in context.targets
        ]

    return dict(t.result() for t in tasks)
```

### Semaphore for Rate Limiting

Limit concurrent operations to avoid overwhelming devices:

```python
async def gather_state_rate_limited(self, context: Context) -> dict:
    """Gather state with max 10 concurrent operations."""
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

## Creating Base Classes

For projects with common patterns, create intermediate base classes:

```python
# tests/base.py
from huginn import TestCase, Context

class NetworkTestCase(TestCase):
    """Base class for network device tests with common setup/cleanup."""

    async def setup(self, context: Context) -> None:
        """Verify all target devices are connected."""
        # Framework manages connections - we just verify
        for device in context.targets:
            if not context.broker.is_connected(device.name):
                raise RuntimeError(f"Device {device.name} is not connected")

    async def cleanup(self, context: Context) -> None:
        """Cleanup after test - framework handles disconnection."""
        # No connection teardown needed
        pass


class LearningTestCase(NetworkTestCase):
    """Base class for learning/testing pattern tests."""

    async def test(self, context: Context) -> None:
        """Execute learning or testing logic."""
        from huginn import ExecutionMode, ResultStatus

        current_state = await self.gather_state(context)

        if context.mode == ExecutionMode.LEARNING:
            await context.parameters.save(current_state)
            context.results.add_result(
                status=ResultStatus.PASSED,
                message="Parameters learned successfully"
            )
        else:
            expected_state = await context.parameters.load()
            self.compare_state(expected_state, current_state, context)

    async def gather_state(self, context: Context) -> dict:
        """Override to gather test-specific state."""
        raise NotImplementedError("Subclass must implement gather_state()")

    def compare_state(
        self,
        expected: dict,
        current: dict,
        context: Context
    ) -> None:
        """Override to implement comparison logic."""
        raise NotImplementedError("Subclass must implement compare_state()")
```

Using the base class:

```python
# tests/verify_ospf_neighbors.py
from tests.base import LearningTestCase
from huginn import Context
import muninn

class VerifyOSPFNeighbors(LearningTestCase):
    """Verify OSPF neighbors match expected state."""

    async def gather_state(self, context: Context) -> dict:
        state = {}
        for device in context.targets:
            output = await context.broker.execute(device, "show ip ospf neighbor")
            state[device.name] = muninn.parse(device.os, "show ip ospf neighbor", output)
        return state

    def compare_state(
        self,
        expected: dict,
        current: dict,
        context: Context
    ) -> None:
        for device_name, expected_data in expected.items():
            current_data = current.get(device_name, {})
            # Comparison logic...
```

## Connection Broker API

All command execution goes through the Connection Broker via `context.broker`. This enables connection pooling and command caching.

### CLI Operations

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

### REST API Operations

For devices with REST API connections:

```python
# GET request (cached by default)
data = await context.broker.get(device, "/api/v1/interfaces")

# GET without caching
data = await context.broker.get(device, "/api/v1/interfaces", use_cache=False)

# POST request (never cached)
response = await context.broker.post(device, "/api/v1/config", data={"vlan": 100})
```

### Connection Status

```python
# Check if a specific device is connected
if context.broker.is_connected(device.name):
    # Device is ready for commands

# Get status of all connections
status = context.broker.get_connection_status()
# Returns: {"spine-01": "connected", "leaf-01": "connected", ...}
```

## Device Adapter Properties

The `DeviceAdapter` provides device metadata (but not command execution):

```python
device.name        # "spine-01"
device.hostname    # "spine-01.lab.local"
device.os          # "nxos"
device.groups      # ["spine", "datacenter-1"]
device.metadata    # {"vendor": "cisco", "model": "N9K-C9336C"}
```

## Error Handling

### Graceful Failure

Record failures without raising exceptions to continue checking other devices:

```python
from huginn import ResultStatus

async def test(self, context: Context) -> None:
    for device in context.targets:
        try:
            output = await context.broker.execute(device, "show ip ospf neighbor")
            # Process output...
            context.results.add_result(status=ResultStatus.PASSED, message="...")
        except Exception as e:
            context.results.add_result(
                status=ResultStatus.ERRORED,
                message=f"{device.name}: {e}"
            )
```

### Critical Failures

Raise exceptions to abort the test entirely:

```python
async def setup(self, context: Context) -> None:
    # Verify all target devices are connected
    disconnected = [
        d.name for d in context.targets
        if not context.broker.is_connected(d.name)
    ]
    if disconnected:
        raise RuntimeError(f"Devices not connected: {disconnected}")
```

### Cleanup Safety

Since the framework manages connections, cleanup is typically minimal:

```python
async def cleanup(self, context: Context) -> None:
    # Only needed if the test modified device state that should be restored
    # Connection management is handled by the framework
    pass
```

## Test Module Structure

Each test module should contain exactly one test class:

```python
# tests/verify_ospf_neighbors.py
"""Verify OSPF neighbor adjacencies match expected state."""

from huginn import TestCase, Context
# Or from your project's base class
# from tests.base import LearningTestCase

# Optional: test metadata as module-level constants
DESCRIPTION = """
This test verifies that all OSPF neighbor adjacencies are in the
expected state (typically FULL for point-to-point or broadcast networks).
"""

PROCEDURE = """
1. Connect to each target device
2. Execute 'show ip ospf neighbor'
3. Parse neighbor state for each adjacency
4. Compare against expected parameters
"""

PASS_CRITERIA = """
All OSPF neighbors must be in FULL state and match the expected
neighbor IP addresses and interface bindings.
"""


class VerifyOSPFNeighbors(TestCase):
    """Verify OSPF neighbors match expected state."""

    async def setup(self, context: Context) -> None:
        ...

    async def test(self, context: Context) -> None:
        ...

    async def cleanup(self, context: Context) -> None:
        ...
```

Module-level constants (`DESCRIPTION`, `PROCEDURE`, `PASS_CRITERIA`) can be used by the reporting system to generate detailed test documentation.

## Integration with Muninn

For parsing CLI output, integrate with the Muninn parser library:

```python
import muninn  # Separate package

async def gather_state(self, context: Context) -> dict:
    state = {}
    for device in context.targets:
        # Execute through broker (enables caching)
        output = await context.broker.execute(device, "show ip ospf neighbor")

        # Parse using Muninn
        parsed = muninn.parse(
            os=device.os,
            command="show ip ospf neighbor",
            output=output
        )

        state[device.name] = parsed

        context.results.add_command_execution(
            device=device.name,
            command="show ip ospf neighbor",
            output=output,
            parsed=parsed
        )

    return state
```

## Best Practices

### 1. Keep Tests Focused

Each test should verify one specific thing. Prefer multiple focused tests over one test that checks everything.

### 2. Use Meaningful Result Messages

```python
from huginn import ResultStatus

# Good: specific and actionable
context.results.add_result(
    status=ResultStatus.FAILED,
    message="spine-01: OSPF neighbor 10.1.1.2 is DOWN, expected FULL"
)

# Bad: vague
context.results.add_result(
    status=ResultStatus.FAILED,
    message="OSPF check failed"
)
```

### 3. Record Command Executions

Always record command output for debugging and reporting:

```python
output = await context.broker.execute(device, command)
context.results.add_command_execution(
    device=device.name,
    command=command,
    output=output,
    parsed=parsed_data
)
```

### 4. Handle Missing Data Gracefully

```python
from huginn import ResultStatus

def compare_state(self, expected: dict, current: dict, context: Context):
    for device_name, expected_data in expected.items():
        current_data = current.get(device_name)

        if current_data is None:
            context.results.add_result(
                status=ResultStatus.FAILED,
                message=f"No data collected for {device_name}"
            )
            continue

        # Continue comparison...
```

### 5. Use Base Classes for Common Patterns

Don't repeat setup/cleanup logic across tests. Create project-specific base classes.

## Related Documents

- [Architecture](02-architecture.md): Context and adapter details
- [Testbed Specification](03-testbed-spec.md): Device definitions
- [Test Plan Specification](04-test-plan-spec.md): Test organization
- [Parser Project Brief](07-parser-project.md): Muninn integration

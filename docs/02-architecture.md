# Architecture

This document describes Huginn's core architecture, components, and execution flow.

## High-Level Architecture

```txt
┌─────────────────────────────────────────────────────────────────┐
│                          CLI / Runner                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐       │
│  │  Test Plan   │    │   Testbed    │    │    Config    │       │
│  │    Loader    │    │    Loader    │    │    Loader    │       │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘       │
│         │                   │                   │               │
│         └───────────────────┼───────────────────┘               │
│                             ▼                                   │
│                    ┌────────────────┐                           │
│                    │    Executor    │                           │
│                    └────────┬───────┘                           │
│                             │                                   │
│                             ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                  Connection Broker                       │   │
│  │  ┌─────────────────────┐    ┌─────────────────────────┐  │   │
│  │  │  Connection Pool    │    │    Command Cache        │  │   │
│  │  │  (SSH, HTTP, etc.)  │    │    (output caching)     │  │   │
│  │  └─────────────────────┘    └─────────────────────────┘  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                             │                                   │
│         ┌───────────────────┼───────────────────┐               │
│         ▼                   ▼                   ▼               │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐       │
│  │    Phase     │    │    Phase     │    │    Phase     │       │
│  │   Executor   │    │   Executor   │    │   Executor   │       │
│  └──────┬───────┘    └──────────────┘    └──────────────┘       │
│         │                                                       │
│         ▼                                                       │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              Test Case Group Executor                    │   │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐                   │   │
│  │  │  Group  │  │  Group  │  │  Group  │   ...             │   │
│  │  └────┬────┘  └─────────┘  └─────────┘                   │   │
│  └───────┼──────────────────────────────────────────────────┘   │
│          ▼                                                      │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    Test Runner                           │   │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐                   │   │
│  │  │  Test   │  │  Test   │  │  Test   │   ...             │   │
│  │  │ Context │  │ Context │  │ Context │                   │   │
│  │  └─────────┘  └─────────┘  └─────────┘                   │   │
│  └──────────────────────────────────────────────────────────┘   │
│                             │                                   │
│                             ▼                                   │
│                    ┌────────────────┐                           │
│                    │    Reporter    │                           │
│                    └────────────────┘                           │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│                        Plugin System                            │
└─────────────────────────────────────────────────────────────────┘
```

## Core Components

### CLI / Runner

The entry point for test execution. Responsibilities:

- Parse command-line arguments (mode, test plan path, filters, etc.)
- Load configuration from `pyproject.toml`
- Orchestrate the loading and execution pipeline
- Handle top-level error conditions

```bash
huginn run --mode testing --testbed testbed.yaml --plan test_plan.yaml
huginn run --mode learning --testbed testbed.yaml --plan test_plan.yaml --tags ospf
```

### Loaders

#### Test Plan Loader

Parses the test plan YAML and constructs an execution graph:

- Loads test case definitions as first-class entities
- Resolves phase dependencies into execution order
- Associates test case groups with phases
- Validates job module references exist
- Expands target specifications (devices, os, device groups) against the testbed
- Applies tag filters if specified (filtered tests excluded from results entirely)

#### Testbed Loader

Parses the testbed YAML and constructs the testbed model:

- Creates device objects with connection parameters
- Resolves group memberships
- Validates connectivity configuration
- Prepares device adapters (but does not connect)

#### Config Loader

Reads framework configuration from `pyproject.toml`:

- Default timeouts
- Report output paths
- Logging configuration
- Plugin settings

#### Data Model Loader

Loads an optional external data model representing intended infrastructure state:

- Recursively scans the specified directory for YAML files
- Merges all YAML files into a unified data structure
- Makes the merged data available via `context.data_model`
- Returns `None` if no data model path is configured

Data models can be specified in the test plan YAML, `pyproject.toml`, or via CLI (`--data-model`). CLI takes precedence.

### Executor

The main orchestration engine. Responsibilities:

- Execute phases in dependency order
- Manage parallel phase execution (where dependencies allow)
- Aggregate results across phases
- Handle phase-level failures and mark dependent phases as blocked
- Compute aggregate results (Passed, Partial, Failed, Blocked, Skipped)

### Phase Executor

Executes all test case groups within a single phase:

- Iterates through test case groups assigned to the phase
- Aggregates results across groups
- Reports phase-level aggregate result with pass/fail counts

### Test Case Group Executor

Executes all tests within a single test case group:

- Resolves test case references to test case definitions
- Determines target devices for each test (intersection of phase, group, and test case targets)
- Manages test parallelism within the test case group
- Collects results from individual tests
- Reports test case group-level aggregate result (Passed, Partial, Failed)

### Test Runner

Executes a single test:

- Instantiates the test class
- Constructs and injects the Context
- Calls `check_applicability()` to determine which targets are relevant
- Updates `context.targets` to contain only applicable devices
- For each non-applicable device, checks if learned parameters exist:
-
  - If parameters exist: Records as LOST_APPLICABILITY (was applicable, now isn't)
  - If no parameters: Records as NOT_APPLICABLE (never was applicable)
- If applicable devices exist, calls `setup()`, `test()`, `cleanup()` in sequence
- Ensures `cleanup()` runs even if `setup()` or `test()` fails
- Captures exceptions and converts to test failures

### Reporter

Generates hierarchical validation and run artifacts (phases → groups → test cases):

- Validation artifact written to `results/<timestamp>-validate/validate.json`
- Run summary artifact written to `results/<timestamp>-<mode>/run.json`
- Per-test case JSON artifacts with command output and granular results
- Aggregate status indicators (Passed, Partial, Failed, Blocked, Skipped, Not Applicable, Lost Applicability)
- Clear distinction between NOT_APPLICABLE (never applicable) and LOST_APPLICABILITY (was applicable, now isn't)
- Structured output (JSON) for CI/CD integration

### Connection Broker

The Connection Broker is a critical architectural component that manages all device connectivity and command execution. It exists because Huginn is designed for scale - test plans may contain thousands of atomic tests, and having each test establish and tear down connections would be prohibitively slow.

#### Responsibilities

1. **Connection Lifecycle Management**
   - Establish connections to all testbed devices at test plan start
   - Maintain connection health throughout test plan execution
   - Reconnect automatically if connections drop
   - Disconnect cleanly at test plan end

2. **Connection Pool**
   - Manage SSH, HTTP, and other transport connections
   - Provide connection handles to tests on demand
   - Track connection state (connected, disconnected, error)

3. **Command Execution**
   - Route command execution requests from tests to appropriate connections
   - Handle timeouts and retries
   - Record command execution for reporting

4. **Command Output Caching**
   - Cache command output to avoid redundant execution
   - Support cache invalidation policies
   - Handle concurrent access with locking

#### Connection Lifecycle

```txt
Test Plan Start
      │
      ▼
┌─────────────────────────────────────┐
│  Connect to ALL testbed devices     │
│  (parallel, with retry logic)       │
└─────────────────┬───────────────────┘
                  │
                  ▼
┌─────────────────────────────────────┐
│  Verify connectivity                │
│  (fail fast if critical devices     │
│   cannot be reached)                │
└─────────────────┬───────────────────┘
                  │
                  ▼
┌─────────────────────────────────────┐
│  Execute test case groups           │
│  (broker provides connections       │
│   to tests on demand)               │
└─────────────────┬───────────────────┘
                  │
                  ▼
┌─────────────────────────────────────┐
│  Disconnect from all devices        │
│  (parallel, graceful cleanup)       │
└─────────────────────────────────────┘
      │
      ▼
Test Plan End
```

#### Command Caching

Many tests execute the same commands. For example, 20 tests might all need output from `show ip ospf neighbor`. Without caching, that command executes 20 times. With caching, it executes once.

**Cache Strategies:**

1. **On-Demand Caching with Locking**
   - First test to request a command executes it and caches the result
   - Concurrent requests wait on a lock until cache is populated
   - Subsequent requests receive cached output

   ```python
   # Pseudocode
   async def execute(self, device: str, command: str, use_cache: bool = True) -> str:
       cache_key = (device, command)

       if use_cache and cache_key in self.cache:
           return self.cache[cache_key]

       async with self.locks[cache_key]:
           # Double-check after acquiring lock
           if use_cache and cache_key in self.cache:
               return self.cache[cache_key]

           output = await self._execute_on_device(device, command)

           if use_cache:
               self.cache[cache_key] = output

           return output
   ```

2. **Pre-Execution Caching** (optional optimization)
   - Before running tests, analyze which commands will be executed
   - Pre-execute and cache non-disruptive commands
   - Tests receive cached output immediately

   ```yaml
   # test_plan.yaml - optional pre-cache hint
   test_case_groups:
     ospf-validation:
       pre_cache:
         - command: "show ip ospf neighbor"
           target: { device_groups: [routers] }
         - command: "show ip ospf interface"
           target: { device_groups: [routers] }
       tests:
         # Tests in this test case group can use cached output
   ```

**Cache Invalidation:**

- Cache is scoped to a test case group by default (cleared between test case groups)
- Tests can opt out of caching for commands that must be fresh
- Configurable commands can be marked as "never cache" (e.g., commands with timestamps)

#### Broker API

```python
class ConnectionBroker:
    """Manages device connections and command execution."""

    # Connection management (called by framework, not tests)
    async def connect_all(self, devices: list[Device]) -> ConnectionReport
    async def disconnect_all(self) -> None
    async def verify_connectivity(self) -> ConnectionReport

    # Command execution (called by tests via Context)
    async def execute(
        self,
        device: DeviceAdapter,
        command: str,
        use_cache: bool = True
    ) -> str

    # REST API execution
    async def get(
        self,
        device: DeviceAdapter,
        endpoint: str,
        use_cache: bool = True
    ) -> dict

    async def post(
        self,
        device: DeviceAdapter,
        endpoint: str,
        data: dict
    ) -> dict  # POST never cached

    # Cache management
    def clear_cache(self, device: str | None = None) -> None
    def get_cache_stats(self) -> CacheStats

    # Connection status
    def is_connected(self, device: str) -> bool
    def get_connection_status(self) -> dict[str, ConnectionStatus]
```

#### Why Tests Don't Manage Connections

In frameworks like PyATS, tests often connect and disconnect from devices:

```python
# PyATS pattern - INEFFICIENT at scale
class MyTest(aetest.Testcase):
    def setup(self):
        self.device.connect()  # SSH handshake, auth, etc.

    def test(self):
        output = self.device.execute("show version")

    def cleanup(self):
        self.device.disconnect()
```

With thousands of atomic tests, this pattern means thousands of SSH handshakes. Each handshake takes 1-5 seconds depending on network latency and authentication method. A test plan with 1000 tests could spend 30+ minutes just on connection overhead.

Huginn's approach:

```python
# Huginn pattern - SCALABLE
class MyTest(TestCase):
    async def setup(self, context: Context) -> None:
        # Verify connectivity (connections already established)
        pass

    async def test(self, context: Context) -> None:
        # Execute through broker (connection reused, output may be cached)
        output = await context.broker.execute(device, "show version")

    async def cleanup(self, context: Context) -> None:
        # Nothing to tear down
        pass
```

## Context Object

The `Context` object is the central hub passed to every test method. It provides access to all framework services.

```python
class Context:
    # Execution metadata
    test_id: str                    # e.g., "1.0.0"
    test_title: str                 # e.g., "Verify OSPF Neighbor State"
    mode: ExecutionMode             # LEARNING or TESTING

    # Target infrastructure
    testbed: TestbedAdapter         # Full testbed metadata
    targets: list[DeviceAdapter]    # Devices this test targets (filtered)

    # Connection broker (primary interface for command execution)
    broker: ConnectionBroker        # Execute commands, access cache

    # Results
    results: ResultCollector        # Add granular pass/fail results

    # Parameters (learning/testing state)
    parameters: ParameterManager    # Save/load learned parameters

    # Data model (external source of truth)
    data_model: dict | None         # Merged data model, or None if not configured

    # Configuration
    config: FrameworkConfig         # Access to framework settings
```

### TestbedAdapter

Provides access to testbed metadata and device lookup. Note that connection management is handled by the Connection Broker, not the TestbedAdapter.

```python
class TestbedAdapter:
    name: str
    devices: dict[str, DeviceAdapter]

    def get_device(self, name: str) -> DeviceAdapter
    def get_devices_by_os(self, os: str) -> list[DeviceAdapter]
    def get_devices_by_group(self, group: str) -> list[DeviceAdapter]
```

### DeviceAdapter

Represents a device with its metadata and connection status. Command execution goes through the Connection Broker, not directly through the DeviceAdapter.

```python
class DeviceAdapter:
    # Device identification and metadata
    name: str                            # Device key from testbed
    os: str
    groups: list[str]
    metadata: dict[str, Any]

    # Connection status (managed by broker)
    connected: bool

    # Connection configuration (used by broker)
    connections: dict[str, ConnectionConfig]
```

Tests execute commands through the broker, passing the device:

```python
# In a test
output = await context.broker.execute(device, "show version")
data = await context.broker.get(device, "/api/v1/system")
```

This design ensures all command execution flows through the broker, enabling caching and connection management.

### ResultCollector

Accumulates test results without affecting control flow:

```python
class ResultCollector:
    results: list[Result]
    command_executions: list[CommandExecution]

    @property
    def status(self) -> ResultStatus  # Overall status

    def add_result(self, status: ResultStatus, message: str) -> None
    def add_command_execution(
        self,
        device: str,
        command: str,
        output: str,
        parsed: dict | None = None
    ) -> None
```

Result statuses:

- `PASSED`: Check succeeded
- `FAILED`: Check failed
- `NOT_APPLICABLE`: Check was not applicable to this device
- `ERRORED`: Check encountered an error
- `INFO`: Informational (does not affect pass/fail)

### ParameterManager

Handles learning/testing state persistence:

```python
class ParameterManager:
    async def save(self, data: dict) -> None    # Learning mode
    async def load(self) -> dict                 # Testing mode

    @property
    def file_path(self) -> Path  # Location of parameters file
```

Parameters are stored as JSON files, enabling version control and manual inspection.

## Execution Flow

### Full Execution Flow

```txt
1.  CLI parses arguments
2.  Config loaded from pyproject.toml
3.  Testbed loaded from YAML
4.  Test plan loaded from YAML (test cases, groups, phases)
5.  Data model loaded (if configured in test plan, config, or CLI)
6.  Tag filters applied (filtered tests excluded from execution entirely)
7.  Phase dependency graph constructed
8.  CONNECTION BROKER: Connect to ALL testbed devices (parallel)
9.  CONNECTION BROKER: Verify connectivity (fail fast if critical devices unreachable)
10. For each phase (in dependency order):
    a. For each test case group in phase:
       i.   Resolve test case references to definitions
       ii.  Resolve target devices (intersection of phase, group, test case targets)
       iii. (Optional) Pre-execute and cache commands if pre_cache defined
       iv.  For each test case in group (potentially parallel):
            - Instantiate job class
            - Construct Context with targets, broker, parameters, data_model
            - Call job.check_applicability(context)
            - For each non-applicable device:
              * If learned parameters exist for device → record as LOST_APPLICABILITY
              * Otherwise → record as NOT_APPLICABLE
            - Update context.targets to contain only applicable devices
            - If no applicable devices, skip to result collection
            - Call job.setup(context)
            - Call job.test(context)
            - Call job.cleanup(context)
            - Collect result (Passed, Failed, Errored, Not Applicable, Lost Applicability)
       v.   Aggregate group results (compute Passed/Partial/Failed)
    b. Clear phase-scoped cache entries
    c. Aggregate phase results (compute Passed/Partial/Failed)
    d. If phase has failures and has dependents, mark dependent phases as blocked
11. CONNECTION BROKER: Disconnect from all devices (parallel)
12. Generate hierarchical report (phases → groups → test cases)
13. Return exit code (0 if all passed, non-zero otherwise)
```

### Test Lifecycle

```txt
                    ┌─────────┐
                    │  Init   │
                    └────┬────┘
                         │
                         ▼
          ┌──────────────────────────┐
          │ check_applicability()    │
          │ (filter targets)         │
          └────────────┬─────────────┘
                       │
           ┌───────────┴───────────┐
           │                       │
    Some Applicable          None Applicable
           │                       │
           ▼                       │
   ┌─────────────────┐             │
   │  setup(context) │             │
   └────────┬────────┘             │
            │                      │
  ┌─────────┴─────────┐            │
  │                   │            │
Success            Failure         │
  │                   │            │
  ▼                   │            │
┌───────────────┐     │            │
│ test(context) │     │            │
└───────┬───────┘     │            │
        │             │            │
        ▼             ▼            │
┌────────────────────────────┐     │
│     cleanup(context)       │     │
│      (always runs)         │     │
└────────────┬───────────────┘     │
             │                     │
             └──────────┬──────────┘
                        │
                        ▼
               ┌───────────────┐
               │Collect Results│
               └───────────────┘
```

**Notes on applicability:**

- `check_applicability()` is called first with all assigned targets
- Non-applicable devices are recorded with their reasons:
  - **NOT_APPLICABLE**: If no learned parameters exist for the device (never was applicable)
  - **LOST_APPLICABILITY**: If learned parameters exist (was applicable, now isn't)
- LOST_APPLICABILITY results contribute to test failure; NOT_APPLICABLE results do not
- `context.targets` is updated to contain only applicable devices
- If no devices are applicable, `setup()` and `test()` are skipped entirely
- `cleanup()` only runs if `setup()` was called

## Plugin System

Huginn supports optional plugins for extensibility without bloating the core.

### Plugin Types

| Type           | Purpose                               | Example                                  |
| -------------- | ------------------------------------- | ---------------------------------------- |
| **Inventory**  | Dynamic testbed from external sources | NetBox, IPAM/DDI, CSV/Excel              |
| **Connection** | Additional connection protocols       | NETCONF, gNMI, SNMP                      |
| **Reporter**   | Transform run artifacts for consumers | HTML dashboards, JUnit XML, Slack digest |
| **Parser**     | Output parsing (typically via Muninn) | Vendor-specific parsers                  |
| **Hook**       | Lifecycle callbacks                   | Pre-test setup, post-test cleanup        |

### Inventory Plugins

Inventory plugins enable loading testbed data from external sources instead of (or in addition to) static YAML files. This supports environments where device inventory is managed in external systems.

**Use Cases:**

- **DCIM/CMDB**: NetBox, Device42, ServiceNow CMDB
- **IPAM/DDI**: Infoblox, BlueCat, phpIPAM
- **File-based**: CSV, Excel spreadsheets, JSON exports
- **Network Controllers**: Cisco DNA Center, Arista CloudVision
- **Custom**: Internal inventory APIs, databases

**Plugin Interface:**

```python
from huginn.plugins import InventoryPlugin
from huginn.models import Testbed, Device

class NetBoxInventory(InventoryPlugin):
    """Load testbed from NetBox DCIM."""

    def load(self, config: dict) -> Testbed:
        """Load devices from NetBox and return a Testbed.

        Args:
            config: Plugin configuration from pyproject.toml

        Returns:
            Testbed object with devices populated from NetBox
        """
        devices = []
        # Query NetBox API...
        for nb_device in self.query_netbox(config["url"], config["token"]):
            devices.append(Device(
                name=nb_device["name"],
                hostname=nb_device["primary_ip"]["address"],
                os=self.map_platform(nb_device["platform"]),
                groups=self.extract_groups(nb_device),
                connections=self.build_connections(nb_device),
                metadata=nb_device.get("custom_fields", {})
            ))
        return Testbed(devices=devices)
```

**Configuration:**

```toml
# pyproject.toml
[tool.huginn]
inventory_plugin = "huginn-netbox"  # Use NetBox plugin instead of YAML

[tool.huginn.plugins.huginn-netbox]
url = "https://netbox.example.com"
token = "${NETBOX_API_TOKEN}"
# Plugin-specific filtering
site = "dc1"
role = ["router", "switch"]
status = "active"
```

**CLI Override:**

```bash
# Use inventory plugin
huginn run --inventory-plugin huginn-netbox

# Override with static testbed (ignores plugin)
huginn run --testbed testbed.yaml
```

### Reporter Plugins

Reporter plugins consume Huginn's structured validation and run artifacts and render
them for downstream consumers. The built-in JSON reporter writes canonical artifacts
to disk, and additional plugins can layer on alternate presentations or export
formats without changing test execution.

**Use Cases:**

- **Human-friendly views**: HTML dashboards, static sites, searchable drill-down UIs
- **Tooling integration**: JUnit XML for CI systems, custom JSON for data pipelines
- **Notifications**: Slack summaries, email digests, incident attachments

This keeps the execution core focused on producing stable machine-readable artifacts
while allowing reporting formats to evolve independently.

### Hook System

Hooks allow code execution at specific lifecycle points:

```python
# In pyproject.toml or plugin registration
[tool.huginn.hooks]
pre_test = "myproject.hooks:before_test"
post_test = "myproject.hooks:after_test"
on_failure = "myproject.hooks:notify_failure"
```

Available hook points:

- `pre_phase`: Before phase execution
- `post_phase`: After phase execution
- `pre_test_case_group`: Before test case group execution
- `post_test_case_group`: After test case group execution
- `pre_test`: Before each test
- `post_test`: After each test
- `on_failure`: When a test fails
- `on_error`: When a test errors

### Plugin Discovery

Plugins are discovered via Python entry points:

```toml
# In plugin's pyproject.toml
[project.entry-points."huginn.plugins"]
my_plugin = "my_plugin:register"
```

This allows pip-installable plugins without modifying Huginn's core.

## Error Handling

### Test-Level Errors

- Exceptions in `setup()`: Test marked as ERRORED, `cleanup()` still runs
- Exceptions in `test()`: Test marked as ERRORED, `cleanup()` still runs
- Exceptions in `cleanup()`: Logged, does not change test status

### Test Case Group-Level Errors

- If a test case group fails, dependent test case groups are marked as BLOCKED
- Test case group failure does not abort execution of independent test case groups

### Framework-Level Errors

- Invalid test plan: Abort with clear error message
- Invalid testbed: Abort with clear error message
- Configuration errors: Abort with clear error message

## Async Patterns

All device operations are async, enabling efficient parallel execution. Commands are executed through the broker:

```python
async def gather_state(self, context: Context) -> dict:
    # Execute commands across all targets in parallel through the broker
    async with asyncio.TaskGroup() as tg:
        tasks = {
            device.name: tg.create_task(
                context.broker.execute(device, "show version")
            )
            for device in context.targets
        }

    return {name: task.result() for name, task in tasks.items()}
```

The framework uses `asyncio.TaskGroup` (Python 3.11+) for structured concurrency, ensuring proper cleanup on failures.

Note that even when executing in parallel, the broker's caching still applies - if multiple concurrent tasks request the same command on the same device, only one execution occurs and others receive the cached result.

## Directory Structure

A typical Huginn project:

```txt
project/
├── pyproject.toml          # Framework config + dependencies
├── testbed.yaml            # Device inventory
├── test_plan.yaml          # Test organization
├── tests/                  # Test modules
│   ├── __init__.py
│   ├── base.py             # Project-specific base classes
│   ├── verify_ospf.py
│   └── verify_bgp.py
├── parameters/             # Learned state (auto-generated)
│   ├── 1.0.0_verify_ospf_parameters.json
│   └── 2.0.0_verify_bgp_parameters.json
├── reports/                # Validation artifacts (auto-generated)
│   └── validate.json
└── results/                # Validation and run artifacts (auto-generated)
    ├── 2026-Feb-07-16-35-10-validate/
    │   └── validate.json
    └── 2026-Feb-07-16-38-43-testing/
        ├── run.json
        └── test-cases/
            ├── 1.0.0_verify_ospf/
            │   └── result.json
            └── 2.0.0_verify_bgp/
                └── result.json
```

## Next Steps

- [Testbed Specification](03-testbed-spec.md): Detailed testbed YAML schema
- [Test Plan Specification](04-test-plan-spec.md): Detailed test plan YAML schema
- [Test Authoring](05-test-authoring.md): Writing tests with the ABC pattern

# Huginn: Test Automation Framework

## Overview

Huginn is a Python-native, async-first test automation framework designed for validating network infrastructure, servers, and applications. Named after one of Odin's ravens in Norse mythology - who flies across the world gathering information and reporting back - Huginn embodies the same principle: dispatch tests to observe your infrastructure, gather state, and report findings.

## Philosophy

### Power Over Simplicity

Huginn is built for skilled practitioners - network engineers who are also proficient Python developers. The framework does not prioritize low-code or no-code experiences. Instead, it maximizes capability for experts who need to accomplish complex tasks efficiently.

### Minimal Core, Optional Extensions

Following the Nornir model, Huginn maintains a minimal, fast core. Additional capabilities are provided through clearly documented, optional plugins. Nothing is bundled that isn't essential. This keeps the framework lightweight and ensures users only pay for what they use.

### Framework Handles Orchestration, Tests Handle Logic

Huginn concerns itself with:

- Test discovery and execution ordering
- Device connection lifecycle (connect at test plan start, disconnect at end)
- Connection brokering and command output caching
- Context construction and injection
- Result aggregation and reporting

Tests themselves control:

- What commands to execute against their target devices
- How to parse and interpret output
- Whether to run operations serially or in parallel across targets
- Pass/fail determination logic

### Scalability by Design

Huginn is designed for test plans containing thousands of atomic tests. Each test typically validates one specific aspect of one command's output. To support this scale:

- **Framework-managed connections**: The framework establishes connections to all testbed devices at test plan start and maintains them throughout execution. Tests do not bring up or tear down connections.
- **Connection broker**: Tests access device channels (SSH, HTTP, etc.) through a broker that manages connection pooling and health.
- **Command output caching**: The broker can cache command output, allowing multiple tests to share results from a single command execution rather than redundantly executing the same command.

### Async-First

All tests are implemented using asynchronous patterns. This enables efficient parallel execution across many devices without thread pool overhead, and aligns with modern Python async libraries like scrapli and httpx.

## Target Users

Huginn is designed for:

- **Network engineers** with strong Python development skills
- **Automation engineers** working with network, server, or application infrastructure
- **Testing specialists** who need flexibility over hand-holding

Users should be comfortable with:

- Python async/await patterns
- Object-oriented design (ABC inheritance)
- YAML configuration
- Network device interaction concepts

## Core Capabilities

### Dual Execution Modes

Huginn supports two primary execution modes:

1. **Learning Mode**: Execute against live infrastructure, capture current state as "known good" parameters. These parameters are persisted for later comparison.
2. **Testing Mode**: Execute against live infrastructure, compare current state against previously-learned parameters, report any deviations.

This pattern enables "golden state" validation without manually defining expected values.

### Flexible Targeting

Tests can target infrastructure by:

- **Specific devices**: Explicit list of hostnames
- **Operating system**: All devices running a particular OS
- **Groups**: Arbitrary device groupings (e.g., "spine-switches", "leaf-switches", "dmz-firewalls")

### Three-Tier Test Organization

Tests are organized into a three-tier hierarchy:

1. **Phases**: High-level stages (e.g., pre-change, change, post-change) with dependencies
2. **Test Case Groups**: Logical groupings of test cases within phases
3. **Test Cases**: First-class entities that can be reused across multiple groups and phases

This structure enables powerful patterns like change validation, where the same test cases run in both pre-change and post-change phases to verify state consistency.

### Parallel Test Execution

The framework can execute multiple tests in parallel within a test case group. Individual tests control their own parallelism when interacting with multiple target devices - the framework provides the targets and connection broker, but tests decide whether to execute commands serially or in parallel across their targets.

### Comprehensive Reporting

Huginn generates structured JSON artifacts for both validation and execution:

- Validation writes `results/<timestamp>-validate/validate.json`
- Each run writes `results/<timestamp>-<mode>/run.json`
- Each test case in a run writes its own `result.json` with command output, parsed data, and granular checks

## Comparison to Existing Frameworks

### vs. PyATS/Genie

| Aspect             | PyATS                          | Huginn                         |
| ------------------ | ------------------------------ | ------------------------------ |
| **Openness**       | Compiled code, poor type hints | Fully open, type-annotated     |
| **Footprint**      | Heavy, batteries-included      | Minimal core, optional plugins |
| **Learning curve** | Steep, many concepts           | Focused, Python-native         |
| **Async support**  | Limited (Unicon is sync)       | Async-first (scrapli)          |
| **Parsing**        | Bundled Genie parsers          | Decoupled (Muninn project)     |

Huginn preserves PyATS's useful patterns (testbed YAML, dual-mode execution, structured test organization) while shedding the bloat, compilation issues, and tight coupling.

### vs. Robot Framework

| Aspect             | Robot Framework                  | Huginn                     |
| ------------------ | -------------------------------- | -------------------------- |
| **Test authoring** | Keyword-based DSL                | Python-native              |
| **Target users**   | Broad, including non-programmers | Skilled Python developers  |
| **Abstraction**    | Multiple keyword layers          | Direct Python control      |
| **Flexibility**    | Constrained by keyword model     | Full Python expressiveness |

Robot Framework prioritizes accessibility through its keyword abstraction. Huginn prioritizes power and directness for users who don't need that abstraction layer.

## Scope

Huginn supports testing:

- **Network devices**: Routers, switches, firewalls (via SSH/CLI or REST APIs)
- **Servers**: Especially out-of-band management (CIMC, ILO, iDRAC)
- **Appliances**: Cisco ISE, ACI APIC, DNA Center, similar platforms
- **Applications**: Any system exposable via SSH, REST, or custom protocols

The framework is deliberately not limited to network devices - "target" is intentionally generic.

## Companion Project: Muninn

Parsing CLI output into structured data is essential for infrastructure testing. Rather than bundling parsers (as PyATS does with Genie), Huginn delegates parsing to a separate companion project: **Muninn**.

Muninn will provide:

- A library of parsers indexed by OS and command
- Schema definitions for parser output
- Regex-based parsing implemented in Python (no external DSL)
- Comprehensive test coverage for parsers

Critically, Muninn is fully decoupled from Huginn. Users can leverage Muninn parsers without installing Huginn, and vice versa. This avoids the dependency entanglement that plagues PyATS/Genie.

See [Parser Project Brief](07-parser-project.md) for details.

## Documentation Structure

| Document                                              | Description                                        |
| ----------------------------------------------------- | -------------------------------------------------- |
| [Glossary](00-glossary.md)                            | Formal lexicon and term definitions                |
| [Architecture](02-architecture.md)                    | Core components, execution flow, plugin system     |
| [Testbed Specification](03-testbed-spec.md)           | Testbed YAML schema, devices, groups, connectivity |
| [Test Plan Specification](04-test-plan-spec.md)       | Test plan YAML schema, phases, groups, test cases  |
| [Test Authoring](05-test-authoring.md)                | ABC class, base classes, async patterns            |
| [Configuration](06-configuration.md)                  | pyproject.toml schema, defaults                    |
| [Parser Project Brief](07-parser-project.md)          | Muninn motivation and goals                        |
| [Future Considerations](99-future-considerations.md)  | Roadmap items and use cases for future exploration |

## Quick Example

```yaml
# testbed.yaml
devices:
  spine-01:
    os: nxos
    groups: [spine, datacenter-1]
    connections:
      ssh:
        host: 10.1.1.1
        port: 22

  leaf-01:
    os: nxos
    groups: [leaf, datacenter-1]
    connections:
      ssh:
        host: 10.1.1.2
        port: 22
```

```yaml
# test_plan.yaml
test_cases:
  "1.0.0":
    title: Verify Device Reachability
    job: tests/verify_reachability.py
    tags: [connectivity]

  "2.0.0":
    title: Verify OSPF Neighbor State
    job: tests/verify_ospf_neighbors.py
    tags: [ospf, routing]
    target:
      device_groups: [spine]

test_case_groups:
  connectivity:
    tests: ["1.0.0"]

  ospf-validation:
    tests: ["2.0.0"]

phases:
  validation:
    description: Validate network state
    test_case_groups: [connectivity, ospf-validation]
```

```python
# tests/verify_ospf_neighbors.py
from huginn import TestCase, Context, ResultStatus, ExecutionMode

class VerifyOSPFNeighbors(TestCase):
    """Verify OSPF neighbors are in expected state."""

    async def setup(self, context: Context) -> None:
        # Verify target devices are connected (framework manages connection lifecycle)
        for device in context.targets:
            if not device.connected:
                context.results.add_result(
                    status=ResultStatus.ERRORED,
                    message=f"Device {device.name} is not connected"
                )

    async def test(self, context: Context) -> None:
        if context.mode == ExecutionMode.LEARNING:
            state = await self.gather_ospf_state(context)
            await context.parameters.save(state)
        else:
            expected = await context.parameters.load()
            current = await self.gather_ospf_state(context)
            self.compare_state(expected, current, context)

    async def cleanup(self, context: Context) -> None:
        # No connection teardown needed - framework manages connections
        pass

    async def gather_ospf_state(self, context: Context) -> dict:
        results = {}
        for device in context.targets:
            # Command execution goes through the connection broker
            output = await context.broker.execute(device, "show ip ospf neighbor")
            parsed = muninn.parse(device.os, "show ip ospf neighbor", output)
            results[device.name] = parsed
        return results

    def compare_state(self, expected: dict, current: dict, context: Context) -> None:
        for device_name, expected_data in expected.items():
            current_data = current.get(device_name, {})
            # Comparison logic with context.results.add_result()
```

This example illustrates the core patterns: YAML-defined testbed and test plan with three-tier organization (phases → groups → test cases), Python-native async job implementation, learning/testing modes, broker-mediated command execution, and Muninn integration for parsing.

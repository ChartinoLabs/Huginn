# Huginn: Test Automation Framework

## Overview

Huginn is a Python-native, async-first test automation framework designed for validating network infrastructure, servers, and applications. Named after one of Odin's ravens in Norse mythology - who flies across the world gathering information and reporting back - Huginn embodies the same principle: dispatch tests to observe your infrastructure, gather state, and report findings.

## Philosophy

### Power Over Simplicity

Huginn is built for skilled practitioners - network engineers who are also proficient Python developers. The framework does not prioritize low-code or no-code experiences. Instead, it maximizes capability for experts who need to accomplish complex tasks efficiently.

### Minimal Core, Optional Extensions

The guiding philosophy is the Nornir model: a minimal, fast core with additional capabilities provided through clearly documented, optional plugins. Nothing bundled that isn't essential. This keeps the framework lightweight and ensures users only pay for what they use.

> **Note:** While Huginn is in early development, the framework ships as a batteries-included package with default plugins built in. The plugin boundaries exist in code, but not all extension points are fully decoupled or independently installable yet. The intent is to converge on the philosophy above as the project matures.

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
- The schema of parameters to save and load
- Whether to run operations serially or in parallel across targets
- Pass/fail determination logic
- The content and detail of test case results

### Scalability by Design

Huginn is designed for test plans containing thousands of atomic tests. Each test typically validates one specific aspect of one command's output. To support this scale, Huginn provides the following capabilities:

- **Framework-managed connections**: The framework establishes connections to all testbed devices at test plan start and maintains them throughout execution. Tests do not bring up or tear down connections.
- **Connection broker**: Tests access device channels (SSH, HTTP, etc.) through a broker that manages connection pooling and health.
- **Command output caching**: The broker can cache command output, allowing multiple tests to share results from a single command execution rather than redundantly executing the same command.

### Async-First

All tests are implemented using asynchronous patterns. This enables efficient parallel execution across many devices without thread pool overhead, and aligns with modern Python async libraries like scrapli and httpx.

## Target Users

Huginn is designed for:

- **Network engineers** with strong Python development skills
- **Automation engineers** working with network, server, or application infrastructure
- **Testing specialists** who need a testing framework addressing test plan organization and test case execution while allowing customizability over test automation implementation, testbed connectivity, and reporting mechanisms

Users should be comfortable with:

- Python async/await patterns
- Object-oriented design (ABC inheritance)
- YAML configuration
- Network device interaction concepts

## Core Capabilities

### Dual Execution Modes

Huginn supports two primary execution modes:

1. **Learning Mode**: Execute against live infrastructure, capture current state as "known good" parameters. These parameters are persisted for later evaluation.
2. **Testing Mode**: Execute against live infrastructure, evaluate current state against previously-learned parameters, report results.

This pattern enables "golden state" validation without manually defining expected values. See [Execution Modes](execution-modes.md) for the full explanation.

### Flexible Targeting

Tests can target infrastructure by:

- **Specific devices**: Explicit list of hostnames
- **Operating system**: All devices running a particular OS
- **Groups**: Arbitrary device groupings (e.g., "spine-switches", "leaf-switches", "dmz-firewalls")

### Test Plan Organization

Tests are organized into a four-tier hierarchy of scenarios, phases, test case groups, and test cases. This structure enables powerful patterns like change validation, where the same test cases run in both pre-change and post-change phases to verify state consistency. See [Test Plan Structure](test-plan-structure.md) for the full explanation.

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

Robot Framework prioritizes accessibility through its keyword abstraction. Huginn prioritizes power and directness for users who don't need that abstraction layer. The appeal of no-code and low-code approaches is also diminishing as AI coding assistants become prevalent - engineers who can describe what they want precisely can generate correct Python directly, making a keyword DSL an unnecessary indirection rather than a productivity gain.

## Scope

Huginn supports testing:

- **Network devices**: Routers, switches, firewalls (via SSH/CLI or REST APIs)
- **Servers**: Especially out-of-band management (CIMC, ILO, iDRAC)
- **Appliances**: Cisco ISE, ACI APIC, DNA Center, similar platforms
- **Applications**: Any system exposable via SSH, REST, or custom protocols

The framework is deliberately not limited to network devices - "target" is intentionally generic.

## Companion Project: Muninn

Parsing CLI output into structured data is essential for infrastructure testing. Rather than bundling parsers (as PyATS does with Genie), Huginn delegates parsing to a separate companion project: **Muninn**.

Muninn provides:

- A library of parsers indexed by OS and command
- TypedDict return types for IDE autocompletion and type checking
- Regex-based parsing implemented in Python (no external DSL)
- Comprehensive test coverage for parsers

Critically, Muninn is fully decoupled from Huginn. Users can leverage Muninn parsers without installing Huginn, and vice versa. This avoids the dependency entanglement that plagues PyATS/Genie.

See the [Muninn documentation](https://chartinolabs.github.io/Muninn/) for details.

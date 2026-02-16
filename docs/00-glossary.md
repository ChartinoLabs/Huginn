# Glossary

This document defines the formal lexicon for Huginn. These terms have specific meanings within the framework and documentation.

## Infrastructure

### Device

A unit of infrastructure within a testbed. Devices can be network equipment (routers, switches, firewalls), servers, appliances, or any system that can be connected to and queried. Each device has a hostname, operating system identifier, optional device group memberships, and one or more connection configurations.

### Device Group

A logical grouping of devices in a testbed. Device groups are arbitrary labels assigned to devices for organizational and targeting purposes. A device can belong to multiple device groups. Common patterns include role-based groups (spine, leaf, border), location-based groups (datacenter-1, building-a), and environment-based groups (production, staging).

### Testbed

A collection of devices making up a production-like, scaled-down version of an environment. The testbed defines the infrastructure inventory including device connection parameters, device group memberships, and metadata. Defined in YAML format.

## Test Definitions

### Job

A unit of test automation that can be executed against one or more devices in a testbed. A job is implemented as a Python module containing a class that inherits from the TestCase base class. Jobs define reusable test logic independent of specific targets or parameters. The same job can be referenced by multiple test cases, each with different parameters.

### Parameters

Expected state data associated with a test case, used for validation during test execution. Parameters can be sourced from:

- **File-based**: JSON files following the convention `parameters/{test_case_id}.json`. In learning mode, parameters are captured from live infrastructure and persisted. In testing mode, parameters are loaded and compared against current state.
- **Data model-based**: Derived from an external data model (e.g., Network as Code YAML) representing intended infrastructure state. The job queries the data model for expected values.

If a test case has no parameters file and no data model, it requires execution in learning mode to establish baseline parameters.

### Data Model

An external source of truth representing intended infrastructure state, typically a YAML file conforming to a defined schema. Data models can serve as parameters for test cases, enabling validation of actual device state against declared intent. This pattern is commonly used with Infrastructure as Code approaches like Cisco's Network as Code.

### Target

The specification of which devices a test case applies to. Targets can be defined by:

- **Explicit devices**: A list of device names.
- **Device groups**: All devices belonging to specified device groups.
- **Operating system**: All devices running specified operating systems.

Multiple selectors are intersected (AND logic). Targets can be specified at the phase level, test case group level, test case level, or any combination (intersected).

### Test Case

A first-class entity in the test plan that instantiates a job with a specific identity. Test cases are defined once in the `test_cases` section of a test plan and referenced by ID in test case groups. Each test case has:

- A unique identifier
- A reference to a job (module path)
- Optional target specification
- Optional tags for filtering
- Parameters sourced by convention (`parameters/{id}.json`) or from a data model

The same test case can be referenced in multiple test case groups, enabling reuse across phases (e.g., pre-change and post-change validation).

### Test Case Group

A logical grouping of test cases and/or other test case groups within a phase. Test case groups reference test cases by ID and can include other groups by name, enabling hierarchical organization. Groups can specify targets that apply to all contained test cases, and the framework executes test cases within a group potentially in parallel.

**Nesting**: Test case groups can be nested to create reusable, feature-specific groupings. For example, an "ospf-tests" group containing OSPF-related test cases can be included in both "pre-change-validation" and "post-change-validation" groups. This promotes reuse and keeps feature-specific tests organized together.

### Phase

A high-level organizational unit in a test plan representing a stage of test execution. Phases contain one or more test case groups and can declare dependencies on other phases. Common patterns include:

- **Pre-change**: Validate state before making changes
- **Change**: Apply configuration or operational changes
- **Post-change**: Validate state after changes

Phases provide structure for reporting (collapse/expand, filtering) and establish execution order through dependencies.

### Test Plan

A collection of test cases, test case groups, phases, and associated metadata defining how testing outcomes should be achieved. The test plan specifies:

- **Test cases**: First-class definitions of what to test
- **Test case groups**: Logical groupings of test case references
- **Phases**: High-level stages with dependencies defining execution order

Defined in YAML format.

## Execution

### Mode

The execution mode for a test run. Huginn supports two modes:

- **Learning**: Execute against live infrastructure, capture current state, and persist it as parameters for future comparison.
- **Testing**: Execute against live infrastructure, compare current state against previously learned parameters (or data model), and report deviations.

### Run

A single execution of a test plan against a testbed. A run establishes connections to all devices, executes phases in dependency order, executes test case groups within each phase, collects results, and generates reports. Test cases filtered out by tags or other criteria do not appear in run results.

### Context

The object passed to jobs during execution. Contains access to the connection broker, target devices, results collector, parameters (file-based or data model), and execution metadata. The context is the primary interface between a job and the framework.

### Result

The outcome of a test case execution. Possible values:

- **Passed**: All assertions succeeded.
- **Failed**: One or more assertions did not match expected state.
- **Errored**: An exception occurred during execution.
- **Skipped**: The test case was in scope but determined at runtime to be not applicable (e.g., feature not configured in data model, no matching targets).
- **Blocked**: The test case could not run because a dependency (phase or group) failed.

Test cases filtered out before execution (e.g., by tags) do not appear in results at all.

### Aggregate Result

The computed outcome for a test case group or phase, derived from the results of contained test cases. Possible values:

- **Passed**: 100% of test cases passed.
- **Partial**: Some test cases passed, some did not (mixed results).
- **Failed**: 0% of test cases passed (catastrophic failure).
- **Blocked**: Could not execute because a dependency failed.
- **Skipped**: All contained test cases were skipped.

Aggregate results include counts (e.g., "1995/2000 passed") to provide visibility into the scope and nature of any failures.

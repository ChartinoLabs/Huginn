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

A unit of test automation that can be executed against one or more devices in a testbed. A job is implemented as a Python class that inherits from the TestCase base class. A test case references its job either by file path relative to the project root (`jobs/iosxe/ospf/verify_neighbor_state.py`) or by dotted module path (`acme_jobs.ospf.verify_neighbor_state`), optionally followed by `:ClassName` to pick one class when the module defines several. Jobs define reusable test logic independent of specific targets or parameters. The same job can be referenced by multiple test cases, each with different parameters.

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
- **Excluded devices**: Device names removed from whatever the other selectors matched.

Values within one selector are combined with OR (`groups: [spine, border]` matches a device in either group). Different selectors are intersected (AND logic). Explicit `devices` cannot be combined with `groups` or `os` in the same target; `exclude_devices` works with either form. Targets can be specified at the phase level, test case group level, test case level, or any combination (intersected).

### Test Case

A first-class entity in the test plan that instantiates a job with a specific identity. Test cases are defined once in the `test_cases` section of a test plan and referenced by ID in test case groups. Each test case has:

- A unique identifier
- A reference to a job (file path or dotted module path, with optional `:ClassName`)
- Optional target specification
- Optional tags for filtering
- Parameters sourced by convention (`parameters/{id}.json`) or from a data model

The same test case can be referenced in multiple test case groups, enabling reuse across phases (e.g., pre-change and post-change validation).

### Test Case Group

A logical grouping of test cases and/or other test case groups within a phase. Test case groups reference test cases by ID and can include other groups by name, enabling hierarchical organization. Groups can specify targets that apply to all contained test cases. By default the framework executes the test cases within a group in parallel; a group's `strategy` can make them serial or cap concurrency.

**Nesting**: Test case groups can be nested to create reusable, feature-specific groupings. For example, an "ospf-tests" group containing OSPF-related test cases can be included in both "pre-change-validation" and "post-change-validation" groups. This promotes reuse and keeps feature-specific tests organized together.

When a phase references a parent group, the child groups' test cases are flattened into it and only the parent's `target`, `tags`, and `strategy` apply. The child's own `target` and `tags` are currently ignored for tests included this way. Carrying the child's `target` (intersected with the parent's) and `tags` (added to the parent's) through the parent is planned in [#218](https://github.com/ChartinoLabs/Huginn/issues/218).

### Scenario

A complete end-to-end validation workflow within a test plan, such as shutting down a link and verifying the network converges. Each scenario contains one or more phases. Scenarios run one at a time, and a phase that does not pass in one scenario does not affect the others.

### Phase

A high-level organizational unit within a scenario representing a stage of test execution. Phases contain one or more test case groups and can optionally declare dependencies on other phases in the same scenario through `depends_on`. Common patterns include:

- **Pre-change**: Validate state before making changes
- **Change**: Apply configuration or operational changes
- **Post-change**: Validate state after changes

Phases provide structure for reporting (collapse/expand, filtering) and establish execution order through dependencies. Phases within a scenario run one at a time; the test case groups within a phase run in parallel by default, subject to the phase's `strategy`.

If a phase finishes with any status other than PASSED, every phase that has not yet run in that scenario is recorded as BLOCKED, whether or not it depends on the phase that did not pass. Changing this so that only a FAILED or ERRORED phase blocks, and only the phases that depend on it, is planned in [#218](https://github.com/ChartinoLabs/Huginn/issues/218).

### Test Plan

A collection of test cases, test case groups, scenarios, and associated metadata defining how testing outcomes should be achieved. The test plan specifies:

- **Test cases**: First-class definitions of what to test
- **Test case groups**: Logical groupings of test case references
- **Scenarios**: End-to-end workflows, each containing phases with dependencies defining execution order

Defined in YAML format.

## Execution

### Mode

The execution mode for a test run. Huginn supports two modes:

- **Learning**: Execute against live infrastructure, capture current state, and persist it as parameters for future comparison.
- **Testing**: Execute against live infrastructure, compare current state against previously learned parameters (or data model), and report deviations.

### Run

A single execution of a test plan against a testbed. A run establishes connections to all devices, executes each scenario's phases in dependency order, executes test case groups within each phase, collects results, and generates reports. Test cases filtered out by tags or other criteria do not appear in run results.

### Command Support

The determination of whether a target device supports the CLI command(s) required by a test case. Command support can be:

- **Static**: Declared in the test plan via target specifications (devices, device groups, operating systems). Resolved before test execution.
- **Dynamic**: Determined at runtime by the test case itself via the `check_command_support()` method or during `gather_state()`. Enables tests to introspect their assigned targets and filter based on device capabilities, running features, or other runtime conditions.

Dynamic non-applicability arises from two distinct situations:

1. **Command not supported**: The device does not recognize the show command the job requires. Detected in `check_command_support()`.
2. **Attribute absent**: The command succeeds but the specific attribute the job validates does not exist in the parsed output - either because the platform does not report it or because the feature is not configured. Detected in `gather_state()` when per-item extraction produces an empty result for a device.

A device that is statically targeted but dynamically determined to lack command support is recorded with a NOT_APPLICABLE result and the reason for non-support. This happens whether or not learned parameters exist for the device; see [Lost Applicability](#lost-applicability) for the planned distinction.

### CommandSupportResult

The return type of the `check_command_support()` method on `LearningTestCase` and its subclasses. Contains:

- **applicable**: List of devices that support the required command(s).
- **not_applicable**: Dictionary mapping device names to reasons why the device does not support the required command(s).

`LearningTestCase.test()` calls `check_command_support()` after `setup()` has run, records NOT_APPLICABLE for each device that is not applicable, and narrows `context.targets` to the applicable devices before calling `gather_state()`. The runner itself only calls `setup()`, `test()`, and `cleanup()`.

### Context

The object passed to jobs during execution. Contains access to the connection broker, target devices, results collector, parameters (file-based or data model), and execution metadata. The context is the primary interface between a job and the framework.

### Result

The outcome of a test case execution. Every test case that runs, or is prevented from running, records exactly one of these statuses:

| Status           | Meaning                                                                                                                                                                   |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `PASSED`         | All assertions succeeded.                                                                                                                                                 |
| `FAILED`         | One or more assertions did not match expected state.                                                                                                                      |
| `INFO`           | An informational check with no effect on pass/fail. Used for individual checks; it never becomes a test case's overall status.                                            |
| `ERRORED`        | An exception or planning error prevented the test case from completing.                                                                                                   |
| `NOT_APPLICABLE` | The test case was in scope but determined at runtime to be not applicable to its targets.                                                                                 |
| `SKIPPED`        | The test case did not execute, for example because no devices matched its target, or because the run is in learning mode and the job does not inherit `LearningTestCase`. |
| `BLOCKED`        | The test case could not run because an earlier phase in its scenario did not pass.                                                                                        |

A test case's status is derived from its individual checks in this order:

1. `ERRORED` if any check errored.
2. Otherwise `FAILED` if any check failed.
3. Otherwise `NOT_APPLICABLE` if every non-`INFO` check is not applicable.
4. Otherwise `SKIPPED` if every non-`INFO` check is skipped.
5. Otherwise `PASSED`.

Test cases filtered out before execution (e.g., by tags) do not appear in results at all. This is distinct from NOT_APPLICABLE, which appears in results with a reason.

### Lost Applicability

`LOST_APPLICABILITY` is a planned status and is not recorded yet ([#254](https://github.com/ChartinoLabs/Huginn/issues/254)). It will cover a test case that was applicable when parameters were learned but is no longer applicable during testing. This indicates that something changed between learning and testing that caused a previously testable device to become untestable, so the status will fail the test.

Until it ships, both situations below are recorded as `NOT_APPLICABLE`:

| Scenario                         | Learned Parameters Exist? | Result today     | Result once #254 ships |
| -------------------------------- | ------------------------- | ---------------- | ---------------------- |
| Device never applicable          | No                        | `NOT_APPLICABLE` | `NOT_APPLICABLE`       |
| Device was applicable, now isn't | Yes                       | `NOT_APPLICABLE` | `LOST_APPLICABILITY`   |

### Aggregate Result

The computed outcome for a test case group, phase, scenario, or whole run, derived from the statuses it contains. The rollup uses this order:

1. `ERRORED` if anything contained errored.
2. Otherwise `FAILED` if anything contained failed.
3. Otherwise `NOT_APPLICABLE` if everything contained is not applicable.
4. Otherwise `SKIPPED` if everything contained is skipped.
5. Otherwise `PASSED`.

A single failure therefore makes the aggregate `FAILED`, however many other test cases passed. `BLOCKED` is not part of the rollup: a blocked phase and its groups are recorded as `BLOCKED` directly. Because blocked entries never satisfy the all-`NOT_APPLICABLE` or all-`SKIPPED` checks, a scenario or run that contains blocked phases is `ERRORED` or `FAILED` if something in it errored or failed, and `PASSED` otherwise.

There is no partial status. Instead, the phase summary and the run summary report a count for each status alongside the aggregate result, for example `status=failed total=2000 passed=1995 failed=5 errored=0 not_applicable=0 skipped=0 blocked=0`, so the scope of any failure stays visible.

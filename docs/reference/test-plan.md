# Test Plan Specification

This document defines the YAML schema for Huginn test plan files. A test plan organizes tests into a four-tier hierarchy: scenarios contain phases, phases reference test case groups, and test case groups reference test cases.

## Overview

The test plan is the orchestration layer. It defines:

- **Test Cases**: First-class entities defining what to test, referencing jobs and parameters
- **Test Case Groups**: Logical groupings of test case references
- **Scenarios**: End-to-end validation workflows, each containing its own phases
- **Phases**: Stages of execution within a scenario, with dependencies
- **Targets**: Which devices, operating systems, or device groups each test applies to
- **Tags**: Labels for filtering test execution

## File Organization

Test plans can be defined as a single YAML file or distributed across multiple files in a directory. The multi-file approach is recommended for large test plans with hundreds or thousands of test cases.

### Single-File Mode

The simplest approach: one `test_plan.yaml` file containing all definitions.

```txt
project/
├── pyproject.toml
├── testbed.yaml
├── test_plan.yaml          # Everything in one file
└── tests/
```

This mode is ideal for small to medium test plans and maintains backward compatibility.

### Directory Mode

For large test plans, definitions can be split across multiple YAML files within a directory. The framework recursively scans the directory and merges all YAML files into a unified test plan.

```txt
project/
├── pyproject.toml
├── testbed.yaml
├── test_plan/                    # Directory instead of single file
│   ├── project.yaml              # Top-level metadata (name, description)
│   ├── scenarios.yaml            # Scenario definitions (contain phases)
│   ├── connectivity/
│   │   └── connectivity.yaml     # Connectivity test cases and groups
│   ├── routing/
│   │   ├── ospf.yaml             # OSPF test cases and groups
│   │   └── bgp.yaml              # BGP test cases and groups
│   └── interfaces/
│       └── interfaces.yaml       # Interface test cases and groups
└── tests/
```

**Enabling Directory Mode:**

Specify a directory path instead of a file path:

```toml
# pyproject.toml
[tool.huginn]
test_plan = "test_plan/"    # Trailing slash optional
```

Or via CLI:

```bash
huginn run --mode testing --plan test_plan/
```

### Top-Level Metadata

Top-level metadata (`name`, `description`, `data_model`) can be defined in any file within the test plan directory. There is no required file name or location.

```yaml
# test_plan/project.yaml (or any name you prefer)
---
name: Production Network Validation
description: >
  Comprehensive validation suite for production network infrastructure.
  Tests are organized by feature domain.

data_model:
  path: ./nac/data/
```

Each top-level metadata key must be defined in exactly one file. If the same key appears in multiple files, the framework reports an error identifying both files.

If no file defines a particular metadata key, that key is unset (empty).

The `defaults` key has been removed. A test plan that sets it fails to load, in both single-file and directory mode. Set `tags` or `target` on scenarios, phases or test case groups instead.

### Merge Semantics

When multiple files define the same section, the framework merges them according to these rules:

| Section            | Merge Strategy                             |
| ------------------ | ------------------------------------------ |
| `name`             | Single definition only; error on duplicate |
| `description`      | Single definition only; error on duplicate |
| `data_model`       | Single definition only; error on duplicate |
| `test_cases`       | Map merge; error on duplicate keys         |
| `test_case_groups` | Map merge; error on duplicate keys         |
| `scenarios`        | Map merge; error on duplicate keys         |

**Example: Merging test_cases from multiple files**

```yaml
# test_plan/routing/ospf.yaml
test_cases:
  "3.0.0":
    title: Verify OSPF Neighbors
    job: jobs/routing/verify_ospf_neighbors.py

  "3.1.0":
    title: Verify OSPF Interfaces
    job: jobs/routing/verify_ospf_interfaces.py
```

```yaml
# test_plan/routing/bgp.yaml
test_cases:
  "4.0.0":
    title: Verify BGP Neighbors
    job: jobs/routing/verify_bgp_neighbors.py
```

**Merged result:**

```yaml
test_cases:
  "3.0.0":
    title: Verify OSPF Neighbors
    # ...
  "3.1.0":
    title: Verify OSPF Interfaces
    # ...
  "4.0.0":
    title: Verify BGP Neighbors
    # ...
```

### Collision Detection

The framework validates that keys are unique across all files:

- Test case IDs must be globally unique
- Test case group names must be globally unique
- Scenario names must be globally unique

If a collision is detected, the framework reports an error identifying both files:

```txt
Duplicate test_cases key '3.0.0' defined in test_plan/routing/ospf.yaml and test_plan/routing/bgp.yaml
```

### File Load Order

Files are loaded in **alphabetical order** by path for determinism. Because all keys must be unique and merging is additive, load order does not affect the final result.

### Excluded Files and Directories

The framework loads every `.yaml` and `.yml` file in the directory tree, skipping any file or directory whose name starts with `_` or `.`. This allows storing drafts, scratch files, or work-in-progress content alongside the active test plan without affecting loading.

```txt
test_plan/
├── project.yaml                  # Loaded
├── scenarios.yaml                # Loaded
├── routing/
│   ├── ospf.yaml                 # Loaded
│   ├── bgp.yml                   # Loaded (.yml extension)
│   └── _isis.yaml                # Excluded (underscore-prefixed file)
├── _drafts/
│   └── wip.yaml                  # Excluded (underscore-prefixed directory)
└── .scratch/
    └── notes.yaml                # Excluded (dot-prefixed directory)
```

## Schema

### Top-Level Structure

```yaml
# test_plan.yaml
---
name: <plan-name>                    # Optional: human-readable name
description: <description>           # Optional: plan description

data_model:                          # Optional: external data model
  path: <path/to/data/directory>

test_cases:                          # Required: test case definitions
  <test-id>:
    title: <title>
    job: <path/to/job.py>
    # Additional test case fields...

test_case_groups:                    # Required: groups referencing test cases
  <group-name>:
    tests: [<test-id>, ...]
    # Additional group fields...

scenarios:                           # Required: end-to-end workflows
  <scenario-id>:
    phases:                          # Required: execution phases
      <phase-name>:
        test_case_groups: [<group>, ...]
        # Additional phase fields...
```

### Test Cases

Test cases are first-class entities defined once and referenced by ID throughout the test plan. Each test case is a key under `test_cases`, with the key serving as the unique identifier.

```yaml
test_cases:
  # Connectivity tests
  "1.0.0":
    title: Verify SSH Connectivity
    job: tests/verify_connectivity.py
    tags: [connectivity, critical]

  "1.1.0":
    title: Verify NTP Synchronization
    job: tests/verify_ntp.py
    tags: [connectivity, ntp]

  # OSPF tests - separate test cases for pre/post change state
  "2.0.0-pre":
    title: Verify OSPF Neighbors (Pre-change)
    job: tests/verify_ospf_neighbors.py
    tags: [ospf, routing, pre-change]
    target:
      groups: [fabric-core]

  "2.0.0-post":
    title: Verify OSPF Neighbors (Post-change)
    job: tests/verify_ospf_neighbors.py    # Same job, different ID = different parameters
    tags: [ospf, routing, post-change]
    target:
      groups: [fabric-core]

  # Change implementation
  change-001:
    title: Apply OSPF Configuration Change
    job: tests/apply_ospf_change.py
    tags: [change]
```

#### Test Case Fields

| Field          | Type         | Required | Description                                           |
| -------------- | ------------ | -------- | ----------------------------------------------------- |
| `title`        | string       | Yes      | Human-readable test name                              |
| `job`          | string       | Yes      | Job reference - see [Job References](#job-references) |
| `description`  | string       | No       | Detailed test description                             |
| `tags`         | list[string] | No       | Labels for filtering                                  |
| `target`       | dict         | No       | Targeting specification                               |
| `priority`     | string       | No       | Priority label (for example, `high`)                  |
| `category`     | string       | No       | Category label (for example, `routing`)               |
| `is_automated` | bool         | No       | Whether the test case is automated (default: `true`)  |
| `metadata`     | dict         | No       | Free-form key/value metadata                          |

#### Job References

The `job` field accepts two forms:

- **File path** (relative to project root): `jobs/verify_ospf.py`
- **Module path** (dot-delimited, resolved via Python's import system): `huginn_jobs_network.ospf.verify_neighbors`

File paths contain `/` or end with `.py`. Module paths have neither and
point to an installed Python package. Both forms accept an optional
`:ClassName` suffix to select a specific `TestCase` subclass when the
module defines more than one:

```yaml
test_cases:
  "1.0.0":
    title: Verify OSPF Neighbors (local job)
    job: jobs/verify_ospf.py

  "1.1.0":
    title: Verify BGP Peering (packaged job)
    job: huginn_jobs_network.bgp.verify_peering

  "1.2.0":
    title: Verify Interface Status (explicit class)
    job: huginn_jobs_network.interfaces.verify_status:VerifyInterfaceStatus
```

See [Package-Based Job References](package-jobs.md) for the
full discussion of packaged jobs.

#### Parameters Convention

Parameters are loaded by convention from `parameters/{test_case_id}.json`. For example:

- Test case `1.0.0` → `parameters/1.0.0.json`
- Test case `2.0.0-pre` → `parameters/2.0.0-pre.json`

If the parameters file does not exist, the test case requires execution in learning mode.

#### Same Job, Different Test Cases

A single job can be referenced by multiple test cases. This is useful when the same validation logic applies to different expected states:

```yaml
test_cases:
  # Same job, different parameters for pre/post change
  ospf-pre:
    title: Verify OSPF Neighbors (Pre-change)
    job: tests/verify_ospf_neighbors.py

  ospf-post:
    title: Verify OSPF Neighbors (Post-change)
    job: tests/verify_ospf_neighbors.py
```

Parameters files:

- `parameters/ospf-pre.json` - Expected neighbors before change
- `parameters/ospf-post.json` - Expected neighbors after change

### Data Model

The `data_model` section points at an external source of truth for expected state, such as a Network as Code data directory. Huginn loads it once per run and passes it to every job as `context.data_model`. Each job decides how to use it. When no data model is configured, `context.data_model` is `None`.

```yaml
data_model:
  path: ./nac/data/
```

| Field  | Type   | Required | Description                                        |
| ------ | ------ | -------- | -------------------------------------------------- |
| `path` | string | Yes      | Path to directory containing data model YAML files |

When `data_model` is present, `path` must be a non-empty string, or the test plan fails to load.

#### Path Resolution

A relative `data_model.path` is resolved against the directory that contains the test plan file. In directory mode, it is resolved against the test plan directory itself. The working directory does not affect it.

A path that does not exist or is not a directory fails with a configuration error, as does a directory with no YAML files.

In directory mode, keep the data model directory outside the test plan directory, or give it a name that starts with `_`, such as `test_plan/_data/`. The test plan loader reads every YAML file in the plan directory, so data model files inside it without the `_` prefix are also merged into the test plan. A data model key that matches a test plan key, such as `name` or `test_cases`, then fails with a duplicate definition error or adds to the test plan.

#### Merge Rules

Huginn recursively discovers YAML files in the data model directory using the same rules as a [test plan directory](#directory-mode):

- Files ending in `.yaml` or `.yml` are loaded, in alphabetical order by path.
- Files and directories whose names start with `_` or `.` are skipped.

Each file must contain a mapping at its root. Files are then deep-merged into one mapping:

- Mappings under the same key are merged recursively.
- Any other value (a string, number, boolean, null or list) can be defined by only one file. If two files set the same key, loading fails with an error that names both files and the dotted key path, even when the values are equal. Lists are not concatenated.

For example, these two files:

```yaml
# nac/data/fabric.yaml
fabric:
  name: dc1
  bgp:
    asn: 65000
```

```yaml
# nac/data/sites/leafs.yaml
fabric:
  leafs: [leaf-01, leaf-02]
```

merge into:

```yaml
fabric:
  name: dc1
  bgp:
    asn: 65000
  leafs: [leaf-01, leaf-02]
```

Adding `fabric.name: dc2` to `leafs.yaml` fails with `Conflicting data model value at 'fabric.name' defined in nac/data/fabric.yaml and nac/data/sites/leafs.yaml`.

Invalid YAML fails with a configuration error that names the file.

#### CLI Override

`--data-model` (or the `HUGINN_DATA_MODEL` environment variable) replaces `data_model.path` for `huginn run`, `huginn validate` and `huginn relearn`. It also works when the test plan has no `data_model` section. A relative path given on the command line is resolved against the working directory.

```bash
huginn run --mode testing --data-model ./alternative/data/
```

`huginn validate` loads the data model and reports a load failure as a `configuration_error`, so a broken data model is caught before a run.

#### Read-Only Access

Every job in a run shares the same data model object, so it is read-only. Every nested mapping and list rejects changes with a `TypeError`. Reads, iteration, `isinstance(..., dict)` and `isinstance(..., list)` checks, `json.dumps` and `yaml.safe_dump` all behave as they do for plain dictionaries and lists.

To modify the data model inside a job, make a private copy with `copy.deepcopy()`. The copy is built from plain, mutable dictionaries and lists:

```python
import copy

interfaces = copy.deepcopy(context.data_model["interfaces"])
interfaces.append({"name": "Loopback0"})
```

#### Usage in Jobs

Jobs can derive expected state from the data model and fall back to file-based parameters when none is configured:

```python
async def test(self, context: Context) -> None:
    if context.data_model is None:
        # Fall back to file-based parameters
        expected = await context.parameters.load()
    else:
        # Derive expected state from data model
        ospf_config = context.data_model.get("ospf")
        if ospf_config is None:
            context.results.add_result(
                ResultStatus.NOT_APPLICABLE, "OSPF not configured in data model"
            )
            return
        expected = ospf_config.get("neighbors", [])

    # Validate current state against expected...
```

See [Context API](context-api.md) for detailed patterns.

### Test Case Groups

Test case groups organize test cases for execution within a phase. Groups reference test cases by ID and can include other groups by name, enabling hierarchical organization.

```yaml
test_case_groups:
  connectivity-checks:
    description: Verify basic device connectivity
    tests: ["1.0.0", "1.1.0"]

  pre-change-state:
    description: Validate state expected to change
    tests: ["2.0.0-pre"]

  post-change-state:
    description: Validate post-change expected state
    tests: ["2.0.0-post"]

  change-implementation:
    description: Apply the configuration change
    tests: ["change-001"]
```

#### Test Case Group Fields

| Field           | Type         | Required | Description                                                     |
| --------------- | ------------ | -------- | --------------------------------------------------------------- |
| `name`          | string       | No       | Display name (defaults to the group key)                        |
| `description`   | string       | No       | Informational only; not read by the loader                      |
| `tests`         | list[string] | No       | List of test case IDs                                           |
| `groups`        | list[string] | No       | List of test case group names to include                        |
| `exclude_tests` | list[string] | No       | Test case IDs to drop from the groups included through `groups` |
| `tags`          | list[string] | No       | Group-level tags (additive with test case tags)                 |
| `target`        | dict         | No       | Group-level targeting (intersected with test case targets)      |
| `strategy`      | dict         | No       | Group test execution strategy (`serial` or `parallel`)          |

At least one of `tests` or `groups` must be specified. `exclude_tests` only applies to test cases inherited through `groups`, so defining it without `groups` fails at load.

#### Nested Test Case Groups

Test case groups can include other test case groups, enabling feature-based organization:

```yaml
test_case_groups:
  # Feature-specific groups
  ospf-tests:
    description: OSPF validation tests
    tests: ["3.0.0", "3.1.0", "3.2.0"]

  bgp-tests:
    description: BGP validation tests
    tests: ["4.0.0", "4.1.0"]

  interface-tests:
    description: Interface state validation
    tests: ["5.0.0", "5.1.0", "5.2.0"]

  # Composite groups that include feature groups
  pre-change-validation:
    description: All validation tests for pre-change phase
    groups: [ospf-tests, bgp-tests, interface-tests]
    tests: ["1.0.0"]  # Can also include direct test case references

  post-change-validation:
    description: All validation tests for post-change phase
    groups: [ospf-tests, bgp-tests, interface-tests]
    tests: ["1.0.0"]
```

This pattern enables:

- **Feature organization**: Group related test cases by protocol or feature
- **Reuse**: Include the same feature group in multiple composite groups
- **Maintainability**: Add a new OSPF test case once to `ospf-tests`, and it automatically runs in all phases that include that group

**Nested Group Flattening**: When a group includes other groups, the framework flattens the hierarchy for execution. Test cases from included groups inherit the parent group's target specification (intersection logic applies).

**Circular Reference Detection**: The framework validates that group inclusions do not form cycles (e.g., group A includes B, B includes A).

#### Group-Level Targeting

Groups can specify targets that apply to all contained test cases:

```yaml
test_case_groups:
  spine-validation:
    description: Tests specific to spine switches
    target:
      groups: [spine]
    tests: ["4.0.0", "4.0.1", "4.0.2"]
```

When both a group and test case specify targets, they are intersected.

#### Group Execution Strategy

Groups can control test-case execution mode:

```yaml
test_case_groups:
  serial-group:
    strategy:
      serial: {}
    tests: ["1.0.0", "1.1.0"]

  bounded-parallel-group:
    strategy:
      parallel:
        maximum: 5
    tests: ["2.0.0", "2.1.0", "2.2.0"]
```

- `strategy.serial` runs test cases one-at-a-time.
- `strategy.parallel` runs test cases concurrently.
- `strategy.parallel.maximum` optionally bounds concurrency.
- If `strategy` is omitted, group execution defaults to unbounded parallel.

### Scenarios

Scenarios are the top-level organizational unit. Each scenario is an end-to-end validation workflow, such as one configuration change with its pre-change and post-change checks, and contains its own set of phases. A test plan must define at least one scenario.

```yaml
scenarios:
  ospf-area-change:
    name: OSPF Area Change
    phases:
      pre-change:
        test_case_groups: [connectivity-checks, pre-change-state]

      change:
        depends_on: [pre-change]
        test_case_groups: [change-implementation]

      post-change:
        depends_on: [change]
        test_case_groups: [connectivity-checks, post-change-state]
```

#### Scenario Fields

| Field    | Type   | Required | Description                                 |
| -------- | ------ | -------- | ------------------------------------------- |
| `phases` | dict   | Yes      | Non-empty mapping of phase names to phases  |
| `name`   | string | No       | Display name (defaults to the scenario key) |

Phase names are scoped to their scenario. Two scenarios can each define a `pre-change` phase, and `depends_on` can only reference phases in the same scenario. Referencing an undefined phase fails at load.

### Phases

Phases represent stages of test execution within a scenario. Phases declare dependencies on other phases to establish execution order.

```yaml
scenarios:
  ospf-area-change:
    phases:
      pre-change:
        description: Validate state before making changes
        test_case_groups: [connectivity-checks, pre-change-state]

      change:
        description: Apply the configuration change
        depends_on: [pre-change]
        test_case_groups: [change-implementation]

      post-change:
        description: Validate state after changes
        depends_on: [change]
        test_case_groups: [connectivity-checks, post-change-state]
```

#### Phase Fields

| Field              | Type         | Required | Description                                                          |
| ------------------ | ------------ | -------- | -------------------------------------------------------------------- |
| `name`             | string       | No       | Display name (defaults to the phase key)                             |
| `description`      | string       | No       | Phase description                                                    |
| `depends_on`       | list[string] | No       | Phases in the same scenario that must complete before this phase     |
| `test_case_groups` | list[string] | Yes      | Groups to execute in this phase                                      |
| `target`           | dict         | No       | Phase-level targeting (intersected with group/test case targets)     |
| `strategy`         | dict         | No       | Group execution strategy within the phase (`serial`/`parallel`)      |
| `preserve_cache`   | bool         | No       | Keep the broker command cache from earlier phases (default: `false`) |

By default, the broker command cache is cleared at the start of each phase, so every phase observes fresh device state. Set `preserve_cache: true` on a phase that can safely reuse command output collected by earlier phases.

#### Phase Dependencies

The `depends_on` field creates a directed acyclic graph (DAG) of phase execution:

```yaml
scenarios:
  fabric-upgrade:
    phases:
      A:
        test_case_groups: [...]

      B:
        depends_on: [A]      # B waits for A
        test_case_groups: [...]

      C:
        depends_on: [A]      # C waits for A (can run parallel with B)
        test_case_groups: [...]

      D:
        depends_on: [B, C]   # D waits for both B and C
        test_case_groups: [...]
```

Execution order: `A` → `B, C` (parallel) → `D`

If a phase fails (any test case fails):

- Dependent phases are marked as **BLOCKED**
- Independent phases continue execution
- Results show **Partial** status with pass/fail counts

#### Reusing Test Case Groups Across Phases

The same test case group can appear in multiple phases. This is the key pattern for change validation:

```yaml
scenarios:
  ospf-area-change:
    phases:
      pre-change:
        test_case_groups: [unchanged-state-checks]    # Run these tests

      change:
        depends_on: [pre-change]
        test_case_groups: [apply-change]

      post-change:
        depends_on: [change]
        test_case_groups: [unchanged-state-checks]    # Same tests again!
```

#### Phase Group Execution Strategy

Phases can control how referenced test case groups execute:

```yaml
scenarios:
  ospf-area-change:
    phases:
      pre-change:
        strategy:
          serial: {}
        test_case_groups: [connectivity-checks, pre-change-state]

      post-change:
        strategy:
          parallel:
            maximum: 2
        test_case_groups: [connectivity-checks, bgp-checks, post-change-state]
```

- `strategy.serial` executes groups in listed order.
- `strategy.parallel` executes groups concurrently.
- `strategy.parallel.maximum` optionally bounds concurrent groups.
- If `strategy` is omitted, phase group execution defaults to unbounded parallel.

### Targeting

The `target` field specifies which devices a test applies to. Targets can be specified at three levels:

- Phase level
- Test case group level
- Test case level

Within one selector, values are combined with OR: `groups: [spine, border]` matches a device in either group. Different selectors in the same `target` block, and `target` blocks at different levels, are combined with AND. Each selector must be a non-empty list of strings.

#### By Device Name

```yaml
target:
  devices: [spine-01, spine-02, leaf-01]
```

#### By Operating System

```yaml
target:
  os: [nxos, iosxe]
```

#### By Device Group

```yaml
target:
  groups: [spine, datacenter-1]
```

#### Combined Targeting

```yaml
target:
  os: [nxos]
  groups: [leaf]
# Targets: NX-OS devices that are also in the "leaf" device group
```

#### Excluding Devices

`exclude_devices` removes specific devices from whatever the other selectors matched. It is applied after `devices`, `groups` and `os`, and can be combined with any of them:

```yaml
target:
  groups: [leaf]
  exclude_devices: [leaf-04]
# Targets: every device in the "leaf" device group except leaf-04
```

#### Explicit vs Dynamic Targeting

Target selector modes are mutually exclusive:

- **Explicit targeting**: use `target.devices`
- **Dynamic targeting**: use `target.groups` and/or `target.os`

Mixing `devices` with `groups` or `os` in the same `target` block fails at load with `cannot define target.devices together with target.groups and/or target.os`. `exclude_devices` is allowed in either mode.

Invalid example:

```yaml
target:
  devices: [leaf-01]
  groups: [leaf]
```

#### Empty Target

If no target is specified at any level, the test receives **all devices** in the testbed.

### Tags

Tags enable filtering test execution from the CLI:

```yaml
test_cases:
  "1.0.0":
    title: Verify OSPF Neighbors
    job: tests/verify_ospf.py
    tags: [ospf, routing, critical, fast]

  "2.0.0":
    title: Verify Full BGP Table
    job: tests/verify_bgp_table.py
    tags: [bgp, routing, slow]
```

CLI filtering:

```bash
# Run only tests tagged "ospf"
huginn run --mode testing --tags ospf

# Run tests tagged "routing" but not "slow"
huginn run --mode testing --tags routing --exclude-tags slow

# Run tests tagged both "critical" and "fast"
huginn run --mode testing --tags critical,fast
```

**Important**: Filtered tests do not appear in results. If you filter to run only OSPF tests, only those tests appear in the report.

Test case groups can also define `tags`. Effective filtering tags are the union of test-case tags and group tags for each execution context.

## Complete Example

```yaml
# test_plan.yaml
---
name: OSPF Change Validation
description: >
  Validates network state before and after an OSPF configuration change.
  Tests are organized into pre-change, change, and post-change phases.

data_model:
  path: ./nac/data/  # Optional: Network as Code data model

test_cases:
  # Connectivity tests - state should not change
  "1.0.0":
    title: Verify Management Connectivity
    job: tests/connectivity/verify_ssh.py
    tags: [connectivity, critical]

  "1.1.0":
    title: Verify NTP Synchronization
    job: tests/connectivity/verify_ntp.py
    tags: [connectivity, ntp]

  "1.2.0":
    title: Verify Syslog Configuration
    job: tests/connectivity/verify_syslog.py
    tags: [connectivity, logging]

  # BGP tests - state should not change
  "2.0.0":
    title: Verify BGP Neighbor State
    job: tests/routing/verify_bgp_neighbors.py
    tags: [bgp, routing]
    target:
      groups: [fabric-core]

  # OSPF tests - state WILL change, need separate pre/post test cases
  "3.0.0-pre":
    title: Verify OSPF Neighbors (Pre-change)
    job: tests/routing/verify_ospf_neighbors.py
    tags: [ospf, routing, pre-change]
    target:
      groups: [fabric-core]

  "3.0.0-post":
    title: Verify OSPF Neighbors (Post-change)
    job: tests/routing/verify_ospf_neighbors.py
    tags: [ospf, routing, post-change]
    target:
      groups: [fabric-core]

  "3.1.0-pre":
    title: Verify OSPF Interface Config (Pre-change)
    job: tests/routing/verify_ospf_interfaces.py
    tags: [ospf, routing, pre-change]
    target:
      groups: [fabric-core]

  "3.1.0-post":
    title: Verify OSPF Interface Config (Post-change)
    job: tests/routing/verify_ospf_interfaces.py
    tags: [ospf, routing, post-change]
    target:
      groups: [fabric-core]

  # Change implementation
  change-001:
    title: Apply OSPF Area Configuration
    job: tests/changes/apply_ospf_area_change.py
    tags: [change, ospf]
    target:
      groups: [fabric-core]

test_case_groups:
  # Feature-specific groups (reusable building blocks)
  connectivity-tests:
    description: Basic connectivity validation
    tests: ["1.0.0", "1.1.0", "1.2.0"]

  bgp-tests:
    description: BGP neighbor state validation
    tests: ["2.0.0"]

  # OSPF tests - separate groups for pre/post since state changes
  ospf-tests-pre:
    description: OSPF state validation (pre-change parameters)
    tests: ["3.0.0-pre", "3.1.0-pre"]

  ospf-tests-post:
    description: OSPF state validation (post-change parameters)
    tests: ["3.0.0-post", "3.1.0-post"]

  # Composite groups using nested groups
  pre-change-validation:
    description: All validation tests for pre-change phase
    groups: [connectivity-tests, bgp-tests, ospf-tests-pre]

  post-change-validation:
    description: All validation tests for post-change phase
    groups: [connectivity-tests, bgp-tests, ospf-tests-post]

  # Change implementation
  apply-change:
    description: Applies the OSPF configuration change
    tests: ["change-001"]

scenarios:
  ospf-area-change:
    name: OSPF Area Change
    phases:
      pre-change:
        description: Validate network state before making changes
        test_case_groups: [pre-change-validation]

      change:
        description: Apply the OSPF configuration change
        depends_on: [pre-change]
        test_case_groups: [apply-change]

      post-change:
        description: Validate network state after changes
        depends_on: [change]
        test_case_groups: [post-change-validation]
```

## Execution Order

Given the above test plan, execution proceeds:

```txt
ospf-area-change
    1. pre-change
       └── pre-change-validation
           ├── connectivity-tests
           │   ├── 1.0.0 Verify Management Connectivity
           │   ├── 1.1.0 Verify NTP Synchronization
           │   └── 1.2.0 Verify Syslog Configuration
           ├── bgp-tests
           │   └── 2.0.0 Verify BGP Neighbor State
           └── ospf-tests-pre
               ├── 3.0.0-pre Verify OSPF Neighbors (Pre-change)
               └── 3.1.0-pre Verify OSPF Interface Config (Pre-change)
       │
       ▼
    2. change
       └── apply-change
           └── change-001 Apply OSPF Area Configuration
       │
       ▼
    3. post-change
       └── post-change-validation
           ├── connectivity-tests (same tests as pre-change!)
           │   ├── 1.0.0 Verify Management Connectivity
           │   ├── 1.1.0 Verify NTP Synchronization
           │   └── 1.2.0 Verify Syslog Configuration
           ├── bgp-tests (same tests as pre-change!)
           │   └── 2.0.0 Verify BGP Neighbor State
           └── ospf-tests-post
               ├── 3.0.0-post Verify OSPF Neighbors (Post-change)
               └── 3.1.0-post Verify OSPF Interface Config (Post-change)
```

Note that `connectivity-tests` and `bgp-tests` are included in both `pre-change-validation` and `post-change-validation`, validating that connectivity and BGP state remain consistent across the change.

## Report Structure

Results are organized hierarchically for easy navigation. Nested groups are shown in their hierarchy:

```txt
OSPF Area Change                                     [PARTIAL] 12/13 (1 failed)
    Pre-change                                       [PASSED]  6/6
    └── pre-change-validation                        [PASSED]  6/6
        ├── connectivity-tests                       [PASSED]  3/3
        │   ├── 1.0.0 Verify Management              [PASSED]
        │   ├── 1.1.0 Verify NTP Sync                [PASSED]
        │   └── 1.2.0 Verify Syslog                  [PASSED]
        ├── bgp-tests                                [PASSED]  1/1
        │   └── 2.0.0 Verify BGP Neighbors           [PASSED]
        └── ospf-tests-pre                           [PASSED]  2/2
            ├── 3.0.0-pre Verify OSPF Neighbors      [PASSED]
            └── 3.1.0-pre Verify OSPF Interfaces     [PASSED]

    Change                                           [PASSED]  1/1
    └── apply-change                                 [PASSED]  1/1
        └── change-001 Apply OSPF Config             [PASSED]

    Post-change                                      [PARTIAL] 5/6 (1 failed)
    └── post-change-validation                       [PARTIAL] 5/6 (1 failed)
        ├── connectivity-tests                       [PASSED]  3/3
        │   ├── 1.0.0 Verify Management              [PASSED]
        │   ├── 1.1.0 Verify NTP Sync                [PASSED]
        │   └── 1.2.0 Verify Syslog                  [PASSED]
        ├── bgp-tests                                [PASSED]  1/1
        │   └── 2.0.0 Verify BGP Neighbors           [PASSED]
        └── ospf-tests-post                          [PARTIAL] 1/2 (1 failed)
            ├── 3.0.0-post Verify OSPF Neighbors     [PASSED]
            └── 3.1.0-post Verify OSPF Interfaces    [FAILED] ← Unexpected state
```

## CLI Filtering

The test plan can be filtered at runtime:

```bash
# Run specific scenario
huginn run --mode testing --scenario ospf-area-change

# Run specific phase (requires --scenario)
huginn run --mode testing --scenario ospf-area-change --phase pre-change

# Run specific test case group
huginn run --mode testing --test-case-group post-change-validation

# Run specific tests by ID
huginn run --mode testing --test-id 3.0.0-pre,3.1.0-pre

# Run tests whose IDs match a regular expression
huginn run --mode testing --test-id-pattern '-post$'

# Run tests matching tags
huginn run --mode testing --tags ospf

# Exclude tests by tag
huginn run --mode testing --exclude-tags slow

# Combine filters
huginn run --mode testing --scenario ospf-area-change --phase post-change --tags ospf
```

Every filter except `--test-id-pattern` accepts comma-separated values and can be repeated. `--scenario`, `--phase`, `--test-case-group` and `--test-id` match any listed value. `--tags` requires every listed tag, and `--exclude-tags` drops a test case that has any listed tag. `--phase` is rejected unless `--scenario` is also given, because phase names are scoped to a scenario.

## Validation

The framework validates test plans on load:

- All test case IDs are unique
- All referenced jobs exist
- All test case IDs referenced in groups exist
- All group names referenced in phases exist
- All group names referenced in other groups exist (for nested groups)
- Nested group references form a valid DAG (no cycles)
- Phase dependencies form a valid DAG (no cycles)
- Target specifications reference valid device groups/OS values
- Required fields are present

## Related Documents

- [Glossary](../concepts/glossary.md): Formal term definitions
- [Testbed Specification](testbed.md): Device and device group definitions
- [Context API](context-api.md): Writing jobs
- [Configuration](configuration.md): Default paths and settings

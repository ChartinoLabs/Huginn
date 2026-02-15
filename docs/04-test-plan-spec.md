# Test Plan Specification

This document defines the YAML schema for Huginn test plan files. A test plan organizes tests into a three-tier hierarchy: phases contain test case groups, which reference test cases.

## Overview

The test plan is the orchestration layer. It defines:

- **Test Cases**: First-class entities defining what to test, referencing jobs and parameters
- **Test Case Groups**: Logical groupings of test case references
- **Phases**: High-level stages of execution with dependencies
- **Targets**: Which devices, operating systems, or device groups each test applies to
- **Tags**: Labels for filtering test execution

## Schema

### Top-Level Structure

```yaml
# test_plan.yaml
---
name: <plan-name>                    # Optional: human-readable name
description: <description>           # Optional: plan description

data_model:                          # Optional: external data model
  path: <path/to/data/directory>

defaults:                            # Optional: default values
  target: {}
  tags: []

test_cases:                          # Required: test case definitions
  <test-id>:
    title: <title>
    job: <path/to/job.py>
    # Additional test case fields...

test_case_groups:                    # Required: groups referencing test cases
  <group-name>:
    tests: [<test-id>, ...]
    # Additional group fields...

phases:                              # Required: execution phases
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

| Field         | Type         | Required | Description                                        |
| ------------- | ------------ | -------- | -------------------------------------------------- |
| `title`       | string       | Yes      | Human-readable test name                           |
| `job`         | string       | Yes      | Path to Python job file (relative to project root) |
| `description` | string       | No       | Detailed test description                          |
| `tags`        | list[string] | No       | Labels for filtering                               |
| `target`      | dict         | No       | Targeting specification                            |

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

The `data_model` section configures an external source of truth for expected state. This is an alternative to file-based parameters, useful for Infrastructure as Code approaches.

```yaml
data_model:
  path: ./nac/data/
```

| Field  | Type   | Required | Description                                        |
| ------ | ------ | -------- | -------------------------------------------------- |
| `path` | string | Yes      | Path to directory containing data model YAML files |

The data model directory is recursively scanned for YAML files, which are merged into a unified data structure accessible via `context.data_model` in jobs.

**CLI Override:**

```bash
# Override data model path at runtime
huginn run --data-model ./alternative/data/
```

CLI arguments take precedence over test plan settings.

**Usage in Jobs:**

Jobs can access the data model to derive expected state:

```python
async def test(self, context: Context) -> None:
    if context.data_model is None:
        # Fall back to file-based parameters
        expected = await context.parameters.load()
    else:
        # Derive expected state from data model
        ospf_config = context.data_model.get("ospf")
        if ospf_config is None:
            context.results.skip("OSPF not configured in data model")
            return
        expected = ospf_config.get("neighbors", [])

    # Validate current state against expected...
```

See [Test Authoring](05-test-authoring.md) for detailed patterns.

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

| Field         | Type         | Required | Description                                                |
| ------------- | ------------ | -------- | ---------------------------------------------------------- |
| `description` | string       | No       | Group description                                          |
| `tests`       | list[string] | No       | List of test case IDs                                      |
| `groups`      | list[string] | No       | List of test case group names to include                   |
| `target`      | dict         | No       | Group-level targeting (intersected with test case targets) |

At least one of `tests` or `groups` must be specified.

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

### Phases

Phases are the top-level organizational unit, representing stages of test execution. Phases declare dependencies on other phases to establish execution order.

```yaml
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

| Field              | Type         | Required | Description                                                      |
| ------------------ | ------------ | -------- | ---------------------------------------------------------------- |
| `description`      | string       | No       | Phase description                                                |
| `depends_on`       | list[string] | No       | Phases that must complete before this phase                      |
| `test_case_groups` | list[string] | Yes      | Groups to execute in this phase                                  |
| `target`           | dict         | No       | Phase-level targeting (intersected with group/test case targets) |

#### Phase Dependencies

The `depends_on` field creates a directed acyclic graph (DAG) of phase execution:

```yaml
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

### Targeting

The `target` field specifies which devices a test applies to. Targets can be specified at three levels:

- Phase level
- Test case group level
- Test case level

All applicable targets are intersected (AND logic).

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

#### Explicit vs Dynamic Targeting

For initial implementation, target selector modes are mutually exclusive:

- **Explicit targeting**: use `target.devices`
- **Dynamic targeting**: use `target.groups` and/or `target.os`

Mixing `devices` with `groups` or `os` in the same `target` block is invalid and should fail validation.

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
huginn run --tags ospf

# Run tests tagged "routing" but not "slow"
huginn run --tags routing --exclude-tags slow

# Run tests tagged both "critical" and "fast"
huginn run --tags critical,fast
```

**Important**: Filtered tests do not appear in results. If you filter to run only OSPF tests, only those tests appear in the report.

### Defaults

The `defaults` section provides fallback values:

```yaml
defaults:
  target:
    groups: [production]
  tags: [regression]

test_cases:
  "1.0.0":
    title: Verify Connectivity
    job: tests/verify_connectivity.py
    # Inherits target: groups: [production]
    # Inherits tags: [regression]
```

Explicit values override defaults.

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

defaults:
  tags: [change-validation]

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
# Run specific phase
huginn run --phase pre-change

# Run specific test case group
huginn run --test-case-group unchanged-state

# Run specific test by ID
huginn run --test-id 3.0.0-pre

# Run tests matching tags
huginn run --tags ospf

# Exclude tests by tag
huginn run --exclude-tags slow

# Combine filters
huginn run --phase post-change --tags ospf
```

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

- [Glossary](00-glossary.md): Formal term definitions
- [Testbed Specification](03-testbed-spec.md): Device and device group definitions
- [Test Authoring](05-test-authoring.md): Writing jobs
- [Configuration](06-configuration.md): Default paths and settings

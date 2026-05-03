# Pruning Non-Applicable Tests

## Overview

After running in learning mode, some tests return `NOT_APPLICABLE` for certain devices -- the device does not support the command, or the command works but produces no meaningful data. These results indicate that the test scope in the test plan is broader than the infrastructure actually requires.

The `huginn prune` command reads learning results and narrows the test plan automatically:

- **Partially applicable tests** (some devices are N/A): adds `target.exclude_devices` to the test case definition so those devices are skipped on future runs.
- **Fully non-applicable tests** (all devices are N/A): removes the test from its group. Leaf groups have the test ID removed from `tests`; composite groups that use `groups` inheritance get an `exclude_tests` entry instead.
- **Orphaned definitions** (optional): with `--remove-orphans`, test case definitions that are no longer referenced by any group are deleted entirely.

Prune is designed to be run once after an initial learning pass against a new testbed. It tightens test scope based on observed reality, eliminating noise from tests that can never pass on the current infrastructure.

## Why tests become non-applicable

There are two distinct sources of `NOT_APPLICABLE` during learning:

### Command support (`check_command_support`)

The device does not support the command at all. For example, a parsed field is missing from the command output because the platform or software version does not implement it. The job's `check_command_support` method detects this and marks the device as non-applicable before any state is gathered.

### Empty gathered state (`gather_state`)

The command executes successfully, but the extracted data is empty for a device. For example, a `show ip ospf neighbor` command returns no neighbors because OSPF is not configured on that device. The job's `gather_state` method detects the empty result and emits a `NOT_APPLICABLE` result. See [Static Parameter Validation - Handling empty gathered state](authoring/static-validation.md#handling-empty-gathered-state) for the recommended pattern.

Both sources produce the same `NOT_APPLICABLE` status in the learning results. The prune command does not distinguish between them -- if a device is non-applicable, it is excluded.

## Workflow

The typical workflow is: learn, preview, apply.

### 1. Run in learning mode

Execute the test plan against the live testbed to capture current state and identify which tests apply to which devices.

```bash
huginn run -m learning -t testbed.yaml -p test_plan/
```

### 2. Preview changes with dry run

Inspect what the prune command would change without modifying any files.

```bash
huginn prune -p test_plan/ --dry-run
```

Example output:

```
Pruning non-applicable tests from test plan
Using results from 2026-Apr-30-14-22-01-learning
Found 3 partially applicable and 2 fully non-applicable test(s)
Partially applicable tests (exclude_devices):
  1.3.0: exclude spine-03
  2.1.0: exclude leaf-04, leaf-05
  3.0.0: exclude spine-01
Fully non-applicable tests (remove from groups):
  4.0.0
  4.1.0
Dry run complete: 3 test(s) would get exclude_devices, 2 test(s) would be removed from groups
```

### 3. Apply the prune

Run without `--dry-run` to modify the test plan files.

```bash
huginn prune -p test_plan/
```

The command validates the modified test plan after writing changes. If validation fails, it reports the error and exits with a non-zero status.

### 4. Optionally remove orphaned definitions

If fully non-applicable tests were removed from all groups, their test case definitions still exist in the YAML but are unreferenced. Use `--remove-orphans` to clean them up.

```bash
huginn prune -p test_plan/ --remove-orphans
```

## CLI reference

```
huginn prune --plan <path> [--results-dir <path>] [--dry-run] [--remove-orphans]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--plan`, `-p` | (required) | Path to test plan YAML file or directory. Also accepts `HUGINN_PLAN` env var. |
| `--results-dir` | `./results/` | Path to results directory. Also accepts `HUGINN_RESULTS_DIR` env var. |
| `--dry-run` | off | Show what would be pruned without modifying files. |
| `--remove-orphans` | off | Delete test case definitions no longer referenced by any group. |
| `--debug` | off | Enable DEBUG-level logging. Also accepts `HUGINN_DEBUG` env var. |
| `--log-level` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR). Also accepts `HUGINN_LOG_LEVEL` env var. |
| `--show-logs` | off | Stream logs to console in addition to file. Also accepts `HUGINN_SHOW_LOGS` env var. |
| `--log-file` | `./huginn.log` | Path to log file. Also accepts `HUGINN_LOG_FILE` env var. |

## What the command modifies

### Partial applicability: `target.exclude_devices`

When some devices are non-applicable but others are not, the prune command adds an `exclude_devices` list to the test case's `target` block. If the test case has no `target` block, one is created.

Before pruning:

```yaml
test_cases:
  "1.3.0":
    title: Verify LLDP Neighbors
    job: tests/verify_lldp_neighbors.py
    target:
      groups: [fabric-core]
```

After pruning (spine-03 does not support the LLDP command):

```yaml
test_cases:
  "1.3.0":
    title: Verify LLDP Neighbors
    job: tests/verify_lldp_neighbors.py
    target:
      groups: [fabric-core]
      exclude_devices: [spine-03]
```

If the test case already has `exclude_devices`, the prune command merges the new exclusions with the existing list. Devices already excluded are not duplicated.

### Full non-applicability: group removal

When all devices are non-applicable for a test, the test ID is removed from its group. The removal strategy depends on the group type:

**Leaf groups** (groups that directly list test IDs in `tests`): the test ID is removed from the `tests` list.

Before:

```yaml
test_case_groups:
  ospf-tests:
    tests: ["3.0.0", "3.1.0", "3.2.0"]
```

After (3.2.0 is fully non-applicable):

```yaml
test_case_groups:
  ospf-tests:
    tests: ["3.0.0", "3.1.0"]
```

**Composite groups** (groups that use `groups` to inherit from other groups): the test ID is added to `exclude_tests` rather than modifying the inherited group.

Before:

```yaml
test_case_groups:
  pre-change-validation:
    groups: [ospf-tests, bgp-tests]
```

After (4.0.0 from bgp-tests is fully non-applicable):

```yaml
test_case_groups:
  pre-change-validation:
    groups: [ospf-tests, bgp-tests]
    exclude_tests: ["4.0.0"]
```

This preserves the inheritance structure. The `exclude_tests` mechanism is the same one used by the [reconcile command](08-parameter-reconciliation.md) to exclude baseline tests that diverge after a change.

### Orphan removal

When `--remove-orphans` is passed, the command checks whether any fully non-applicable test IDs are still referenced by at least one group after all group removals are applied. Test case definitions with no remaining group references are deleted from the YAML.

This is a destructive operation -- the test case definition and its key are removed from the `test_cases` map. The associated parameter files in `parameters/` are not touched; remove those manually if desired.

## Idempotency

Running `huginn prune` a second time against the same results is safe. The command detects tests that are already pruned (devices already in `exclude_devices`, tests already removed from groups) and skips them. A message reports how many tests were skipped.

## Directory mode

When the `--plan` argument points to a directory, the prune command locates the correct YAML file for each test case and group using the same discovery logic as the framework's test plan loader. Changes are written only to the files that contain affected definitions. Formatting is preserved using round-trip YAML parsing.

## See also

- [Test Plan Specification - Targeting](04-test-plan-spec.md#targeting) -- the `target` block and device filtering.
- [Test Plan Specification - Test Case Groups](04-test-plan-spec.md#test-case-groups) -- group structure, `tests`, `groups`, and `exclude_tests`.
- [Parameter Reconciliation](08-parameter-reconciliation.md) -- a related command that creates new test case variants after a network change.
- [Static Parameter Validation - Handling empty gathered state](authoring/static-validation.md#handling-empty-gathered-state) -- the `gather_state` pattern that produces `NOT_APPLICABLE` results consumed by prune.
- [Authoring Jobs - Command Support](authoring/index.md#command-support) -- the `check_command_support` pattern that produces `NOT_APPLICABLE` results consumed by prune.

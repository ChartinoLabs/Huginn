# Pruning Non-Applicable Tests

## Overview

After running in learning mode, some tests return `NOT_APPLICABLE` for certain devices - the device does not support the command, or the command works but produces no meaningful data. These results indicate that the test scope in the test plan is broader than the infrastructure actually requires.

The `huginn prune` command reads learning results and narrows the test plan automatically:

- **Partially applicable tests** (some devices are N/A): adds `target.exclude_devices` to the test case definition so those devices are skipped on future runs.
- **Fully non-applicable tests** (all devices are N/A): removes the test from every group that includes it. Leaf groups have the test ID removed from `tests`; composite groups that use `groups` inheritance get an `exclude_tests` entry instead. A test in a leaf group that a composite group includes gets both changes.
- **Orphaned definitions** (optional): with `--remove-orphans`, every test case definition that no group references is deleted entirely. This includes orphans left by earlier prune runs and test cases that were never placed in any group. See [Orphan removal](#orphan-removal).

Prune is designed to be run once after an initial learning pass against a new testbed. It tightens test scope based on observed reality, eliminating noise from tests that can never pass on the current infrastructure.

## Why tests become non-applicable

There are two distinct sources of `NOT_APPLICABLE` during learning:

### Command support (`check_command_support`)

The device does not support the command at all. For example, a parsed field is missing from the command output because the platform or software version does not implement it. The job's `check_command_support` method detects this and marks the device as non-applicable before any state is gathered.

### Empty gathered state (`gather_state`)

The command executes successfully, but the extracted data is empty for a device. For example, a `show ip ospf neighbor` command returns no neighbors because OSPF is not configured on that device. The job's `gather_state` method detects the empty result and emits a `NOT_APPLICABLE` result. See [Static Parameter Validation - Handling empty gathered state](../authoring/static-validation.md#handling-empty-gathered-state) for the recommended pattern.

Both sources produce the same `NOT_APPLICABLE` status in the learning results. The prune command does not distinguish between them - if a device is non-applicable, it is excluded.

Prune acts only on `NOT_APPLICABLE` devices. A device recorded as `LOST_APPLICABILITY`, because it supported the command when parameters were learned but no longer does in testing, is a failure rather than a scope problem, so prune never excludes it. See [Lost Applicability](../concepts/glossary.md#lost-applicability).

## Workflow

The typical workflow is: learn, preview, apply.

### Run in learning mode

Execute the test plan against the live testbed to capture current state and identify which tests apply to which devices.

```bash
huginn run -m learning -t testbed.yaml -p test_plan/
```

### Preview changes with dry run

Inspect what the prune command would change without modifying any files.

```bash
huginn prune -p test_plan/ --dry-run
```

Example output:

```
Pruning non-applicable tests from test plan
Using results from 2026-Sep-29-09-42-54-learning
Found 3 partially applicable and 2 fully non-applicable test(s)
Partially applicable tests (exclude_devices):
  1.3.0: exclude spine-03
  2.1.0: exclude leaf-04, leaf-05
  3.0.0: exclude spine-01
Fully non-applicable tests (remove from groups):
  3.2.0
  4.0.0
Applying exclude_devices to test cases:
  1.3.0: exclude_devices=['spine-03']
  2.1.0: exclude_devices=['leaf-04', 'leaf-05']
  3.0.0: exclude_devices=['spine-01']
Removing tests from groups:
  4.0.0 from bgp-tests
  3.2.0 from ospf-tests
  3.2.0 from pre-change-validation
  4.0.0 from pre-change-validation
Dry run complete: 3 test(s) would get exclude_devices, 4 test(s) would be removed from groups
```

The first two lists come from the learning results. The `Applying exclude_devices to test cases` and `Removing tests from groups` lists are the changes to the test plan, with one line per test case and one line per group membership. A test is removed from every group whose tests include it, so the removed-from-groups count in the last line counts group memberships, not distinct tests: 2 fully non-applicable tests here make 4 removals. Each line is prefixed with a timestamp, omitted here.

### Apply the prune

Run without `--dry-run` to modify the test plan files.

```bash
huginn prune -p test_plan/
```

The command validates the modified test plan after writing changes. If validation fails, it reports the error and exits with a non-zero status.

### Optionally remove orphaned definitions

If fully non-applicable tests were removed from all groups, their test case definitions still exist in the YAML but are unreferenced. Use `--remove-orphans` to clean them up. You can pass it on the same run that does the pruning, or on a later, separate run.

```bash
huginn prune -p test_plan/ --remove-orphans
```

`--remove-orphans` removes every unreferenced test case definition in the plan, not only the ones the current run pruned. That includes test cases that no group has ever listed, such as drafts you have not added to a group yet. Preview with `--dry-run` first:

```bash
huginn prune -p test_plan/ --remove-orphans --dry-run
```

The dry-run output lists each definition that would be deleted under `Removing orphaned test case definitions`.

## CLI reference

```
huginn prune --plan <path> [--results-dir <path>] [--dry-run] [--remove-orphans]
             [--debug] [--log-level <level>] [--show-logs] [--log-file <path>]
```

| Option                      | Default        | Description                                                                                                        |
| --------------------------- | -------------- | ------------------------------------------------------------------------------------------------------------------ |
| `--plan`, `-p`              | (required)     | Path to test plan YAML file or directory. Also accepts `HUGINN_PLAN` env var.                                      |
| `--results-dir`             | `./results/`   | Path to results directory. Also accepts `HUGINN_RESULTS_DIR` env var.                                              |
| `--dry-run`                 | off            | Show what would be pruned without modifying files.                                                                 |
| `--remove-orphans`          | off            | Delete every test case definition that no group references (see [Orphan removal](#orphan-removal)).                |
| `--no-unknown-key-warnings` | off            | Do not warn about unknown keys in the test plan or testbed. Also accepts `HUGINN_NO_UNKNOWN_KEY_WARNINGS` env var. |
| `--debug`                   | off            | Enable DEBUG-level logging. Also accepts `HUGINN_DEBUG` env var.                                                   |
| `--log-level`               | `INFO`         | Logging level (DEBUG, INFO, WARNING, ERROR). Also accepts `HUGINN_LOG_LEVEL` env var.                              |
| `--show-logs`               | off            | Stream logs to console in addition to file. Also accepts `HUGINN_SHOW_LOGS` env var.                               |
| `--log-file`                | `./huginn.log` | Path to log file. Also accepts `HUGINN_LOG_FILE` env var.                                                          |

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
      exclude_devices:
      - spine-03
```

If the test case already has `exclude_devices`, the prune command merges the new exclusions with the existing list. Devices already excluded are not duplicated.

### Full non-applicability: group removal

When all devices are non-applicable for a test, the test ID is removed from every group whose tests include it, directly or through nested `groups`. How it is removed depends on the group type, and a plan with nested groups usually gets both kinds of change at once.

#### Leaf groups

Groups that list test IDs only in `tests`, with no `groups` key, have the test ID removed from the list.

#### Composite groups

Groups that include other groups through `groups` have the test ID added to `exclude_tests`, rather than modifying the included group. This also applies to a test ID the composite group lists in its own `tests`.

#### Example

Before (3.2.0 and 4.0.0 are fully non-applicable):

```yaml
test_case_groups:
  ospf-tests:
    tests: ["3.0.0", "3.1.0", "3.2.0"]
  bgp-tests:
    tests: ["4.0.0", "4.1.0"]
  pre-change-validation:
    groups: [ospf-tests, bgp-tests]
```

After:

```yaml
test_case_groups:
  ospf-tests:
    tests: ["3.0.0", "3.1.0"]
  bgp-tests:
    tests: ["4.1.0"]
  pre-change-validation:
    groups: [ospf-tests, bgp-tests]
    exclude_tests:
    - 3.2.0
    - 4.0.0
```

The leaf groups `ospf-tests` and `bgp-tests` lose the test IDs from `tests`. The composite group `pre-change-validation` gets them in `exclude_tests`, which preserves its inheritance structure. The `exclude_tests` mechanism is the same one used by the [reconcile command](reconcile.md) to exclude baseline tests that diverge after a change.

### Orphan removal

When `--remove-orphans` is passed, the command checks every test case defined in the plan, whether or not the current run pruned it. A test case is referenced if at least one group's effective tests include it. A group's effective tests are:

1. The test IDs in its `tests`, plus the tests it inherits through nested `groups`.
2. Minus the test IDs in its `exclude_tests`.
3. Minus the test IDs this run removes from that group.

Test case definitions that no group references are deleted from the YAML. Some consequences:

- A test case that no group has ever listed, such as a draft, is an orphan and is deleted.
- A test case that appears only in a group's `exclude_tests` is an orphan.
- Any group counts, including a group that no scenario phase uses. A test case referenced only by such a group is kept.

This is a destructive operation - the test case definition and its key are removed from the `test_cases` map. The associated parameter files in `parameters/` are not touched; remove those manually if desired.

## Exit codes

| Code | Meaning                                                                                                                                    |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| 0    | The prune was applied or previewed, there was nothing to prune, or the pruning was already applied.                                        |
| 1    | The results directory does not exist or has no learning run, the test plan could not be loaded, or the pruned test plan failed validation. |
| 2    | [Usage error](cli.md#usage-errors), such as a missing `--plan` or a `--plan` path that does not exist.                                     |

## Idempotency

Running `huginn prune` a second time against the same results is safe. The command detects tests that are already pruned (devices already in `exclude_devices`, tests already removed from groups) and skips them. A message reports how many tests were skipped.

## Directory mode

When the `--plan` argument points to a directory, the prune command locates the correct YAML file for each test case and group using the same discovery logic as the framework's test plan loader. Changes are written only to the files that contain affected definitions. Formatting is preserved using round-trip YAML parsing.

## See also

- [CLI Reference](cli.md) - every `huginn` command, option and environment variable.
- [Test Plan Specification - Excluding Devices](test-plan.md#excluding-devices) - the `target.exclude_devices` field that prune adds.
- [Test Plan Specification - Test Case Group Fields](test-plan.md#test-case-group-fields) - group structure, `tests`, `groups`, and `exclude_tests`.
- [Parameter Reconciliation](reconcile.md) - a related command that creates new test case variants after a network change.
- [Static Parameter Validation - Handling empty gathered state](../authoring/static-validation.md#handling-empty-gathered-state) - the `gather_state` pattern that produces `NOT_APPLICABLE` results consumed by prune.
- [Authoring Jobs - Command Support](../authoring/index.md#command-support) - the `check_command_support` pattern that produces `NOT_APPLICABLE` results consumed by prune.

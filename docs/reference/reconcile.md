# Parameter Reconciliation

## Overview

When a network change occurs (e.g., a link shutdown), some baseline test cases will fail because the device state no longer matches the pre-change parameters. Huginn's `reconcile` command automates the process of creating new test case variants that reflect the post-change expected state.

## Workflow

### Run the scenario in testing mode

Execute the scenario against the live testbed. Tests in the post-change phase will fail because they're still comparing against baseline parameters.

```bash
uv run huginn run -m testing -t testbed.yaml -p test_plan/ --scenario link-shutdown-r1r2
```

The failures are recorded in `results/<timestamp>-testing/run.json`.

### Reconcile the failures

Run the `reconcile` command, pointing it at the phase that contains the failures.

```bash
uv run huginn reconcile -p test_plan/ --phase post-shutdown --scenario link-shutdown-r1r2
```

This does several things automatically:

- Parses the latest test run results to identify which tests failed
- Creates new test case definitions named `<id>-<scenario>-<phase>` (e.g., `1.1.0-link-shutdown-r1r2-post-shutdown`)
- Creates a new test case group named the same way (e.g., `post-shut-r1r2-link-shutdown-r1r2-post-shutdown`) that:
  - Inherits from the original group (`post-shut-r1r2`)
  - Excludes the failing baseline test IDs
  - Includes the new reconciled variant test IDs
  - Keeps the `target` and `tags` the original tests received from their groups (see [How targets and tags are preserved](#how-targets-and-tags-are-preserved))
- Copies baseline parameter files to new `<id>-<scenario>-<phase>.json` parameter files as a starting point
- Updates the phase in the scenario definition to reference the new reconciled group
- Writes the new definitions to `reconciled-<phase>.yaml` (when using a directory-based test plan)

The command prints how many test cases, groups, and parameter files it created, but not their IDs. Read the new IDs from `reconciled-<phase>.yaml` (or the plan file) before moving on.

### Re-learn the post-change parameters

The copied parameter files still contain baseline values. Run the new variants in learning mode so Huginn captures the actual post-change device state. Select them by test ID:

```bash
uv run huginn run -m learning -t testbed.yaml -p test_plan/ --test-id 1.1.0-link-shutdown-r1r2-post-shutdown
```

Repeat `--test-id` once per variant. When there are many, `--test-id-pattern '-link-shutdown-r1r2-post-shutdown$'` selects the same set with a regular expression.

This overwrites the copied parameter files (e.g., `parameters/1.1.0-link-shutdown-r1r2-post-shutdown.json`) with values gathered from the devices in their post-change state.

Avoid selecting the reconciled group or the whole phase here. The reconciled group inherits every test in its parent group that did not fail. Selecting it with `--test-case-group post-shut-r1r2-link-shutdown-r1r2-post-shutdown`, or selecting the phase with `--scenario link-shutdown-r1r2 --phase post-shutdown`, also re-learns those inherited baseline tests (`1.2.0` in this example) and overwrites their parameter files with post-change state. Select the variants by `--test-id` or `--test-id-pattern` to leave the baseline parameters untouched.

This run executes only the phases that contain a selected test, here `post-shutdown`. It does not replay the `shutdown` phase, so the devices must already be in their post-change state when you run it.

### Validate

Run the scenario again in testing mode. The post-change phase should now pass.

```bash
uv run huginn run -m testing -t testbed.yaml -p test_plan/ --scenario link-shutdown-r1r2
```

## Example: reconciled group structure

After reconciliation, the generated group in `reconciled-post-shutdown.yaml` looks like this:

```yaml
test_case_groups:
  post-shut-r1r2-link-shutdown-r1r2-post-shutdown:
    groups:
    - post-shut-r1r2                            # inherit from parent group
    exclude_tests:
    - 1.1.0                                     # exclude baseline tests that fail post-change
    - 1.6.1
    - 1.7.0
    # ...
    tests:
    - 1.1.0-link-shutdown-r1r2-post-shutdown    # include reconciled variants
    - 1.6.1-link-shutdown-r1r2-post-shutdown
    - 1.7.0-link-shutdown-r1r2-post-shutdown
    # ...
```

### How targets and tags are preserved

A reconciled variant runs on exactly the devices its original ran on in that phase, and carries the same inherited tags for `--tags` and `--exclude-tags` filtering. Reconcile writes the targeting into the generated groups rather than onto the variant test case:

- The reconciled group copies the `target` and `tags` of the original group, so a variant the original group lists in its own `tests` is narrowed and tagged the same way.
- When the original group inherited the failing test through nested `groups`, the child groups' `target` and `tags` also applied to it. Reconcile rebuilds each such inclusion path as generated groups named `<reconciled-group>-path<N>`, with one group per `target` on the path (inner levels are suffixed `-2`, `-3`, and so on). The reconciled group includes these, and the innermost one lists the variant and carries the path's tags.
- When the original was reachable through several paths with different targets, the variant gets one generated path per distinct path, so it again runs on the union of the devices those paths select.
- The phase `target` still applies, because the reconciled group stays in the same phase.

For example, if `grand` has `target: {groups: [leaf]}` and includes `child`, which has `target: {os: [nxos]}` and lists `lp-t1`, reconciling `lp-t1` in phase `post` of scenario `s1` writes:

```yaml
test_case_groups:
  grand-s1-post:
    groups:
    - grand
    - grand-s1-post-path1                       # rebuilds the path through child
    exclude_tests:
    - lp-t1
    target:                                     # copied from grand
      groups:
      - leaf
  grand-s1-post-path1:
    tests:
    - lp-t1-s1-post
    target:                                     # copied from child
      os:
      - nxos
```

Targets are copied as selectors, never resolved into a `target.devices` list, so the reconciled plan keeps working when the testbed changes.

The reconciled group copies the original group's `description`, if it has one.

The scenario name is part of every reconciled ID, so reconciling the same phase name in two scenarios produces separate variants. If a group ID is identical to the phase name, the redundant prefix is dropped and the reconciled group is named `<scenario>-<phase>`.

## CLI reference

```
huginn reconcile --plan <path> --phase <phase-name> [--scenario <scenario-id>] [--results-dir <path>] [--parameters-dir <path>]
```

| Option                      | Default         | Description                                                                                                                                       |
| --------------------------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--plan`, `-p`              | (required)      | Path to test plan YAML file or directory. Also accepts `HUGINN_PLAN` env var.                                                                     |
| `--phase`                   | (required)      | Phase whose failures to reconcile. Combined with the scenario name to form the `-<scenario>-<phase>` suffix. Also accepts `HUGINN_PHASE` env var. |
| `--scenario`                | none            | Scenario to reconcile. Optional only when exactly one scenario in the results contains the phase. Also accepts `HUGINN_SCENARIO` env var.         |
| `--results-dir`             | `./results/`    | Directory containing test run results. Also accepts `HUGINN_RESULTS_DIR` env var.                                                                 |
| `--parameters-dir`          | `./parameters/` | Directory containing parameter files. Also accepts `HUGINN_PARAMETERS_DIR` env var.                                                               |
| `--no-unknown-key-warnings` | off             | Do not warn about unknown keys in the test plan or testbed. Also accepts `HUGINN_NO_UNKNOWN_KEY_WARNINGS` env var.                                |
| `--debug`                   | off             | Enable DEBUG-level logging. Also accepts `HUGINN_DEBUG` env var.                                                                                  |
| `--log-level`               | `INFO`          | Logging level (DEBUG, INFO, WARNING, ERROR). Also accepts `HUGINN_LOG_LEVEL` env var.                                                             |
| `--show-logs`               | off             | Stream logs to console in addition to file. Also accepts `HUGINN_SHOW_LOGS` env var.                                                              |
| `--log-file`                | `./huginn.log`  | Path to log file. Also accepts `HUGINN_LOG_FILE` env var.                                                                                         |

Reconcile reads the most recent `*-testing` directory under `--results-dir`. When more than one scenario in that run contains the phase and `--scenario` is omitted, the command stops with `Multiple scenarios contain phase '<phase>': [...]. Use --scenario to specify which one to reconcile.`

## Exit codes

| Code | Meaning                                                                                                                                                                |
| ---- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0    | Reconciliation applied, no failures found in the phase, or reconciliation already applied.                                                                             |
| 1    | Reconciliation could not proceed: no testing results, phase or scenario not found, `--scenario` needed to disambiguate, or the reconciled test plan failed validation. |
| 2    | Usage error, such as a missing `--phase` option.                                                                                                                       |

## What the command modifies

### Test plan files

For a directory-based test plan, reconcile writes the new test cases and groups to `reconciled-<phase>.yaml` in the plan directory and rewrites the file that defines the scenario so the phase points at the reconciled group. Other files are not touched.

For a single-file test plan, reconcile edits that file in place. The new test cases and groups are appended to the existing `test_cases` and `test_case_groups` sections, and the phase reference is updated in the same file.

Every file reconcile writes is re-serialized with PyYAML. Comments, blank lines, key quoting, and flow-style lists such as `tests: [1.1.0, 1.2.0]` are lost in those files. Commit the test plan before reconciling if you want to review or restore the original formatting.

### Reconciled test case contents

Each variant keeps the original `job`, `tags`, and `target`. The `target` and `tags` it inherited from its groups are kept by the generated groups, as described in [How targets and tags are preserved](#how-targets-and-tags-are-preserved). Its `title` gets a ` (<scenario> <phase>)` suffix, for example `Verify OSPF neighbor 10.1.1.1 (link-shutdown-r1r2 post-shutdown)`. The `description`, `priority`, `category`, `is_automated`, and `metadata` fields are not copied, so add them back by hand if the variant needs them.

### Parameter files

For each variant, reconcile copies `<parameters-dir>/<id>.json` to `<parameters-dir>/<id>-<scenario>-<phase>.json`. A missing source file, or a destination that already exists, is skipped with a warning.

### Re-running reconcile

Running reconcile again for the same scenario and phase skips IDs that already exist and reports `Reconciliation already applied -- no changes needed`.

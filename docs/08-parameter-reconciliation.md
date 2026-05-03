# Parameter Reconciliation

## Overview

When a network change occurs (e.g., a link shutdown), some baseline test cases will fail because the device state no longer matches the pre-change parameters. Huginn's `reconcile` command automates the process of creating new test case variants that reflect the post-change expected state.

## Workflow

### 1. Run the scenario in testing mode

Execute the scenario against the live testbed. Tests in the post-change phase will fail because they're still comparing against baseline parameters.

```bash
uv run huginn run -m testing -t testbed.yaml -p test_plan/ --scenario link-shutdown-r1r2
```

The failures are recorded in `results/<timestamp>-testing/run.json`.

### 2. Reconcile the failures

Run the `reconcile` command, pointing it at the phase that contains the failures.

```bash
uv run huginn reconcile -p test_plan/ --phase post-shutdown --scenario link-shutdown-r1r2
```

This does several things automatically:

- Parses the latest test run results to identify which tests failed
- Creates new test case definitions with a `-<phase>` suffix (e.g., `1.1.0-post-shutdown`)
- Creates a new test case group (e.g., `post-shut-r1r2-post-shutdown`) that:
  - Inherits from the original group (`post-shut-r1r2`)
  - Excludes the failing baseline test IDs
  - Includes the new `-post-shutdown` variant test IDs
- Copies baseline parameter files to new `-<phase>` parameter files as a starting point
- Updates the scenario in `scenarios.yaml` to reference the new reconciled group
- Writes the new definitions to `reconciled-<phase>.yaml` (when using a directory-based test plan)

### 3. Re-learn the post-change parameters

The copied parameter files still contain baseline values. Run the reconciled group in learning mode so Huginn captures the actual post-change device state.

```bash
uv run huginn run -m learning -t testbed.yaml -p test_plan/ --test-case-group post-shut-r1r2-post-shutdown
```

This overwrites the copied parameter files (e.g., `parameters/1.1.0-post-shutdown.json`) with values gathered from the devices in their post-change state.

### 4. Validate

Run the scenario again in testing mode. The post-change phase should now pass.

```bash
uv run huginn run -m testing -t testbed.yaml -p test_plan/ --scenario link-shutdown-r1r2
```

## Example: reconciled group structure

After reconciliation, the generated group in `reconciled-post-shutdown.yaml` looks like this:

```yaml
test_case_groups:
  post-shut-r1r2-post-shutdown:
    groups:
    - post-shut-r1r2              # inherit from parent group
    exclude_tests:
    - 1.1.0                       # exclude baseline tests that fail post-change
    - 1.6.1
    - 1.7.0
    # ...
    tests:
    - 1.1.0-post-shutdown         # include reconciled variants
    - 1.6.1-post-shutdown
    - 1.7.0-post-shutdown
    # ...
```

## CLI reference

```
huginn reconcile --plan <path> --phase <phase-name> [--scenario <scenario-id>] [--results-dir <path>] [--parameters-dir <path>]
```

| Option             | Default         | Description                                               |
| ------------------ | --------------- | --------------------------------------------------------- |
| `--plan`, `-p`     | (required)      | Path to test plan file or directory                       |
| `--phase`          | (required)      | Phase name to reconcile (used as suffix for new test IDs) |
| `--scenario`       | all             | Filter to a specific scenario                             |
| `--results-dir`    | `./results/`    | Directory containing test run results                     |
| `--parameters-dir` | `./parameters/` | Directory containing parameter files                      |

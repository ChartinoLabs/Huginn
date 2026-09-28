# Selective Re-learning

## Overview

When a testing run produces failures because learned parameters no longer reflect the current state of the environment, the `huginn relearn` command refreshes only the affected parameters. It parses the latest testing results, identifies failed and errored test cases, and re-runs only those tests in learning mode to capture current device state as the new expected parameters -- without re-learning tests that are already passing.

The command re-runs each failed test only in the exact scenario and phase where it failed, avoiding redundant device connections when the same test ID appears across many scenarios.

## Workflow

### 1. Run in testing mode

Execute the test plan against the live testbed. Some tests may fail due to parameter drift.

```bash
huginn run -m testing -t testbed.yaml -p test_plan/ --scenario link-shutdown-r1r2
```

Failures are recorded in `results/<timestamp>-testing/run.json`.

### 2. Inspect the failures

Before re-learning, confirm that the failures reflect expected drift (stale parameters from an earlier learning pass) rather than real problems. The HTML report at `reports/latest/` provides detailed diffs between expected and actual values.

### 3. Re-learn failed tests

Run the `relearn` command to refresh parameters for just the failed tests.

```bash
huginn relearn -p test_plan/ -t testbed.yaml
```

Example output:

```
Analyzing latest testing run for failures
Using results from 2026-Jun-22-17-52-44-testing
Re-learning 9 failed test context(s) (9 test(s) in 1 scenario(s), 1 phase(s)): link-shutdown-r1r2/pre-change/BGP-SUMMARY-NEIGHBOR-EXISTENCE, link-shutdown-r1r2/pre-change/BGP-SUMMARY-NEIGHBOR-TABLE-VERSION, ...
Starting run in learning mode
Primed runtime connections in 2.846s
Re-learn complete: total=9 passed=9 failed=0 errored=0 not_applicable=0
Successfully re-learned parameters for 9 test(s)
```

### 4. Verify

Run testing mode again to confirm the refreshed parameters resolve the failures.

```bash
huginn run -m testing -t testbed.yaml -p test_plan/ --scenario link-shutdown-r1r2
```

## Filtering

By default, the command re-learns all failures from the latest testing run. Use `--scenario` and `--phase` to narrow scope further.

Re-learn only failures from a specific scenario:

```bash
huginn relearn -p test_plan/ -t testbed.yaml --scenario link-shutdown-r1r2
```

Re-learn only failures from a specific phase:

```bash
huginn relearn -p test_plan/ -t testbed.yaml --phase pre-change
```

Both filters can be combined:

```bash
huginn relearn -p test_plan/ -t testbed.yaml --scenario link-shutdown-r1r2 --phase pre-change
```

## Automatic scoping

The command does not simply filter by test ID. It records each failure as a scenario, phase, and test ID context, and re-runs each test only in the contexts where it failed. This prevents a test ID that appears in 50 scenarios from being re-learned in all 50 when only one had a failure.

For example, if `BGP-SUMMARY-ROUTER-ID` failed only in the `link-shutdown-r1r2` scenario's `pre-change` phase, the relearn run will execute that test only in that specific scenario and phase context -- not across all scenarios that reference the same test ID. If another test failed only in a different scenario's `post-change` phase, `BGP-SUMMARY-ROUTER-ID` is not re-run there either. The summary line lists each context as `<scenario>/<phase>/<test ID>`.

Phases that contain no failures are not run. When a phase with failures depends on a phase without failures, the dependency is dropped and the phase runs on its own. When both phases contain failures, the dependency is kept, so the dependent phase is blocked if re-learning fails in the earlier phase.

## CLI reference

```
huginn relearn [--plan <path>] [--testbed <path>] [--scenario <id>] [--phase <id>] [--results-dir <path>] [--parameters-dir <path>]
```

| Option                     | Default                | Description                                                                                                                                                          |
| -------------------------- | ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--plan`, `-p`             | `./test_plan`          | Path to test plan YAML file or directory. Also accepts `HUGINN_PLAN` env var.                                                                                        |
| `--testbed`, `-t`          | `./testbed.yaml`       | Path to testbed YAML file. Also accepts `HUGINN_TESTBED` env var.                                                                                                    |
| `--scenario`               | all                    | Re-learn only failures from the specified scenario.                                                                                                                  |
| `--phase`                  | all                    | Re-learn only failures from the specified phase.                                                                                                                     |
| `--data-model`, `-d`       | none                   | Data model directory. Overrides the test plan's `data_model.path`; a relative path resolves against the working directory. Also accepts `HUGINN_DATA_MODEL` env var. |
| `--inventory-plugin`, `-i` | none                   | Use an inventory plugin instead of a static testbed. Also accepts `HUGINN_INVENTORY_PLUGIN` env var.                                                                 |
| `--results-dir`            | `./results/`           | Directory containing test run results. Also accepts `HUGINN_RESULTS_DIR` env var.                                                                                    |
| `--parameters-dir`         | `./parameters/`        | Directory containing parameter files. Also accepts `HUGINN_PARAMETERS_DIR` env var.                                                                                  |
| `--output-dir`             | `<run-dir>/artifacts/` | Output directory for run artifacts. Also accepts `HUGINN_OUTPUT_DIR` env var.                                                                                        |
| `--debug`                  | off                    | Enable DEBUG-level logging. Also accepts `HUGINN_DEBUG` env var.                                                                                                     |
| `--log-level`              | `INFO`                 | Logging level (DEBUG, INFO, WARNING, ERROR). Also accepts `HUGINN_LOG_LEVEL` env var.                                                                                |
| `--show-logs`              | off                    | Stream logs to console in addition to file. Also accepts `HUGINN_SHOW_LOGS` env var.                                                                                 |
| `--log-file`               | `./huginn.log`         | Path to log file. Also accepts `HUGINN_LOG_FILE` env var.                                                                                                            |

## What the command modifies

The relearn command overwrites parameter files in the `--parameters-dir` directory for each test that is re-learned. For example, if `BGP-SUMMARY-ROUTER-ID` fails and is re-learned, the file `parameters/BGP-SUMMARY-ROUTER-ID.json` is overwritten with freshly gathered device state.

No test plan YAML files are modified. The test plan structure remains unchanged -- only the parameter values are refreshed.

## Exit codes

| Code | Meaning                                                                                        |
| ---- | ---------------------------------------------------------------------------------------------- |
| 0    | No failures found, or no re-learned test case is `failed`, `errored` or `blocked`.             |
| 1    | A re-learned test case is `failed`, `errored` or `blocked`, or a configuration error occurred. |

A non-zero exit during re-learning typically means the device could not be reached or a job raised an unexpected error. The parameter files for those tests will not have been updated.

## See also

- [CLI Reference](cli.md) - every `huginn` command, option and environment variable.
- [Concepts - Re-learning](../concepts/relearning.md) - when and why to use relearn vs. reconciliation.
- [CLI - reconcile](reconcile.md) - creating post-change test variants (different use case).
- [CLI - prune](prune.md) - removing non-applicable tests from the plan.
- [Execution Modes](../concepts/execution-modes.md) - how learning mode works under the hood.

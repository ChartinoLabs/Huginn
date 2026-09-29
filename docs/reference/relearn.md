# Selective Re-learning

## Overview

When a testing run produces failures because learned parameters no longer reflect the current state of the environment, the `huginn relearn` command refreshes only the affected parameters. It parses the latest testing results, identifies test cases that are `failed`, `errored` or `lost_applicability`, and re-runs only those tests in learning mode to capture current device state as the new expected parameters, without re-learning tests that are already passing.

The command re-runs each failed test only in the exact scenario and phase where it failed, avoiding redundant device connections when the same test ID appears across many scenarios.

## Workflow

### Run in testing mode

Execute the test plan against the live testbed. Some tests may fail due to parameter drift.

```bash
huginn run -m testing -t testbed.yaml -p test_plan/ --scenario link-shutdown-r1r2
```

Failures are recorded in `results/<timestamp>-testing/run.json`.

### Inspect the failures

Before re-learning, confirm that the failures reflect expected drift (stale parameters from an earlier learning pass) rather than real problems. The HTML report at `reports/latest/` provides detailed diffs between expected and actual values.

### Re-learn failed tests

Run the `relearn` command to refresh parameters for just the failed tests.

```bash
huginn relearn -p test_plan/ -t testbed.yaml
```

Example output:

```
Analyzing latest testing run for failures
Using results from 2026-Sep-29-09-51-58-testing
Re-learning 3 failed test context(s) (3 test(s) in 1 scenario(s), 1 phase(s)): link-shutdown-r1r2/pre-change/OSPF-NEIGHBOR-STATE, link-shutdown-r1r2/pre-change/BGP-SUMMARY-NEIGHBOR-EXISTENCE, link-shutdown-r1r2/pre-change/BGP-SUMMARY-TABLE-VERSION
Loading inventory and test plan
Loaded inventory and test plan in 0.001s
Planning test execution
Planned test execution in 0.000s (tests=3 errors=0)
Execution order:
  Scenario: link-shutdown-r1r2
    Phase: pre-change
Priming runtime connections
Priming connection set: broker=RuntimeBroker methods=ssh targets=r1,r2
Primed connection set: broker=RuntimeBroker methods=ssh targets=r1,r2 duration=0.000s
Primed runtime connections in 0.000s
Executing scenarios and phases
Starting scenario: link-shutdown-r1r2
  Starting phase: pre-change
Starting test: OSPF-NEIGHBOR-STATE (Verify OSPF neighbor state)
Finished test: OSPF-NEIGHBOR-STATE status=passed
Starting test: BGP-SUMMARY-NEIGHBOR-EXISTENCE (Verify BGP neighbors exist)
Finished test: BGP-SUMMARY-NEIGHBOR-EXISTENCE status=passed
Starting test: BGP-SUMMARY-TABLE-VERSION (Verify BGP table version)
Finished test: BGP-SUMMARY-TABLE-VERSION status=passed
Phase complete: link-shutdown-r1r2.pre-change status=passed total=3 passed=3 failed=0 errored=0 not_applicable=0 lost_applicability=0 skipped=0 blocked=0
Finished phase execution in 0.002s
Finished all scenario execution in 0.002s
Report written to /home/netops/fabric-tests/reports/2026-Sep-29-09-51-59-learning/html/index.html
Run completed in 0.023s
Re-learn complete: total=3 passed=3 failed=0 errored=0 not_applicable=0
Successfully re-learned parameters for 3 test(s)
```

The lines between `Re-learning` and `Re-learn complete` are the progress output of the learning run, the same as `huginn run` prints. Each line is prefixed with a timestamp, omitted here.

### Verify

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

For example, if `BGP-SUMMARY-ROUTER-ID` failed only in the `link-shutdown-r1r2` scenario's `pre-change` phase, the relearn run will execute that test only in that specific scenario and phase context, not across all scenarios that reference the same test ID. If another test failed only in a different scenario's `post-change` phase, `BGP-SUMMARY-ROUTER-ID` is not re-run there either. The summary line lists each context as `<scenario>/<phase>/<test ID>`.

Phases that contain no failures are not run. When a phase with failures depends on a phase without failures, the dependency is dropped and the phase runs on its own. When both phases contain failures, the dependency is kept, so the dependent phase is blocked if re-learning fails in the earlier phase. It is also blocked when the earlier phase has a change or action job, which learning mode skips (see [Blocking in learning mode](test-plan.md#blocking-in-learning-mode)). Its parameters are then not updated, and the command still exits 0.

## CLI reference

```
huginn relearn [--plan <path>] [--testbed <path> | --inventory-plugin <name>] [--scenario <id>] [--phase <id>]
               [--data-model <path>] [--results-dir <path>] [--parameters-dir <path>] [--output-dir <path>]
               [--debug] [--log-level <level>] [--show-logs] [--log-file <path>]
```

| Option                      | Default                | Description                                                                                                                                                          |
| --------------------------- | ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--plan`, `-p`              | `./test_plan`          | Path to test plan YAML file or directory. Also accepts `HUGINN_PLAN` env var.                                                                                        |
| `--testbed`, `-t`           | `./testbed.yaml`       | Path to testbed YAML file. Also accepts `HUGINN_TESTBED` env var.                                                                                                    |
| `--scenario`                | all                    | Re-learn only failures from the specified scenario. Also accepts `HUGINN_SCENARIO` env var.                                                                          |
| `--phase`                   | all                    | Re-learn only failures from the specified phase. Does not require `--scenario`. Also accepts `HUGINN_PHASE` env var.                                                 |
| `--data-model`, `-d`        | none                   | Data model directory. Overrides the test plan's `data_model.path`; a relative path resolves against the working directory. Also accepts `HUGINN_DATA_MODEL` env var. |
| `--inventory-plugin`, `-i`  | none                   | Use an inventory plugin instead of a static testbed. Also accepts `HUGINN_INVENTORY_PLUGIN` env var.                                                                 |
| `--results-dir`             | `./results/`           | Directory containing test run results. Also accepts `HUGINN_RESULTS_DIR` env var.                                                                                    |
| `--parameters-dir`          | `./parameters/`        | Directory containing parameter files. Also accepts `HUGINN_PARAMETERS_DIR` env var.                                                                                  |
| `--output-dir`              | `<run-dir>/artifacts/` | Output directory for run artifacts. Also accepts `HUGINN_OUTPUT_DIR` env var.                                                                                        |
| `--no-unknown-key-warnings` | off                    | Do not warn about unknown keys in the test plan or testbed. Also accepts `HUGINN_NO_UNKNOWN_KEY_WARNINGS` env var.                                                   |
| `--debug`                   | off                    | Enable DEBUG-level logging. Also accepts `HUGINN_DEBUG` env var.                                                                                                     |
| `--log-level`               | `INFO`                 | Logging level (DEBUG, INFO, WARNING, ERROR). Also accepts `HUGINN_LOG_LEVEL` env var.                                                                                |
| `--show-logs`               | off                    | Stream logs to console in addition to file. Also accepts `HUGINN_SHOW_LOGS` env var.                                                                                 |
| `--log-file`                | `./huginn.log`         | Path to log file. Also accepts `HUGINN_LOG_FILE` env var.                                                                                                            |

## What the command modifies

The relearn command overwrites parameter files in the `--parameters-dir` directory for each test that is re-learned. For example, if `BGP-SUMMARY-ROUTER-ID` fails and is re-learned, the file `parameters/BGP-SUMMARY-ROUTER-ID.json` is overwritten with freshly gathered device state.

No test plan YAML files are modified. The test plan structure remains unchanged; only the parameter values are refreshed.

## Exit codes

| Code | Meaning                                                                                                                                                                                                                      |
| ---- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0    | No failures to re-learn, or no re-learned test case is `failed`, `errored` or `blocked`. Test cases blocked only because a phase was not run in learning mode do not count.                                                  |
| 1    | A re-learned test case is `failed`, `errored` or `blocked`; the results directory has no testing run; the testbed, test plan or data model could not be loaded; or a broker error occurred.                                  |
| 2    | [Usage error](cli.md#usage-errors), such as passing both `--testbed` and `--inventory-plugin`; inventory plugin failure; phase dependencies in a scenario could not be resolved; or results or reports could not be written. |

A test case that learning mode skips, such as a change or action job, is not re-learned and does not cause a non-zero exit. If every failed test case is skipped this way, the command exits 0 and reports `Successfully re-learned parameters for 0 test(s)`.

A non-zero exit during re-learning typically means the device could not be reached or a job raised an unexpected error. The parameter files for those tests will not have been updated.

## See also

- [CLI Reference](cli.md) - every `huginn` command, option and environment variable.
- [Concepts - Re-learning](../concepts/relearning.md) - when and why to use relearn vs. reconciliation.
- [CLI - reconcile](reconcile.md) - creating post-change test variants (different use case).
- [CLI - prune](prune.md) - removing non-applicable tests from the plan.
- [Execution Modes](../concepts/execution-modes.md) - how learning mode works under the hood.

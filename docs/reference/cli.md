# CLI Reference

## Overview

The `huginn` command groups every Huginn operation under one entry point. Run `huginn --help`, or `huginn <command> --help`, to print the same options from the installed version.

| Command                         | Purpose                                                                  |
| ------------------------------- | ------------------------------------------------------------------------ |
| [`run`](#run)                   | Execute a test plan against a testbed in learning or testing mode.       |
| [`validate`](#validate)         | Validate the testbed and test plan without connecting to devices.        |
| [`execute`](#execute)           | Run ad-hoc commands on testbed devices.                                  |
| [`inject new`](#inject-new)     | Create a new test case group from job files.                             |
| [`inject into`](#inject-into)   | Add job files to an existing test case group.                            |
| [`reconcile`](#reconcile)       | Create post-change variants of test cases that failed in a phase.        |
| [`relearn`](#relearn)           | Re-learn parameters for the tests that failed in the latest testing run. |
| [`prune`](#prune)               | Remove non-applicable tests and devices from the test plan.              |
| [`version`](#version)           | Print the installed Huginn version.                                      |
| [Shell completion](#completion) | Install or print a completion script for the current shell.              |

## Conventions

### Environment variables

Most options can also be set through an environment variable, listed in the Env var column of each table. Options with an empty Env var column can only be set on the command line.

For each option, a value given on the command line takes precedence over its environment variable, which takes precedence over a [project default](configuration.md#project-defaults-in-toolhuginn) in the `[tool.huginn]` table of `./pyproject.toml`, which takes precedence over the built-in default. See [Configuration - Precedence](configuration.md#precedence).

Boolean flags such as `--debug` accept `1`, `true`, `yes` or `on` (and their negative forms) when set through the environment:

```bash
export HUGINN_TESTBED=testbed.yaml
export HUGINN_DEBUG=true
huginn run -m testing -p test_plan/
```

### Repeatable and comma-separated values

Options marked as repeatable can be given more than once, and each value can also hold a comma-separated list. These two commands select the same test cases:

```bash
huginn run -m testing --test-id BGP-SUMMARY-ROUTER-ID --test-id OSPF-NEIGHBOR-STATE
huginn run -m testing --test-id BGP-SUMMARY-ROUTER-ID,OSPF-NEIGHBOR-STATE
```

Whitespace around each item is stripped and duplicates are dropped. When a repeatable option is set through its environment variable, separate the values with spaces or commas, for example `HUGINN_TAGS="ospf,critical"`.

### Default paths

Paths default to locations relative to the current working directory, such as `./test_plan` and `./testbed.yaml`. The Default column in the tables below shows these built-in defaults. A `[tool.huginn]` table in `./pyproject.toml` can replace them for the plan, testbed, parameters, results, output and log file paths, and can set a default inventory plugin; see [Configuration - Supported keys](configuration.md#supported-keys). `huginn <command> --help` marks a default that comes from `pyproject.toml`. When a default path is required and does not exist, the command stops with a usage error.

### Logging options

Every command except `inject`, `version` and shell completion accepts the same logging options. They are listed here once and referred to as the logging options in the tables below.

| Option        | Short | Env var            | Default        | Description                                             |
| ------------- | ----- | ------------------ | -------------- | ------------------------------------------------------- |
| `--debug`     |       | `HUGINN_DEBUG`     | off            | Enable DEBUG-level logging. Overrides `--log-level`.    |
| `--log-level` |       | `HUGINN_LOG_LEVEL` | `INFO`         | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`).    |
| `--show-logs` |       | `HUGINN_SHOW_LOGS` | off            | Stream logs to the console in addition to the log file. |
| `--log-file`  |       | `HUGINN_LOG_FILE`  | `./huginn.log` | Path to the log file.                                   |

### Usage errors

A missing required option, an invalid value, or a conflicting combination of options is reported as a usage error with exit code 2 before any work starts. This applies to every command, so the exit code tables below list code 2 only where a command also uses it for other failures.

## run

Execute a test plan against infrastructure. In learning mode, current device state is captured as baseline parameters. In testing mode, current state is compared against the learned parameters.

```
huginn run --mode <learning|testing> [--plan <path>] [--testbed <path> | --inventory-plugin <name>]
           [--tags <tags>] [--exclude-tags <tags>] [--scenario <ids>] [--phase <ids>]
           [--test-case-group <ids>] [--test-id <ids>] [--test-id-pattern <regex>]
           [--results-dir <path>] [--parameters-dir <path>] [--output-dir <path>]
           [logging options]
```

| Option               | Short | Env var                   | Default                | Description                                                                                                                |
| -------------------- | ----- | ------------------------- | ---------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `--mode`             | `-m`  | `HUGINN_MODE`             | (required)             | Execution mode. One of `learning` or `testing`.                                                                            |
| `--plan`             | `-p`  | `HUGINN_PLAN`             | `./test_plan`          | Path to test plan YAML file or directory of YAML files.                                                                    |
| `--testbed`          | `-t`  | `HUGINN_TESTBED`          | `./testbed.yaml`       | Path to testbed YAML file defining device inventory. Mutually exclusive with `--inventory-plugin`.                         |
| `--inventory-plugin` | `-i`  | `HUGINN_INVENTORY_PLUGIN` | none                   | Use an inventory plugin instead of a static testbed YAML file. Mutually exclusive with `--testbed`.                        |
| `--tags`             |       | `HUGINN_TAGS`             | none                   | Run only test cases that have every listed tag. Repeatable, comma-separated.                                               |
| `--exclude-tags`     |       | `HUGINN_EXCLUDE_TAGS`     | none                   | Skip test cases that have any listed tag. Repeatable, comma-separated.                                                     |
| `--scenario`         |       | `HUGINN_SCENARIO`         | none                   | Run only the listed scenarios. Repeatable, comma-separated.                                                                |
| `--phase`            |       | `HUGINN_PHASE`            | none                   | Run only the listed phases. Requires `--scenario`. Repeatable, comma-separated.                                            |
| `--test-case-group`  |       | `HUGINN_TEST_CASE_GROUP`  | none                   | Run only the listed test case groups. Repeatable, comma-separated.                                                         |
| `--test-id`          |       | `HUGINN_TEST_ID`          | none                   | Run only the listed test case IDs. Repeatable, comma-separated.                                                            |
| `--test-id-pattern`  |       | `HUGINN_TEST_ID_PATTERN`  | none                   | Python regular expression matched anywhere in the test case ID, for example `'-post-shutdown$'`.                           |
| `--data-model`       | `-d`  | `HUGINN_DATA_MODEL`       | none                   | Data model directory. Overrides the test plan's `data_model.path`. A relative path resolves against the working directory. |
| `--results-dir`      |       | `HUGINN_RESULTS_DIR`      | `./results/`           | Directory where run results are written.                                                                                   |
| `--parameters-dir`   |       | `HUGINN_PARAMETERS_DIR`   | `./parameters/`        | Directory where learned parameters are written in learning mode and read in testing mode.                                  |
| `--output-dir`       |       | `HUGINN_OUTPUT_DIR`       | `<run-dir>/artifacts/` | Directory for run artifacts.                                                                                               |
| logging options      |       |                           |                        | See [Logging options](#logging-options).                                                                                   |

### Filtering

Filters narrow the test plan before it is validated and executed. All filters combine, so a test case must pass every filter that is given. `--scenario`, `--phase`, `--test-case-group` and `--test-id` match any listed value, `--tags` requires every listed tag, and `--exclude-tags` drops a test case that has any listed tag.

`--phase` is rejected with `--phase requires --scenario to be specified.` unless `--scenario` is also given, because phase names are scoped to a scenario.

```bash
huginn run -m testing -t testbed.yaml -p test_plan/ --scenario ospf-area-change --phase post-change
huginn run -m testing -t testbed.yaml -p test_plan/ --tags ospf,critical --exclude-tags slow
huginn run -m learning -t testbed.yaml -p test_plan/ --test-id-pattern '-post-shutdown$'
```

See [Test Plan Specification - CLI Filtering](test-plan.md#cli-filtering) for how filters interact with groups and phases. A filter that matches nothing is not an error: the run completes with `No test cases were selected for execution` and exits 0.

### Exit codes

| Code | Meaning                                                                                                                                                 |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0    | The overall run status is `passed`, or no test cases were selected.                                                                                     |
| 1    | The overall run status is `failed`, `errored`, `not_applicable` or `skipped`; the testbed or test plan could not be loaded; or a broker error occurred. |
| 2    | Usage error; inventory plugin failure; phase dependencies in a scenario could not be resolved; or results or reports could not be written.              |

An invalid `--test-id-pattern` regular expression currently ends the run with a Python traceback and exit code 1.

## validate

Validate the testbed and test plan without executing tests. Validation loads both inputs, applies the filters, resolves phase order, and checks that every test case can be loaded and targeted. No devices are contacted.

```
huginn validate --plan <path> [--testbed <path> | --inventory-plugin <name>]
                [--tags <tags>] [--exclude-tags <tags>] [--scenario <ids>] [--phase <ids>]
                [--test-case-group <ids>] [--test-id <ids>] [--test-id-pattern <regex>]
                [logging options]
```

| Option               | Short | Env var                   | Default          | Description                                                                                                                |
| -------------------- | ----- | ------------------------- | ---------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `--plan`             | `-p`  | `HUGINN_PLAN`             | (required)       | Path to test plan YAML file or directory of YAML files to validate.                                                        |
| `--testbed`          | `-t`  | `HUGINN_TESTBED`          | `./testbed.yaml` | Path to testbed YAML file defining device inventory. Mutually exclusive with `--inventory-plugin`.                         |
| `--inventory-plugin` | `-i`  | `HUGINN_INVENTORY_PLUGIN` | none             | Use an inventory plugin instead of a static testbed YAML file. Mutually exclusive with `--testbed`.                        |
| `--tags`             |       | `HUGINN_TAGS`             | none             | Validate only test cases that have every listed tag. Repeatable, comma-separated.                                          |
| `--exclude-tags`     |       | `HUGINN_EXCLUDE_TAGS`     | none             | Skip test cases that have any listed tag. Repeatable, comma-separated.                                                     |
| `--scenario`         |       | `HUGINN_SCENARIO`         | none             | Validate only the listed scenarios. Repeatable, comma-separated.                                                           |
| `--phase`            |       | `HUGINN_PHASE`            | none             | Validate only the listed phases. Requires `--scenario`. Repeatable, comma-separated.                                       |
| `--test-case-group`  |       | `HUGINN_TEST_CASE_GROUP`  | none             | Validate only the listed test case groups. Repeatable, comma-separated.                                                    |
| `--test-id`          |       | `HUGINN_TEST_ID`          | none             | Validate only the listed test case IDs. Repeatable, comma-separated.                                                       |
| `--test-id-pattern`  |       | `HUGINN_TEST_ID_PATTERN`  | none             | Python regular expression matched anywhere in the test case ID.                                                            |
| `--data-model`       | `-d`  | `HUGINN_DATA_MODEL`       | none             | Data model directory. Overrides the test plan's `data_model.path`. A relative path resolves against the working directory. |
| logging options      |       |                           |                  | See [Logging options](#logging-options).                                                                                   |

The filters behave exactly as they do for [`run`](#filtering), including the rule that `--phase` requires `--scenario`. The validation result is written under `./results/`; `validate` has no `--results-dir` option.

```bash
huginn validate -p test_plan/ -t testbed.yaml
huginn validate -p test_plan/ -t testbed.yaml --scenario link-shutdown-r1r2 --phase pre-change
```

### Exit codes

| Code | Meaning                                                                                           |
| ---- | ------------------------------------------------------------------------------------------------- |
| 0    | Validation passed. Warnings, if any, are printed but do not change the exit code.                 |
| 3    | Validation failed, including when the testbed, inventory plugin or test plan could not be loaded. |

An invalid `--test-id-pattern` regular expression currently ends validation with a Python traceback and exit code 1.

## execute

Run ad-hoc commands on testbed devices and print the raw output. Single-command mode takes `--device` and `--command` together. Batch mode takes `--commands` with a YAML file and cannot be combined with `--device` or `--command`.

```
huginn execute --testbed <path> --device <name> --command <command> [--broker <ssh|http|netconf>] [--no-prompt] [logging options]
huginn execute --testbed <path> --commands <path> [--no-prompt] [logging options]
```

| Option          | Short | Env var          | Default    | Description                                                               |
| --------------- | ----- | ---------------- | ---------- | ------------------------------------------------------------------------- |
| `--testbed`     | `-t`  | `HUGINN_TESTBED` | (required) | Path to testbed YAML file defining device inventory.                      |
| `--device`      |       |                  | none       | Device name from the testbed. Requires `--command`.                       |
| `--command`     | `-c`  |                  | none       | Command string or API path to execute on the device. Requires `--device`. |
| `--commands`    |       |                  | none       | Path to a YAML file defining batch command executions.                    |
| `--broker`      | `-b`  |                  | `ssh`      | Broker type for single-command mode: `ssh`, `http` or `netconf`.          |
| `--no-prompt`   |       |                  | off        | Hide the simulated device prompt line above command output.               |
| logging options |       |                  |            | See [Logging options](#logging-options).                                  |

`execute` requires a static testbed file; it does not accept `--inventory-plugin`.

```bash
huginn execute -t testbed.yaml --device spine-01 -c "show version"
huginn execute -t testbed.yaml --device ctrl-01 -c "/api/v1/status" -b http
huginn execute -t testbed.yaml --commands commands.yaml
```

### Batch file format

The `--commands` file is a YAML list. Each entry needs `device` and either `command` or `path` (an alias that reads better for HTTP and NETCONF). `broker` is optional and defaults to `ssh`; `--broker` does not apply in batch mode.

```yaml
- device: spine-01
  command: show version
- device: spine-01
  command: show ip bgp summary
- device: ctrl-01
  path: /api/v1/status
  broker: http
```

### Exit codes

| Code | Meaning                                                                                       |
| ---- | --------------------------------------------------------------------------------------------- |
| 0    | Every command succeeded.                                                                      |
| 1    | At least one command returned an error, or the testbed or batch file could not be loaded.     |
| 2    | Usage error, such as `--device` without `--command` or `--commands` combined with `--device`. |

## inject new

Create a new test case group from job files. `inject new` discovers the job files in `PATH`, adds a test case for each one with an allocated ID, creates a group containing them, and wires the group into the plan through `--phase`, `--parent-group`, or both. At least one of the two is required.

```
huginn inject new <PATH> (--phase <ids> | --parent-group <id>) [--plan <dir>] [--group <id>]
                  [--target-groups <groups>] [--tags <tags>] [--id-style <style>] [--dry-run]
```

| Argument | Description                                    |
| -------- | ---------------------------------------------- |
| `PATH`   | Directory of job files or a single `.py` file. |

| Option            | Short | Env var       | Default           | Description                                                                                                       |
| ----------------- | ----- | ------------- | ----------------- | ----------------------------------------------------------------------------------------------------------------- |
| `--phase`         |       |               | none              | Phase(s) to add the new group to, in every scenario that has a phase with that name. Repeatable, comma-separated. |
| `--parent-group`  |       |               | none              | Existing composite group to nest the new group under, through its `groups` list.                                  |
| `--plan`          | `-p`  | `HUGINN_PLAN` | `./test_plan`     | Path to the test plan directory. Must be a directory.                                                             |
| `--group`         |       |               | derived from path | Explicit group identifier.                                                                                        |
| `--target-groups` |       |               | none              | Device groups to set as `target.groups` on each new test case. Repeatable, comma-separated.                       |
| `--tags`          |       |               | none              | Tags to set on each new test case. Repeatable, comma-separated.                                                   |
| `--id-style`      |       |               | `prefix-counter`  | ID generation style. `prefix-counter` is the only style implemented; other values are accepted but ignored.       |
| `--dry-run`       |       |               | off               | Print the planned changes without writing any files.                                                              |

### How IDs and names are derived

Paths are resolved relative to the parent directory of the test plan directory. The ID prefix comes from the job directory path with a leading `jobs/` removed, upper-cased, and with `_` and `/` turned into `-`. For `jobs/iosxe/cdp_global/`, the prefix is `IOSXE-CDP-GLOBAL`, new test cases are numbered `IOSXE-CDP-GLOBAL-1`, `IOSXE-CDP-GLOBAL-2` and so on after the highest existing counter, and the default group ID is `iosxe-cdp-global`.

When `PATH` is a directory, every `.py` file directly inside it is a job, except files whose names start with `_`. Jobs whose path is already referenced by a test case in the plan are skipped.

The command writes test cases to `test_cases/<group>.yaml`, the group to `groups/<group>.yaml`, and phase references to `scenarios.yaml` under the plan directory.

```bash
huginn inject new jobs/iosxe/cdp_global/ --phase pre-change
huginn inject new jobs/iosxe/vrf/ --parent-group state-baseline --target-groups core,edge
huginn inject new jobs/iosxe/bgp/ --parent-group state-baseline --dry-run
```

### Exit codes

| Code | Meaning                                                                                                                                                                                       |
| ---- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0    | Test cases were injected, the dry run completed, or every job was already in the plan.                                                                                                        |
| 1    | Neither `--phase` nor `--parent-group` was given; the test plan could not be loaded; no job files were found; a job could not be loaded; or the parent group or scenarios file was not found. |

## inject into

Add job files to an existing test case group. `inject into` discovers the job files in `PATH`, adds a test case for each one with an allocated ID, and appends the new IDs to the `tests` list of `GROUP`.

```
huginn inject into <GROUP> <PATH> [--plan <dir>] [--target-groups <groups>] [--tags <tags>] [--id-style <style>] [--dry-run]
```

| Argument | Description                                    |
| -------- | ---------------------------------------------- |
| `GROUP`  | Existing group identifier to inject into.      |
| `PATH`   | Directory of job files or a single `.py` file. |

| Option            | Short | Env var       | Default          | Description                                                                                                 |
| ----------------- | ----- | ------------- | ---------------- | ----------------------------------------------------------------------------------------------------------- |
| `--plan`          | `-p`  | `HUGINN_PLAN` | `./test_plan`    | Path to the test plan directory. Must be a directory.                                                       |
| `--target-groups` |       |               | none             | Device groups to set as `target.groups` on each new test case. Repeatable, comma-separated.                 |
| `--tags`          |       |               | none             | Tags to set on each new test case. Repeatable, comma-separated.                                             |
| `--id-style`      |       |               | `prefix-counter` | ID generation style. `prefix-counter` is the only style implemented; other values are accepted but ignored. |
| `--dry-run`       |       |               | off              | Print the planned changes without writing any files.                                                        |

IDs are derived from `PATH` as described for [`inject new`](#how-ids-and-names-are-derived). The group must be defined in a file under the plan's `groups/` directory.

```bash
huginn inject into cdp-global-baseline jobs/iosxe/cdp_global/
huginn inject into iosxe-vrf-detail jobs/iosxe/vrf_detail/verify_vrf_route_targets.py
```

### Exit codes

| Code | Meaning                                                                                                          |
| ---- | ---------------------------------------------------------------------------------------------------------------- |
| 0    | Test cases were injected, the dry run completed, or every job was already in the plan.                           |
| 1    | The test plan could not be loaded, `GROUP` was not found, no job files were found, or a job could not be loaded. |

## reconcile

Create post-change variants of the test cases that failed in a phase of the latest testing run.

```
huginn reconcile --plan <path> --phase <phase-name> [--scenario <scenario-id>] [--results-dir <path>] [--parameters-dir <path>] [logging options]
```

`--plan`/`-p` and `--phase` are required. `--plan` reads `HUGINN_PLAN`, `--phase` reads `HUGINN_PHASE`, `--scenario` reads `HUGINN_SCENARIO`, `--results-dir` reads `HUGINN_RESULTS_DIR`, and `--parameters-dir` reads `HUGINN_PARAMETERS_DIR`. Unlike `run`, `--phase` and `--scenario` take a single value each. The command exits 0 on success or when there is nothing to reconcile, and 1 when reconciliation cannot proceed.

See [Parameter Reconciliation](reconcile.md) for the full option table, exit codes and workflow.

## relearn

Re-learn parameters for the tests that failed or errored in the latest testing run, in the exact scenario and phase where each one failed.

```
huginn relearn [--plan <path>] [--testbed <path> | --inventory-plugin <name>] [--scenario <id>] [--phase <id>]
               [--results-dir <path>] [--parameters-dir <path>] [--output-dir <path>] [logging options]
```

The options match those of `run` with the same names and environment variables, including the `./test_plan` and `./testbed.yaml` defaults. `--scenario` and `--phase` take a single value each and filter the failures to re-learn; `--phase` does not require `--scenario`. `--data-model`/`-d` overrides the test plan's `data_model.path`, as for `run`. The command exits 0 when every test is re-learned or there are no failures, 1 when a test fails during re-learning, and 2 in the same run-level error cases as `run`.

See [Selective Re-learning](relearn.md) for the full option table, exit codes and workflow.

## prune

Remove non-applicable tests and device targets from the test plan, based on the latest learning run.

```
huginn prune --plan <path> [--results-dir <path>] [--dry-run] [--remove-orphans] [logging options]
```

`--plan`/`-p` is required and reads `HUGINN_PLAN`; `--results-dir` reads `HUGINN_RESULTS_DIR`. `--dry-run` and `--remove-orphans` have no environment variable. The command exits 0 on success or when there is nothing to prune, and 1 when the results or test plan cannot be read or the pruned plan fails validation.

See [Pruning Non-Applicable Tests](prune.md) for the full option table and the changes each option makes.

## version

Print the installed Huginn version and exit 0. `version` takes no options.

```bash
huginn version
```

```
huginn v0.2.0
```

## Completion

The top-level `huginn` command has two options for shell completion. Both detect the current shell.

| Option                 | Short | Env var | Default | Description                                                                 |
| ---------------------- | ----- | ------- | ------- | --------------------------------------------------------------------------- |
| `--install-completion` |       |         | off     | Install completion for the current shell.                                   |
| `--show-completion`    |       |         | off     | Print the completion script for the current shell, to copy or customize it. |

```bash
huginn --install-completion
```

Restart the shell after installing for completion to take effect.

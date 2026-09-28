# Configuration

This page describes how Huginn picks up its settings: command-line flags, `HUGINN_*` environment variables, and project defaults in the `[tool.huginn]` table of `pyproject.toml`. For the full option list of each command, see the [CLI Reference](cli.md).

## Overview

Huginn has three configuration sources:

- **Command-line flags**, such as `--plan` or `--results-dir`, for a single invocation.
- **`HUGINN_*` environment variables**, such as `HUGINN_PLAN`, for a shell session or CI job.
- **`[tool.huginn]` in `pyproject.toml`**, for defaults that belong to the repository: where the test plan, testbed and output directories live, logging, and which plugins are active.

A CLI flag overrides its environment variable, which overrides the `[tool.huginn]` key, which overrides the built-in default. See [Precedence](#precedence).

Execution behavior is not configured here. Concurrency comes from the `strategy` of each group or phase in the [test plan](test-plan.md#group-execution-strategy), and connection timeouts and transport options come from each connection in the [testbed](testbed.md#connection-types).

## Project defaults in `[tool.huginn]`

A repository can store its paths and logging settings in `[tool.huginn]`, so you don't have to pass `-p` and `-t` on every command:

```toml
[tool.huginn]
test_plan = "test_plan"
testbed = "inventory/lab.yaml"
parameters_dir = "state/parameters"
results_dir = "state/results"
output_dir = "state/artifacts"
log_file = "logs/huginn.log"
log_level = "INFO"
```

With this table in place, `huginn run -m testing` uses the plan, testbed and directories above.

### Supported keys

Each key sets the default for one CLI option. A command uses a key only if it has that option.

| Key                | CLI option              | Commands                                                              |
| ------------------ | ----------------------- | --------------------------------------------------------------------- |
| `test_plan`        | `-p/--plan`             | `run`, `validate`, `relearn`, `reconcile`, `prune`, `inject new/into` |
| `testbed`          | `-t/--testbed`          | `run`, `validate`, `relearn`, `execute`                               |
| `inventory_plugin` | `-i/--inventory-plugin` | `run`, `validate`, `relearn`                                          |
| `parameters_dir`   | `--parameters-dir`      | `run`, `relearn`, `reconcile`                                         |
| `results_dir`      | `--results-dir`         | `run`, `relearn`, `reconcile`, `prune`                                |
| `output_dir`       | `--output-dir`          | `run`, `relearn`                                                      |
| `log_file`         | `--log-file`            | `run`, `validate`, `relearn`, `reconcile`, `prune`, `execute`         |
| `log_level`        | `--log-level`           | `run`, `validate`, `relearn`, `reconcile`, `prune`, `execute`         |

Every value is a string. `log_level` must be one of `DEBUG`, `INFO`, `WARNING` or `ERROR`, in any case. `mode` is not supported, because a `learning` default would silently overwrite baselines.

There is no key for the data model. Set `data_model.path` in the [test plan](test-plan.md#data-model), or pass `--data-model` on the command line.

### Precedence

For each option, the first of these that is set wins:

1. The CLI flag
2. The `HUGINN_*` environment variable, for example `HUGINN_PLAN` or `HUGINN_RESULTS_DIR`
3. The key in `[tool.huginn]`
4. The built-in default, for example `./test_plan` or `./results/`

`huginn <command> --help` marks each default that comes from `pyproject.toml`, for example `[default: (state/results from pyproject.toml)]`.

### Discovery and path resolution

Huginn reads `pyproject.toml` from the current working directory only. It doesn't search parent directories, and there is no option to point at a different file. If the file or its `[tool.huginn]` table is missing, only the built-in defaults apply.

Relative paths resolve against the directory that contains `pyproject.toml`, which is the current working directory. Absolute paths are used as written.

### Testbed and inventory plugin

`testbed` and `inventory_plugin` are mutually exclusive, the same as `--testbed` and `--inventory-plugin`:

- Setting both keys in `[tool.huginn]` is an error.
- If you pass one on the CLI or through its environment variable, it overrides the other key from `[tool.huginn]` for that run. For example, `huginn run -m testing -i file:inventory/staging.yaml` ignores a `testbed` key.
- Passing both on the CLI, or one on the CLI and the other through its environment variable, is a usage error.

`inventory_plugin` takes the same `<plugin>:<config>` value as `--inventory-plugin`. The built-in `file` plugin loads a testbed file, for example `file:inventory/lab.yaml`. Other plugin names are looked up in the `huginn.inventory` entry point group, and the text after the colon is passed to the plugin as its configuration.

### Errors

Huginn validates `[tool.huginn]` before running any command except `version`. The command prints the error and exits with code 1 if:

- `pyproject.toml` is not valid TOML
- `[tool.huginn]` or `[tool.huginn.plugins]` is not a table
- the table has a key that is not in the table above or `plugins`, for example `mode`, `parallel_tests` or `hooks`
- a value is not a non-empty string
- `log_level` is outside the accepted levels
- both `testbed` and `inventory_plugin` are set

For example, a leftover `mode` key fails with:

```txt
ERROR: Unknown key(s) in [tool.huginn]: mode
```

`[tool.huginn.plugins]` is validated in the same way. The command also fails if:

- the plugins table has a key other than `brokers`, `reporters`, `hooks` or `config`
- `brokers`, `reporters` or `hooks` is not a list of non-empty strings
- `config` is not a table, or a value inside it is not a table

An `enabled` key, from older documentation, fails with a hint to use the current keys:

```txt
ERROR: Unknown key(s) in [tool.huginn.plugins]: enabled. Use 'brokers', 'reporters' or 'hooks' instead of 'enabled'.
```

## Plugins in `[tool.huginn.plugins]`

Huginn discovers plugins through Python entry points. `[tool.huginn.plugins]` limits which discovered plugins are active and passes options to them:

```toml
[tool.huginn.plugins]
brokers = ["ssh", "netconf"]
reporters = ["html"]
hooks = []
```

| Key         | Type            | When absent               | Description                                                                                          |
| ----------- | --------------- | ------------------------- | ---------------------------------------------------------------------------------------------------- |
| `brokers`   | list of strings | Every discovered broker   | Connection brokers a run may use. Requiring a broker that is installed but not listed fails the run. |
| `reporters` | list of strings | Every discovered reporter | Reporters that run after `run` and `relearn`. An empty list disables reporting.                      |
| `hooks`     | list of strings | Every discovered hook     | Hook plugins to activate. Not used until hooks are dispatched; see [Hooks](#hooks).                  |
| `config`    | table of tables | No options                | Per-plugin options, one sub-table per plugin name, for example `[tool.huginn.plugins.config.html]`.  |

Each name matches an entry point name, not a package name. `run` and `relearn` resolve brokers and reporters through this table. `validate` resolves only the built-in `file` inventory plugin, and `execute` uses the built-in brokers directly.

### Built-in plugins

Huginn registers these entry points itself:

| Group              | Name      | Plugin                                                  |
| ------------------ | --------- | ------------------------------------------------------- |
| `huginn.brokers`   | `ssh`     | SSH broker for CLI commands                             |
| `huginn.brokers`   | `http`    | HTTP broker for REST APIs                               |
| `huginn.brokers`   | `netconf` | NETCONF broker                                          |
| `huginn.inventory` | `file`    | Loads a testbed YAML file                               |
| `huginn.reporters` | `html`    | HTML dashboard written under `reports/`, with `latest/` |

An installed package adds plugins by registering entry points in the same groups. See [Connection Broker - Plugin Discovery](../design/connection-broker.md#plugin-discovery) for how brokers are resolved.

### Plugin options

`config.<name>` holds options for the plugin whose entry point is `<name>`:

```toml
[tool.huginn.plugins.config.html]
title = "DC1 lab"
```

Huginn passes the table to the plugin unchanged. A reporter receives it as the `config` argument of `generate_report()`. Hook plugins are not loaded yet; see [Hooks](#hooks). The plugin decides which options it reads. The built-in `html` reporter reads no options, so a `config.html` table is accepted but has no effect today.

Inventory plugins do not read `config.<name>`. They take their configuration from the text after the colon in `--inventory-plugin` or `inventory_plugin`.

## Hooks

A hook plugin is a class that implements the `HookPlugin` protocol from `huginn.hooks`: a `name`, a `subscriptions()` method that returns the lifecycle events it listens to, and an async `on_event(event, context)` method. Hook plugins are registered in the `huginn.hooks` entry point group:

```toml
# pyproject.toml of the package that provides the hook
[project.entry-points."huginn.hooks"]
change-window = "acme_hooks.change_window:ChangeWindowHook"
```

A project selects hook plugins with `hooks` under `[tool.huginn.plugins]` and passes them options with `config.<name>`:

```toml
[tool.huginn.plugins]
hooks = ["change-window"]

[tool.huginn.plugins.config.change-window]
calendar = "network-changes"
```

The runner does not load or dispatch hook plugins yet, so an installed hook plugin is never called during a run, whatever `hooks` lists. Wiring hooks into the runner is tracked in [#210](https://github.com/ChartinoLabs/Huginn/issues/210).

## Environment variables

Every `HUGINN_*` variable sets the CLI option of the same name on each command that has it. A flag given on the command line takes precedence over its variable, and the variable takes precedence over `[tool.huginn]`.

| Variable                  | CLI option              | Commands                                                                        |
| ------------------------- | ----------------------- | ------------------------------------------------------------------------------- |
| `HUGINN_MODE`             | `-m/--mode`             | `run`                                                                           |
| `HUGINN_PLAN`             | `-p/--plan`             | `run`, `validate`, `relearn`, `reconcile`, `prune`, `inject new`, `inject into` |
| `HUGINN_TESTBED`          | `-t/--testbed`          | `run`, `validate`, `relearn`, `execute`                                         |
| `HUGINN_INVENTORY_PLUGIN` | `-i/--inventory-plugin` | `run`, `validate`, `relearn`                                                    |
| `HUGINN_DATA_MODEL`       | `-d/--data-model`       | `run`, `validate`, `relearn`                                                    |
| `HUGINN_TAGS`             | `--tags`                | `run`, `validate`                                                               |
| `HUGINN_EXCLUDE_TAGS`     | `--exclude-tags`        | `run`, `validate`                                                               |
| `HUGINN_SCENARIO`         | `--scenario`            | `run`, `validate`, `relearn`, `reconcile`                                       |
| `HUGINN_PHASE`            | `--phase`               | `run`, `validate`, `relearn`, `reconcile`                                       |
| `HUGINN_TEST_CASE_GROUP`  | `--test-case-group`     | `run`, `validate`                                                               |
| `HUGINN_TEST_ID`          | `--test-id`             | `run`, `validate`                                                               |
| `HUGINN_TEST_ID_PATTERN`  | `--test-id-pattern`     | `run`, `validate`                                                               |
| `HUGINN_RESULTS_DIR`      | `--results-dir`         | `run`, `relearn`, `reconcile`, `prune`                                          |
| `HUGINN_PARAMETERS_DIR`   | `--parameters-dir`      | `run`, `relearn`, `reconcile`                                                   |
| `HUGINN_OUTPUT_DIR`       | `--output-dir`          | `run`, `relearn`                                                                |
| `HUGINN_DEBUG`            | `--debug`               | `run`, `validate`, `relearn`, `reconcile`, `prune`, `execute`                   |
| `HUGINN_LOG_LEVEL`        | `--log-level`           | `run`, `validate`, `relearn`, `reconcile`, `prune`, `execute`                   |
| `HUGINN_SHOW_LOGS`        | `--show-logs`           | `run`, `validate`, `relearn`, `reconcile`, `prune`, `execute`                   |
| `HUGINN_LOG_FILE`         | `--log-file`            | `run`, `validate`, `relearn`, `reconcile`, `prune`, `execute`                   |

See [CLI Reference - Environment variables](cli.md#environment-variables) for how boolean and repeatable values are written.

## CLI overrides

Any flag overrides the environment and `[tool.huginn]` for one invocation. With the [Complete Example](#complete-example) below in place:

```bash
# Run a different plan against the staging testbed
huginn run -m testing -p plans/smoke/ -t inventory/staging.yaml

# Load the testbed through the file inventory plugin instead of the testbed key
huginn run -m testing -i file:inventory/staging.yaml

# Log at DEBUG for one learning run
huginn run -m learning --log-level DEBUG

# Use a different data model directory than the plan's data_model.path
huginn run -m testing -d nac/staging/

# Keep this run's results apart from the configured results_dir
HUGINN_RESULTS_DIR=/var/tmp/huginn-results huginn run -m testing

# Validate the plan against the staging testbed before a run
huginn validate -t inventory/staging.yaml
```

## Complete Example

```toml
# pyproject.toml

[project]
name = "dc1-network-tests"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "huginn-framework",
]

[tool.huginn]
test_plan = "plans/full-validation/"
testbed = "inventory/production.yaml"
parameters_dir = "state/parameters"
results_dir = "state/results"
output_dir = "state/artifacts"
log_file = "logs/huginn.log"
log_level = "INFO"

[tool.huginn.plugins]
brokers = ["ssh", "netconf"]
reporters = ["html"]
```

From the project root, `huginn run -m testing` then runs `plans/full-validation/` against `inventory/production.yaml`, reads parameters from `state/parameters/`, writes results under `state/results/`, and logs to `logs/huginn.log`. Only the SSH and NETCONF brokers are available, and the HTML report is written under `reports/`.

## Related Documents

- [CLI Reference](cli.md): Every command, option and environment variable
- [Test Plan Specification](test-plan.md): Test plan format, including the `data_model` section
- [Testbed Specification](testbed.md): Devices, credentials and connection options
- [Connection Broker Plugin Architecture](../design/connection-broker.md): How brokers are discovered and resolved

# Configuration

This document describes Huginn's configuration system, using `pyproject.toml` as the primary configuration file.

## Overview

Huginn follows modern Python conventions by storing configuration in `pyproject.toml`. This eliminates the need for separate configuration files and keeps all project settings in one place.

Configuration is hierarchical:

1. **Built-in defaults**: Sensible defaults for all settings
2. **pyproject.toml**: Project-level overrides
3. **CLI arguments**: Runtime overrides

## pyproject.toml Schema

```toml
[tool.huginn]
# Test execution settings
testbed = "testbed.yaml"           # Default testbed file
test_plan = "test_plan.yaml"       # Default test plan file
mode = "testing"                   # Default mode: "learning" or "testing"

# Inventory plugin (alternative to static testbed YAML)
inventory_plugin = ""              # Plugin name (e.g., "huginn-netbox")

# Output paths
parameters_dir = "parameters"      # Learned parameters directory
reports_dir = "reports"            # Validation report directory
logs_dir = "logs"                  # Log files directory

# Execution settings
parallel_tests = true              # Run tests in parallel within test case groups
max_parallel_tests = 10            # Maximum concurrent test executions
fail_fast = false                  # Stop on first test case group failure

# Timeouts (in seconds)
connection_timeout = 30            # Device connection timeout
command_timeout = 60               # Command execution timeout
test_timeout = 300                 # Overall test timeout

# Logging
log_level = "INFO"                 # DEBUG, INFO, WARNING, ERROR
log_to_file = true                 # Write logs to file
log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# Reporting
report_format = "json"             # Report output format (JSON is the current built-in format)
include_command_output = true      # Include raw command output in reports
include_parsed_data = true         # Include parsed data in reports

[tool.huginn.connections]
# Default connection settings
default_transport = "asyncssh"     # SSH transport: asyncssh, ssh2
auth_strict_key = false            # SSH host key verification
default_port = 22                  # Default SSH port

[tool.huginn.connections.rest]
# Default REST API settings
verify_ssl = true                  # SSL certificate verification
timeout = 30                       # Request timeout

[tool.huginn.hooks]
# Lifecycle hooks (Python entry points)
pre_run = ""                       # Before test run starts
post_run = ""                      # After test run completes
pre_phase = ""                     # Before each phase
post_phase = ""                    # After each phase
pre_test_case_group = ""           # Before each test case group
post_test_case_group = ""          # After each test case group
pre_test = ""                      # Before each test
post_test = ""                     # After each test
on_failure = ""                    # When a test fails
on_error = ""                      # When a test errors

[tool.huginn.plugins]
# Plugin configuration
enabled = []                       # List of enabled plugins
# Plugin-specific settings can be added as sub-tables
```

## Configuration Sections

### Core Settings

```toml
[tool.huginn]
testbed = "testbed.yaml"
test_plan = "test_plan.yaml"
mode = "testing"
```

| Setting     | Type   | Default            | Description                                     |
| ----------- | ------ | ------------------ | ----------------------------------------------- |
| `testbed`   | string | `"testbed.yaml"`   | Path to testbed file (relative to project root) |
| `test_plan` | string | `"test_plan.yaml"` | Path to test plan file                          |
| `mode`      | string | `"testing"`        | Default execution mode: `learning` or `testing` |

### Inventory Plugins

```toml
[tool.huginn]
inventory_plugin = "huginn-netbox"
```

| Setting            | Type   | Default | Description                                        |
| ------------------ | ------ | ------- | -------------------------------------------------- |
| `inventory_plugin` | string | `""`    | Inventory plugin to use (empty = use testbed file) |

Inventory plugins load device inventory from external sources (NetBox, IPAM systems, CSV files, etc.) instead of relying solely on a static YAML testbed.

**Behavior:**

- If `inventory_plugin` is empty, the framework uses the `testbed` YAML file
- If `inventory_plugin` is set, the plugin replaces the testbed file entirely

**Plugin Configuration:**

Each inventory plugin has its own configuration section:

```toml
[tool.huginn.plugins.huginn-netbox]
url = "https://netbox.example.com"
token = "${NETBOX_API_TOKEN}"
site = "dc1"
status = "active"
```

See [Architecture - Inventory Plugins](02-architecture.md#inventory-plugins) for plugin development details.

### Output Paths

```toml
[tool.huginn]
parameters_dir = "parameters"
reports_dir = "reports"
logs_dir = "logs"
```

| Setting          | Type   | Default        | Description                           |
| ---------------- | ------ | -------------- | ------------------------------------- |
| `parameters_dir` | string | `"parameters"` | Directory for learned parameter files |
| `reports_dir`    | string | `"reports"`    | Directory for validation reports      |
| `logs_dir`       | string | `"logs"`       | Directory for log files               |

Paths are relative to the project root (directory containing `pyproject.toml`).

Validation artifacts are written under `reports/`. Run artifacts are written under
`results/<timestamp>-<mode>/`, with one `run.json` file for the run and one
`result.json` file per test case.

### Execution Settings

```toml
[tool.huginn]
parallel_tests = true
max_parallel_tests = 10
fail_fast = false
```

| Setting              | Type | Default | Description                                        |
| -------------------- | ---- | ------- | -------------------------------------------------- |
| `parallel_tests`     | bool | `true`  | Execute tests within a test case group in parallel |
| `max_parallel_tests` | int  | `10`    | Maximum concurrent test executions                 |
| `fail_fast`          | bool | `false` | Stop execution on first test case group failure    |

When `fail_fast` is `true`, the framework stops after any test case group fails. Dependent test case groups are still marked as blocked, but independent test case groups are not executed.

### Timeouts

```toml
[tool.huginn]
connection_timeout = 30
command_timeout = 60
test_timeout = 300
```

| Setting              | Type | Default | Description                               |
| -------------------- | ---- | ------- | ----------------------------------------- |
| `connection_timeout` | int  | `30`    | Seconds to wait for device connection     |
| `command_timeout`    | int  | `60`    | Seconds to wait for command response      |
| `test_timeout`       | int  | `300`   | Maximum seconds for entire test execution |

Timeouts can be overridden per-device in the testbed file.

### Logging

```toml
[tool.huginn]
log_level = "INFO"
log_to_file = true
log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
```

| Setting       | Type   | Default     | Description                                    |
| ------------- | ------ | ----------- | ---------------------------------------------- |
| `log_level`   | string | `"INFO"`    | Minimum log level: DEBUG, INFO, WARNING, ERROR |
| `log_to_file` | bool   | `true`      | Write logs to file in `logs_dir`               |
| `log_format`  | string | (see above) | Python logging format string                   |

### Reporting

```toml
[tool.huginn]
report_format = "json"
include_command_output = true
include_parsed_data = true
```

| Setting                  | Type   | Default  | Description                                    |
| ------------------------ | ------ | -------- | ---------------------------------------------- |
| `report_format`          | string | `"json"` | Primary report format; JSON is the current built-in format |
| `include_command_output` | bool   | `true`   | Include raw command output in reports          |
| `include_parsed_data`    | bool   | `true`   | Include parsed/structured data in reports      |

Current builds default to JSON output. Additional report formats can be added via
report plugins as support is implemented:

```toml
report_format = "json"
```

### Connection Defaults

```toml
[tool.huginn.connections]
default_transport = "asyncssh"
auth_strict_key = false
default_port = 22

[tool.huginn.connections.rest]
verify_ssl = true
timeout = 30
```

These provide defaults for device connections. Per-device settings in the testbed override these.

| Setting             | Type   | Default      | Description                           |
| ------------------- | ------ | ------------ | ------------------------------------- |
| `default_transport` | string | `"asyncssh"` | SSH transport library                 |
| `auth_strict_key`   | bool   | `false`      | Require known SSH host keys           |
| `default_port`      | int    | `22`         | Default SSH port                      |
| `rest.verify_ssl`   | bool   | `true`       | Verify SSL certificates for REST APIs |
| `rest.timeout`      | int    | `30`         | REST API request timeout              |

### Hooks

```toml
[tool.huginn.hooks]
pre_run = "myproject.hooks:before_run"
post_run = "myproject.hooks:after_run"
on_failure = "myproject.hooks:notify_failure"
```

Hooks are Python entry points in the format `module.path:function_name`. They're called at specific lifecycle points.

| Hook                   | When Called                 | Arguments                          |
| ---------------------- | --------------------------- | ---------------------------------- |
| `pre_run`              | Before test run starts      | `(config, test_plan, testbed)`     |
| `post_run`             | After test run completes    | `(config, results)`                |
| `pre_phase`            | Before each phase           | `(phase_name, phase_config)`       |
| `post_phase`           | After each phase            | `(phase_name, phase_results)`      |
| `pre_test_case_group`  | Before each test case group | `(group_name, group_config)`       |
| `post_test_case_group` | After each test case group  | `(group_name, group_results)`      |
| `pre_test`             | Before each test            | `(test_id, context)`               |
| `post_test`            | After each test             | `(test_id, context, results)`      |
| `on_failure`           | When a test fails           | `(test_id, context, failure_info)` |
| `on_error`             | When a test errors          | `(test_id, context, error)`        |

Example hook implementation:

```python
# myproject/hooks.py

def before_run(config, test_plan, testbed):
    """Called before test execution begins."""
    print(f"Starting test run with {len(testbed.devices)} devices")

def notify_failure(test_id, context, failure_info):
    """Called when a test fails."""
    # Send Slack notification, create Jira ticket, etc.
    send_slack_message(f"Test {test_id} failed: {failure_info}")
```

### Plugins

```toml
[tool.huginn.plugins]
enabled = ["huginn-netconf", "huginn-slack-reporter"]

[tool.huginn.plugins.huginn-slack-reporter]
webhook_url = "https://hooks.slack.com/..."
channel = "#network-automation"
```

Plugins extend Huginn's functionality. They're discovered via Python entry points and configured here.

## Complete Example

```toml
# pyproject.toml

[project]
name = "my-network-tests"
version = "1.0.0"
requires-python = ">=3.11"
dependencies = [
    "huginn>=1.0.0",
    "muninn>=1.0.0",  # Parser library
]

[tool.huginn]
# Core settings
testbed = "inventory/production.yaml"
test_plan = "plans/full-validation.yaml"
mode = "testing"

# Paths
parameters_dir = "data/parameters"
reports_dir = "output/reports"
logs_dir = "output/logs"

# Execution
parallel_tests = true
max_parallel_tests = 20
fail_fast = false

# Timeouts
connection_timeout = 45
command_timeout = 120
test_timeout = 600

# Logging
log_level = "INFO"
log_to_file = true

# Reporting
report_format = "json"
include_command_output = true
include_parsed_data = true

[tool.huginn.connections]
default_transport = "asyncssh"
auth_strict_key = false

[tool.huginn.connections.rest]
verify_ssl = false  # Lab environment
timeout = 60

[tool.huginn.hooks]
pre_run = "myproject.hooks:setup_environment"
post_run = "myproject.hooks:generate_summary"
on_failure = "myproject.hooks:notify_team"

[tool.huginn.plugins]
enabled = ["huginn-slack-reporter"]

[tool.huginn.plugins.huginn-slack-reporter]
webhook_url = "${SLACK_WEBHOOK_URL}"
channel = "#network-ops"
notify_on = ["failure", "error"]
```

## CLI Overrides

Configuration can be overridden at runtime:

```bash
# Override testbed and test plan
huginn run --testbed staging.yaml --plan smoke-tests.yaml

# Override mode
huginn run --mode learning

# Override logging
huginn run --log-level DEBUG

# Override parallelism
huginn run --no-parallel
huginn run --max-parallel 5

# Override fail-fast
huginn run --fail-fast

# Override data model path
huginn run --data-model ./nac/data/

# Use inventory plugin
huginn run --inventory-plugin huginn-netbox
```

CLI arguments take precedence over `pyproject.toml` settings.

When `--testbed` is explicitly provided, it takes precedence over `--inventory-plugin` (the plugin is ignored).

## Environment Variables

Certain settings support environment variable expansion:

```toml
[tool.huginn.plugins.huginn-slack-reporter]
webhook_url = "${SLACK_WEBHOOK_URL}"
```

Additionally, some settings can be set via environment variables directly:

| Variable            | Overrides                                            |
| ------------------- | ---------------------------------------------------- |
| `HUGINN_MODE`       | `mode`                                               |
| `HUGINN_LOG_LEVEL`  | `log_level`                                          |
| `HUGINN_TESTBED`    | `testbed`                                            |
| `HUGINN_TEST_PLAN`  | `test_plan`                                          |
| `HUGINN_DATA_MODEL` | `data_model` path (from test plan or pyproject.toml) |

Precedence: CLI > Environment Variables > Test Plan > pyproject.toml > Defaults

## Configuration Discovery

Huginn searches for configuration in this order:

1. Explicit `--config` CLI argument
2. `pyproject.toml` in current directory
3. `pyproject.toml` in parent directories (up to filesystem root)
4. Built-in defaults

The first `pyproject.toml` with a `[tool.huginn]` section is used.

## Validation

Configuration is validated on startup. Invalid settings produce clear error messages:

```txt
Configuration error in pyproject.toml:
  [tool.huginn] mode = "invalid"
  Expected one of: learning, testing
```

## Related Documents

- [Architecture](02-architecture.md): How configuration is loaded and used
- [Test Plan Specification](04-test-plan-spec.md): Test plan file format
- [Testbed Specification](03-testbed-spec.md): Testbed file format

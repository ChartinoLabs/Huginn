# Output and Logging Design

This document describes the design for Huginn's unified output and logging system using the Rich library.

## Implementation Status

| Component                                                                     | Status                               |
| ----------------------------------------------------------------------------- | ------------------------------------ |
| Two-stream separation (console vs logging)                                    | Implemented                          |
| `Output` class with `status()`, `success()`, `warning()`, `error()`           | Implemented                          |
| Logging methods (`log_debug()`, `log_info()`, `log_warning()`, `log_error()`) | Implemented                          |
| Structured field logging (`log_debug_fields()`, `log_info_fields()`, etc.)    | Implemented (beyond original design) |
| Python `logging` hierarchy with `huginn` parent logger                        | Implemented                          |
| File handler (always writes to log file)                                      | Implemented                          |
| `RichHandler` (conditional on `--show-logs`)                                  | Implemented                          |
| CLI flags: `--debug`, `--log-level`, `--show-logs`, `--log-file`              | Implemented                          |
| Dependency injection via `Context` (not a singleton)                          | Implemented                          |
| Progress bars via `Output.progress()`                                         | Not yet implemented                  |
| `Output.result()` for structured result display                               | Not yet implemented                  |
| Rich `Live`/`Layout` for combined progress + log panel                        | Not yet implemented                  |
| `--no-color` CLI flag                                                         | Not yet implemented                  |

## Overview

Huginn separates output into two distinct streams with different purposes and audiences:

1. **Console Output** - The application's user interface
2. **Logging** - Diagnostic trace for troubleshooting

These are parallel streams, not the same thing at different verbosity levels. They serve fundamentally different purposes and can be controlled independently.

## Console Output

**Audience:** End users running the tool

**Purpose:** Progress updates, status messages, and results

**Examples:**

- "Connecting to devices (3/10)..."
- "Test `test_ospf_neighbors` running..."
- "Phase 1 complete: 15/15 passed"
- "All tests passed"

Console output uses Rich for aesthetically pleasing display including:

- Colored status messages (green for success, yellow for warnings, red for errors)
- Progress bars for device connections and test execution (not yet implemented)
- Status spinners for long-running operations (not yet implemented)
- Formatted tables for results summaries (not yet implemented)

## Logging

**Audience:** Developers and test engineers debugging issues

**Purpose:** Detailed execution record for troubleshooting

**Examples:**

- "SSH attempt to 192.168.1.5, retry 2/3, timeout=30s"
- "Executing `show ip ospf neighbor`, response_time=1.2s"
- "Parsing output with pattern X, matched 15 lines"
- "Cache hit for command `show version` on device router-01"

Logging uses Python's standard `logging` module and goes to a file by default. Even INFO-level logs are considered internal detail primarily meant for troubleshooting - users may run tests all day without needing to look at them.

## Default Behavior

```txt
┌─────────────────────────────────────────────────────────────┐
│                     Console (Rich)                          │
│  - Status messages, colored pass/fail indicators            │
│  - Displayed to user via stdout                             │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                     Log File                                │
│  - Detailed diagnostic information                          │
│  - Written to file (e.g., huginn.log)                       │
│  - Not shown to user unless requested                       │
└─────────────────────────────────────────────────────────────┘
```

By default:

- Console output goes to stdout via Rich
- Logs go to file only
- Users see a clean, focused interface

## CLI Options

Log level and log destination are controlled independently:

| Flag                | Effect                                                          |
| ------------------- | --------------------------------------------------------------- |
| `--debug`           | Sets log level to DEBUG (logs still go to file)                 |
| `--log-level=LEVEL` | Sets log level to specified level (DEBUG, INFO, WARNING, ERROR) |
| `--show-logs`       | Streams logs to console in addition to file                     |
| `--log-file=PATH`   | Path to log file (default: `./huginn.log`)                      |

**Examples:**

```bash
# Default: Rich console output, INFO logs to file
huginn run --testbed testbed.yaml --plan test_plan.yaml

# Verbose logging to file, console unchanged
huginn run --debug --testbed testbed.yaml --plan test_plan.yaml

# Show logs in console at INFO level
huginn run --show-logs --testbed testbed.yaml --plan test_plan.yaml

# Show DEBUG logs in console (for deep troubleshooting)
huginn run --show-logs --debug --testbed testbed.yaml --plan test_plan.yaml
```

The `--show-logs` flag is additive - logs always go to file, and the flag additionally streams them to the console (via stderr).

## Console Layout with Logs (Not Yet Implemented)

When `--show-logs` is enabled, logs currently appear interleaved with console output on stderr. A future enhancement would use Rich's `Live` display with a `Layout` to present logs in a separate panel:

```txt
┌─ Progress ────────────────────────────────────────────────────┐
│ Connecting to devices [████████████████────────] 8/10         │
│ Current: Establishing SSH to router-09                        │
└───────────────────────────────────────────────────────────────┘
┌─ Logs ────────────────────────────────────────────────────────┐
│ 14:23:01 INFO  SSH to 192.168.1.5 established                 │
│ 14:23:02 INFO  SSH to 192.168.1.6 established                 │
│ 14:23:03 DEBUG Sending keepalive to router-01                 │
│ 14:23:03 INFO  SSH to 192.168.1.7 established                 │
│ ...                                                           │
└───────────────────────────────────────────────────────────────┘
```

This layout would maintain:

- A fixed progress section at the top
- A scrolling log panel below

The log panel would only appear when `--show-logs` is set, keeping the default view clean.

## Output Class Interface

A unified `Output` class coordinates both streams:

```python
class Output:
    """Coordinate user-facing console output and diagnostic logging."""

    def __init__(
        self,
        *,
        show_logs: bool = False,
        log_level: str = "INFO",
        log_file: Path | None = None,
    ) -> None: ...

    # Console output methods (always displayed)
    def status(self, message: str) -> None:
        """Print a neutral status message to stdout."""
        ...

    def success(self, message: str) -> None:
        """Print a success message to stdout (green)."""
        ...

    def warning(self, message: str) -> None:
        """Print a warning message to stdout (yellow)."""
        ...

    def error(self, message: str) -> None:
        """Print an error message to stderr (red)."""
        ...

    # Logging methods (file by default, console with --show-logs)
    def log_debug(self, message: str, *args: object) -> None: ...
    def log_info(self, message: str, *args: object) -> None: ...
    def log_warning(self, message: str, *args: object) -> None: ...
    def log_error(self, message: str, *args: object) -> None: ...

    # Structured field logging (appends key=value pairs to message)
    def log_debug_fields(self, message: str, **fields: object) -> None: ...
    def log_info_fields(self, message: str, **fields: object) -> None: ...
    def log_warning_fields(self, message: str, **fields: object) -> None: ...
    def log_error_fields(self, message: str, **fields: object) -> None: ...
```

### Not Yet Implemented

The following methods from the original design are not yet implemented:

```python
    def progress(self, description: str, total: int) -> ProgressContext:
        """Create a progress bar context."""
        ...

    def result(self, data: Any) -> None:
        """Display program output/results."""
        ...
```

## Instance Management

The `Output` class is **not** a singleton. Instead, a single instance is created at framework startup and shared via dependency injection through the `Context` object.

**Why not a singleton:**

- Singletons make testing difficult (hard to substitute mocks)
- Global state complicates multiprocessing scenarios
- Dependency injection is more explicit about what a component needs

**How it works:**

```python
# Framework startup (in CLI/runner)
output = Output(
    show_logs=args.show_logs,
    log_level=args.log_level,
    log_file=args.log_file,
)

# Output is attached to Context, passed to all tests
context = Context(
    output=output,
    broker=broker,
    # ... other context fields
)

# Tests access output through context
class MyTest(TestCase):
    async def test(self, context: Context) -> None:
        context.output.status("Checking OSPF neighbors...")
        context.output.log_info("Querying device for OSPF state")
```

This pattern matches `ConnectionBroker` - a single shared instance injected via context rather than global state. All tests share the same `Output` instance, ensuring coordinated access to the console and log file without the downsides of a singleton.

## Logger Integration

Test automation typically creates loggers using the standard pattern:

```python
import logging
logger = logging.getLogger(__name__)  # e.g., "huginn.tests.verify_ospf"

class VerifyOspfNeighbors(TestCase):
    async def test(self, context: Context) -> None:
        logger.info("Querying OSPF neighbor table")
        # ...
```

These loggers automatically route through the `Output` class's handlers via Python's logging hierarchy.

### How It Works

The `Output` class configures handlers on the `huginn` parent logger. Child loggers inherit these handlers:

```python
class Output:
    def _configure_logger(self, *, show_logs: bool, log_level: str) -> None:
        self.logger = logging.getLogger("huginn")
        self.logger.propagate = False
        self.logger.setLevel(getattr(logging, log_level.upper()))

        # Always add file handler
        file_handler = logging.FileHandler(self.log_file, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
        ))
        self.logger.addHandler(file_handler)

        # Conditionally add Rich console handler
        if show_logs:
            from rich.logging import RichHandler
            console_handler = RichHandler(
                console=Console(stderr=True),
                show_time=True,
                show_path=False,
                rich_tracebacks=True,
            )
            self.logger.addHandler(console_handler)
```

### Logger Hierarchy

```txt
huginn                          <- Output configures handlers here
├── huginn.cli                  <- Inherits handlers
├── huginn.runner               <- Inherits handlers
├── huginn.brokers              <- Inherits handlers
└── huginn.tests                <- Inherits handlers
    ├── huginn.tests.verify_ospf
    └── huginn.tests.verify_bgp
```

Any logger created with `logging.getLogger(__name__)` in a module under the `huginn` package automatically inherits the file handler (always) and the Rich console handler (when `--show-logs` is enabled).

### Test Author Experience

Test authors don't need to know about `Output` internals. They use standard Python logging:

```python
import logging
logger = logging.getLogger(__name__)

class VerifyBgpPeers(TestCase):
    async def test(self, context: Context) -> None:
        logger.debug("Starting BGP peer verification")

        for device in context.targets:
            logger.info(f"Checking BGP peers on {device.name}")
            output = await context.broker.execute(device, "show ip bgp summary")
            logger.debug(f"Raw output: {output[:200]}...")

            # Use context.output for user-facing messages
            context.output.status(f"Verified {device.name}: 5 peers established")
```

- `logger.*` calls go to file (and console if `--show-logs`)
- `context.output.*` calls go to Rich console (always)

This separation remains clear: logging for diagnostics, output for user interface.

## Implementation Notes

### Rich Integration

- Use `rich.console.Console` for all console output
- Use `rich.logging.RichHandler` for styled log output when `--show-logs` is enabled
- Rich auto-detects TTY and degrades gracefully for piped output

### Thread Safety

Both Rich's Console and Python's logging are thread-safe, which is important for parallel test execution where multiple tests may emit output concurrently.

### TTY Detection and Graceful Degradation

When stdout is not a TTY (e.g., piped to a file or another process):

- Rich automatically disables colors and animations
- Progress bars degrade to simple text updates (once progress is implemented)

### Structured Logging

For production use cases, consider supporting structured logging (JSON) to the log file while keeping Rich formatting for console display. This enables log aggregation and analysis tools.

```python
# Future consideration
huginn run --log-format=json --log-file=huginn.json
```

## Design Rationale

### Why Separate Streams?

Traditional approaches often conflate logging levels with user output:

- "Use INFO for user messages, DEBUG for internal details"
- This breaks down because a user-facing progress message and a diagnostic log entry can both be INFO-level

By separating the streams entirely:

- Console output is purely for user experience
- Logging is purely for diagnostics
- Each can be controlled independently
- The mental model is cleaner

### Why Rich?

- Provides modern, aesthetically pleasing terminal output
- Handles terminal capabilities detection automatically
- Includes progress bars, tables, syntax highlighting, and more
- Has a `RichHandler` for styled logging output
- Actively maintained and widely used

### Why Additive `--show-logs`?

Logs always go to file because:

- Users may want to review logs after the fact
- Log files can be attached to bug reports
- There's no performance benefit to skipping file writes

The `--show-logs` flag adds console output for real-time visibility during troubleshooting, without removing the persistent log file.

## Related Documents

- [Architecture](../design/architecture.md): Overall framework architecture
- [Configuration](../reference/configuration.md): Configuration file format

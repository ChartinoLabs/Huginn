# Architecture

This page explains how Huginn is put together and why: the modules under `src/huginn/`, the path a run takes through them, and the points where you can extend it. It describes the current implementation. Field-level and flag-level detail lives in the reference pages linked from each section. Work that is planned but not built is tracked in [Future Considerations](future.md) and [Connection Broker - Future](connection-broker.md#future-broker-configuration-and-extraction).

## Component overview

```txt
                        huginn <command>  (cli.py)
                                 │
           ./pyproject.toml ─────┤  project_config.py: [tool.huginn] defaults,
                                 │  [tool.huginn.plugins] ─► PluginRegistry
                                 │                          (plugin_registry.py)
                                 ▼
  ┌──────────────────────────── runner.py: run_test_plan() ───────────────────────────┐
  │                                                                                   │
  │  inventory_plugins.py ─► Testbed       loaders.py ─► TestPlan, data model         │
  │  (testbed file or plugin)              (unknown_keys.py, read_only.py)            │
  │                   │                           │                                   │
  │                   │                           ▼                                   │
  │                   │               plan_filtering.py ─► filtered TestPlan          │
  │                   │                           │                                   │
  │                   │                           ▼                                   │
  │                   │               jobs.py ─► TestCase classes, required brokers   │
  │                   │                           │                                   │
  │                   ▼                           ▼                                   │
  │   run_hooks.py / hooks.py ◄──── scenarios ─► phases ─► groups ─► test cases       │
  │   (HookPlugin events)                                  │                          │
  │                                                        ▼                          │
  │                                       Context (context.py) per test case:         │
  │                                       ResultCollector, ParameterManager,          │
  │                                       RuntimeBroker, data model                   │
  │                                                        │                          │
  │               runtime_broker.py: RuntimeBroker ◄───────┘                          │
  │               (connections, cache, per-device locks)                              │
  │                        │                                                          │
  │                        ▼                                                          │
  │               brokers/ssh.py, brokers/http.py, brokers/netconf.py                 │
  │                                                                                   │
  │  RunResult ─► result_store.py (results/<run>/run.json, result.json)               │
  │            ─► reporter plugins (reporting/html.py ─► reports/<run>/html)          │
  └───────────────────────────────────────────────────────────────────────────────────┘

  Commands that work on results or the plan without running jobs:
  validation.py (validate), reconcile.py, relearn.py (then runner.py), prune.py,
  inject.py, execute.py (ad hoc commands through RuntimeBroker)
```

### CLI and project configuration

`cli.py` defines every command with Typer. Before any command except `version` runs, the app callback `_load_project_defaults` calls `load_project_config` in `project_config.py`, which reads `[tool.huginn]` from `./pyproject.toml` in the current directory only. Its path, logging, inventory and warning keys become Click defaults, which rank below CLI flags and `HUGINN_*` environment variables. It holds no timeout, connection, reporting or data model settings. `[tool.huginn.plugins]` becomes a `PluginConfig` that the command passes to a `PluginRegistry`. There is no framework-wide configuration object: once the CLI has resolved its options, it calls plain functions such as `run_test_plan` and `validate_inputs` with explicit arguments. See [Configuration](../reference/configuration.md) and the [CLI Reference](../reference/cli.md).

### Loaders

`loaders.py` turns YAML into the in-memory models, and fails with `ConfigurationError` on anything it cannot load.

- `load_testbed` expands `${VAR}` and `${VAR:-default}` references in every string of the testbed file before it validates the file, then builds `Testbed`, `Device` and `ConnectionDefinition` objects and merges global and device credentials. Expansion applies to testbed files only, not to test plans or `pyproject.toml`. See [Testbed Specification](../reference/testbed.md).
- `load_test_plan` accepts a single file or a directory. In directory mode, `discover_yaml_files` collects every `.yaml` and `.yml` file below the directory, skipping any path segment that starts with `_` or `.`, and the sections of all files are merged with collision detection. The removed `defaults` key is rejected. See [Test Plan Specification - File Organization](../reference/test-plan.md#file-organization).
- Nested test case groups are flattened at load time; see [Nested groups](#nested-groups-and-inclusion-paths).
- `load_plan_data_model` resolves the data model directory from the plan's `data_model.path`, relative to the plan file's directory (or the plan directory in directory mode), or from `--data-model` (`HUGINN_DATA_MODEL`), relative to the current directory, which overrides it. Nothing in `pyproject.toml` sets it. `load_data_model` deep-merges every YAML file below it: mappings merge recursively, and a scalar or list defined by two files fails the load with a message that names both files and the dotted key path. See [Test Plan Specification - Data Model](../reference/test-plan.md#data-model).

Two helper modules keep loading honest:

- `unknown_keys.py` checks every test plan and testbed mapping against the keys the loaders read. An unknown key is a warning, not an error, because some projects keep data for other tools in these files. `run` prints the warnings and `validate` reports them as `unknown_key` warnings, each with a close match when there is one. See [Test Plan Specification - Unknown keys](../reference/test-plan.md#unknown-keys).
- `read_only.py` provides `freeze`, which converts dicts and lists into `ReadOnlyDict` and `ReadOnlyList`. The loaded data model and each `Device.metadata` are frozen once, because every job in a run shares the same object. A mutation raises `TypeError`, and `copy.deepcopy()` returns plain mutable containers. Freezing once costs one pass per run and nothing per job, where a copy per `Context` would cost a full copy per test case.

### Models

`models.py` holds plain dataclasses in three families:

- Plan: `TestPlan`, `Scenario`, `Phase`, `TestCaseGroup`, `TestCaseDefinition`, `TargetDefinition`, `ExecutionStrategy` and `InclusionPath`.
- Testbed: `Testbed`, `Device` and `ConnectionDefinition`.
- Results: `ExecutedScenario`, `ExecutedPhase`, `ExecutedTestCaseGroup`, `ExecutedTestCase`, `CheckResult`, `CommandExecution`, `MetadataSection`, `RunSummary`, `RunAbort` and `RunResult`.

`enums.py` defines `ExecutionMode`, `ResultStatus`, `SkipKind`, `BlockKind`, `BrokerType`, `ConnectionProtocol` and `ErrorCode`. Every executed item stores its status as the `ResultStatus` string value, so the result models serialize to JSON directly.

### Plan filtering

`plan_filtering.py` applies a `PlanFilterOptions` to a loaded plan with `filter_test_plan`, before validation and before execution. It filters groups first, test case by test case and inclusion path by inclusion path, so `--test-case-group` and tag filters can select a test through a child group. Then it drops scenarios and phases that are not selected or have nothing left, removes `depends_on` entries that point at a phase that was filtered out, and keeps only test cases that some group still references. Test cases filtered out this way do not appear in the results at all.

`test_contexts` is the one filter the CLI does not expose. It keeps a test only in the exact `(scenario, phase, test_id)` tuples it lists. Because groups are shared across phases, a phase that needs a different subset of a group gets its own synthetic copy of the group in the filtered plan, with the original group `identifier` kept for results. `huginn relearn` uses it; see [Relearn](#relearn). The filter options are documented in [Test Plan Specification - CLI Filtering](../reference/test-plan.md#cli-filtering).

### Validation

`validation.py` implements `huginn validate` in `validate_inputs`. It loads the testbed, the plan and the data model and applies the filters, as a run does, then resolves each scenario's phase order, loads every job to read its `required_brokers`, and resolves the targets of every test case in every phase it appears in. It contacts no device and dispatches no hook. The result, a `ValidationResult`, is written to `results/<timestamp>-validate/validate.json` by `write_validation_result` in `result_store.py`. See [CLI Reference - validate](../reference/cli.md#validate).

### Runner

`runner.py` executes a plan, starting from `run_test_plan`. Everything below it is a module-level function (`_execute_scenario`, `_execute_phase`, `_execute_group`, `_execute_test_case` and their helpers), not an executor class. Each level takes the same explicit arguments (mode, testbed, plan, broker, parameters directory, output directory, data model, hooks) and returns the matching result model: `ExecutedScenario`, `ExecutedPhase`, `ExecutedTestCaseGroup` or `ExecutedTestCase`. [Run lifecycle](#run-lifecycle) walks through the flow.

`runner.py` also owns target resolution (`resolve_targets` and `_resolve_targets`) and the status rollup (`_derive_status_from_values`).

### RuntimeBroker and brokers

Jobs never open connections. `RuntimeBroker` in `runtime_broker.py` is the object a job sees as `context.broker`. The runner creates one per run and uses it for every test case. It:

- holds the protocol brokers the run needs, resolved by name through the `PluginRegistry`;
- opens one connection per device and broker with `connect_targets`, choosing the device connection whose protocol matches the broker and the credential that connection names, and closes them all with `disconnect_targets`;
- serializes operations per device and broker with an `asyncio.Lock`, so jobs running in parallel never interleave commands on one session;
- caches `execute()` and `get()` results by operation, device, broker, command or path, and keyword arguments, and runs concurrent identical calls as one in-flight request;
- exposes `for_protocol` to pin a client to one broker, and wraps every broker error in `RuntimeBrokerError`.

The operations return `CommandResult`, not strings. The job-facing API is in [Context API - Connection broker API](../reference/context-api.md#connection-broker-api).

The protocol brokers implement `ConnectionBrokerProtocolV1` from `brokers/protocol.py`: `SSHBroker` (`brokers/ssh.py`, Scrapli), `HTTPBroker` (`brokers/http.py`, aiohttp) and `NETCONFBroker` (`brokers/netconf.py`, scrapli-netconf). `brokers/null.py` holds `NullBroker`, a no-op placeholder that is not registered as an entry point and that the runner does not use. [Connection Broker Plugin Architecture](connection-broker.md) covers the protocol, the exception hierarchy and broker plugins.

Centralizing connections is what lets Huginn scale to thousands of small test cases. A plan with 1,000 test cases on 20 devices opens 20 SSH sessions instead of 1,000, and 20 test cases that need `show ip ospf neighbor` on the same device run it once.

### Plugin registry

`plugin_registry.py` discovers plugins through Python entry points in four groups, `huginn.brokers`, `huginn.inventory`, `huginn.reporters` and `huginn.hooks`, and filters them with the `brokers`, `reporters` and `hooks` lists of `[tool.huginn.plugins]`. `get_plugin_config` returns a plugin's `[tool.huginn.plugins.config.<name>]` table. An entry point that fails to import, or a reporter or hook class that fails to instantiate, is logged and left out. Huginn registers its own built-ins in its `pyproject.toml`: `ssh`, `http` and `netconf` brokers, the `file` inventory plugin and the `html` reporter. See [Configuration - Plugins](../reference/configuration.md#plugins-in-toolhuginnplugins).

### Inventory plugins

`inventory_plugins.py` produces the run's `Testbed`. `resolve_inventory_testbed` loads the file given with `--testbed`, or parses an `--inventory-plugin` spec of the form `<plugin>:<config>`. `--testbed` and `--inventory-plugin` are mutually exclusive, and so are the `testbed` and `inventory_plugin` keys of `[tool.huginn]`. When one comes from the command line or environment and the other from `pyproject.toml`, the CLI drops the `pyproject.toml` one.

The built-in `file` plugin, `FileInventoryPlugin`, loads the testbed file named after the colon, relative to the project root. Any other name is resolved from the `huginn.inventory` entry-point group and instantiated as `cls(config=<text after the colon>)`. Its `resolve_testbed(project_root)` may be sync or async and must return a `Testbed`. Inventory plugins do not read `[tool.huginn.plugins.config.<name>]`. `validate` resolves only the `file` plugin.

### Jobs and job loading

A test case's `job` names a Python class. `load_test_case_class` in `jobs.py` accepts four forms:

- `jobs/verify_ospf.py` or `jobs/verify_ospf.py:VerifyOspfNeighbors`, a file path relative to the project root (the current directory), loaded with `importlib` without being added to `sys.modules`;
- `huginn_jobs_network.ospf.verify_neighbors` or the same with `:ClassName`, a module path imported from the active environment.

A reference is a module path when it has no `/` and no `.py` suffix. Without `:ClassName`, the first concrete `TestCase` subclass defined in that module is used. Any failure, including an exception raised while the module is imported, becomes a `JobLoadError`. See [Test Plan Specification - Job References](../reference/test-plan.md#job-references) and [Package-Based Job References](../reference/package-jobs.md).

### Test cases and parameters

`testcase.py` defines the job base classes:

- `TestCase` is the abstract base with async `setup`, `test` and `cleanup`, and a `required_brokers` class attribute that defaults to `{BrokerType.SSH}`.
- `LearningTestCase` implements `test()` as the learn-or-compare flow described in [Learning and testing](#learning-and-testing). Subclasses implement `gather_state()` and `compare_state()`, and may override `check_command_support()` and `learned_devices()`. Its `DESCRIPTION`, `SETUP`, `PROCEDURE` and `PASS_FAIL_CRITERIA` templates render into report sections in testing mode.

`volatile.py` builds `VolatileLearningTestCase` and `OperatorVolatileLearningTestCase` on top of `LearningTestCase`. They compare each observation with the previous one in the same run instead of with a stored value, and chain observations through JSONL files in `context.output_dir`. See [Volatile Parameters](volatile-parameters.md).

`parameters.py` stores learned parameters as one JSON file per test case ID, `<parameters_dir>/<test_id>.json`, through `ParameterManager.save()` and `ParameterManager.load()`. `context.py` defines the `Context` a job receives, a dataclass with the test's identity and location, the mode, the testbed and targets, `broker`, `parameters`, `results`, `output_dir` and `data_model`, typed `Mapping[str, object] | None` and read-only. Both are documented in the [Context API](../reference/context-api.md).

### Results and the result store

`results.py` holds `ResultCollector`, which a job reaches as `context.results`. It records checks, rendered metadata sections, command executions and `not_applicable_devices`, and `derive_status()` turns the checks into the test case status. The runner copies them into an `ExecutedTestCase`.

`result_store.py` writes results to disk. `create_run_dir` creates `results/<timestamp>-<mode>/` when the run starts, so jobs have an artifacts directory before any result exists. `write_run_result` writes one `test-cases/<scenario>-<phase>-<test_id>/result.json` per executed test case, with every check, command execution, error and traceback, and then `run.json` with the summary, the scenario tree and a `result_path` for each test case. The JSON files are written by the runner itself, not by a reporter, so they exist even when reporting is disabled. [Directory and output layout](#directory-and-output-layout) shows a real tree.

### Reporting

After the results are written, the runner calls every active reporter plugin with the `RunResult`, the run directory, `reports/` and the paths of the `result.json` files. The only built-in reporter is `html`, `HTMLReporterPlugin` in `reporting/html.py`. It renders `reports/<run>/html/index.html` and one page per test case from the Jinja2 templates in `reporting/templates/`, and points the `reports/latest` symlink at the newest report. `reporters = []` in `[tool.huginn.plugins]` disables reporting. `ReporterPlugin` is defined in `reporting/protocol.py`.

### Hooks

`hooks.py` defines the `HookPlugin` protocol, the `HookEvent` values, the `HookSkip` and `HookAbort` results and `HookDispatcher`, which calls the hooks subscribed to each event one at a time. `run_hooks.py` defines `RunHooks`, which the runner calls at each lifecycle point. It builds each event's payload from plain copies of runner state, so a hook cannot change the run by mutating its context, and it builds nothing when no hook subscribes. It also records the first abort, which the runner checks before it starts each scenario, phase, group and test case. See [Hook Plugins](../reference/hooks.md).

### Commands around the run

These modules implement the commands that prepare a plan or act on results:

- `reconcile.py` (`huginn reconcile`) reads the latest testing run, creates post-change variants of the test cases that failed in one phase, and copies their parameter files. See [Parameter Reconciliation](../reference/reconcile.md).
- `relearn.py` (`huginn relearn`) reads the latest testing run's failures, and the CLI re-runs them in learning mode through `run_test_plan`. See [Selective Re-learning](../reference/relearn.md).
- `prune.py` (`huginn prune`) reads the latest learning run's not-applicable devices and narrows the plan. See [Pruning Non-Applicable Tests](../reference/prune.md).
- `inject.py` (`huginn inject new`, `huginn inject into`) adds job files to the plan as test cases in a new or existing group.
- `execute.py` (`huginn execute`) runs ad hoc commands. `execute_commands` is also a public SDK function. It uses a `RuntimeBroker` with the built-in brokers directly, without a plan, hooks, reporters or result files.

[Learning and testing](#learning-and-testing) explains how reconcile, relearn and prune fit the learn-then-test cycle.

## Execution hierarchy

A test plan has four levels:

```txt
scenario            runs one at a time, in declared order
└── phase           runs one at a time, in depends_on order
    └── test case group   runs serially or in parallel (phase strategy)
        └── test case     runs serially or in parallel (group strategy)
```

`test_cases` and `test_case_groups` are top-level maps keyed by ID. Phases reference groups by ID and groups reference test cases by ID, so one group can appear in several phases and scenarios. That reuse is how a change-validation scenario checks the same state before and after a change. See [Test Plan Structure](../concepts/test-plan-structure.md) for the concepts and [Test Plan Specification](../reference/test-plan.md) for every field.

### Nested groups and inclusion paths

A group can include other groups with `groups`. The loader flattens every group into one list of test IDs at load time, and rejects groups that include each other in a cycle. The phase runs the flattened group, and results report each test case under the group the phase references. For each test a group inherits, the loader records every `InclusionPath` that reaches it: the chain of child groups, the `target` of each group on the chain, and the union of their `tags`.

- Targets intersect. A test inherited through a child group is narrowed by the child's `target` as well as the parent's, so a child can narrow the device set but never widen it.
- Tags are a union. The test carries its own tags, the parent's and those of every group on the path, and tag filters see all of them.
- Paths merge. When one group reaches a test through several children, the test runs once, on the union of the devices each path selects. Paths that apply the same targets and carry the same tags are merged into one, so stacked diamonds of nested groups do not multiply. A test that still has more than `MAX_INCLUSION_PATHS` (256) distinct paths in one group fails the load.

See [Test Plan Specification - Nested Group Flattening](../reference/test-plan.md#nested-group-flattening).

## Run lifecycle

`huginn run` and `huginn relearn` both call `run_test_plan`. The steps below are in execution order.

### Load

1. The CLI loads `[tool.huginn]`, builds the `PluginRegistry` from `[tool.huginn.plugins]`, and creates the `Output`, which writes to the console and to `huginn.log`.
2. `create_run_dir` creates `results/<timestamp>-<mode>/` and its `artifacts/` directory, or uses `--output-dir` for artifacts.
3. The testbed is resolved from the file or inventory plugin, the plan is loaded, and the data model is loaded when one is configured. Unknown-key warnings from the testbed and plan are printed at the end of loading, even when loading fails.

### Filter and plan

1. `filter_test_plan` applies the CLI filters, or the `test_contexts` of a relearn.
2. `_plan_executions` loads every job class once and reads its `required_brokers`, producing a `PlannedExecution` per test case. A job that fails to load records a planning error for that test case only. In learning mode, a job that does not inherit `LearningTestCase` is marked to be skipped with `SkipKind.LEARNING_MODE_UNSUPPORTED`.
3. The union of the brokers that runnable test cases require becomes the set of protocol brokers the run creates.

### Start hooks

The hook plugins are resolved once, after planning, and `run_start` is dispatched. A hook that returns `HookAbort` on `run_start` stops the run before any broker is created: every test case is recorded `BLOCKED` with `BlockKind.HOOK_ABORT`, and results and reports are still written.

### Prime connections

`_prime_runtime_connections` connects only what the run will use. `_collect_prime_targets` resolves the targets of every planned test case in every phase it appears in, skipping test cases with a planning error or a planned skip, and groups the devices by the set of brokers their test cases require. Each set is then connected with one `connect_targets` call, which opens the device-broker pairs concurrently and opens each pair once. There is no separate connectivity check and no automatic retry or reconnect: a connection that fails stops the run with a broker error, described in [Error handling](#error-handling).

### Execute scenarios and phases

Scenarios run one at a time in declared order, and `scenario_start` and `scenario_end` surround each one. Within a scenario, phases also run one at a time. `_select_next_phase_name` picks the first phase in declared order whose `depends_on` phases have all finished.

Before a phase runs, the runner checks whether a hook abort or a dependency blocks it; see [Blocking](#blocking). A phase that is not blocked clears the whole `RuntimeBroker` cache first, unless it sets `preserve_cache: true`, so each phase sees fresh device state by default. Then `phase_start` is dispatched. A hook can skip the phase there, which records every test case in it as `SKIPPED` with `SkipKind.HOOK`.

### Execute groups and test cases

A phase's `strategy` decides whether its groups run serially or in parallel, and a group's `strategy` decides the same for its test cases. Both default to unbounded parallel. `parallel.maximum` bounds the concurrency with an `asyncio.Semaphore`. Parallel items run as asyncio tasks joined with `asyncio.gather`, which works on every supported Python version (3.10 and later), and results keep the declared order. `group_start` and `test_case_start` can skip a group or a test case the same way `phase_start` skips a phase. See [Test Plan Specification - Group Execution Strategy](../reference/test-plan.md#group-execution-strategy).

In learning mode, a test ID runs at most once per run. When the same test case appears in a later phase or scenario, the runner reuses the first execution's result instead of learning the same parameters again, and the hook events still fire for each phase.

### Run one test case

For each test case, `_execute_test_case_once`:

1. Resolves the targets at execution time, for this phase and group. The testbed's devices are intersected with the phase `target`, the group `target`, the `target` of each group on the inclusion path and the test case `target`, and the result is the union over the test's inclusion paths. Each `target` can filter by `devices`, `groups` and `os`, and remove devices with `exclude_devices`. An unknown device name makes the test case `ERRORED`, and an empty result makes it `SKIPPED` with `SkipKind.NO_MATCHING_TARGETS`. See [Test Plan Specification - Targeting](../reference/test-plan.md#targeting).
2. Builds the `Context`, with a fresh `ResultCollector` and a `ParameterManager` for the test ID.
3. Records the planning error as `ERRORED`, or the planned learning-mode skip as `SKIPPED`, when there is one.
4. Instantiates the job and awaits `setup()` and `test()`, then `cleanup()` in a `finally`. An exception from any of the three makes the test case `ERRORED` with `ErrorCode.EXECUTION_ERROR` and the traceback. When `cleanup()` raises after an earlier error, the first error is kept and the cleanup traceback is appended to it.
5. Otherwise derives the status from the recorded checks with `ResultCollector.derive_status()`.

The runner calls only `setup()`, `test()` and `cleanup()`. Command support checks, parameter saving and comparison all happen inside `LearningTestCase.test()`.

### LearningTestCase flow

`LearningTestCase.test()` runs these steps:

1. It calls `check_command_support()`. For each target reported as not applicable, it records `NOT_APPLICABLE`, except in testing mode when `learned_devices()` finds the device in the learned parameters. That device supported the command when the parameters were learned, so it is recorded as `LOST_APPLICABILITY`, which fails the test case and is left out of `not_applicable_devices` so prune never removes it.
2. When no target is applicable, it records an `INFO` check and returns.
3. It narrows `context.targets` to the applicable devices and calls `gather_state()`. A supported device missing from the returned `devices` mapping is added to `not_applicable_devices`.
4. In learning mode it saves the gathered state with `context.parameters.save()` and records `PASSED`, unless every target was not applicable. In testing mode it loads the learned parameters, renders the metadata sections and calls `compare_state()` with the expected and current state.

See [Context API - Command support regression detection](../reference/context-api.md#command-support-regression-detection) and [Lost Applicability](../concepts/glossary.md#lost-applicability).

### Blocking

`_dependency_block` decides whether a phase runs:

- A dependency that finished `FAILED`, `ERRORED` or `LOST_APPLICABILITY` blocks the phase with `BlockKind.DEPENDENCY_FAILED`.
- In learning mode, a dependency with any test case skipped as `LEARNING_MODE_UNSUPPORTED` blocks the phase with `BlockKind.DEPENDENCY_NOT_LEARNED`, because the change it exists to make did not happen.
- A blocked dependency passes its block on, so blocking is transitive and the reason always names the phase where it started. When several dependencies block, a failure takes precedence over a learning-mode block.
- Other outcomes do not block: `NOT_APPLICABLE`, a skip because no device matched, and a phase, group or test case that a hook skipped.
- After a hook returns `HookAbort` on any event except `run_end`, items that are running finish, nothing new starts, and every test case that has not started is recorded `BLOCKED` with `BlockKind.HOOK_ABORT`.

A blocked phase runs no job and dispatches no hook event, and all of its test cases are recorded `BLOCKED` with the reason. Phases that do not depend on the failed phase still run. See [Test Plan Specification - Failure Blocking](../reference/test-plan.md#failure-blocking).

### Finish

After the last scenario, the runner disconnects every connection, then:

1. `_build_summary` counts each status and rolls up the run status.
2. `write_run_result` writes `result.json` for each test case and then `run.json`.
3. The active reporters run.
4. `run_end` is dispatched with the summary. It is also dispatched, with the error, when the run stops with an error after `run_start`.
5. The CLI prints the status and one count per status, and exits with the code described in [Statuses and rollup](#statuses-and-rollup).

## Statuses and rollup

Every test case records exactly one status. The statuses and what produces each one are listed in the [Glossary - Result](../concepts/glossary.md#result) table. `SkipKind` and `BlockKind` record why a test case was skipped or blocked.

Groups, phases, scenarios and the run are rolled up by `_derive_status_from_values`, in this order: `ERRORED` if anything errored, else `FAILED`, else `LOST_APPLICABILITY`, else `NOT_APPLICABLE` if everything is not applicable, else `SKIPPED` if everything is skipped, else `BLOCKED` if everything is blocked, else `PASSED`. A test case's own checks roll up the same way in `ResultCollector.derive_status()`, without the `BLOCKED` step and ignoring `INFO` checks. There is no partial status. The summaries report one count per status instead. See [Aggregate Result](../concepts/glossary.md#aggregate-result).

`huginn run` exits 1 when any test case is `failed`, `errored` or `lost_applicability`, when any test case is `blocked` for a reason other than a learning-mode skip, or when a hook aborted the run. `NOT_APPLICABLE`, `SKIPPED` and learning-mode blocks alone exit 0. The full table, including the exit codes for load and broker errors, is in [CLI Reference - Exit codes](../reference/cli.md#exit-codes).

## Learning and testing

The run's `--mode` applies to every phase. In learning mode, a `LearningTestCase` saves what `gather_state()` returns to `./parameters/<test_id>.json`, or to the `--parameters-dir` directory. In testing mode it loads that file and compares. Parameter files are keyed by test case ID only, so a test case that appears in several phases compares against one set of parameters, and a later learning run overwrites them. See [Execution Modes](../concepts/execution-modes.md).

Change and action jobs take one of two shapes in learning mode:

- A job that inherits `TestCase` but not `LearningTestCase` is not run at all. It is recorded `SKIPPED` with `SkipKind.LEARNING_MODE_UNSUPPORTED`, and the phases that depend on its phase are blocked. Those blocks do not fail the run, so learning a change-validation plan exits 0 without saving the unchanged network as post-change state.
- A change job built on `LearningTestCase`, as in [Change Jobs](../authoring/change.md), learns its candidate targets in learning mode and performs the action only in `compare_state()` in testing mode, so a learning run never changes the testbed.

### Reconcile

A testing run after a change fails the post-change test cases whose expected state really did change. `huginn reconcile` reads the latest testing `run.json`, creates variants of the test cases that failed in the chosen phase with IDs of the form `<id>-<scenario>-<phase>`, adds a group that inherits from the original group and swaps the variants in, points the phase at the new group, and copies the baseline parameter files to the variant IDs. A learning run of the variants then records their post-change state. See [Reconciliation](../concepts/reconciliation.md) and [Parameter Reconciliation](../reference/reconcile.md).

### Relearn

`huginn relearn` handles expected drift that does not need new variants. It reads the latest testing `run.json`, collects the `(scenario, phase, test_id)` contexts that are `failed`, `errored` or `lost_applicability`, and runs `run_test_plan` in learning mode with those contexts as `test_contexts`, so each test is re-learned only where it failed. See [Selective Re-learning - Automatic scoping](../reference/relearn.md#automatic-scoping).

### Prune

`huginn prune` narrows a plan that was written broader than the testbed. It reads the latest learning `run.json` and each test case's `not_applicable_devices` from `result.json`, adds `target.exclude_devices` for devices that were not applicable, and removes test cases that were not applicable anywhere from the groups that include them. See [Pruning](../concepts/pruning.md) and [Pruning Non-Applicable Tests](../reference/prune.md).

## Extension points

### Entry-point plugins

Installed packages extend Huginn by registering entry points in four groups:

| Group              | Plugin interface                                     | Selected by                                                      |
| ------------------ | ---------------------------------------------------- | ---------------------------------------------------------------- |
| `huginn.brokers`   | `ConnectionBrokerProtocolV1` (`brokers/protocol.py`) | `brokers` in `[tool.huginn.plugins]`, and job `required_brokers` |
| `huginn.inventory` | `InventoryPlugin` (`inventory_plugins.py`)           | `--inventory-plugin <name>:<config>`                             |
| `huginn.reporters` | `ReporterPlugin` (`reporting/protocol.py`)           | `reporters` in `[tool.huginn.plugins]`                           |
| `huginn.hooks`     | `HookPlugin` (`hooks.py`)                            | `hooks` in `[tool.huginn.plugins]`                               |

When `brokers`, `reporters` or `hooks` is absent, every discovered plugin in the group is active, and an empty `reporters` or `hooks` list disables the group. Reporters receive their `[tool.huginn.plugins.config.<name>]` table as `config`, and hooks receive it as a constructor argument. A hook can skip a phase, group or test case with `HookSkip` or `HookSignal.SKIP`, or stop the run with `HookAbort`. See [Hook Plugins](../reference/hooks.md), [Configuration - Plugins](../reference/configuration.md#plugins-in-toolhuginnplugins) and [Connection Broker - Plugin Discovery](connection-broker.md#plugin-discovery).

### Learned devices on LearningTestCase

`LearningTestCase.learned_devices()` tells the framework which devices the learned parameters cover, which decides between `NOT_APPLICABLE` and `LOST_APPLICABILITY`. The default reads the keys of `parameters["devices"]`. A job with a different parameter schema overrides it. See [Context API - Custom parameter schemas](../reference/context-api.md#custom-parameter-schemas).

### Package-based jobs

Because a `job` reference can be a module path, jobs can ship as ordinary Python packages, versioned and installed like any other dependency. No registration is needed: the job module only has to be importable. See [Package-Based Job References](../reference/package-jobs.md).

## Directory and output layout

This tree comes from a real project: the `learning_testing_parameters` fixture under `tests/fixtures/runner/`, run once in learning mode and once in testing mode with the fake broker from `tests/runner/conftest.py`:

```txt
project/
├── test_plan.yaml
├── testbed.yaml
├── jobs/
│   └── test_verify_learning_testing.py
├── parameters/
│   └── 1.0.0.json
├── results/
│   ├── 2026-Sep-29-13-21-24-learning/
│   │   ├── artifacts/
│   │   ├── run.json
│   │   └── test-cases/
│   │       └── scenario-1-phase-1-1.0.0/
│   │           └── result.json
│   └── 2026-Sep-29-13-21-24-testing/
│       ├── artifacts/
│       ├── run.json
│       └── test-cases/
│           └── scenario-1-phase-1-1.0.0/
│               └── result.json
├── reports/
│   ├── 2026-Sep-29-13-21-24-learning/
│   │   └── html/
│   │       ├── index.html
│   │       ├── styles.css
│   │       └── test-cases/
│   │           └── scenario-1-phase-1-1.0.0.html
│   ├── 2026-Sep-29-13-21-24-testing/
│   │   └── html/
│   │       ├── index.html
│   │       ├── styles.css
│   │       └── test-cases/
│   │           └── scenario-1-phase-1-1.0.0.html
│   └── latest -> 2026-Sep-29-13-21-24-testing/html
└── huginn.log
```

- `results/<timestamp>-<mode>/` is one run. A second run that starts in the same second gets a `-01` suffix. `--results-dir` moves the whole tree.
- `run.json` holds the summary, with one count per status, and the scenario, phase, group and test case tree, where each test case has its status, any error, and the `result_path` of its `result.json`.
- `test-cases/<scenario>-<phase>-<test_id>/result.json` holds everything the test case recorded. A test case that appears twice in one phase, through two groups, gets a `-01` suffix on its second directory.
- `artifacts/` is `context.output_dir`, where jobs write files. Volatile jobs keep their observation logs here. `--output-dir` points it elsewhere.
- `reports/<run>/html/` is written by the `html` reporter, and `reports/latest` points at the newest one.
- `parameters/<test_id>.json` is written in learning mode and read in testing mode.
- `huginn.log` is the log file; `--log-file` moves it. See [Output and Logging Design](output-logging.md).

`huginn validate` writes `results/<timestamp>-validate/validate.json` and the log, and no artifacts, parameters or reports.

## Error handling

Huginn separates errors that affect one test case from errors that stop the run.

### Errors in one test case

- A job that cannot be imported or found, or that declares an invalid `required_brokers`, is recorded `ERRORED` with `error_code` `planning_error` in every phase where it appears. The rest of the run continues, and the job is never instantiated.
- A target selector that names a device the testbed does not have makes that test case `ERRORED` with `validation_error`.
- An exception from `setup()`, `test()` or `cleanup()` makes the test case `ERRORED` with `execution_error`, and dependent phases are blocked like any other failure.

### Errors in a hook

A hook that raises from `on_event` is reported as a `hook_error` warning, on the console and with its traceback in the log. The other hooks still run, the item runs as if the hook had returned `None`, and the exit code is unchanged. A `HookAbort` returned from `run_end` is ignored with a `hook_abort_ignored` warning. See [Hook Plugins - Errors in a hook](../reference/hooks.md#errors-in-a-hook).

### Errors that stop the run

`run_test_plan` raises `ConfigurationError` for a testbed, plan or data model that cannot be loaded, and `RunExecutionError` with an `ErrorCode` for the rest. The CLI maps them to exit codes:

| Error                                                              | Raised as                                  | Exit code |
| ------------------------------------------------------------------ | ------------------------------------------ | --------- |
| Testbed, test plan, data model or `[tool.huginn]` cannot be loaded | `ConfigurationError`                       | 1         |
| A broker fails to connect or to disconnect                         | `RunExecutionError`, `broker_error`        | 1         |
| An inventory plugin fails                                          | `RunExecutionError`, `configuration_error` | 2         |
| Phase dependencies in a scenario cannot be resolved                | `RunExecutionError`, `validation_error`    | 2         |
| Results or reports cannot be written                               | `RunExecutionError`, `configuration_error` | 2         |

When a broker fails to connect, the run stops before any test case runs. The run directory exists, but `run.json` and the report are not written, and `run_end` is dispatched with the error. A load error happens before hook plugins are loaded, so it dispatches no event.

### Validation errors

`huginn validate` does not stop at the first bad input. It collects every problem it finds, testbed, plan and data model load failures included, into the `errors` of `validate.json`, prints them, and exits 3 when there is at least one. Only a `[tool.huginn]` table that cannot be loaded, which every command rejects before it starts, exits 1 instead. Warnings, such as unknown keys and test cases with no matching devices, are printed and do not change the exit code. See [CLI Reference - validate](../reference/cli.md#validate).

## Related Documents

- [Test Plan Structure](../concepts/test-plan-structure.md): the scenario, phase, group and test case hierarchy
- [Test Plan Specification](../reference/test-plan.md): every test plan field, targeting, blocking and filtering
- [Testbed Specification](../reference/testbed.md): devices, connections, credentials and `${VAR}` expansion
- [Context API](../reference/context-api.md): what a job sees at runtime
- [Configuration](../reference/configuration.md): `[tool.huginn]`, plugins and environment variables
- [Hook Plugins](../reference/hooks.md): events, payloads, skipping and aborting
- [Connection Broker Plugin Architecture](connection-broker.md): the broker protocol and broker plugins

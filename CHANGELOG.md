# Changelog

All notable changes to Huginn are documented in this file.

<!-- towncrier release notes start -->

## 0.3.0 - 2026-09-29

### Breaking Changes

- A failed or errored phase now blocks only the phases that depend on it, directly or transitively, instead of every remaining phase in the scenario. Not-applicable and skipped phases no longer block anything, except a phase whose change or action job was skipped in learning mode, which still blocks its dependents.
- Removed the unused test plan `defaults` block. A test plan that sets a top-level `defaults` key now fails to load; set `tags` or `target` on scenarios, phases or test case groups instead.
- Test cases included through nested test case groups now keep each child group's `target` (intersected with the parent's) and `tags` (added to the parent's), so they may run on fewer devices than before, and `--test-case-group` and `--tags` filters now match nested groups.
- `[tool.huginn.plugins]` now rejects unknown keys, non-list `brokers`/`reporters`/`hooks` values and a `config` table whose values are not tables, instead of silently accepting them.
- `huginn run` and `huginn relearn` now exit non-zero only when a test case is `failed`, `errored`, `lost_applicability` or `blocked`. A run whose results are only `passed`, `not_applicable` or `skipped` now exits 0 (it previously exited 1 for any run that was not fully `passed`), and test cases blocked only because learning mode skipped a change job do not fail the run.

### Added

- Added `huginn relearn` command to selectively re-learn parameters for failed tests from the latest testing run. ([#153](https://github.com/ChartinoLabs/Huginn/pull/153))
- Added optional `description`, `priority`, `category`, `is_automated`, and `metadata` fields to `TestCaseDefinition` for richer test case declarations and external tooling integration. ([#197](https://github.com/ChartinoLabs/Huginn/pull/197))
- Added `load_test_case_parameters()` and `list_available_parameters()` synchronous helpers to `huginn.parameters` for reading learned parameters without the async execution engine.
- Added `resolve_job_file_path()`, `read_job_source()`, and `extract_test_case_metadata()` to `huginn.jobs` for inspecting job files and class metadata without executing tests.
- Added a CLI reference page documenting every `huginn` command, option, environment variable and exit code.
- Added documentation for the `huginn relearn` command: concepts page and CLI reference.
- Added public `resolve_targets()` and `TargetResolutionError` to `huginn.runner` for resolving test case target devices without executing tests.
- Added the `LOST_APPLICABILITY` result status: in testing mode, a device that supported a job's command when parameters were learned but no longer does now fails the test (and the run) instead of passing as `NOT_APPLICABLE`, with its own count in the run summary, `run.json` and the HTML report. `LearningTestCase.learned_devices()` can be overridden for parameter schemas without a `devices` mapping.
- Huginn now supports Python 3.10; the minimum supported version is lowered from 3.11.
- Jobs now receive the test plan's external data model as `context.data_model`: Huginn deep-merges the YAML files under `data_model.path` (or `--data-model` / `HUGINN_DATA_MODEL`) once per run for `run`, `validate` and `relearn`, and exposes it read-only.
- Scenarios, phases and test case groups now load their optional `description`, which appears in `run.json` and under each heading in the HTML report.
- Test plan and testbed files now produce a warning for each key Huginn does not read, with the file, the dotted key path and a "did you mean" suggestion; turn them off with `--no-unknown-key-warnings`, `HUGINN_NO_UNKNOWN_KEY_WARNINGS` or `[tool.huginn] unknown_key_warnings = false`. The testbed top-level `name` is now a validated string stored as `Testbed.name`.
- Testbed device `metadata` is now loaded and exposed to jobs as a read-only `Device.metadata` mapping.
- Testbed files now expand `${VAR}` and `${VAR:-default}` environment variable references in string values at load time, and fail with an error naming the variable when one is not set.
- The CLI now reads project defaults for `test_plan`, `testbed`, `inventory_plugin`, `parameters_dir`, `results_dir`, `output_dir`, `log_file` and `log_level` from `[tool.huginn]` in `pyproject.toml`, below CLI flags and `HUGINN_*` environment variables.
- `huginn run` and `huginn relearn` now call installed hook plugins (the `huginn.hooks` entry point group, filtered by `[tool.huginn.plugins] hooks`) at every lifecycle event, from `run_start` to `run_end`, including `on_failure` and `on_error`. A hook can skip a phase, group or test case by returning `HookSignal.SKIP` or `HookSkip("reason")`, which records its test cases as `skipped` with skip kind `hook` and does not block dependent phases. A hook that raises prints a warning and the run continues. See the new Hook Plugins reference page. A hook can also stop the whole run by returning `HookAbort("reason")` from any event except `run_end`: running test cases finish, every test case that has not started is recorded `blocked` with block kind `hook_abort`, `run.json` records the abort in a new `aborted` field, and the run exits 1. An abort on `run_start` connects no device. The Hook Plugins page adds tested example plugins for webhook notifications, a testbed lock and job telemetry.

### Changed

- Reconciled test case and group IDs now include the scenario name as a suffix for disambiguation across scenarios. ([#163](https://github.com/ChartinoLabs/Huginn/pull/163))
- Raise the minimum supported `typer` version from 0.9.0 to 0.16.0, the oldest release that handles the CLI's `X | None` option annotations on Python 3.10 and supports Click 8.2.

### Fixed

- Fixed `huginn reconcile` not carrying over `exclude_devices` target constraints from parent test case definitions. ([#154](https://github.com/ChartinoLabs/Huginn/pull/154))
- An invalid `--test-id-pattern` regular expression is now a usage error (exit code 2) instead of a traceback, and `inject --id-style` rejects styles other than `prefix-counter`.
- Corrected the execution modes, relearn and prune docs to describe the parameters directory, the per-run mode, current sample output and exit codes.
- Corrected the installation docs and README to state the Python 3.10 minimum, the real `huginn version` output and the full runtime dependency list, and updated the project status on the docs landing page.
- Corrected the package jobs reference with installable dependency pins, the actual job reference resolution and validation behavior, and module path import requirements.
- Corrected the quick start guide to include the Muninn install step, match the real HTML report layout, and describe test failure messages accurately.
- Corrected the reconcile docs to use the real `<id>-<scenario>-<phase>` naming, select reconciled variants by test ID when re-learning, and document side effects, logging options, and exit codes.
- Corrected the test plan reference to document the scenarios hierarchy and fixed its Complete Example.
- Corrected the testbed reference so its REST examples load, and documented the supported protocols, connection options, credential fields, OS identifiers, and where each testbed check is enforced.
- Corrected the volatile validation guide on broker caching, the per-device operator schema and how to change operators, and documented the supported operators, custom-scheme hooks, and the silent pass when nothing is observed.
- Fixed `huginn version` crashing with `PackageNotFoundError`; it now prints the installed Huginn version.
- Fixed the gate and change authoring examples so they run, and corrected the authoring guides on metadata templating, caching, empty-state handling, change-job preconditions and non-CLI actions.
- Fixed the unit testing guide so its example harness runs as written, with fakes that accept the real broker's keywords and a documented pytest layout.
- Job modules that raise while being imported, such as a job file importing a missing dependency, are now reported as a `planning_error` by `huginn validate` and `huginn run` instead of crashing the command.
- Made the glossary the canonical result status table with all seven statuses and the real rollup order, marked LOST_APPLICABILITY as planned, removed the nonexistent Partial status, and corrected the scenario, target, job reference, blocking, and parallelism descriptions on the concepts pages.
- NETCONF connections no longer fail with `TypeError: ... unexpected keyword argument 'platform'`, because the broker stopped passing `platform` to scrapli-netconf's `AsyncNetconfDriver`.
- Plan filters no longer reset a phase's `preserve_cache` or a group's `exclude_tests`, and no longer drop the test plan's `name`, `description` and `data_model`.
- Reconciled test case variants now keep the `target` and `tags` their originals inherited from parent and nested test case groups, so they run on the same devices.
- Rewrote the Context API reference to match the current `Context`, `Device`, `RuntimeBroker`, `CommandResult`, `ResultCollector` and `LearningTestCase` APIs, with runnable examples.
- Rewrote the architecture design page to match the implementation: the scenario hierarchy, the run lifecycle, the real modules and plugin entry points, and an output layout taken from a real run.
- Rewrote the configuration reference to document only the supported `[tool.huginn]` keys, `[tool.huginn.plugins]` schema and `HUGINN_*` environment variables, and updated the CLI, context API, relearn and glossary pages now that the data model is implemented.
- Updated the connection broker, output logging, and future considerations design pages to match the current implementation, including broker entry point discovery, how caching and routing really work, and which job loggers reach huginn.log.
- `huginn prune --remove-orphans` now removes every test case that no group references, including orphans left by an earlier prune and test cases never placed in a group, instead of doing nothing on a follow-up run.
- `huginn relearn` now re-runs each failed test only in the exact scenario and phase where it failed, instead of in every combination of the failed scenarios and phases.
- `parse_duration_seconds` now parses `D:HH:MM:SS`, `D+HH:MM:SS`, and `N days, HH:MM[:SS]` durations instead of returning `0` or dropping the clock.
- `parse_duration_seconds` now parses every component of compact durations such as `1d02h` and `2y3w` instead of silently dropping hours, minutes, seconds, and years.

### Internal

- Switched PyPI publishing to OIDC trusted publishing (no API token required). ([#169](https://github.com/ChartinoLabs/Huginn/pull/169))
- Upgraded ruff to 0.16 and applied its updated formatting, including code blocks in the documentation. ([#206](https://github.com/ChartinoLabs/Huginn/pull/206))
- Reorganized the test suite so each module is named after what its tests cover, moved the hook integration tests into `tests/runner/hooks/`, and renamed the `tests/fixtures/first_slice_runner/` fixtures to `tests/fixtures/runner/`.
- Run the lowest-dependency and per-version CI jobs on their matrix Python instead of the `.python-version` interpreter.
- Run the release workflow's pre-publish tests on Python 3.10 as well, matching the supported versions.


## 0.2.0 - 2026-06-17

### Added

- Added a concepts documentation page for pruning, explaining the motivation, lifecycle placement, and relationship to reconciliation. ([#142](https://github.com/ChartinoLabs/Huginn/pull/142))

### Internal

- Relax mainline dependency version floors to true minimums, pin dev dependencies to exact versions, and add CI job to test lowest dependency bounds. ([#143](https://github.com/ChartinoLabs/Huginn/pull/143))


## 0.1.0 - 2026-06-15

### Added

- Initial release of the `huginn-framework` package with async-first test automation, plugin-based architecture, and SSH/HTTP/NETCONF brokers.

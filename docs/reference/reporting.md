# Reporting

## Overview

After every `run` and `relearn`, Huginn writes its results twice: as JSON files, which are the complete record of the run, and through reporter plugins, which render that record for people and tools. Two reporters are built in:

| Reporter | Output                                        | For                                                   |
| -------- | --------------------------------------------- | ----------------------------------------------------- |
| `html`   | `reports/<run>/html/index.html`, and `latest` | People reviewing a run in a browser                   |
| `junit`  | `results/<run>/junit.xml`                     | CI systems such as Jenkins, GitHub Actions and GitLab |

Both run by default. `reporters` in `[tool.huginn.plugins]` chooses which reporters run, and `reporters = []` disables them all. The JSON files are written by the runner, not by a reporter, so they exist even when reporting is disabled. See [Configuration - Plugins](configuration.md#plugins-in-toolhuginnplugins).

## JSON results

`results/<run>/run.json` holds the run summary and the scenario, phase, group and test case tree. Each test case lists its status, any error, its `elapsed_seconds` when its job ran, and the `result_path` of its `test-cases/<scenario>-<phase>-<test_id>/result.json`, which holds every check, command execution, error and traceback. `huginn reconcile`, `huginn relearn` and `huginn prune` read these files, and they are the format to build on when JUnit or HTML do not carry what you need. See [Architecture - Directory and output layout](../design/architecture.md#directory-and-output-layout).

`elapsed_seconds` on a test case is the wall-clock time from the start of its job's setup to the end of its cleanup. A test case whose job did not run, because it was blocked, aborted or skipped by a hook, has none. In learning mode, a test case reused in a later phase reports the time spent waiting for the first execution.

## JUnit XML

The `junit` reporter writes one file that validates against the Jenkins/Surefire JUnit schema, which Jenkins, GitHub Actions test summaries and GitLab test reports accept.

### Structure

| Huginn                                     | JUnit                                                                                                                               |
| ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------- |
| Run                                        | `<testsuites name="huginn">`, with totals and the run's `time`                                                                      |
| A test case group in a phase of a scenario | `<testsuite name="<scenario>.<phase>.<group>">`, with its counts, the sum of its test case times and the run's start as `timestamp` |
| Test case                                  | `<testcase classname="<scenario>.<phase>.<group>" name="<test_id>">`, with `time` when its job ran                                  |

A group used in two phases produces two suites, one per phase.

### Statuses

JUnit has four outcomes and Huginn has eight statuses. The `type` attribute of the outcome element keeps the Huginn status, and the kind of skip or block where there is one:

| Huginn status        | JUnit outcome | `type`                                                          | `message`                                 | Body                           |
| -------------------- | ------------- | --------------------------------------------------------------- | ----------------------------------------- | ------------------------------ |
| `passed`, `info`     | Passed        | -                                                               | -                                         | -                              |
| `failed`             | `<failure>`   | `failed`                                                        | The first failing check                   | Every failing check            |
| `lost_applicability` | `<failure>`   | `lost_applicability`                                            | The first lost-applicability check        | Every lost-applicability check |
| `errored`            | `<error>`     | The error code, for example `execution_error`                   | The error message                         | The traceback                  |
| `skipped`            | `<skipped>`   | `skipped:<skip_kind>`, for example `skipped:hook`               | The skip reason                           | -                              |
| `not_applicable`     | `<skipped>`   | `not_applicable`                                                | Each not-applicable device and its reason | -                              |
| `blocked`            | `<skipped>`   | `blocked:<block_kind>`, for example `blocked:dependency_failed` | The block reason                          | -                              |

`blocked` maps to skipped because a blocked test case never ran; the failure that blocked it is reported on the test cases of the phase it depends on. A run in which a hook aborted every test case reports only skipped test cases but exits 1, so a CI job should gate on Huginn's exit code rather than on the JUnit counts. See [CLI Reference - Exit codes](cli.md#exit-codes).

Every `<testcase>` also has a `<system-out>` with its title, its Huginn status, every check and any not-applicable devices.

Characters that XML 1.0 cannot hold, such as the escape character in ANSI color codes, are removed.

### Options

```toml
[tool.huginn.plugins.config.junit]
path = "ci/huginn-junit.xml"
```

| Key    | Type   | Default                   | Description                                                                                                                    |
| ------ | ------ | ------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `path` | string | `results/<run>/junit.xml` | Where to write the report. A relative path is resolved against the project root. Each run overwrites the file at a fixed path. |

An unknown key is logged as a warning and ignored. A `path` that is not a non-empty string, or that cannot be written, fails the run with a configuration error after the JSON results are written.

### CI examples

Jenkins, with the JUnit plugin:

```groovy
post {
    always {
        junit 'results/*/junit.xml'
    }
}
```

GitHub Actions, with a fixed `path` so the step does not need a glob:

```yaml
- name: Run Huginn
  run: huginn run -m testing -t testbed.yaml -p test_plan/
- name: Publish test results
  if: always()
  uses: dorny/test-reporter@v2
  with:
    name: Huginn
    path: ci/huginn-junit.xml
    reporter: java-junit
```

## Writing a reporter

A reporter is a class registered under the `huginn.reporters` entry point group that implements `ReporterPlugin` from `huginn.reporting.protocol`. Its `generate_report()` receives the in-memory `RunResult`, the run's results directory, the `reports/` directory, the `result.json` path of each test case and its `[tool.huginn.plugins.config.<name>]` table, and returns the path of its main output or `None`. See [Architecture - Entry-point plugins](../design/architecture.md#entry-point-plugins).

## Related Documents

- [Configuration](configuration.md) - enabling reporters and passing them options
- [Architecture](../design/architecture.md) - where results and reports are written
- [CLI Reference](cli.md) - exit codes and the `--results-dir` option

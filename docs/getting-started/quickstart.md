# Quick Start

This guide walks through running your first test with Huginn. You will:

- Define a testbed
- Write a test job
- Create a test plan
- Execute the test plan
- Review the HTML report

## Define your testbed

Create a `testbed.yaml` describing the devices you want to test against:

```yaml
devices:
  rtr-01:
    os: iosxe
    credentials:
      default:
        username: admin
        password: ${DEVICE_PASSWORD}
    connections:
      ssh:
        protocol: ssh
        host: 10.0.0.1
        port: 22
        auth_strict_key: false
```

Each device needs an OS identifier, at least one connection, and credentials. Environment variables (like `${DEVICE_PASSWORD}`) are resolved at runtime.

## Write a test job

This test job executes `show version` on each target device and validates that the current IOS-XE software version matches the learned baseline. It uses [Muninn](https://github.com/ChartinoLabs/muninn) to parse raw CLI output into structured data.

> **Note:** Muninn is not required. You can use regular expressions, TextFSM templates, or pyATS Genie parsers to extract structured data from CLI output. Muninn is recommended because it provides type-hinted return values and integrates cleanly with Huginn's async patterns.

Create `jobs/verify_ios_version.py`:

```python
from typing import TypedDict

import muninn

from huginn import Context, LearningTestCase, ResultStatus

mn = muninn.Muninn()
mn.load_builtin_parsers()


class VersionDeviceParameters(TypedDict):
    value: str


class VersionParameters(TypedDict):
    devices: dict[str, VersionDeviceParameters]


class VerifyIosVersion(LearningTestCase[VersionParameters]):
    """Learn and verify the IOS-XE software version."""

    command = "show version"

    async def gather_state(self, context: Context) -> VersionParameters:
        """Collect current IOS version from each target device."""
        devices: dict[str, VersionDeviceParameters] = {}
        for device in context.targets:
            result = await context.broker.execute(device, self.command)
            parsed = mn.parse(os=device.os, command=self.command, output=result.output)
            context.results.add_command_execution(
                device=device.name,
                command=self.command,
                output=result,
                parsed=parsed,
            )
            devices[device.name] = {"value": str(parsed["version"])}
        return {"devices": devices}

    async def compare_state(
        self,
        *,
        expected: VersionParameters,
        current: VersionParameters,
        context: Context,
    ) -> None:
        """Compare learned IOS version against current state."""
        for device in context.targets:
            expected_version = expected["devices"][device.name]["value"]
            current_version = current["devices"][device.name]["value"]
            if current_version == expected_version:
                context.results.add_result(
                    ResultStatus.PASSED,
                    f"{device.name}: IOS version '{current_version}' matches baseline",
                )
            else:
                context.results.add_result(
                    ResultStatus.FAILED,
                    f"{device.name}: IOS version drifted from '{expected_version}' "
                    f"to '{current_version}'",
                )
```

A job containing a class that inherits from `LearningTestCase` implements two methods:

- **`gather_state`** — collects current device state (runs in both modes)
- **`compare_state`** — compares learned state against current state (runs only in testing mode)

When the job is executed in learning mode, Huginn saves the output of `gather_state` as parameters in a JSON file, typically in a directory named `parameters`. When the job is executed in testing mode, it loads those saved parameters and passes them to `compare_state` to compare those saved parameters against the current device state.

## Create a test plan

Next, we need to create a test plan that defines defines how test cases will be executed. The hierarchy of objects in a test plan are:

- **Scenario**: An organizational unit in a test plan representing a stage of test execution. Scenarios contain one or more phases.
- **Phase**: An organizational unit in a test plan representing a stage of test execution. Phases contain one or more test case groups and can have dependencies on other phases in the same scenario.
- **Test Case Group**: A logical grouping of test cases. Test case groups reference test cases by ID and can include other groups by name, enabling hierarchical organization. Groups can specify targets that apply to all contained test cases, and the framework executes test cases within a group in parallel.
- **Test Case**: A first-class entity defining what to test. A test case references a job and, and the test case identifier drives the name of the JSON file where parameters are stored.

Create `test_plan.yaml` referencing your job:

```yaml
test_cases:
  VERSION-IOS-VERSION:
    title: IOS version matches learned baseline
    job: jobs/verify_ios_version.py
    tags:
      - version

test_case_groups:
  version-baseline:
    tests:
      - VERSION-IOS-VERSION

scenarios:
  validation:
    phases:
      pre-change:
        test_case_groups:
          - version-baseline
```

The test plan organizes test cases into groups, which are arranged into phases within scenarios.

## Run in learning mode

Learning mode captures the current device state as the expected parameters to be used for comparison against when the test plan is executed in testing mode.

```bash
huginn run -m learning -t testbed.yaml -p test_plan.yaml
```

This connects to each device, executes `gather_state`, and saves the results as learned parameters. You should see a JSON file in the `parameters` directory with the name `VERSION-IOS-VERSION.json` containing the learned parameters that look something like this:

```json
{
  "devices": {
    "rtr-01": {
      "value": "17.18.02"
    }
  }
}
```

## Run in testing mode

Testing mode compares current state against the learned parameters. This is typically when you want to validate that the device state matches the expected parameters before or after a change has been made.

```bash
huginn run -m testing -t testbed.yaml -p test_plan.yaml
```

If the device state matches the learned parameters, the test passes. If state has drifted, the test fails with a diff showing what changed.

## Review the HTML report

After each run, Huginn generates an HTML report in the `reports/` directory. The report includes a dashboard with pass/fail statistics and a detail page for each test case showing the commands executed, parsed output, and comparison results.

The report is written to `reports/<run-timestamp>/html/index.html`. A `latest` symlink always points to the most recent run:

```
reports/
  latest -> 2026-06-05T10-30-00/html
  2026-06-05T10-30-00/
    html/
      index.html          # dashboard
      styles.css
      test-cases/
        VERSION-IOS-VERSION.html
```

To view the report locally, start a simple HTTP server from the report directory:

```bash
python -m http.server 8000 --directory reports/latest
```

Then open `http://localhost:8000` in your browser. The dashboard shows a summary of all test cases with their status, and you can click into any test case to see the full execution details — including the raw CLI output, parsed data, and pass/fail checks.

## Next steps

- [Concepts Overview](../01-overview.md) — understand what the framework does and doesn't do
- [Job Archetypes](../concepts/archetypes.md) — the four shapes a job can take
- [Authoring Jobs](../authoring/index.md) — detailed guides for each archetype
- [Testbed Specification](../03-testbed-spec.md) — full testbed YAML reference
- [Test Plan Specification](../04-test-plan-spec.md) — full test plan YAML reference

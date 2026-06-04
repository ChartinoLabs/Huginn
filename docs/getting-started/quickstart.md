# Quick Start

This guide walks through running your first test with Huginn: define a testbed, write a test job, create a test plan, and execute it.

## Define your testbed

Create a `testbed.yaml` describing the devices you want to test against:

```yaml
devices:
  spine-01:
    os: nxos
    groups:
      - spine
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

Create `jobs/verify_hostname.py` with a minimal learning/testing job:

```python
from huginn import Context, LearningTestCase, ResultStatus


class VerifyHostname(LearningTestCase):
    """Learn and verify device hostnames."""

    async def gather_state(self, context: Context) -> dict[str, object]:
        """Collect current hostname from each target device."""
        devices: dict[str, dict[str, object]] = {}
        for device in context.targets:
            output = await device.ssh.send_command("show hostname")
            devices[device.name] = {"hostname": output.result.strip()}
        return {"devices": devices}

    async def compare_state(
        self,
        *,
        expected: dict[str, object],
        current: dict[str, object],
        context: Context,
    ) -> None:
        """Compare learned hostnames against current state."""
        if expected == current:
            context.results.add_result(ResultStatus.PASSED, "Hostnames match")
        else:
            context.results.add_result(
                ResultStatus.FAILED,
                f"Hostname mismatch: expected={expected}, current={current}",
            )
```

A `LearningTestCase` implements two methods:

- **`gather_state`** — collects current device state (runs in both modes)
- **`compare_state`** — compares learned state against current state (runs only in testing mode)

In learning mode, Huginn saves the output of `gather_state` as parameters. In testing mode, it loads those saved parameters and passes them to `compare_state`.

## Create a test plan

Create `test_plan.yaml` referencing your job:

```yaml
test_cases:
  1.0.0:
    title: Verify Device Hostname
    job: jobs/verify_hostname.py
    tags:
      - baseline

test_case_groups:
  baseline-checks:
    tests:
      - 1.0.0

scenarios:
  validation:
    phases:
      verify-state:
        test_case_groups:
          - baseline-checks
```

The test plan organizes test cases into groups, which are arranged into phases within scenarios.

## Run in learning mode

Learning mode captures the current device state as your baseline:

```bash
huginn run -m learning -t testbed.yaml -p test_plan.yaml
```

This connects to each device, executes `gather_state`, and saves the results as learned parameters.

## Run in testing mode

Testing mode compares current state against the learned baseline:

```bash
huginn run -m testing -t testbed.yaml -p test_plan.yaml
```

If the device state matches the learned parameters, the test passes. If state has drifted, the test fails with a diff showing what changed.

## Next steps

- [Concepts Overview](../01-overview.md) — understand what the framework does and doesn't do
- [Job Archetypes](../concepts/archetypes.md) — the four shapes a job can take
- [Authoring Jobs](../authoring/index.md) — detailed guides for each archetype
- [Testbed Specification](../03-testbed-spec.md) — full testbed YAML reference
- [Test Plan Specification](../04-test-plan-spec.md) — full test plan YAML reference

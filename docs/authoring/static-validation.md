# Static Parameter Validation Jobs

A static parameter validation job confirms that a previously-learned, deterministic value still matches the current state observed on the testbed. This is the most common archetype in a typical test plan.

## When to use this archetype

Use static parameter validation when the attribute being validated is one of:

- **A fixed value** that does not change unless an explicit configuration or hardware change occurs. Examples: interface descriptions, OSPF costs, BGP ASN configurations, device serial numbers, software versions.
- **An enumerable state value** that transitions between a known set of discrete states. Examples: interface status (`up` / `administratively down`), routing protocol adjacency state (`FULL` / `DOWN`), BGP peering status (`Established` / `Idle`).

Both cases share the property that the *expected* value at any point in the test plan can be captured as a learned parameter and compared exactly.

If the attribute changes continuously as a normal consequence of operation (counters, uptimes, table versions), use [Volatile Parameter Validation](volatile-validation.md) instead.

## Anatomy of a static validation job

A complete reference example follows. The job validates that each BGP neighbor's session state on each device still matches the learned baseline.

```python
"""Atomic BGP neighbor test: session state should match baseline."""

from typing import Any, TypedDict

import muninn

from huginn import ApplicabilityResult, Context, LearningTestCase, ResultStatus
from huginn.utils.commands import is_command_unsupported

mn = muninn.Muninn()
mn.load_builtin_parsers()

NOT_SUPPORTED_REASON = "Device does not support '{command}'"
MISSING_LEARNED_BASELINE = (
    "{device} is missing learned BGP neighbor session state baseline parameters"
)
MISSING_CURRENT_STATE = (
    "{device} is missing current BGP neighbor session state state"
)
MISSING_NEIGHBOR = (
    "{device}'s learned BGP neighbor '{neighbor}' is missing from current state."
)
VALUE_MISMATCH = (
    "{device}'s BGP neighbor '{neighbor}' session state has drifted - we expected "
    "'{expected_value}' but found '{current_value}' instead."
)
VALUES_MATCH = (
    "{device}'s current BGP neighbor session state values match baseline parameters"
)


class BgpNeighborStateDeviceParameters(TypedDict):
    values: dict[str, str]


class BgpNeighborStateParameters(TypedDict):
    devices: dict[str, BgpNeighborStateDeviceParameters]


class VerifyBgpNeighborState(LearningTestCase[BgpNeighborStateParameters]):
    """Value check for parsed BGP neighbor session state."""

    DESCRIPTION = (
        "Validate that each BGP neighbor's session state remains aligned with "
        "the learned baseline."
    )
    SETUP = (
        "- Devices are reachable over SSH.\n"
        "- The `show ip bgp neighbors` command is supported on applicable targets.\n"
        "- Learned BGP neighbor session state baseline parameters are available for testing mode."
    )
    PROCEDURE = (
        "- Execute `show ip bgp neighbors` on each applicable device.\n"
        "- Parse the command output and extract `neighbors.*.bgp_state`.\n"
        "- Compare current values against the learned baseline.\n"
    )
    PASS_FAIL_CRITERIA = (
        "- Pass when each neighbor's session state matches the learned baseline.\n"
        "- Fail on missing baseline/current state, missing neighbors, or value mismatch."
    )

    command = "show ip bgp neighbors"

    async def check_applicability(self, context: Context) -> ApplicabilityResult:
        applicable = []
        not_applicable: dict[str, str] = {}
        for device in context.targets:
            result = await context.broker.execute(device, self.command)
            if is_command_unsupported(result.output):
                not_applicable[device.name] = NOT_SUPPORTED_REASON.format(
                    command=self.command,
                )
                continue
            applicable.append(device)
        return ApplicabilityResult(applicable=applicable, not_applicable=not_applicable)

    async def gather_state(self, context: Context) -> BgpNeighborStateParameters:
        devices: dict[str, BgpNeighborStateDeviceParameters] = {}
        for device in context.targets:
            result = await context.broker.execute(device, self.command)
            parsed = mn.parse(os=device.os, command=self.command, output=result.output)
            context.results.add_command_execution(
                device=device.name,
                command=self.command,
                output=result,
                parsed=parsed,
            )
            values: dict[str, str] = {}
            for neighbor, data in parsed["neighbors"].items():
                values[neighbor] = str(data["bgp_state"])
            devices[device.name] = {"values": values}
        return {"devices": devices}

    async def compare_state(
        self,
        *,
        expected: BgpNeighborStateParameters,
        current: BgpNeighborStateParameters,
        context: Context,
    ) -> None:
        for device in context.targets:
            try:
                expected_values = expected["devices"][device.name]["values"]
            except KeyError:
                context.results.add_result(
                    ResultStatus.FAILED,
                    MISSING_LEARNED_BASELINE.format(device=device.name),
                )
                continue

            try:
                current_values = current["devices"][device.name]["values"]
            except KeyError:
                context.results.add_result(
                    ResultStatus.FAILED,
                    MISSING_CURRENT_STATE.format(device=device.name),
                )
                continue

            has_failures = False
            for neighbor, expected_value in expected_values.items():
                current_value = current_values.get(neighbor)
                if current_value is None:
                    context.results.add_result(
                        ResultStatus.FAILED,
                        MISSING_NEIGHBOR.format(
                            device=device.name, neighbor=neighbor,
                        ),
                    )
                    has_failures = True
                    continue
                if current_value != expected_value:
                    context.results.add_result(
                        ResultStatus.FAILED,
                        VALUE_MISMATCH.format(
                            device=device.name,
                            neighbor=neighbor,
                            expected_value=expected_value,
                            current_value=current_value,
                        ),
                    )
                    has_failures = True

            if not has_failures:
                context.results.add_result(
                    ResultStatus.PASSED,
                    VALUES_MATCH.format(device=device.name),
                )
```

## What each piece does

### Module-level message constants

Every comparison outcome you might emit gets its own named constant with `{placeholder}` slots. This makes message wording consistent across the catalog and easy to grep.

The standard families are:

- `NOT_SUPPORTED_REASON` - applicability skip reason when the show command is unsupported.
- `MISSING_LEARNED_BASELINE` - testing mode failure when the learned parameter file is missing data for a device.
- `MISSING_CURRENT_STATE` - testing mode failure when the current observation is missing data for a device.
- One or more drift messages (`VALUE_MISMATCH`, `MISSING_NEIGHBOR`, …) - per-item failure reasons.
- One pass message (`VALUES_MATCH`) - per-device success.

### TypedDicts

The parameters payload is always wrapped in an outer `<Subject>Parameters` TypedDict containing `devices: dict[str, <Subject>DeviceParameters]`. The inner per-device TypedDict's shape depends on cardinality:

| Inner shape | When to use | Inner field |
|---|---|---|
| Scalar | One value per device (e.g. IOS version, hostname, contact email) | `value: str` |
| Single-keyed dict | One value per object per device (e.g. one state per BGP neighbor) | `values: dict[str, str]` |
| Double-keyed dict | One value per object-pair per device (e.g. one capability per neighbor per interface) | `<plural>: dict[str, dict[str, str]]` |
| List | Membership-only checks (e.g. set of expected route prefixes) | `<plural>: list[str]` |

Always type the parameters in the class generic: `LearningTestCase[<Subject>Parameters]`.

### `check_applicability`

Standard idiom - see [Authoring overview](index.md#applicability). Verify that the show command is supported on each target. Skip targets that respond with an unsupported-command marker.

### `gather_state`

For each target:

1. Execute the show command through the broker.
2. Parse with `mn.parse(os=device.os, command=self.command, output=result.output)`.
3. Record the execution with `context.results.add_command_execution(...)` so the report includes the raw and parsed output.
4. Extract the values you care about into the inner TypedDict shape.
5. Stuff the per-device record into `devices[device.name]`.

Return `{"devices": devices}`.

In **learning mode**, the framework persists this return value to a parameter file. In **testing mode**, the framework calls `gather_state` to get the current observation, then loads the persisted file as the expected baseline and calls `compare_state`.

### `compare_state`

For each target, in this order:

1. Try to read `expected["devices"][device.name][...]`. On `KeyError`, emit `MISSING_LEARNED_BASELINE` and `continue` to the next device.
2. Try to read `current["devices"][device.name][...]`. On `KeyError`, emit `MISSING_CURRENT_STATE` and `continue`.
3. Walk the inner items. For each item, classify as missing, mismatched, or matched. Emit per-item `FAILED` results for the first two; track a `has_failures` flag.
4. If `has_failures` is false at the end of the device loop body, emit one `PASSED` result for the device.

For scalar (single-value-per-device) jobs, skip the `has_failures` accumulator - emit `FAILED` or `PASSED` directly.

## Variations by parameter cardinality

The reference example above uses the **single-keyed dict** shape. The other shapes follow the same skeleton with mechanical changes:

### Scalar

```python
class IosVersionDeviceParameters(TypedDict):
    value: str

class IosVersionParameters(TypedDict):
    devices: dict[str, IosVersionDeviceParameters]
```

`compare_state` does a single equality check per device and emits one result.

### Double-keyed dict

```python
class LldpCapabilitiesDeviceParameters(TypedDict):
    capabilities: dict[str, dict[str, str]]   # interface -> neighbor -> value

class LldpCapabilitiesParameters(TypedDict):
    devices: dict[str, LldpCapabilitiesDeviceParameters]
```

`compare_state` walks two nested loops and uses the `has_failures` accumulator.

### List (existence / membership)

```python
class RouteExistenceDeviceParameters(TypedDict):
    prefixes: list[str]

class RouteExistenceParameters(TypedDict):
    devices: dict[str, RouteExistenceDeviceParameters]
```

`compare_state` checks set membership: each learned prefix must appear in the current observation. There is no value to mismatch against.

## Common pitfalls

- **Don't pass kwargs to `add_result`.** The convention is positional: `add_result(ResultStatus.FAILED, "message")`.
- **Don't skip `add_command_execution`.** The reporting layer relies on it to render raw and parsed output for debugging.
- **Don't put `command` at module scope.** It belongs as a class attribute (`self.command`). Module-level `command = "..."` is an inconsistency in the legacy catalog and should not be reproduced.
- **Don't catch `muninn` parser errors silently.** If parsing fails, let the exception propagate or emit `ResultStatus.ERRORED` explicitly with context. Silent failure makes the job look healthy when it isn't.
- **Don't mutate `context.targets`.** The framework owns target filtering via `check_applicability`. Inside `gather_state` and `compare_state`, treat the targets as read-only.
- **Don't override `setup` or `cleanup`** unless you genuinely need to. The defaults provided by `LearningTestCase` are correct for the vast majority of jobs.

## See also

- [Volatile Parameter Validation](volatile-validation.md) - for attributes that change continuously.
- [Test Plan Specification](../04-test-plan-spec.md) - how to reference a job from a test case.
- [Glossary](../00-glossary.md) - formal definitions of `Job`, `Parameters`, `Test Case`, and related terms.

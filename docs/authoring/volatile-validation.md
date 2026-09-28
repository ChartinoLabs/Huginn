# Volatile Parameter Validation Jobs

A volatile parameter validation job tracks an attribute that changes continuously as a normal consequence of network operation, and asserts the *relationship* between consecutive observations rather than equality against a fixed baseline.

For the design rationale behind this archetype - including why "expected failures" and "re-learning" were rejected as alternatives - read [Volatile Parameters](../design/volatile-parameters.md). This page is the practical guide to writing one.

## When to use this archetype

Use volatile parameter validation when the attribute being validated:

- Changes continuously without any explicit configuration or hardware change. Examples: BGP session uptimes, message counters, keepalive counts, table versions.
- Has a meaningful directional relationship between consecutive observations. Examples: monotonically increasing (counters), recently-reset-after-disruption (uptime drops to a small value after a session reset).

If the attribute is deterministic - meaning you can predict its expected value at any point in the test plan - use [Static Parameter Validation](static-validation.md) instead.

If the attribute is volatile but does not have a clean directional relationship (e.g., TCP ephemeral ports, "last reset reason" strings), the volatile archetype is not the right fit. Consider whether a static parameter with per-scenario reconciliation, an existence check, or a state-marker check is more appropriate.

## Anatomy of a volatile validation job

Volatile jobs are dramatically smaller than static validation jobs because the framework owns the observation chain, comparison, and parameter schema. The author's job is to declare:

1. The narrative class metadata (`DESCRIPTION`, `SETUP`, `PROCEDURE`, `PASS_FAIL_CRITERIA`).
2. The series prefix used to identify this observation stream across phases.
3. How observations are gathered from each target.

A complete reference example follows. The job tracks BGP keepalives sent per neighbor per device.

```python
"""Volatile BGP neighbor test: keepalives sent observation chain."""

from collections.abc import Iterable

import muninn

from huginn import (
    Context,
    Observation,
    OperatorVolatileLearningTestCase,
)

mn = muninn.Muninn()
mn.load_builtin_parsers()


class VerifyBgpNeighborKeepalivesSentIncreasing(OperatorVolatileLearningTestCase):
    """Observation chain for BGP neighbor keepalives sent."""

    DESCRIPTION = (
        "Validate that each BGP neighbor's keepalives sent count satisfies the "
        "expected comparison operator relative to the most recent prior "
        "observation within this run."
    )
    SETUP = (
        "- Devices are reachable over SSH.\n"
        "- The `show ip bgp neighbors` command is supported on applicable targets."
    )
    PROCEDURE = (
        "- Execute `show ip bgp neighbors` on each applicable device.\n"
        "- Parse and extract `neighbors.*.message_stats.keepalives_sent`.\n"
        "- Write observations to the run's observation log and compare against "
        "the most recent prior observation using each device's operator:\n"
        "{% for device, params in parameters.devices.items() %}"
        "  - {{ device }}: `{{ params.operator }}`\n"
        "{% endfor %}"
    )
    PASS_FAIL_CRITERIA = (
        "- Pass when each neighbor's keepalives sent count satisfies the "
        "comparison operator relative to the prior observation.\n"
        "- Pass without comparing when this is the first observation in the run.\n"
        "- Fail if any count violates the comparison operator."
    )

    SERIES_PREFIX = "bgp-neighbor-keepalives-sent"
    command = "show ip bgp neighbors"

    async def gather_observations(
        self,
        context: Context,
    ) -> Iterable[Observation]:
        observations: list[Observation] = []
        for device in context.targets:
            result = await context.broker.execute(
                device,
                self.command,
                use_cache=False,
            )
            parsed = mn.parse(
                os=device.os,
                command=self.command,
                output=result.output,
            )
            context.results.add_command_execution(
                device=device.name,
                command=self.command,
                output=result,
                parsed=parsed,
            )
            for neighbor, data in parsed.get("neighbors", {}).items():
                stats = data.get("message_stats", {})
                value = stats.get("keepalives_sent")
                if value is None:
                    continue
                observations.append(
                    Observation(
                        device=device.name,
                        series_key=neighbor,
                        value=int(value),
                        raw=str(value),
                        extra={"neighbor": neighbor},
                    )
                )
        return observations
```

That is the entire job. There are no message constants, no `TypedDict`s, no `check_command_support`, no `gather_state`, and no `compare_state`. The base class provides all of them.

Running it in learning mode saves only the per-device operator, for example `{"devices": {"r1": {"operator": "gte"}}}`. The first execution in a testing run passes with "r1: observations for bgp-neighbor-keepalives-sent recorded (first in this run, no prior to compare against)". A later execution in the same run fails if a neighbor's count drops.

### Sharing boilerplate across volatile jobs

The example above repeats the `muninn` parse pipeline inside `gather_observations`. If your job package contains many volatile jobs that all use the same parsing pipeline, factor that boilerplate into a package-local intermediate base class that overrides `gather_observations` once and exposes a smaller `extract_observations(device_name, parsed)` hook for subclasses. Volatile jobs in that package then inherit from your intermediate base and only need to declare `SERIES_PREFIX`, `command`, and `extract_observations`.

This is a job-package convention, not a framework requirement. The framework only knows about `OperatorVolatileLearningTestCase` and its `gather_observations` hook.

## What each piece does

### Imports

A volatile job that uses the framework class directly imports:

```python
from collections.abc import Iterable

import muninn  # or whichever parser library you use

from huginn import Context, Observation, OperatorVolatileLearningTestCase
```

If your job package provides its own intermediate base class (see [Sharing boilerplate](#sharing-boilerplate-across-volatile-jobs) above), import that instead and skip the parser imports.

### Class metadata

Same four narrative class attributes as every other archetype: `DESCRIPTION`, `SETUP`, `PROCEDURE`, `PASS_FAIL_CRITERIA`. The `PROCEDURE` attribute may interpolate the active comparison operators via Jinja. The operator is stored per device, so loop over `parameters.devices`, as the reference example does. A bare `{{ parameters.operator }}` renders as an empty string.

### `SERIES_PREFIX`

A string identifying this observation stream. The framework composes the full series identity by combining `SERIES_PREFIX` with the per-observation `series_key` (and the device). This identity must remain stable across every execution that should participate in the same comparison stream - including reconciled post-change variants of the same job.

The convention is `<category>-<subject>-<aspect>`, lowercase and hyphenated:

| Example                      | Series prefix                  |
| ---------------------------- | ------------------------------ |
| BGP neighbor keepalives sent | `bgp-neighbor-keepalives-sent` |
| BGP neighbor uptime          | `bgp-neighbor-uptime`          |
| Device uptime                | `version-uptime`               |
| OSPF database LSA ages       | `ospf-database-lsa-ages`       |

### `command`

The `show` command to execute on each target. As with other archetypes, prefer a class attribute (`self.command`).

### `gather_observations`

An async method. The framework calls it once per execution and expects an iterable of `Observation` objects covering every logical object the job tracks across every applicable target.

`Observation` fields:

- `device` - the device name.
- `series_key` - the per-object identity within this device's contribution to the series. For BGP, this is typically the neighbor address. For OSPF, the LSA ID. For per-device scalars, use the device name or an empty string.
- `value` - the comparable scalar. **Must be an `int`** for operator-based comparisons (`gte`, `lt`, etc.). For duration strings, parse to seconds with `huginn.parse_duration_seconds(...)`.
- `raw` - the human-readable form of the value, recorded in the observation log alongside the comparable scalar. Useful for debugging.
- `extra` - optional dict of additional context attached to the observation in the log. Its keys are merged over `series`, `value`, `raw`, and `device` in the record, so do not reuse those names (see [Common pitfalls](#common-pitfalls)).

Pass `use_cache=False` to `context.broker.execute(...)` in `gather_observations` (see [Bypassing the broker cache](#bypassing-the-broker-cache)).

Skip an observation if the underlying parsed value is missing rather than yielding an `Observation` with a sentinel value.

#### Targets with no observations

The base class only reports on devices that produced at least one observation. A device that yields none records no result at all, and if no device yields anything, the test PASSES with no checks. If an empty result means the job does not apply, or that something is wrong, record it yourself in `gather_observations`. Start the message with the device name:

```python
from huginn import ResultStatus

NO_OBSERVATIONS_REASON = "{device}: no BGP neighbors reported keepalive counters"

# Inside gather_observations, after the per-neighbor loop for a device:
if not device_observations:
    context.results.add_result(
        ResultStatus.NOT_APPLICABLE,
        NO_OBSERVATIONS_REASON.format(device=device.name),
    )
```

Use `ResultStatus.FAILED` instead when the observed objects are expected to exist. `gather_observations` runs only in testing mode, so this does not affect learning.

## Choosing a comparison operator

The operator lives in the parameter file, one per device:

```json
{
  "devices": {
    "r1": {"operator": "gte"},
    "r2": {"operator": "gte"}
  }
}
```

In learning mode, the base class writes the class attribute `DEFAULT_OPERATOR` (`"gte"` unless the job overrides it) for every applicable device. Learning does not call `gather_observations`, so it records no observations and no series identity. In testing mode, the base class loads the file and applies each device's operator to that device's observations.

The default operator for most volatile attributes is `gte` (greater than or equal to) - counters increment, uptimes grow, table versions advance. Override `DEFAULT_OPERATOR` on the job class only when a different direction is the normal case for the attribute.

The supported operators are:

| Operator | Passes when                                |
| -------- | ------------------------------------------ |
| `gte`    | `current >= prior`                         |
| `gt`     | `current > prior`                          |
| `lt`     | `current < prior`                          |
| `lte`    | `current <= prior`                         |
| `any`    | always (the observation is still recorded) |

A device that is missing from the parameter file always passes. Any other operator value raises `ValueError`, and the test ERRORs.

To use a different operator for one phase boundary, create a post-change variant with [Parameter Reconciliation](../reference/reconcile.md), then hand-edit `devices.<device>.operator` in the variant's copied parameter file. For example, a scenario that resets BGP sessions on `r1` sets `r1` to `lt` (the post-change uptime is *less than* the pre-change uptime). Do not re-learn the variant: re-learning overwrites every device's operator with `DEFAULT_OPERATOR` again.

The `"any"` operator is special - observations are still recorded in the chain, but comparisons always pass. Use `"any"` at phase boundaries where the impact on individual series is heterogeneous (e.g., a disruption that resets some sessions but not others).

## Series identity discipline

Volatile observations are chained by series identity. If you change `SERIES_PREFIX` or the `series_key` shape between executions, the framework will not recognize a continuation and will treat the new identity as the start of a fresh chain. This means:

- **Don't change `SERIES_PREFIX` lightly.** The prefix is not stored in parameter files. It names the run's observation log, `<output_dir>/<SERIES_PREFIX>.jsonl`, so a baseline job and its reconciled variants chain together only while they share it. Renaming it within one variant starts a separate chain for that variant.
- **Compose `series_key` from stable identifiers.** Use neighbor addresses, LSA IDs, interface names - not transient identifiers like TCP ports or session IDs.
- **For per-device scalars, use a stable string.** A common convention is the empty string, since the device dimension is already provided.

## Bypassing the broker cache

Volatile observations must reflect fresh state. Reusing cached output would compare a stale value against a newer one and defeat the purpose of the volatile comparison.

The base class does not bypass the cache for you. `gather_observations` issues its own commands, so pass `use_cache=False` on every `context.broker.execute(...)` call there, as the reference example does. The base `check_command_support` runs the same command with the cache enabled, so without `use_cache=False` the observation would reuse that output, or output cached earlier in the phase.

## Common pitfalls

- **Don't add `check_command_support`, `gather_state`, or `compare_state` overrides** unless you have a genuinely custom comparison scheme. The base class' implementations are correct for almost every case. If you do need a custom scheme that does not fit the single-operator model, see [Custom comparison schemes](#custom-comparison-schemes).
- **Don't use `series`, `value`, `raw`, or `device` as `extra` keys.** `extra` is merged over those fields in the observation record, so `extra={"value": ...}` replaces the value that later comparisons read. The run metadata fields (`timestamp`, `test_id`, `scenario`, `phase`, `test_case_group`) are written last and override `extra`.
- **Don't yield observations whose `value` is not directly comparable with `gte` / `lt`.** If the underlying value is a duration string, parse it to seconds first. If it's a string with no ordinal relationship, this archetype is not the right fit.
- **Don't compose `series_key` from values that change as a side effect of the job's own execution.** The series identity must survive across phase boundaries unchanged.
- **Don't expect the first observation in a run to compare against anything.** It establishes the baseline for the chain. The framework records it and reports PASSED without comparing. Subsequent observations in the same run compare against the most recent prior observation.

## Custom comparison schemes

`OperatorVolatileLearningTestCase` and its parameter types, `OperatorVolatileParameters` and `OperatorVolatileDeviceParameters`, cover the single-operator model. For anything else, such as tolerance bands or per-series operators, inherit from `VolatileLearningTestCase[<YourParameters>]` directly. It owns the observation log and `compare_state`, and leaves the rest to you:

| Hook                                                                | Required | Purpose                                                                            |
| ------------------------------------------------------------------- | -------- | ---------------------------------------------------------------------------------- |
| `SERIES_PREFIX`                                                     | Yes      | Names the observation log. Class definition fails with `TypeError` if it is empty. |
| `gather_state(context)`                                             | Yes      | Returns the parameters to persist in learning mode, in your own schema.            |
| `gather_observations(context)`                                      | Yes      | Returns the current `Observation` objects.                                         |
| `passes_comparison(*, parameters, observation, prior, context)`     | Yes      | Returns `True` if `observation` is acceptable given the `prior` record (a dict).   |
| `check_command_support(context)`                                    | No       | Defaults to treating every target as applicable.                                   |
| `build_first_observation_message(device_name)`                      | No       | Message for a device's PASSED result when it has no prior observation in the run.  |
| `build_success_message(device_name)`                                | No       | Message for a device's PASSED result when all its observations pass.               |
| `build_failure_message(*, device_name, series_key, prior, current)` | No       | Message for each FAILED observation.                                               |

Read [Volatile Parameters](../design/volatile-parameters.md) before designing a custom scheme.

## See also

- [Volatile Parameters](../design/volatile-parameters.md) - design rationale, alternatives considered, and the operator-transition worked example.
- [Static Parameter Validation](static-validation.md) - for attributes whose expected value is deterministic.
- [Parameter Reconciliation](../reference/reconcile.md) - how to create the post-change variants whose operators you then edit.

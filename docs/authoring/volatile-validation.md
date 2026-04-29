# Volatile Parameter Validation Jobs

A volatile parameter validation job tracks an attribute that changes continuously as a normal consequence of network operation, and asserts the *relationship* between consecutive observations rather than equality against a fixed baseline.

For the design rationale behind this archetype — including why "expected failures" and "re-learning" were rejected as alternatives — read [Volatile Parameters](../09-volatile-parameters.md). This page is the practical guide to writing one.

## When to use this archetype

Use volatile parameter validation when the attribute being validated:

- Changes continuously without any explicit configuration or hardware change. Examples: BGP session uptimes, message counters, keepalive counts, table versions.
- Has a meaningful directional relationship between consecutive observations. Examples: monotonically increasing (counters), recently-reset-after-disruption (uptime drops to a small value after a session reset).

If the attribute is deterministic — meaning you can predict its expected value at any point in the test plan — use [Static Parameter Validation](static-validation.md) instead.

If the attribute is volatile but does not have a clean directional relationship (e.g., TCP ephemeral ports, "last reset reason" strings), the volatile archetype is not the right fit. Consider whether a static parameter with per-scenario reconciliation, an existence check, or a state-marker check is more appropriate.

## Anatomy of a volatile validation job

Volatile jobs are dramatically smaller than static validation jobs because the framework owns the observation chain, comparison, and parameter schema. The author's job is to declare:

1. The narrative class metadata (`DESCRIPTION`, `SETUP`, `PROCEDURE`, `PASS_FAIL_CRITERIA`).
2. The series prefix used to identify this observation stream across phases.
3. The show command to execute.
4. How to extract per-object observations from the parsed output.

A complete reference example follows. The job tracks BGP keepalives sent per neighbor per device.

```python
"""Volatile BGP neighbor test: keepalives sent observation chain."""

from collections.abc import Iterable
from typing import Any

from catalog._volatile import Observation, VolatileLearningTestCase


class VerifyBgpNeighborKeepalivesSentIncreasing(VolatileLearningTestCase):
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
        "the most recent prior observation using operator "
        "'{{ parameters.operator }}'."
    )
    PASS_FAIL_CRITERIA = (
        "- Pass when each neighbor's keepalives sent count satisfies the "
        "comparison operator relative to the prior observation.\n"
        "- Skip comparison when this is the first observation in the run.\n"
        "- Fail if any count violates the comparison operator."
    )

    SERIES_PREFIX = "bgp-neighbor-keepalives-sent"
    command = "show ip bgp neighbors"

    def extract_observations(
        self, device_name: str, parsed: dict[str, Any],
    ) -> Iterable[Observation]:
        for neighbor, data in parsed.get("neighbors", {}).items():
            stats = data.get("message_stats", {})
            value = stats.get("keepalives_sent")
            if value is None:
                continue
            yield Observation(
                device=device_name,
                series_key=neighbor,
                value=int(value),
                raw=str(value),
                extra={"neighbor": neighbor},
            )
```

That is the entire job. There are no message constants, no `TypedDict`s, no `check_applicability`, no `gather_state`, and no `compare_state`. The base class provides all of them.

## What each piece does

### Imports

Volatile jobs import only:

```python
from collections.abc import Iterable
from typing import Any

from catalog._volatile import Observation, VolatileLearningTestCase
```

`VolatileLearningTestCase` (the catalog-local subclass) wraps the framework's `huginn.OperatorVolatileLearningTestCase` and adds the `muninn`-aware command execution and parsing pipeline that the rest of the catalog uses. Inherit from this — not from the framework class directly.

### Class metadata

Same four narrative class attributes as every other archetype: `DESCRIPTION`, `SETUP`, `PROCEDURE`, `PASS_FAIL_CRITERIA`. The `PROCEDURE` attribute may interpolate the active comparison operator via Jinja: `{{ parameters.operator }}`.

### `SERIES_PREFIX`

A string identifying this observation stream. The framework composes the full series identity by combining `SERIES_PREFIX` with the per-observation `series_key` (and the device). This identity must remain stable across every execution that should participate in the same comparison stream — including reconciled post-change variants of the same job.

The convention is `<category>-<subject>-<aspect>`, lowercase and hyphenated:

| Example | Series prefix |
|---|---|
| BGP neighbor keepalives sent | `bgp-neighbor-keepalives-sent` |
| BGP neighbor uptime | `bgp-neighbor-uptime` |
| Device uptime | `version-uptime` |
| OSPF database LSA ages | `ospf-database-lsa-ages` |

### `command`

The `show` command to execute on each target. As with other archetypes, prefer a class attribute (`self.command`).

### `extract_observations`

A regular (non-async) method. The base class calls it once per device, after executing `self.command` and parsing with `muninn`. Yield one `Observation` per logical object the job tracks on that device.

`Observation` fields:

- `device` — the device name. Use the `device_name` argument as-is.
- `series_key` — the per-object identity within this device's contribution to the series. For BGP, this is typically the neighbor address. For OSPF, the LSA ID. For per-device scalars, use the device name or an empty string.
- `value` — the comparable scalar. **Must be an `int`** for operator-based comparisons (`gte`, `lt`, etc.). For duration strings, parse to seconds with `huginn.parse_duration_seconds(...)`.
- `raw` — the human-readable form of the value, recorded in the observation log alongside the comparable scalar. Useful for debugging.
- `extra` — optional dict of additional context attached to the observation in the log.

Skip yielding an observation if the underlying parsed value is missing — `extract_observations` returns an `Iterable`, so a `continue` cleanly omits the item.

## Choosing a comparison operator

The operator is part of the *learned* parameter set, not a class attribute. In learning mode, the framework persists the operator alongside the series identity. In testing mode, it loads the operator and applies it to each comparison.

The default operator for most volatile attributes is `gte` (greater than or equal to) — counters increment, uptimes grow, table versions advance.

The operator can be overridden per-scenario via parameter reconciliation. For example, a scenario that resets BGP sessions can reconcile the post-change comparison to use `lt` (the post-change uptime is *less than* the pre-change uptime). See [Parameter Reconciliation](../08-parameter-reconciliation.md).

The `"any"` operator is special — observations are still recorded in the chain, but comparisons always pass. Use `"any"` at phase boundaries where the impact on individual series is heterogeneous (e.g., a disruption that resets some sessions but not others).

## Series identity discipline

Volatile observations are chained by series identity. If you change `SERIES_PREFIX` or the `series_key` shape between executions, the framework will not recognize a continuation and will treat the new identity as the start of a fresh chain. This means:

- **Don't change `SERIES_PREFIX` lightly.** Renaming it breaks parameter files for every test plan that uses the job.
- **Compose `series_key` from stable identifiers.** Use neighbor addresses, LSA IDs, interface names — not transient identifiers like TCP ports or session IDs.
- **For per-device scalars, use a stable string.** A common convention is the empty string, since the device dimension is already provided.

## Why the framework bypasses the broker cache

Volatile jobs always read fresh state. The base class issues commands without using the broker's cache — reusing cached output from an earlier phase would compare a stale value against a newer one and defeat the purpose of the volatile comparison.

You do not need to opt into this behavior. The base class handles it. Do not add `use_cache=False` calls of your own; let the base class own the cache discipline.

## Common pitfalls

- **Don't add `check_applicability`, `gather_state`, or `compare_state` overrides** unless you have a genuinely custom comparison scheme. The base class' implementations are correct for almost every case. If you do override, inherit from the framework's `VolatileLearningTestCase` (not the catalog wrapper) and study `09-volatile-parameters.md` first.
- **Don't yield observations whose `value` is not directly comparable with `gte` / `lt`.** If the underlying value is a duration string, parse it to seconds first. If it's a string with no ordinal relationship, this archetype is not the right fit.
- **Don't compose `series_key` from values that change as a side effect of the job's own execution.** The series identity must survive across phase boundaries unchanged.
- **Don't expect the first observation in a run to compare against anything.** It establishes the baseline for the chain. The framework records it but does not compare. Subsequent observations in the same run compare against the most recent prior observation.

## See also

- [Volatile Parameters](../09-volatile-parameters.md) — design rationale, alternatives considered, and the operator-transition worked example.
- [Static Parameter Validation](static-validation.md) — for attributes whose expected value is deterministic.
- [Parameter Reconciliation](../08-parameter-reconciliation.md) — how scenarios override parameters (including operators) for specific phases.

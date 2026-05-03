# Gate Jobs

A gate job halts test plan execution until the testbed reaches a stable expected state. Gates exist because validation runs faster than infrastructure converges - without one, post-change validation can race convergence and produce false failures.

## When to use this archetype

Use a gate whenever a test plan transitions from a [change job](change.md) to a validation phase, and the change can take measurable time to fully propagate. Common examples:

- After bringing a link down, wait for BGP and OSPF sessions to flap and re-establish over alternate paths before validating the new topology.
- After applying a configuration change, wait for the change to take effect across all relevant devices before validating downstream state.
- After reloading a device, wait for it to come back online and finish initial protocol convergence before validating its post-reload state.

Without a gate, the post-change validation phase may execute before convergence completes. The validation observations would reflect a transient mid-convergence state, and would fail in ways that have nothing to do with the actual change being tested.

If the wait you need is short, fixed, and known in advance, a `asyncio.sleep(...)` inside the change job's verification step may be sufficient. Use a gate when:

- The wait time depends on infrastructure behavior, not on a fixed delay.
- Multiple downstream effects must complete (e.g., BGP and OSPF must both re-converge).
- The plan needs explicit, reportable evidence that the testbed reached the expected state before validation began.

## Anatomy of a gate job

A complete reference example follows. The gate polls BGP summary on each device until each peer matches the expected post-change state, or fails on timeout.

```python
"""Convergence gate: wait for BGP peers to reach expected state."""

import asyncio
import time
from typing import TypedDict

import muninn

from huginn import CommandSupportResult, Context, LearningTestCase, ResultStatus
from huginn.utils.commands import is_command_unsupported

mn = muninn.Muninn()
mn.load_builtin_parsers()

DEFAULT_TIMEOUT = 90
DEFAULT_INTERVAL = 5

NOT_SUPPORTED_REASON = "Device does not support '{command}'"
MISSING_CURRENT_STATE = "{device} is missing current BGP summary state"
PEER_NOT_ESTABLISHED = (
    "{device}'s BGP peer '{neighbor}' has not reached established state - "
    "currently '{current}'."
)
PEER_STATE_MISMATCH = (
    "{device}'s BGP peer '{neighbor}' has not converged - "
    "expected '{expected}' but found '{current}'."
)
GATE_PASSED = "{device}'s BGP peering has converged to expected state"
GATE_TIMEOUT = (
    "{device}'s BGP peering did not converge within {timeout}s. "
    "Remaining issues: {issues}"
)


class BgpPeeringGateDeviceParameters(TypedDict):
    neighbors: dict[str, str]


class BgpPeeringGateParameters(TypedDict):
    timeout: int
    interval: int
    devices: dict[str, BgpPeeringGateDeviceParameters]


class GateBgpPeeringStatus(LearningTestCase[BgpPeeringGateParameters]):
    """Convergence gate that polls BGP summary until peers match expected state."""

    DESCRIPTION = (
        "Wait for BGP peering sessions to converge to the expected "
        "post-change state before proceeding with verification tests."
    )
    SETUP = (
        "- Devices are reachable over SSH.\n"
        "- The `show ip bgp summary` command is supported on applicable targets.\n"
        "- Learned BGP peering gate parameters are available for testing mode."
    )
    PROCEDURE = (
        "- Poll `show ip bgp summary` on each applicable device.\n"
        "- Parse output and compare peer states against expected state.\n"
        "- Repeat every {interval}s until all peers match or {timeout}s elapses."
    )
    PASS_FAIL_CRITERIA = (
        "- Pass when all BGP peer states match expected state.\n"
        "- Fail if peer states do not converge within the configured timeout."
    )

    command = "show ip bgp summary"

    async def check_command_support(self, context: Context) -> CommandSupportResult:
        # Standard idiom - see authoring overview.
        ...

    async def gather_state(self, context: Context) -> BgpPeeringGateParameters:
        devices: dict[str, BgpPeeringGateDeviceParameters] = {}
        for device in context.targets:
            result = await context.broker.execute(
                device, self.command, use_cache=False,
            )
            parsed = mn.parse(
                os=device.os, command=self.command, output=result.output,
            )
            context.results.add_command_execution(
                device=device.name,
                command=self.command,
                output=result,
                parsed=parsed,
            )
            af_data = next(iter(parsed["address_families"].values()))
            neighbors: dict[str, str] = {}
            for neighbor, data in af_data["neighbors"].items():
                neighbors[neighbor] = str(data.get("state_pfxrcd", ""))
            devices[device.name] = {"neighbors": neighbors}
        return {
            "timeout": DEFAULT_TIMEOUT,
            "interval": DEFAULT_INTERVAL,
            "devices": devices,
        }

    async def compare_state(
        self,
        *,
        expected: BgpPeeringGateParameters,
        current: BgpPeeringGateParameters,
        context: Context,
    ) -> None:
        timeout = expected.get("timeout", DEFAULT_TIMEOUT)
        interval = expected.get("interval", DEFAULT_INTERVAL)
        deadline = time.monotonic() + timeout

        while True:
            issues = _check_convergence(expected, current)
            if not issues:
                for device_name in expected["devices"]:
                    context.results.add_result(
                        ResultStatus.PASSED,
                        GATE_PASSED.format(device=device_name),
                    )
                return

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                for device_name, device_issues in issues.items():
                    context.results.add_result(
                        ResultStatus.FAILED,
                        GATE_TIMEOUT.format(
                            device=device_name,
                            timeout=timeout,
                            issues="; ".join(device_issues),
                        ),
                    )
                return

            await asyncio.sleep(min(interval, remaining))
            current = await self.gather_state(context)


def _is_established(state: str) -> bool:
    """A numeric state_pfxrcd value indicates an established BGP session."""
    try:
        int(state)
        return True
    except ValueError:
        return False


def _check_convergence(
    expected: BgpPeeringGateParameters,
    current: BgpPeeringGateParameters,
) -> dict[str, list[str]]:
    """Return per-device issues. Empty dict means converged."""
    issues: dict[str, list[str]] = {}
    for device_name, expected_device in expected["devices"].items():
        current_device = current.get("devices", {}).get(device_name)
        if current_device is None:
            issues[device_name] = [
                MISSING_CURRENT_STATE.format(device=device_name),
            ]
            continue

        device_issues: list[str] = []
        current_neighbors = current_device.get("neighbors", {})
        for neighbor, expected_state in expected_device["neighbors"].items():
            current_state = current_neighbors.get(neighbor, "")
            if _is_established(expected_state):
                if not _is_established(current_state):
                    device_issues.append(
                        PEER_NOT_ESTABLISHED.format(
                            device=device_name,
                            neighbor=neighbor,
                            current=current_state,
                        ),
                    )
            else:
                if current_state != expected_state:
                    device_issues.append(
                        PEER_STATE_MISMATCH.format(
                            device=device_name,
                            neighbor=neighbor,
                            expected=expected_state,
                            current=current_state,
                        ),
                    )
        if device_issues:
            issues[device_name] = device_issues
    return issues
```

## What makes a gate different from validation

Both gate jobs and static validation jobs inherit from `LearningTestCase`. Both override `gather_state` and `compare_state`. The difference is in what `compare_state` does:

| Aspect                 | Static validation                         | Gate                                                                              |
| ---------------------- | ----------------------------------------- | --------------------------------------------------------------------------------- |
| Number of observations | One observation, compared once.           | Multiple observations, polled until convergence.                                  |
| Failure mode           | Drift between learned and current values. | Timeout: convergence did not occur within the configured window.                  |
| Pass mode              | Per-target, after walking learned values. | Per-target, on the first poll where all targets match.                            |
| Tuning knobs           | None (baseline is the parameter).         | `timeout` and `interval` carried as top-level fields in the parameters TypedDict. |

A gate is essentially a validation job in a `while True:` loop with a deadline.

## The convergence-loop skeleton

Every gate's `compare_state` follows this skeleton:

1. Read `timeout` and `interval` from the parameters payload (with sensible defaults).
2. Compute a `deadline = time.monotonic() + timeout`.
3. Loop:
   - Call a module-level `_check_convergence(expected, current) -> dict[str, list[str]]` helper that returns per-device issues. An empty dict means the testbed has converged.
   - On empty issues: emit one `GATE_PASSED` per device and return.
   - If `time.monotonic() >= deadline`: emit one `GATE_TIMEOUT` per device with the unresolved issues and return.
   - Otherwise: `await asyncio.sleep(min(interval, remaining))` and re-call `self.gather_state(context)` to get a fresh observation.

The `_check_convergence` helper is the only piece that varies between gates. The structure of the loop, the deadline arithmetic, and the result-emission pattern are identical.

## Module-level constants

Gate jobs use a slightly different constant set than the other archetypes:

| Constant                              | Purpose                                                                                        |
| ------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `DEFAULT_TIMEOUT`, `DEFAULT_INTERVAL` | Module-level defaults for the polling parameters.                                              |
| `NOT_SUPPORTED_REASON`                | Standard applicability skip reason.                                                            |
| `MISSING_CURRENT_STATE`               | Emitted by `_check_convergence` when a device's current observation is missing entirely.       |
| One or more per-target issue messages | E.g., `PEER_NOT_ESTABLISHED`, `PEER_STATE_MISMATCH`. Composed into the per-device issues list. |
| `GATE_PASSED`, `GATE_TIMEOUT`         | Final per-device results.                                                                      |

Notably, gates do **not** use `MISSING_LEARNED_BASELINE`. A gate's parameters describe an expected post-change state, not a baseline; if the parameters are missing entirely the test plan is misconfigured and the framework will surface that earlier.

## Present vs absent variants

Gates often come in pairs: `gate_*_present` and `gate_*_absent`. The mechanism is identical; only the convergence predicate flips:

- `gate_*_present` waits for an object to appear (e.g., a route is in the table).
- `gate_*_absent` waits for an object to disappear (e.g., a route is no longer in the table).

When writing a new pair, share as much of the message-constant palette and TypedDict shape as possible - only the convergence loop body should differ.

## Choosing `timeout` and `interval`

The parameter TypedDict carries `timeout` and `interval` as top-level fields so test plan authors can tune them per-instance via the parameters file. Pick defaults that reflect typical convergence behavior on the kinds of testbeds the gate will run against:

- **`interval`** - how often the gate polls. Lower values catch convergence sooner but generate more device load. 2–10 seconds is typical.
- **`timeout`** - how long the gate is willing to wait. Set this to a comfortable margin above the worst-case convergence time you expect. Too low produces false-failure noise; too high turns the gate into an opaque hang.

If a particular test plan needs different values than your defaults, the author can override them in the per-test-case parameters file.

## Common pitfalls

- **Don't call the broker without `use_cache=False`.** Each poll must reflect fresh state. Using cached output would compare the same observation against itself across iterations and either pass on the first poll (incorrect) or hang indefinitely.
- **Don't busy-poll.** Always `await asyncio.sleep(...)` between iterations. The `min(interval, remaining)` clamp prevents the last sleep from overshooting the deadline.
- **Don't write per-target convergence loops.** One gate, one polling loop, all targets in parallel. This is what makes a gate scalable to many devices - each iteration reads all targets in one pass.
- **Don't return early from `_check_convergence`.** The helper must compute the full issue set, even if it knows the result will be non-empty. The reported issues are how operators understand *why* a gate timed out.
- **Don't conflate gate semantics with validation semantics.** A gate proves the testbed reached an expected state; it does not prove the *correctness* of that state. Pair the gate with static or volatile validation jobs in the post-change phase to assert correctness.
- **Don't extend the gate's responsibilities.** Gates are deliberately small. If you find yourself adding action steps inside a gate, you are writing a [change](change.md) job. If you find yourself recording per-attribute values for later comparison, you are writing a [validation](static-validation.md) job. Keep the archetypes distinct.

## See also

- [Change Jobs](change.md) - typically run immediately before a gate.
- [Static Parameter Validation](static-validation.md) - typically run immediately after a gate.
- [Test Plan Specification](../04-test-plan-spec.md) - how gates slot into the change-to-validation transition.

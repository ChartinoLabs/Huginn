# Change Jobs

A change job invokes an action against the testbed - applying a configuration change, clearing a session, reloading a device, bringing a link up or down, and so on - and verifies that the action took effect.

## When to use this archetype

Use a change job whenever the test plan needs to *do* something to the testbed, as opposed to *observe* something. Examples of actions a change job might perform include bringing a link up or down, shutting or unshutting an interface, clearing a routing process, applying or removing a configuration block, mismatching or matching MTUs, and reloading a device.

A change job describes the action itself, not the intent behind it. The same job may be invoked in different test plans to introduce a condition or to remove one - the job does not need to know which.

## Anatomy of a change job

A complete reference example follows. The job clears a specific BGP peer and verifies the session resets.

```python
"""Action job: clear a specific BGP peer and verify session reset."""

import asyncio
from typing import TypedDict

import muninn

from huginn import (
    CommandSupportResult,
    Context,
    LearningTestCase,
    ResultStatus,
    parse_duration_seconds,
)
from huginn.utils.commands import is_command_unsupported

mn = muninn.Muninn()
mn.load_builtin_parsers()

NOT_SUPPORTED_REASON = "Device does not support '{command}'"
MISSING_LEARNED_PARAMETERS = (
    "{device} is missing learned BGP peer parameters"
)
MISSING_CURRENT_STATE = "{device} is missing current BGP peer state"
PRECONDITION_FAILED = (
    "{device}'s BGP neighbor {neighbor} is not in Established state "
    "(current state: '{state}') - cannot clear"
)
CLEAR_CONFIRMED = (
    "{device}'s BGP neighbor {neighbor} session was reset successfully - "
    "state duration decreased (before='{before}', after='{after}')"
)
CLEAR_FAILED = (
    "{device}'s BGP neighbor {neighbor} state duration did not reset after "
    "clear (before='{before}', after='{after}')"
)
MISSING_NEIGHBOR = (
    "{device}'s BGP neighbor {neighbor} is missing from current state"
)
NEIGHBOR_DOWN_AFTER_CLEAR = (
    "{device}'s BGP neighbor {neighbor} is in '{state}' state after clear - "
    "session has not yet re-established"
)

_POST_CLEAR_DELAY_SECONDS = 5


class BgpPeerCandidate(TypedDict):
    remote_as: int
    bgp_state: str
    state_duration: str
    description: str


class ClearBgpPeerDeviceParameters(TypedDict):
    neighbors: dict[str, BgpPeerCandidate]


class ClearBgpPeerParameters(TypedDict):
    devices: dict[str, ClearBgpPeerDeviceParameters]


class ChangeClearBgpPeer(LearningTestCase[ClearBgpPeerParameters]):
    """Clear a specific BGP peer and verify the session resets."""

    DESCRIPTION = (
        "Clear selected BGP peer sessions on target devices and verify "
        "each session resets by observing a decrease in state duration."
    )
    SETUP = (
        "- Devices are reachable over SSH.\n"
        "- The `show ip bgp neighbors` command is supported on applicable targets.\n"
        "- Selected BGP neighbors are currently in Established state."
    )
    PROCEDURE = (
        "- Execute `show ip bgp neighbors` on each applicable device.\n"
        "- Verify selected neighbors are Established (precondition).\n"
        "- Execute `clear ip bgp <neighbor>` for each selected peer.\n"
        "- Re-check neighbor state and confirm session reset."
    )
    PASS_FAIL_CRITERIA = (
        "- Pass when each cleared neighbor's state duration resets.\n"
        "- Fail if preconditions are not met or the session does not reset."
    )

    command = "show ip bgp neighbors"

    async def check_command_support(self, context: Context) -> CommandSupportResult:
        # Standard idiom - see authoring overview.
        ...

    async def gather_state(self, context: Context) -> ClearBgpPeerParameters:
        devices: dict[str, ClearBgpPeerDeviceParameters] = {}
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
            # Collect Established neighbors as candidates for the action.
            neighbors: dict[str, BgpPeerCandidate] = {}
            for neighbor, data in parsed["neighbors"].items():
                if data["bgp_state"] == "Established":
                    neighbors[neighbor] = {
                        "remote_as": data["remote_as"],
                        "bgp_state": data["bgp_state"],
                        "state_duration": data.get("state_duration", ""),
                        "description": data.get("description", ""),
                    }
            devices[device.name] = {"neighbors": neighbors}
        return {"devices": devices}

    async def compare_state(
        self,
        *,
        expected: ClearBgpPeerParameters,
        current: ClearBgpPeerParameters,
        context: Context,
    ) -> None:
        for device in context.targets:
            try:
                target_neighbors = expected["devices"][device.name]["neighbors"]
            except KeyError:
                context.results.add_result(
                    ResultStatus.FAILED,
                    MISSING_LEARNED_PARAMETERS.format(device=device.name),
                )
                continue

            try:
                current_neighbors = current["devices"][device.name]["neighbors"]
            except KeyError:
                context.results.add_result(
                    ResultStatus.FAILED,
                    MISSING_CURRENT_STATE.format(device=device.name),
                )
                continue

            # Step 1: validate preconditions.
            preconditions_met = True
            pre_durations: dict[str, str] = {}
            for neighbor in target_neighbors:
                current_nbr = current_neighbors.get(neighbor)
                if current_nbr is None:
                    context.results.add_result(
                        ResultStatus.FAILED,
                        MISSING_NEIGHBOR.format(
                            device=device.name, neighbor=neighbor,
                        ),
                    )
                    preconditions_met = False
                    continue
                pre_durations[neighbor] = current_nbr["state_duration"]
            if not preconditions_met:
                continue

            # Step 2: apply the action.
            for neighbor in target_neighbors:
                await context.broker.execute(
                    device, f"clear ip bgp {neighbor}", use_cache=False,
                )

            # Step 3: wait for the action to settle.
            await asyncio.sleep(_POST_CLEAR_DELAY_SECONDS)

            # Step 4: verify the action took effect.
            verify_result = await context.broker.execute(
                device, self.command, use_cache=False,
            )
            verify_parsed = mn.parse(
                os=device.os, command=self.command,
                output=verify_result.output,
            )
            context.results.add_command_execution(
                device=device.name,
                command=self.command,
                output=verify_result,
                parsed=verify_parsed,
            )

            for neighbor in target_neighbors:
                post_data = verify_parsed["neighbors"].get(neighbor)
                if post_data is None:
                    context.results.add_result(
                        ResultStatus.FAILED,
                        MISSING_NEIGHBOR.format(
                            device=device.name, neighbor=neighbor,
                        ),
                    )
                    continue
                post_state = post_data["bgp_state"]
                post_duration = post_data.get("state_duration", "")
                pre_duration = pre_durations.get(neighbor, "")

                if post_state != "Established":
                    context.results.add_result(
                        ResultStatus.FAILED,
                        NEIGHBOR_DOWN_AFTER_CLEAR.format(
                            device=device.name,
                            neighbor=neighbor,
                            state=post_state,
                        ),
                    )
                    continue

                if (
                    pre_duration
                    and post_duration
                    and parse_duration_seconds(post_duration)
                    < parse_duration_seconds(pre_duration)
                ):
                    context.results.add_result(
                        ResultStatus.PASSED,
                        CLEAR_CONFIRMED.format(
                            device=device.name,
                            neighbor=neighbor,
                            before=pre_duration,
                            after=post_duration,
                        ),
                    )
                else:
                    context.results.add_result(
                        ResultStatus.FAILED,
                        CLEAR_FAILED.format(
                            device=device.name,
                            neighbor=neighbor,
                            before=pre_duration,
                            after=post_duration,
                        ),
                    )
```

## Why a change job inherits from `LearningTestCase`

Change jobs do not "validate" in the sense that static and volatile jobs do, but they still need a parameter file. The parameter file records *which targets the job is eligible to act on*: which BGP peers were Established and therefore eligible to be cleared, which interfaces were up and therefore eligible to be shut down, and so on. The test author then reviews and edits this parameter file to narrow the candidate set down to the targets the job should actually act on at that point in the test plan. This identification-and-curation step is exactly what `LearningTestCase` was built for.

The verbs `gather_state` and `compare_state` describe the interface contract, not the semantic intent:

- `gather_state` - identify candidate targets and capture metadata about them (current state, descriptions, identifiers).
- `compare_state` - execute the action against the curated parameters and verify it took effect.

This overload is intentional. Treat the verb names as fixed by the framework's interface, not as descriptions of what your job does. Use the docstring and message constants to communicate intent.

## The four-step skeleton inside `compare_state`

Every change job's `compare_state` follows the same four-step skeleton:

1. **Resolve targets** - pull the per-device payload out of `expected` (the candidates captured during learning) and `current` (the freshly observed state). Emit `MISSING_LEARNED_PARAMETERS` or `MISSING_CURRENT_STATE` and `continue` on missing data.
2. **Validate preconditions** - for each candidate, confirm it is currently in the state required for the action to be meaningful. Emit `PRECONDITION_FAILED` (or a more specific message) and `continue` to the next device on any precondition failure.
3. **Apply the action** - execute the change. Use `context.broker.execute(device, "<exec command>", use_cache=False)` for exec-mode commands like `clear ip bgp` or `reload`. Use `context.broker.edit(device, "<config block>")` for configuration changes. For non-CLI changes (REST APIs, controller calls), see [Non-CLI change jobs](#non-cli-change-jobs).
4. **Wait, then verify** - sleep for a fixed `_POST_*_DELAY_SECONDS` (or poll for `_MAX_POLL_ATTEMPTS × _POLL_INTERVAL_SECONDS`), then re-execute the show command and confirm the action took effect. Emit `*_CONFIRMED` or `*_FAILED` per target.

Following this skeleton produces jobs that are predictable to read, debug, and modify. Deviating from it makes both reviewing the job and troubleshooting failures more difficult, because readers can no longer rely on the standard structure to locate the action, the precondition check, or the verification step.

## Module-level message constants

Change jobs add a few constants beyond the standard set:

| Family           | Examples                                                                                                              | Purpose                                   |
| ---------------- | --------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| Failure handling | `NOT_SUPPORTED_REASON`, `MISSING_LEARNED_PARAMETERS`, `MISSING_CURRENT_STATE`                                         | Same as static validation.                |
| Precondition     | `PRECONDITION_FAILED`, `MISSING_NEIGHBOR`, `MISSING_INTERFACE`                                                        | Emitted in step 2.                        |
| Action outcome   | `CLEAR_CONFIRMED` / `SHUTDOWN_CONFIRMED` / `RELOAD_CONFIRMED`, `CLEAR_FAILED` / `SHUTDOWN_FAILED` / `RELOAD_FAILED_*` | Emitted in step 4.                        |
| Tuning constants | `_POST_CLEAR_DELAY_SECONDS`, `_POLL_INTERVAL_SECONDS`, `_MAX_POLL_ATTEMPTS`                                           | Private (`_` prefix). Used by step 3 / 4. |

Keep tuning constants as private module-level names. Do not hoist them to class attributes unless the test plan needs to override them per-instance, at which point they belong as top-level fields in the parameters TypedDict alongside `devices` (see [TypedDict shape](#typeddict-shape) below).

## TypedDict shape

Change jobs use a richer per-device payload than static validation, because the captured metadata feeds the action. The outer wrapper still uses `devices: dict[str, ...]`. The inner per-device dict typically contains an `<plural>` key (`neighbors`, `interfaces`, `links`) mapping object identifier to a candidate record. The candidate record carries everything the action needs:

- The current state (used for precondition validation).
- Identifiers required by the action command (route-map names, BGP AS numbers, lab IDs).
- Optional descriptive fields for reporting (`description`, `label`).

If the change job exposes a tuning knob to the test plan author (e.g., `flap_count`, `hold_down_seconds`, `timeout`), add it as a top-level field in the parameters TypedDict alongside `devices`.

## Non-CLI change jobs

Some changes target controllers, REST APIs, or out-of-band orchestration systems rather than the device CLI. A change job that brings a virtual link up or down through a network simulator's API is one example; a change job that toggles a power outlet through a smart PDU's HTTP interface is another.

Non-CLI change jobs follow the same four-step skeleton, but step 3 (apply the action) uses HTTP requests, SDK calls, or other mechanisms instead of `broker.execute(...)`. A few additional patterns apply:

- **Read controller credentials from the testbed.** The controller is itself a `Device` in the testbed YAML, with a connection definition and credentials. Pull them via `context.testbed.devices[<name>]` and `context.testbed.credentials[<name>]`.
- **Wrap blocking I/O in `asyncio.to_thread(...)`.** Synchronous client libraries (e.g., `urllib`, `requests`) must not be called directly inside an async function.
- **Verify via the controller, not the device CLI.** The action's effect is most reliably observed at the controller that performed it, since the device side may take additional time to react.

Otherwise, the structure (TypedDicts, message constants, four-step skeleton in `compare_state`) is identical.

## Common pitfalls

- **Don't put `command` at module scope.** It belongs as a class attribute. Module-level `command = "..."` makes the show command invisible to subclasses and harder to override per-job.
- **Don't skip the precondition step.** If the action assumes a starting state, validate that state explicitly. Skipping the check makes failures look like the action failed when it actually never had a chance to run.
- **Don't boil the ocean with the precondition step.** The precondition is a final, narrowly-scoped safety check on the immediate state required for the action to be meaningful (e.g., "this BGP neighbor is currently Established before we clear it"). It is not the place to bake in pre-change validation. Broader correctness checks belong as atomic [static validation jobs](static-validation.md) in the phase leading up to the change, where they can be reused across scenarios and reported on independently.
- **Don't use a single fixed sleep when the convergence time varies.** If the action's effect is observable within a known window but the exact time varies, use the poll loop pattern (`_POLL_INTERVAL_SECONDS × _MAX_POLL_ATTEMPTS`) and break early on success.
- **Don't poke at framework internals** to work around connection or session lifecycle issues. If a change like a device reload requires evicting and rebuilding broker connections, raise the gap as a framework feature request rather than reaching into private attributes from inside the job.
- **Don't conflate change and gate semantics.** A change job applies an action and verifies that the immediate effect occurred. If the test plan needs to wait for downstream convergence (e.g., wait for BGP sessions to re-establish after the action) before post-change validation runs, that is the [Gate](gate.md) archetype's responsibility, not the change job's.

## See also

- [Gate Jobs](gate.md) - for halting the test plan until convergence completes after a change.
- [Volatile Parameter Validation](volatile-validation.md) - for tracking attributes that the change job's effect will modify.
- [Test Plan Specification](../reference/test-plan.md) - phases, scenarios, and how change jobs slot into the change phase.

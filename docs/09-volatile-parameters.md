# Volatile Parameters

## Overview

Huginn's `LearningTestCase` pattern captures device state during a learning phase and compares it against the same state during a testing phase. This works well for values that remain stable across test plan executions or that transition between well-defined, enumerable states. These are **static parameters**, and they fall into two subcategories:

- **Fixed values** - attributes that do not change unless an explicit configuration or hardware change occurs. Examples include interface descriptions, OSPF costs, inventory serial numbers, BGP ASN configurations, and software versions.
- **Enumerable state values** - attributes that transition between a known set of discrete states, where the expected state can be determined for any given scenario. Examples include interface operational status (`up` / `down`), routing protocol adjacency state (`FULL` / `DOWN`), and BGP peering status (`Established` / `Idle`). A link shutdown scenario changes an interface from `up` to `down`, but both values are concrete, predictable, and can be expressed as static learned parameters for the pre-change and post-change phases respectively.

In both cases, the expected value at any point in the test plan is deterministic and can be captured as a learned parameter.

However, a separate category of device state values changes continuously as a natural consequence of normal network operation. BGP session uptimes, message counters, keepalive counts, and table versions all increment over time without any explicit action. These values may also reset as a side effect of disruptive changes intentionally introduced by the test plan. These are **volatile parameters** - values that are inherently non-deterministic, where the specific value at any given moment depends on how much time has elapsed and what disruptions have occurred since the value was last initialized.

This document describes the problem that volatile parameters introduce, the alternatives that were considered, and the design that addresses both isolated scenario execution and full sequential test plan execution.

## Problem Statement

### Static parameters and shared pre-change groups

Test plans in Huginn are organized into scenarios, each with phases (typically pre-change, change, and post-change). The pre-change and post-change validation phases reference shared test case groups - most commonly a `state-baseline` group - so that every scenario validates the same set of device state expectations.

This works because static parameters represent a stable ground truth. Whether the test plan runs the first scenario or the fifteenth, the expected OSPF cost on an interface is the same value. The shared group with shared parameters can be reused across all scenarios without issue.

### Where volatile parameters break down

Consider a test plan with the following scenarios executed in sequence:

1. **Link shutdown R1-R2** - shuts an interface, validates convergence, normalizes.
2. **OSPF restart R1** - clears the OSPF process on R1, validates recovery.
3. **Device reload R1** - reloads R1, validates it returns to service.

Scenario 2 (`clear ip ospf process` on R1) causes all OSPF adjacencies on R1 to reset. Because BGP sessions in this topology are established over loopback addresses resolved through OSPF, the OSPF disruption cascades into BGP session resets on R1. After reconvergence, the BGP sessions re-establish, but their state has changed:

- **Uptime** drops from days/weeks to minutes.
- **Message counters** (keepalives sent/received, total messages) reset to low values.
- **Table versions** increment past their original baseline values.
- **TCP ports** change as sessions are re-established with new ephemeral ports.
- **Last reset reason** changes from empty to a string describing the disruption.

If the pre-change validation phase of scenario 3 uses the same learned parameters as scenario 1's pre-change phase, it will fail - not because anything is wrong, but because scenario 2 legitimately changed the values that the static parameters expect.

### Two axioms that must hold

A well-structured test plan should satisfy two properties:

1. **Scenario isolation.** Any single scenario should be executable in isolation and produce reliable results. A scenario should not depend on which other scenarios have or have not been executed before it.

2. **Test plan repeatability.** The full test plan should be executable repeatedly, producing consistent results each time, barring actual bugs in the test automation or the product under test.

Static parameters naturally satisfy both axioms because their expected values do not change across scenarios or across test plan executions. Volatile parameters, when treated as static parameters, violate both axioms: sequential execution causes cascading failures in subsequent scenarios, and repeated full-plan execution produces different results because counter values drift.

## Alternatives Considered

### Expected failures (xfail)

One approach is to mark specific tests as "expected to fail" within certain scenarios. If a test fails as expected, it does not count against the overall run status. If it unexpectedly passes, that is surfaced as noteworthy.

This was ruled out because it conflicts with axiom 1 (scenario isolation). A test marked as expected-to-fail within a scenario's post-change group would be correct when the full plan runs sequentially (prior scenarios have reset the counters), but incorrect when the same scenario runs in isolation (the counters haven't been reset by anything, and the test should pass). The annotation is only valid in one execution context, not both.

### Re-learning after disruptions

Another approach is to add a re-learning phase after each disruptive scenario, capturing new parameter values that reflect the post-disruption state. Subsequent scenarios would then compare against the refreshed parameters.

This was ruled out because it conflates two fundamentally different categories of parameters. The overwhelming majority of test cases validate static parameters - values that are deterministic and stable across scenarios. Interface descriptions, OSPF costs, BGP ASN configurations, and similar attributes do not change as a side effect of disruptive scenarios. Re-learning these values after every disruption is redundant: the re-learned values would be identical to the original baseline, yet each scenario would carry its own copy of the parameter files. This creates a proliferation of duplicate parameter sets that adds maintenance burden without adding value.

The small subset of test cases that validate volatile parameters genuinely cannot reuse a single set of learned values across scenarios. But the solution for that subset should not force the entire parameter model to change. Re-learning everything per-scenario treats a targeted problem (volatile values drifting) as a global one (all parameters need refreshing), which is both wasteful and misleading - it obscures which parameters actually changed and why.

The selected design (described below) addresses this by separating volatile parameter tests into their own test case groups, leaving the shared static parameter groups untouched. Only the volatile subset gets per-scenario treatment, while static parameters continue to benefit from a single shared baseline across all scenarios.

Additionally, even if re-learning were scoped to only volatile parameters, the re-learned values would still be time-dependent. A re-learned BGP uptime of 30 seconds captured immediately after a disruption will be wrong by the time the next scenario's pre-change phase executes minutes later. Re-learning captures a point-in-time snapshot of values that are, by definition, continuously changing - which is the same fundamental problem that static learned values have with volatile parameters.

### Event-driven parameter adjustment

A more sophisticated approach: change jobs publish structured events (e.g., "OSPF process cleared on R1 at time T") to a run-scoped event log. Volatile parameter tests subscribe to relevant event types and dynamically adjust their expectations based on what disruptions have occurred.

This was ruled out due to the combinatorial complexity of mapping events to effects. An OSPF restart on R1 resets BGP sessions involving R1, but not sessions between other devices. Whether an OSPF disruption affects BGP at all depends on the network topology, the BGP transport path, and whether alternative IGP routes exist. Encoding this topology-dependent knowledge into event-to-effect mappings makes the test framework brittle and impossible to generalize. In practice, the mapping would only cover a small percentage of real-world edge cases, with the majority of scenarios encountering unmapped indirect effects.

## Design

### Core concept: learn the relationship, not the value

For volatile parameters, the learned parameter is not an absolute value captured at a point in time. Instead, it is a **comparison operator** or other job-defined comparison semantics that describe the expected relationship between consecutive observations of the same value during a test run.

The choice of comparison operator is defined by the volatile job itself, because the job author knows what kind of relationship is meaningful for that specific attribute. For many volatile parameters, this will default to `gte` (greater than or equal to) - under normal operation, uptimes increase, counters increment, and table versions grow. But that choice is local to the job rather than globally determined by the framework. During learning mode, the framework persists the job's selected comparison semantics for later use in testing mode; the specific observed value is never stored in the parameter file.

During testing mode, the framework captures the current value each time the test executes and writes it to the run results as a **runtime artifact**. When the test executes a second time within the same run, it reads its own most recent prior observation, applies the comparison operator, and records the result.

Each runtime observation also carries run-scoped ordering metadata so the framework can determine which observation is the immediate predecessor for a given comparison. Conceptually, this can be treated as a time-step key associated with the observation: later observations in the same run sort after earlier ones, and the most recent prior observation becomes the comparison reference point. This design assumes that the selected ordering metadata remains monotonic for the duration of a run. Pathological cases where wall-clock time jumps backward mid-run are acknowledged but are out of scope for this design and are not handled specially.

Crucially, observations are chained by a stable **observation series identity** defined by the volatile job itself, not by the Huginn test case identifier. This identity must remain constant across every execution that is intended to participate in the same comparison stream, including reconciled test case variants created for specific phases. A reconciled post-change test case may change the comparison operator for a boundary, but it must still append its runtime artifact to the same logical observation series as the corresponding baseline test. For jobs that track multiple logical objects, the series identity may need to be composed from both a job-level metric identity and an object identity within the gathered state (for example, device plus BGP neighbor).

Because volatile comparisons depend on the latest live device state, volatile jobs should gather observations by explicitly bypassing broker cache. Reusing cached command output would risk comparing a fresh observation against stale data from an earlier execution boundary in the same run, which would defeat the purpose of treating the parameter as volatile.

### Runtime observation chain

Each execution of a volatile parameter test within a single run produces an observation. The chain of observations forms the basis for comparison:

```
Scenario 1 pre-change:   observation 1 (captured, no comparison - first execution)
Scenario 1 post-change:  observation 2 (compared against observation 1)
Scenario 2 pre-change:   observation 3 (compared against observation 2)
Scenario 2 post-change:  observation 4 (compared against observation 3)
...
```

This design assumes that each volatile observation series appears at most once within a given phase. In practice, that means a volatile job may be reused across scenarios and phases, but after group expansion and flattening, the same logical volatile series must not be referenced multiple times within a single phase. Huginn may execute different tests in a phase in parallel, but that does not create ambiguity for volatile comparisons as long as each series contributes only one observation per phase boundary. If a plan references the same volatile series more than once in a phase, the resulting comparison order is undefined and the plan should be restructured.

Each comparison applies the operator from the learned parameters. For a test with operator `gte`:

- Observation 2 >= observation 1? The value hasn't decreased since pre-change. Pass.
- Observation 3 >= observation 2? The value hasn't decreased between scenarios. Pass.
- Observation 4 >= observation 3? The value hasn't decreased since the latest pre-change. Pass.

When a disruptive scenario legitimately resets a value (e.g., BGP uptime drops after an OSPF restart), the post-change observation will be less than the pre-change observation. The comparison operator for that specific scenario's post-change group is reconciled to `lt` (less than), following the same reconciliation workflow that already exists for static parameters.

### Separation of static and volatile test groups

Each scenario's pre-change and post-change phases reference two categories of test case groups:

- **Static test case groups** - shared across all scenarios, using absolute learned values. These are the existing `state-baseline` groups.
- **Volatile test case groups** - per-scenario, using comparison operators. These are new groups specific to volatile parameter tests.

The static groups remain unchanged. The volatile groups allow each scenario to carry its own set of comparison operators, reflecting whether that specific scenario's change is expected to disrupt the volatile values.

For example:

```yaml
ospf-restart-r1:
  phases:
    pre-change:
      test_case_groups:
        - state-baseline           # static parameters - shared
        - volatile-baseline        # volatile parameters - comparison operators
    change:
      test_case_groups:
        - action-ospf-restart-r1
    post-change:
      test_case_groups:
        - post-ospf-restart-r1     # reconciled static parameters
        - volatile-post-ospf-restart-r1  # reconciled comparison operators
```

In the `volatile-baseline` group, BGP uptime uses operator `gte`. In `volatile-post-ospf-restart-r1`, the BGP uptime for sessions involving R1 uses operator `lt` (the disruption resets them), while sessions not involving R1 retain `gte`.

### Scenario isolation

When a scenario runs in isolation, the volatile parameter test executes once in pre-change (observation 1, no comparison) and once in post-change (observation 2, compared against observation 1). The comparison reflects only the effect of that scenario's change, with no dependency on prior scenarios.

If a volatile phase is executed without any earlier observation in the same run - for example, by running only a post-change phase or by filtering execution down to an individual volatile test case group - then the volatile comparison has no predecessor to evaluate against. In that situation, the observation is still recorded as a runtime artifact, but the comparison should be reported as skipped for that execution because there is no valid reference point.

### Full plan repeatability

When the full plan runs sequentially, observations chain across scenarios. Each comparison is against the most recent prior observation in the same run, not against a static learned value. Counter resets from prior scenarios do not cause cascading failures because subsequent observations compare against the post-reset values, not the original baseline.

### Operator transitions during sequential execution

A common concern is what happens when the comparison operator changes mid-plan - for example, when the first several scenarios use `gte` for BGP uptime, but a later scenario's post-change group flips it to `lt` because a device reload resets the session. The following worked example traces BGP uptime for a session involving R1 through a sequential test plan:

```
Scenario 1 (link flap R1-R2):
  pre-change:   obs 1 = 2w3d    no prior observation, comparison skipped
  post-change:  obs 2 = 2w3d    operator gte: obs 2 >= obs 1? yes - pass

Scenario 2 (link flap R1-R3):
  pre-change:   obs 3 = 2w3d    operator gte: obs 3 >= obs 2? yes - pass
  post-change:  obs 4 = 2w3d    operator gte: obs 4 >= obs 3? yes - pass

  ...scenarios 3–4 follow the same pattern...

Scenario 5 (device reload R1):
  pre-change:   obs 9 = 2w3d    operator gte: obs 9 >= obs 8? yes - pass
  post-change:  obs 10 = 0:03   operator lt:  obs 10 < obs 9?  yes - pass

Scenario 6 (device reload R2):
  pre-change:   obs 11 = 0:05   operator gte: obs 11 >= obs 10? yes - pass
  post-change:  obs 12 = 0:07   operator gte: obs 12 >= obs 11? yes - pass
```

The critical transition is between scenario 5's post-change and scenario 6's pre-change. Scenario 5's post-change records a BGP uptime of 3 minutes (the session just re-established after the reload). Scenario 6's pre-change, which uses the shared `volatile-baseline` group with operator `gte`, observes 5 minutes. Since 5 minutes is greater than 3 minutes, the comparison passes - even though both values are far below the original baseline of 2w3d.

The comparison operator is scoped to a single phase boundary: the relationship between one observation and its immediate predecessor. The `lt` operator in scenario 5's post-change group only asserts that the value decreases across that specific boundary. Every other boundary in the plan uses `gte`, which holds naturally because time moves the value upward between phases. The observation chain absorbs the reset without any special handling.

### Categories of volatile parameters

Not all volatile parameters use the same comparison operator or assertion strategy. The following categories are illustrative rather than prescriptive: they show common patterns, but each volatile job remains responsible for choosing the comparison semantics that make sense for the attribute it validates.

| Category           | Examples                                     | Default operator | Notes                                                                     |
| ------------------ | -------------------------------------------- | ---------------- | ------------------------------------------------------------------------- |
| Uptime / duration  | BGP neighbor uptime, state duration          | `gte`            | Often flips to `lt` when a disruption resets the session.                 |
| Monotonic counters | Messages sent/received, keepalives           | `gte`            | Often flips to `lt` when a disruption resets the counters.                |
| Version counters   | BGP table version, AF table/neighbor version | `gte`            | Often behaves monotonically within a run and may not require overrides.   |

Some values that currently fail alongside volatile parameters do not fit the comparison operator model and should remain as static parameters with per-scenario reconciliation:

| Value type            | Examples                | Why it doesn't fit                                                                                                                                                                                       |
| --------------------- | ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Ephemeral identifiers | TCP local/foreign ports | No directional relationship between old and new values. Ports are effectively random after session re-establishment.                                                                                     |
| State markers         | Last reset reason       | String values with no ordinal relationship. Expected value after a disruption is a specific string, not a direction.                                                                                     |
| Compound objects      | AF prefix activity      | Contains a mix of monotonic sub-fields (total prefixes, withdraws) and stable gauge fields (current prefixes, bestpath count). Requires decomposition into separate tests or field-level categorization. |

More broadly, the volatile comparison model assumes that the logical object being observed survives from one execution boundary to the next. If an object is intentionally removed, newly created, or replaced in a way that changes its identity, the problem is no longer just "did the value move in the expected direction?" In those cases, separate existence, membership, or static-value tests are usually more appropriate than a volatile comparison for the affected object.

For example, consider a scenario that removes BGP from R1 entirely. A volatile job that tracks BGP session uptime for R1's neighbors is no longer observing the same logical objects after the change, because the sessions themselves are expected to disappear. In that case, the post-change validation should not try to compare uptime directionally across the boundary. Instead, the plan should replace that volatile uptime check with tests that validate the intended new state, such as confirming that BGP is absent from R1's configuration or that the expected BGP neighbors no longer exist.

More generally, it is the responsibility of the test plan author to ensure that a scenario's post-change validation does not continue to run tests that assume a feature or object should still exist when the scenario is explicitly designed to remove it. This is not unique to volatile parameter handling. The same authoring discipline already applies to static parameter tests: if a scenario intentionally removes a feature, the corresponding post-change validation must be updated to assert the new intended state rather than continuing to validate the old one.

## Framework Base Classes

Two volatile base classes are exported from `huginn`:

- **`VolatileLearningTestCase`** — schema-agnostic base owning the
  observation chain mechanics. Subclasses define their own parameter
  schema, `gather_observations`, and `passes_comparison`. Use this when
  a job needs a custom comparison scheme (tolerance bands, per-series
  operators, or anything beyond a single operator key).
- **`OperatorVolatileLearningTestCase`** — intermediate base for the
  common single-operator pattern. Fixes the parameter schema to
  `{"operator": str}`, provides command-based applicability checking,
  operator comparison via `apply_operator`, and an `"any"` operator
  that records observations in the chain but always passes. Subclasses
  declare `SERIES_PREFIX` and `command`, then implement
  `gather_observations` (the parser boundary — the framework does not
  prescribe a parser library).

The helper `parse_duration_seconds` is also exported for jobs that
parse Cisco-style uptime strings (`"5 weeks, 2 days, 13 hours"`,
`"1w2d"`, `"HH:MM:SS"`) into a monotonic integer value.

The `"any"` operator is useful at phase boundaries where the impact on
individual series is heterogeneous — for example, an OSPF restart
resets BGP sessions involving the restarted device but leaves other
sessions untouched, so a single directional operator cannot satisfy
every series at once. Reconciling the operator to `"any"` for that
boundary records the observations in the chain (so subsequent
boundaries still have a prior to compare against) while avoiding a
false failure on series that were not disrupted.

## Related Documents

- [Test Authoring Guide](05-test-authoring.md): `LearningTestCase` base class and execution modes
- [Parameter Reconciliation](08-parameter-reconciliation.md): Reconciliation workflow for post-change parameter overrides
- [Test Plan Specification](04-test-plan-spec.md): Scenario and phase structure
- [Future Considerations](99-future-considerations.md): Additional enhancement ideas

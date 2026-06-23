# Re-learning

Re-learning is a convenience command that selectively refreshes baseline parameters for tests that are failing in a testing run. Rather than re-running the entire test plan in learning mode -- which would overwrite parameters for tests that are already passing -- it targets only the failures and re-learns just those.

## The problem: expected drift between learning and testing

Learned parameters represent device state at a specific point in time. Between when parameters are originally learned and when the test plan is next executed in testing mode, the environment may have changed in expected ways:

- **The testbed was partially configured during initial learning.** Parameters were captured against an incomplete environment -- perhaps BGP peers hadn't been configured yet, or OSPF adjacencies hadn't formed. Now that the testbed is fully built out, those original parameters no longer reflect reality.

- **Time has passed and the environment has evolved.** Changes have been applied to the environment since learning: new routes were added, interfaces were provisioned, software was upgraded. External factors have also shifted state -- the number of routes learned from the Internet has changed, LLDP neighbors have been added or removed as adjacent devices were modified, and so on.

In both cases, the test plan is being run in testing mode (typically in a pre-change or baseline phase where everything is expected to pass), and a subset of tests fail. The failures are not indicating real problems -- they reflect the fact that the learned parameters are stale for those specific tests.

## What re-learning does

The `huginn relearn` command identifies tests that are failing in the most recent testing run and re-runs only those tests in learning mode to capture the current device state as the new expected parameters. Tests that are already passing are left untouched.

This is the key value: you do not need to re-learn the entire phase or test plan. If 300 tests pass and 9 fail, only those 9 are re-learned. The passing tests keep their existing parameters, which are still accurate.

The command also automatically scopes execution to only the scenarios and phases that contained failures. A test ID that appears across many scenarios but only failed in one will only be re-learned in that specific context.

## When to use relearn

Re-learning fits after a testing run where some tests have failed due to expected drift in a baseline or pre-change phase:

```
1. Run testing mode against live testbed    → some tests fail in pre-change
2. Inspect failures (confirm they are expected drift, not real problems)
3. huginn relearn                           → refreshes just those parameters
4. Run testing mode again                   → passes cleanly
```

Common situations where relearn is appropriate:

- First execution after completing testbed buildout, when parameters were learned against an earlier partial configuration.
- Returning to a testbed after a period of inactivity, where expected changes have accumulated.
- After applying planned maintenance or configuration changes that affect baseline state but are not modeled as change-validation scenarios.

## Relationship to reconciliation

Re-learning and [reconciliation](reconciliation.md) both address test failures, but for fundamentally different reasons:

| Concern       | Re-learning                                  | Reconciliation                                          |
| ------------- | -------------------------------------------- | ------------------------------------------------------- |
| **Trigger**   | Expected drift in baseline/pre-change state  | Intentional network change alters post-change state     |
| **Action**    | Overwrites existing parameter files in-place | Creates new test case variants with separate parameters |
| **Scope**     | Same test ID, same parameter file            | New test ID, separate parameter file                    |
| **Lifecycle** | Ongoing maintenance                          | One-time during scenario development                    |
| **Frequency** | As needed when baselines go stale            | Once per change-validation scenario                     |

The key distinction: re-learning refreshes the *same* parameter file because the test's expected behavior hasn't changed -- only the specific values have drifted. Reconciliation creates *new* test variants because the post-change state is structurally different from baseline and both sets of expected values must coexist in the plan.

## Relationship to volatile parameters

Huginn's [volatile parameter](../design/volatile-parameters.md) archetype handles values that are *inherently unstable* -- counters that always increment, timers that always change. Volatile jobs use comparison strategies (e.g., "value increased") rather than exact-match assertions, so they do not fail due to natural change.

Re-learning addresses a different category: values that are *stable in steady state* but have drifted because the environment itself has changed. These are tests using static parameter validation (exact-match) where the expected value was correct at learning time but is no longer correct because the infrastructure evolved.

## When NOT to use relearn

- **Failures indicate a real problem.** If BGP neighbors are unexpectedly down, re-learning would capture the broken state as the new baseline, masking the issue.
- **The test plan structure needs to change.** If the expected post-change state differs from baseline, use reconciliation to create distinct variants rather than overwriting baseline parameters.
- **You haven't inspected the failures.** Always review what failed before re-learning. The command overwrites parameters unconditionally for every failed test it finds.

## See also

- [Reconciliation](reconciliation.md) - creating post-change test variants when expected state differs.
- [Pruning](pruning.md) - removing tests that are not applicable to the current testbed.
- [Execution Modes](execution-modes.md) - learning mode, which relearn invokes under the hood.
- [Volatile Parameters](../design/volatile-parameters.md) - a different approach for values that are inherently unstable.
- [Reference - relearn CLI](../reference/relearn.md) - the command reference with full option details.

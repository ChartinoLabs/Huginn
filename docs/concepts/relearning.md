# Re-learning

Re-learning is a convenience command that refreshes baseline parameters for tests that have drifted from current device state. Rather than re-running the entire test plan in learning mode, it targets only the tests that failed in the most recent testing run and automatically scopes execution to the scenarios and phases that contained those failures.

## The problem: parameters drift over time

Learned parameters represent device state at a point in time. Some values are inherently volatile - they change without any intentional configuration modification:

- **Counters** - OSPF SPF execution counts, BGP message counters, interface error counters.
- **Versions** - BGP table versions increment as routes are processed.
- **Sizes** - File system free space changes as logs accumulate.
- **Timers** - Uptime values, neighbor hold times, session durations.

When these values drift past what the test expects, the test fails. The failure is not a real problem - the device is healthy - but the parameter file is stale.

## What re-learning does

The `huginn relearn` command automates the refresh:

1. Finds the most recent testing run results.
2. Identifies test cases that failed or errored.
3. Re-runs only those tests in learning mode, overwriting their parameter files with current device state.

Crucially, it also scopes execution to only the scenarios and phases that contained failures. A test ID that appears in 50 scenarios but only failed in one will only be re-learned in that one scenario's context, avoiding redundant device connections.

## When to use relearn

Re-learning fits after a routine testing run where a few tests have failed due to parameter drift, not due to a real issue:

```
1. Run testing mode against live testbed    → a few tests fail (drift)
2. Inspect failures (confirm they are drift, not real problems)
3. huginn relearn                           → refreshes just those parameters
4. Run testing mode again                   → passes cleanly
```

This is a runtime maintenance operation. You may run it periodically as part of normal testbed operation, unlike reconciliation (a one-time development operation) or pruning (a one-time onboarding operation).

## Relationship to reconciliation

Re-learning and [reconciliation](reconciliation.md) both address test failures, but for different reasons:

| Concern       | Re-learning                                    | Reconciliation                                   |
| ------------- | ---------------------------------------------- | ------------------------------------------------ |
| **Trigger**   | Parameter drift (counters, versions, timers)   | Intentional network change alters expected state |
| **Action**    | Overwrites existing parameter files in-place   | Creates new test case variants with new parameters |
| **Scope**     | Same test ID, same parameter file              | New test ID, separate parameter file             |
| **Lifecycle** | Ongoing maintenance                            | One-time during scenario development             |
| **Frequency** | As needed after testing runs                   | Once per change-validation scenario              |

The key distinction: re-learning assumes the test *should* still exist with the same ID and the same expected behavior - only the specific parameter values need refreshing. Reconciliation assumes the post-change state is fundamentally different and requires a distinct test variant.

## When NOT to use relearn

Do not use relearn when:

- **Failures indicate a real problem.** If BGP neighbors are down unexpectedly, re-learning would capture "no neighbors" as the new baseline, masking the issue.
- **The test plan structure needs to change.** If an interface was intentionally removed, you need reconciliation (to create a post-change variant) or pruning (to remove the test entirely), not re-learning.
- **You haven't inspected the failures.** Always review what failed before re-learning. The command is a sharp tool - it overwrites parameters unconditionally for any failed test it finds.

## See also

- [Reconciliation](reconciliation.md) - creating post-change test variants when expected state differs.
- [Pruning](pruning.md) - removing tests that are not applicable to the current testbed.
- [Execution Modes](execution-modes.md) - learning mode, which re-learn invokes under the hood.
- [Reference - relearn CLI](../reference/relearn.md) - the command reference with full option details.

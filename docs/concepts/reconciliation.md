# Reconciliation

Reconciliation is a convenience command used during test plan development. It automates the creation of post-change parameter variants so you don't have to manually duplicate test cases and groups when building a change-validation scenario.

## Starting point: a change-validation test plan

A typical change-validation scenario has pre-change and post-change phases that reference the same validation groups (at least initially, while the test plan is being built):

```yaml
scenarios:
  link-shutdown-r1r2:
    phases:
      pre-change:
        test_case_groups:
          - ospf-neighbor-baseline
          - bgp-summary-baseline
      shutdown:
        test_case_groups:
          - action-shut-r1r2
      post-shutdown:
        test_case_groups:
          - ospf-neighbor-baseline      # same group as pre-change
          - bgp-summary-baseline        # same group as pre-change
```

Both `pre-change` and `post-shutdown` point to the same groups, which means they reference the same learned parameters.

## What happens when you run this

1. **Pre-change** runs in learning mode and captures baseline parameters - OSPF neighbors, BGP peers, all healthy.
2. **Shutdown** disables the R1-R2 link.
3. **Post-shutdown** runs in testing mode and compares current state against the baseline parameters captured in step 1.

The OSPF tests in `post-shutdown` fail. The parameters say "neighbor 10.1.1.1 exists on GigabitEthernet2" but after the shutdown, that neighbor is gone. This is expected behavior - the link is down - but the test plan has no way to express that the post-change expected state differs from baseline.

## What reconciliation does

The `huginn reconcile` command is a convenience method that creates the post-change variants for you. You run it once during test plan development after you've observed which tests fail due to the intentional change. Reconciliation performs the following tasks:

1. Creates new test case definitions with a phase-specific suffix (e.g., `OSPF-NEIGHBOR-EXISTENCE-post-shutdown`)
2. Creates a reconciled test case group that inherits from the baseline group but swaps in the new variants
3. Copies baseline parameter files as a starting point for the new variants

After reconciliation, you re-learn parameters for just the reconciled variants to capture the actual post-change state. Then you run the full scenario again end-to-end to confirm it passes.

## What the reconciled test plan looks like

The original scenario references baseline groups in the post-change phase:

```yaml
post-shutdown:
  test_case_groups:
    - ospf-neighbor-baseline
```

After reconciliation, it references a reconciled group instead:

```yaml
post-shutdown:
  test_case_groups:
    - ospf-neighbor-baseline-post-shutdown
```

The reconciled group inherits from the baseline, excludes tests within the baseline that fail due to the intentional change, and includes phase-specific variants:

```yaml
test_case_groups:
  ospf-neighbor-baseline-post-shutdown:
    groups:
      - ospf-neighbor-baseline
    exclude_tests:
      - OSPF-NEIGHBOR-EXISTENCE
      - OSPF-NEIGHBOR-STATE
      - OSPF-NEIGHBOR-INTERFACE
      - OSPF-NEIGHBOR-PRIORITY
    tests:
      - OSPF-NEIGHBOR-EXISTENCE-post-shutdown
      - OSPF-NEIGHBOR-STATE-post-shutdown
      - OSPF-NEIGHBOR-INTERFACE-post-shutdown
      - OSPF-NEIGHBOR-PRIORITY-post-shutdown
```

The reconciled variants point to the same job modules as their baseline counterparts - only their parameters differ.

## The reconciliation workflow

This is a development-time workflow. You run it once while building and validating a new scenario, not every time you execute the test plan:

```
1. Run scenario end-to-end             → post-change tests fail (expected)
2. huginn reconcile --phase <phase>    → creates variants + reconciled groups
3. Re-learn the reconciled variants    → captures actual post-change state
4. Run scenario end-to-end again       → passes cleanly
```

Once the reconciled parameters are in place and you've confirmed the scenario passes, the test plan is ready for repeated use without further reconciliation.

## Why not just re-learn everything?

Re-learning the entire baseline would overwrite pre-change parameters with post-change values. Then the pre-change phase would fail instead. The test plan needs *both* sets of parameters - baseline for phases that validate steady state, and reconciled variants for phases that validate post-change state.

Reconciliation preserves this distinction by creating separate parameter files for each phase that needs different expected values, while leaving the baseline parameters untouched.

## See also

- [Test Plan Structure](test-plan-structure.md) - how scenarios, phases, and groups relate.
- [Reference - reconcile CLI](../reference/reconcile.md) - the command reference and full workflow.
- [Reference - prune CLI](../reference/prune.md) - a related command that narrows test scope based on learning results.

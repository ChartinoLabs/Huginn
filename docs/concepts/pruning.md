# Pruning

Pruning is a development-time command that narrows a test plan based on observed learning results. After running in learning mode, some tests return `NOT_APPLICABLE` for certain devices because the device does not support the command, or the command produces no meaningful data. These results indicate that the test plan's scope is broader than what the infrastructure actually requires. Pruning removes that excess automatically.

## The problem: test plans are written broadly

When authoring a test plan, you typically target entire device groups — "all spines", "all leafs", "the full fabric". This is the right starting point because you want comprehensive coverage. But not every test applies to every device:

- A spine running a minimal routing stack has no LLDP neighbors to validate.
- A leaf that does not participate in OSPF has no OSPF state to check.
- A device on an older software version may not support a particular `show` command at all.

If you leave these tests in place, every execution produces predictable N/A results. This creates noise in reports, slows down execution, and makes it harder to distinguish real failures from inapplicable tests that were never going to pass.

## What pruning does

The `huginn prune` command inspects the most recent learning run and modifies the test plan to reflect observed reality:

- **Partially applicable tests** — When some devices return data but others are N/A, the non-applicable devices are added to `target.exclude_devices` on the test case definition. The test remains in the plan but skips those specific devices.
- **Fully non-applicable tests** — When all devices are N/A, the test is removed from its group entirely. It will not run in any future execution against this testbed.
- **Orphaned definitions** (optional) — When a fully non-applicable test is no longer referenced by any group, its test case definition can be deleted from the YAML.

The result is a tighter test plan that only validates what the infrastructure actually supports.

## When to prune

Pruning fits into the test plan development lifecycle at a specific point: after initial learning against a new testbed, before you begin building change-validation scenarios.

```
1. Author test plan (broad scope)
2. Run learning mode against live testbed
3. Prune non-applicable tests          ← here
4. Build change scenarios (with reconciliation)
5. Execute in testing mode
```

You typically prune once when onboarding a new testbed or when testbed composition changes significantly (devices added, removed, or upgraded). It is not a recurring runtime operation — once the plan is narrowed, it stays narrowed until the infrastructure changes.

## Relationship to reconciliation

Pruning and [reconciliation](reconciliation.md) both reshape test scope, but for different reasons:

| Concern | Pruning | Reconciliation |
|---------|---------|----------------|
| **Trigger** | Device does not support the test | Intentional network change alters expected state |
| **Direction** | Narrows scope (removes tests/devices) | Expands scope (creates post-change variants) |
| **Lifecycle** | Before building scenarios | After observing expected failures in a scenario |
| **Frequency** | Once per testbed onboarding | Once per change-validation scenario |

In practice, you prune first to eliminate noise, then reconcile to handle intentional state differences. Both are development-time operations that produce a test plan ready for repeated execution.

## Why not just remove tests manually?

You could edit the YAML by hand, but the prune command provides:

- **Accuracy** — It reads actual learning results rather than relying on human judgment about which devices support which commands.
- **Idempotency** — Running prune a second time against the same results is safe. Already-pruned tests are detected and skipped.
- **Validation** — After applying changes, the command reloads the modified plan to confirm it is still structurally valid.
- **Auditability** — The dry-run mode shows exactly what would change before any files are modified, giving you a chance to review.

For plans with dozens of test cases across many device groups, manual editing is error-prone. Pruning automates the mechanical work of aligning test scope to infrastructure reality.

## See also

- [Reference - prune CLI](../reference/prune.md) — command reference, flags, and detailed YAML examples.
- [Reconciliation](reconciliation.md) — a related concept that creates post-change test variants.
- [Execution Modes](execution-modes.md) — learning mode, which produces the results that prune consumes.
- [Test Plan Structure](test-plan-structure.md) — how test cases, groups, and scenarios relate.

# Authoring Jobs

This section is the practical guide to writing Huginn jobs. It is organized by archetype because each archetype has a distinct shape, and writing one well means following that shape closely.

If you have not yet read [Concepts › Job Archetypes](../concepts/archetypes.md), do that first - it covers what the four archetypes are and why each one exists. The rest of this section assumes you understand which archetype your job belongs to.

## Pages in this section

- [Static Parameter Validation](static-validation.md)
- [Volatile Parameter Validation](volatile-validation.md)
- [Change Jobs](change.md)
- [Gate Jobs](gate.md)

The remainder of this page covers conventions that apply to *every* archetype. The per-archetype pages above pick up where this one leaves off and assume you have read it.

## Conventions shared across all archetypes

Before reading the per-archetype pages, internalize these conventions. They apply universally and are not repeated on every page.

### One job per module

Every job lives in its own Python module containing exactly one job class. The filename and class name follow the archetype's prefix convention:

| Archetype | Filename prefix | Class prefix |
|---|---|---|
| Static parameter validation | `verify_*` | `Verify*` |
| Volatile parameter validation | `verify_*_increasing` (or similar comparison-direction suffix) | `Verify*Increasing` |
| Change | `change_*` (and `change_*_restore` for paired restore jobs) | `Change*` / `Change*Restore` |
| Gate | `gate_*` (often `gate_*_present` or `gate_*_absent`) | `Gate*` |

### Module structure

Every job module follows the same top-to-bottom layout:

1. Module docstring (one line).
2. Standard library imports.
3. Third-party imports (`muninn`, `huginn`).
4. Local package imports.
5. Module-level helper objects (typically `mn = muninn.Muninn(); mn.load_builtin_parsers()`).
6. Module-level message constants (named in `SCREAMING_SNAKE_CASE`, with `{placeholder}` slots).
7. Module-level tuning constants (private, `_LIKE_THIS`).
8. `TypedDict` definitions for the parameters payload.
9. The job class.

Volatile jobs are an exception - they do not need message constants or `TypedDict`s because the framework owns the schema. See [Volatile Parameter Validation](volatile-validation.md).

### Class metadata

Every job class declares four narrative class attributes, in this order:

- `DESCRIPTION` - one or two sentences explaining what the job validates or does.
- `SETUP` - bulleted list of preconditions assumed by the job.
- `PROCEDURE` - bulleted list of steps the job performs. May include inlined Jinja templating to interpolate the parameters payload.
- `PASS_FAIL_CRITERIA` - bulleted list of pass and fail conditions.

These attributes are consumed by the reporting system to generate per-test documentation.

### Recording results

Use `context.results.add_result(ResultStatus.X, message)` (positional arguments) for outcomes. Use `context.results.add_command_execution(...)` for every command executed against the testbed. Both are required for the report to render correctly.

### Cache control

Most jobs read fresh state. Pass `use_cache=False` when calling `context.broker.execute(...)` if the read must reflect a state change that just happened in the same job (post-action verification, gate poll, volatile observation).

### Applicability

Jobs use `check_applicability` to exclude targets before `gather_state` runs. A device is not applicable when it cannot produce meaningful data for the job. There are two standard reasons:

1. **Command not supported.** The device does not recognize the `show` command (e.g., a platform that lacks the feature entirely). This is the baseline check that every job should perform.

2. **Attribute absent from parsed output.** The command succeeds, but the specific field the job needs does not exist in the parsed data. This happens when a platform variant omits certain fields (e.g., `config_register` absent from C9300 `show version` output) or when a feature is simply not configured on the device (e.g., no OSPF authentication, no BGP peer groups). In learning mode, saving empty parameters for these devices creates ambiguity  -  the prune tooling cannot distinguish "the job ran and found nothing" from "the job found data and it was empty." Marking the device as not-applicable makes the distinction explicit.

The standard idiom for reason 1 alone:

```python
async def check_applicability(self, context: Context) -> ApplicabilityResult:
    applicable = []
    not_applicable: dict[str, str] = {}
    for device in context.targets:
        result = await context.broker.execute(device, self.command)
        if is_command_unsupported(result.output):
            not_applicable[device.name] = NOT_SUPPORTED_REASON.format(command=self.command)
            continue
        applicable.append(device)
    return ApplicabilityResult(applicable=applicable, not_applicable=not_applicable)
```

When the job targets a specific parsed field that may be absent, extend the check to also verify the field exists:

```python
async def check_applicability(self, context: Context) -> ApplicabilityResult:
    applicable = []
    not_applicable: dict[str, str] = {}
    for device in context.targets:
        result = await context.broker.execute(device, self.command)
        if is_command_unsupported(result.output):
            not_applicable[device.name] = NOT_SUPPORTED_REASON.format(command=self.command)
            continue
        parsed = mn.parse(os=device.os, command=self.command, output=result.output)
        if "target_field" not in parsed:
            not_applicable[device.name] = MISSING_FIELD_REASON.format(command=self.command)
            continue
        applicable.append(device)
    return ApplicabilityResult(applicable=applicable, not_applicable=not_applicable)
```

For jobs that extract per-item values (e.g., per-interface or per-neighbor), the equivalent check is whether `gather_state` would produce an empty `values` dict for a device. When every item's value is absent in the parsed output, the device has no data for this job and should be not-applicable. This can be checked either in `check_applicability` (by pre-scanning the parsed data) or as a post-gather step in `gather_state`  -  see [Static Parameter Validation § gather_state](static-validation.md#gather_state) for the recommended pattern.

## See also

- [Test Authoring (legacy)](../05-test-authoring.md) - the original authoring document. Material from this page is being migrated into the per-archetype guides.

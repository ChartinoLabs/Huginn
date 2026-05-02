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

### Command Support

Most jobs use `check_command_support` to skip targets where the relevant `show` command is not supported. The standard idiom:

```python
async def check_command_support(self, context: Context) -> CommandSupportResult:
    applicable = []
    not_applicable: dict[str, str] = {}
    for device in context.targets:
        result = await context.broker.execute(device, self.command)
        if is_command_unsupported(result.output):
            not_applicable[device.name] = NOT_SUPPORTED_REASON.format(command=self.command)
            continue
        applicable.append(device)
    return CommandSupportResult(applicable=applicable, not_applicable=not_applicable)
```

Data-level applicability (e.g., a specific parsed field is absent, or per-item extraction yields nothing for a device) is handled in `gather_state`, not `check_command_support`. When `gather_state` determines a device has no meaningful data, it emits a `NOT_APPLICABLE` result via `context.results.add_result()` and omits the device from the returned parameters. See [Static Parameter Validation § gather_state](static-validation.md#gather_state) for the recommended pattern.

## See also

- [Test Authoring (legacy)](../05-test-authoring.md) - the original authoring document. Material from this page is being migrated into the per-archetype guides.

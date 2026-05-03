# Documentation Style Guide

This page defines the writing conventions for Huginn documentation. Follow these rules when creating or editing pages under `docs/`.

## Structural rules

### Use headings for structural divisions, not bold text

If a piece of text introduces a distinct concept, variant, or category that a reader might want to jump to, it must be a heading (`###`, `####`), not bold inline text. Bold text is appropriate for emphasis within a sentence, but not as a substitute for heading structure.

Headings appear in the table of contents, enable deep linking, and help readers scan the page. Bold text does none of these.

Wrong:

```markdown
**Leaf groups** (groups that directly list test IDs): the test ID is removed.

**Composite groups** (groups that inherit via `groups`): the test ID is added to `exclude_tests`.
```

Right:

```markdown
#### Leaf groups

Groups that directly list test IDs in `tests` have the test ID removed from the list.

#### Composite groups

Groups that inherit from other groups via `groups` have the test ID added to `exclude_tests`.
```

### No numbered headings

Do not prefix headings with numbers to indicate sequence. Headings should describe content, not position. Ordering is already conveyed by the page layout.

Wrong:

```markdown
### 1. Run in learning mode
### 2. Preview changes
### 3. Apply the prune
```

Right:

```markdown
### Run in learning mode
### Preview changes
### Apply the prune
```

If a procedure requires explicit ordering, use a numbered list within a section rather than encoding the sequence into the heading text.

### Heading hierarchy

Use heading levels to reflect the document outline. Do not skip levels (e.g., `##` followed by `####` with no `###` in between).

- `#` -- page title (one per page)
- `##` -- major sections
- `###` -- subsections
- `####` -- sub-subsections (use sparingly)

## Punctuation and typography

### No em-dashes

Do not use the Unicode em-dash character (U+2014). Use a space-surrounded hyphen (` -- `) instead.

This rule is enforced by CI via `tests/test_docs_em_dashes.py`. Pages with em-dashes will fail the test suite.

Wrong: `The command reads results -- then modifies the plan.` (em-dash)

Right: `The command reads results -- then modifies the plan.` (space-hyphen-hyphen-space)

### No smart quotes

Use straight quotes (`"`, `'`), not curly or smart quotes. Most editors default to straight quotes; ensure your editor does not auto-replace them.

## Prose style

### Lead with the outcome, not the mechanism

When describing what a feature does, state the user-visible outcome first, then explain the mechanism if needed.

Wrong: `The framework iterates context.targets and checks each device against the returned devices dict, marking absent ones as NOT_APPLICABLE, which means the device is excluded from the test.`

Right: `Devices with no applicable data are excluded from the test. The framework detects this by comparing the targets list against the devices returned by gather_state.`

### Avoid LLM writing patterns

When using AI tools to draft documentation, watch for and correct these common patterns:

- **Bold-as-heading** -- covered above. If the bold text could have been a heading, make it one.
- **Redundant lead-in sentences** -- phrases like "Let's take a look at..." or "In this section, we will explore..." add no information. Start with the content.
- **Over-qualification** -- phrases like "It is important to note that" or "It should be noted that" can almost always be deleted without changing the meaning.
- **Trailing summaries** -- restating what was just explained in a "In summary" paragraph. If the section is well-organized, the reader already understood it.

## Code examples

### Use fenced code blocks with language tags

Always specify the language for syntax highlighting.

````markdown
```yaml
test_cases:
  "1.0.0":
    title: Verify Hostname
    job: catalog.iosxe.version.verify_hostname
```
````

### Use realistic examples

Code examples should use plausible values (real command names, realistic IP addresses, device names that match the documentation context). Avoid placeholder patterns like `foo`, `bar`, `example-1`.

## Cross-references

Link to other documentation pages using relative paths. Include a short description of what the linked page covers so the reader can decide whether to follow the link.

Wrong: `See [here](04-test-plan-spec.md).`

Right: `See [Test Plan Specification - Targeting](04-test-plan-spec.md#targeting) for the full target block schema.`

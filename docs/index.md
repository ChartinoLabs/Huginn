# Huginn

Huginn is a Python-native, async-first test automation framework for validating network infrastructure, servers, and applications. It is named after one of Odin's ravens — dispatched across the world to gather information and report back.

## Why Huginn?

- **Python-native** — Write tests as real Python classes with full IDE support, type hints, and debugging.
- **Async-first** — Concurrent device connections and test execution out of the box.
- **Dual-mode execution** — Learning mode captures baseline state; testing mode detects drift.
- **Plugin-extensible** — Inventory plugins, connection brokers, and reporting hooks are all pluggable.
- **Companion to Muninn** — Pair with the [Muninn](https://chartinolabs.github.io/Muninn/) parser library for structured CLI output parsing.

## Quick example

```python
import muninn
from huginn import Context, LearningTestCase, ResultStatus

mn = muninn.Muninn()
mn.load_builtin_parsers()


class VerifyIosVersion(LearningTestCase):
    """Learn and verify the IOS-XE software version."""

    command = "show version"

    async def gather_state(self, context: Context) -> dict[str, object]:
        devices: dict[str, dict[str, object]] = {}
        for device in context.targets:
            result = await context.broker.execute(device, self.command)
            parsed = mn.parse(os=device.os, command=self.command, output=result.output)
            devices[device.name] = {"value": str(parsed["version"])}
        return {"devices": devices}

    async def compare_state(self, *, expected, current, context: Context) -> None:
        for device in context.targets:
            if expected["devices"][device.name] == current["devices"][device.name]:
                context.results.add_result(ResultStatus.PASSED, f"{device.name}: ok")
            else:
                context.results.add_result(ResultStatus.FAILED, f"{device.name}: drifted")
```

```bash
huginn run -m learning -t testbed.yaml -p test_plan.yaml   # capture baseline
huginn run -m testing  -t testbed.yaml -p test_plan.yaml   # detect drift
```

## Where to start

If you are new to Huginn, read in order:

1. **[Concepts - Overview](concepts/overview.md)** - what the framework does and what it doesn't.
2. **[Concepts - Execution Modes](concepts/execution-modes.md)** - how learning and testing modes work together.
3. **[Concepts - Glossary](concepts/glossary.md)** - the formal lexicon. Most other pages assume you know these terms.
4. **[Concepts - Job Archetypes](concepts/archetypes.md)** - the four shapes a job can take in Huginn.
5. **[Authoring Jobs](authoring/index.md)** - one page per archetype, each with a complete worked example.

If you are extending the framework itself or trying to understand a specific design decision, the **Design** section preserves the original decision documents.

## What lives where

- **Concepts** - what Huginn is, what its pieces are called, and how they fit together.
- **Authoring Jobs** - practical guides for writing new jobs, organized by archetype.
- **Reference** - the formal shape of testbed YAML, test plan YAML, configuration, and the context API.
- **Design** - architecture, design decisions, and rationale documents. Useful when you are trying to understand *why* something is the way it is.

## Status

Huginn is under active development and is not yet open-source. This documentation is a work in progress, being migrated out of the original PRD-style design dump into a structure aimed at readers learning the framework.

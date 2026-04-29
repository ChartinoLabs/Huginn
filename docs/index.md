# Huginn

Huginn is a Python-native, async-first test automation framework for validating network infrastructure, servers, and applications. It is named after one of Odin's ravens - dispatched across the world to gather information and report back.

This site is the working documentation for the framework. Public hosting is intentionally not configured yet; until then, build the site locally with `mkdocs serve` from the repository root.

## Where to start

If you are new to Huginn, read in order:

1. **[Concepts › Overview](01-overview.md)** - what the framework does and what it doesn't.
2. **[Concepts › Glossary](00-glossary.md)** - the formal lexicon. Most other pages assume you know these terms.
3. **[Concepts › Job Archetypes](concepts/archetypes.md)** - the four shapes a job can take in Huginn.
4. **[Authoring Jobs](authoring/index.md)** - one page per archetype, each with a complete worked example.

If you are extending the framework itself or trying to understand a specific design decision, the **Design Notes** section preserves the original decision documents.

## What lives where

- **Concepts** - what Huginn is, what its pieces are called, and how they fit together.
- **Authoring Jobs** - practical guides for writing new jobs, organized by archetype.
- **Specifications** - the formal shape of testbed YAML, test plan YAML, and the test-authoring API.
- **Design Notes** - design decisions, RFCs, and rationale documents. Useful when you are trying to understand *why* something is the way it is.

## Status

Huginn is under active development and is not yet open-source. This documentation is a work in progress, being migrated out of the original PRD-style design dump into a structure aimed at readers learning the framework.

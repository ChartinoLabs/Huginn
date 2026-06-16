# Changelog Fragments

Huginn uses [towncrier](https://towncrier.readthedocs.io/) to manage release notes.
Each pull request should include a changelog fragment file in this directory.

## File Naming

Fragment files follow the pattern `<PR_or_issue>.<type>`:

```txt
changes/123.added
changes/124.fixed
changes/125.changed
changes/126.breaking
changes/127.internal
```

For local changes not tied to a PR number yet, use an orphan fragment with `+`:

```txt
changes/+my-change.internal
```

## Fragment Types

| Type | Description |
|---|---|
| `added` | New features, plugins, or capabilities |
| `changed` | Behavior changes or enhancements to existing features |
| `fixed` | Bug fixes |
| `breaking` | Backward-incompatible changes |
| `internal` | CI/CD, tooling, docs process, refactors, or maintenance work |

## Writing Good Fragments

Each fragment should contain one concise, user-facing statement.
Empty or whitespace-only fragments fail CI.

Good:

```txt
Added NETCONF broker support for edit-config operations.
```

Avoid implementation-heavy details when user impact can be described directly.

## Building a Release Changelog

Run the following command during release prep:

```bash
uv run towncrier build --version X.Y.Z --yes
```

This compiles fragments into `CHANGELOG.md` and removes consumed fragment files.

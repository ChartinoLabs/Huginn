# Package-Based Job References

This document describes the design for referencing test automation jobs from installed Python packages, enabling organizations to maintain reusable job libraries that can be shared across multiple projects.

## Motivation

As test automation matures, organizations accumulate large libraries of reusable jobs — OSPF neighbor verification, BGP peering checks, interface status validation, and so on. These jobs are not specific to any one project or testbed; they encode general validation logic that applies across environments.

Currently, jobs are referenced as file paths relative to the project root:

```yaml
test_cases:
  "1.0.0":
    title: Verify OSPF Neighbors
    job: jobs/verify_ospf_neighbors.py
```

This means every project that needs OSPF validation must either copy the job file or maintain a shared directory. Neither scales well:

- **Copy-paste** leads to drift — bug fixes in one copy don't propagate to others
- **Shared directories** create tight coupling and awkward path management
- **Version pinning** is impossible — there's no way to say "use v2.1 of the OSPF checks"

## Solution: Python Package References

Jobs from installed Python packages are referenced using dot-delimited module paths instead of file paths:

```yaml
test_cases:
  "1.0.0":
    title: Verify OSPF Neighbors
    job: huginn_jobs_network.ospf.verify_neighbors

  "1.1.0":
    title: Verify BGP Peering
    job: huginn_jobs_network.bgp.verify_peering

  "2.0.0":
    title: Verify Interface Status
    job: jobs/verify_interface_status.py  # Local job — file path still works
```

The framework detects whether a `job` value is a file path or a module path and handles each accordingly.

### Detection Logic

The framework distinguishes between local file paths and package module paths:

- **File path**: Contains `/` or ends with `.py` — resolved relative to the project root
- **Module path**: Dot-delimited identifier with no `/` and no `.py` suffix — resolved via Python's import system

```
jobs/verify_ospf.py             → file path (contains /)
jobs.verify_ospf                → module path (dots only)
huginn_jobs_network.ospf.verify → module path (dots only)
```

The `:ClassName` suffix works with both forms:

```yaml
job: jobs/verify_ospf.py:VerifyOSPFNeighbors       # File path + explicit class
job: huginn_jobs_network.ospf.verify:VerifyOSPFNeighbors  # Module path + explicit class
```

When no class is specified, the framework loads the first concrete `TestCase` (or `LearningTestCase`) subclass found in the module, consistent with the existing behavior for file-based jobs.

### Advantages Over Git References

An earlier design considered referencing jobs via git repository URLs and refs. The package-based approach is simpler and more robust:

| Concern | Git References | Package References |
|---------|---------------|-------------------|
| Version pinning | `ref: v2.1.0` (custom) | `huginn-jobs-network>=2.1.0,<3.0.0` (standard) |
| Dependency resolution | Manual, no conflict detection | Handled by `uv`/`pip` |
| Installation | Clone at runtime | Pre-installed via `uv sync` |
| Offline support | Requires network at execution | Works after install |
| IDE support | None (code not in environment) | Full (autocomplete, type checking) |
| Reproducibility | Depends on git state | Lock file guarantees |

## Job Package Structure

A job package is a standard Python package that contains `LearningTestCase` subclasses. There is no special framework-level interface required — any installable package with importable job modules works.

### Example Package Layout

```
huginn-jobs-network/
├── pyproject.toml
├── src/
│   └── huginn_jobs_network/
│       ├── __init__.py
│       ├── ospf/
│       │   ├── __init__.py
│       │   ├── verify_neighbors.py
│       │   ├── verify_interfaces.py
│       │   └── verify_routes.py
│       ├── bgp/
│       │   ├── __init__.py
│       │   ├── verify_peering.py
│       │   └── verify_routes.py
│       └── interfaces/
│           ├── __init__.py
│           └── verify_status.py
```

### Package Configuration

```toml
# huginn-jobs-network/pyproject.toml
[project]
name = "huginn-jobs-network"
version = "2.1.0"
description = "Network validation jobs for Huginn"
requires-python = ">=3.11"
dependencies = [
    "huginn>=1.0.0,<2.0.0",
    "muninn>=1.0.0",
]
```

### Job Implementation

Jobs in packages are identical to local jobs — they inherit from `LearningTestCase` and follow the same patterns:

```python
# src/huginn_jobs_network/ospf/verify_neighbors.py
"""OSPF neighbor validation against learned baseline."""

from typing import TypedDict

import muninn

from huginn import ApplicabilityResult, Context, LearningTestCase, ResultStatus
from huginn.utils.commands import is_command_unsupported

mn = muninn.Muninn()
mn.load_local_parsers()

# ... TypedDict definitions, message templates, LearningTestCase subclass
# Exactly the same structure as a local job.
```

### Installing in a Project

```toml
# Project's pyproject.toml
[project]
dependencies = [
    "huginn>=1.0.0",
    "huginn-jobs-network>=2.1.0,<3.0.0",
]
```

```bash
uv sync  # Jobs are now importable
```

## Test Plan Usage

### Mixing Local and Package Jobs

A single test plan can reference both local file-based jobs and package-based jobs:

```yaml
test_cases:
  # Package jobs — shared across projects
  "1.0.0":
    title: Verify OSPF Neighbors
    job: huginn_jobs_network.ospf.verify_neighbors

  "1.1.0":
    title: Verify BGP Peering
    job: huginn_jobs_network.bgp.verify_peering

  # Local jobs — project-specific
  "3.0.0":
    title: Apply OSPF Configuration Change
    job: jobs/apply_ospf_change.py

  "3.1.0":
    title: Verify Custom Business Logic
    job: jobs/verify_custom_logic.py
```

### Validation

The framework validates job references at startup:

- **File paths**: Checks that the file exists on disk (current behavior)
- **Module paths**: Checks that the module is importable and contains a concrete `TestCase` subclass

Both types of validation errors are reported before any tests execute, consistent with the fail-fast principle.

## Versioning and Compatibility

### Pinning Job Package Versions

Standard Python dependency specifiers control which version of a job package is used:

```toml
dependencies = [
    # Pin to compatible range
    "huginn-jobs-network>=2.1.0,<3.0.0",

    # Or pin exactly for maximum reproducibility
    "huginn-jobs-network==2.1.0",
]
```

The `uv.lock` file ensures reproducible installs across environments.

### Framework Compatibility

Job packages declare their Huginn framework dependency:

```toml
dependencies = [
    "huginn>=1.0.0,<2.0.0",
]
```

If a job package requires a newer framework version than the project uses, `uv`/`pip` will report the conflict at install time — not at test execution time.

## Open Questions

The following questions will be resolved as we build the first job package:

1. **Formal package interface**: Does the framework need a registration mechanism (e.g., entry points) for job packages, or is any importable module with `LearningTestCase` subclasses sufficient?

2. **Job discovery / browsing**: Should the framework provide tooling to list available jobs from installed packages (e.g., `huginn jobs list --package huginn-jobs-network`)?

3. **Parser bundling**: Should job packages bundle their own Muninn parsers, or depend on a separate parser package?

4. **Unit test conventions**: Should job packages follow the same spec-driven test harness pattern documented in the [Unit Testing Automation](08-unit-testing-automation.md) guide?

## Related Documents

- [Test Plan Specification](04-test-plan-spec.md): Test case `job` field definition
- [Architecture](02-architecture.md): Job loading and execution flow
- [Unit Testing Automation](08-unit-testing-automation.md): Testing patterns for jobs

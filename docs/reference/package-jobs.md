# Package-Based Job References

A test case's `job` field can reference a job in an installed Python package as well as a local file. Organizations can keep reusable jobs in versioned packages and share them across projects. This page covers the reference syntax, how references are resolved and validated, and how to build and version a job package.

## Motivation

As test automation matures, organizations accumulate large libraries of reusable jobs - OSPF neighbor verification, BGP peering checks, interface status validation, and so on. These jobs are not specific to any one project or testbed; they encode general validation logic that applies across environments.

A job referenced by file path lives inside the project that uses it:

```yaml
test_cases:
  "1.0.0":
    title: Verify OSPF Neighbors
    job: jobs/verify_ospf_neighbors.py
```

Sharing a file-based job means copying the file into each project or keeping a shared directory. Neither scales well:

- **Copy-paste** leads to drift - bug fixes in one copy don't propagate to others
- **Shared directories** create tight coupling and awkward path management
- **Version pinning** is impossible - there's no way to say "use v2.1 of the OSPF checks"

## Module Path References

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
    job: jobs/verify_interface_status.py  # Local job - file path still works
```

The framework detects whether a `job` value is a file path or a module path and handles each accordingly.

### Detection Logic

The framework splits off an optional `:ClassName` suffix at the last `:`, then classifies the rest of the reference:

- **File path**: contains `/` or ends with `.py`. Resolved relative to the project root, which is the directory `huginn` is run from.
- **Module path**: otherwise, contains a `.` or is a valid Python identifier. Resolved via Python's import system.
- **Anything else** (for example `verify-ospf`) is treated as a file path.

```txt
jobs/verify_ospf.py             -> file path (contains /)
verify_ospf.py                  -> file path (ends with .py)
jobs/verify_ospf                -> file path (contains /, so no file is found)
huginn_jobs_network.ospf.verify -> module path (contains .)
verify_ospf                     -> module path (bare identifier)
```

A bare identifier such as `verify_ospf` is a module path, not a file in the project root. Write `verify_ospf.py` to reference a local file.

Both forms are loaded by executing the module. A file path is imported from its location on disk, and a module path is imported by name, so any top-level code in the job module runs when the reference is resolved.

### Module Paths and sys.path

Module paths are resolved with `importlib.import_module`, so the module must be importable from `sys.path` in the process running `huginn`. In practice, the package must either be installed in the active environment (for example with `uv sync`) or have its parent directory on `PYTHONPATH`.

The project root is not added to `sys.path`. When `huginn` runs as a console script, `sys.path[0]` is the environment's `bin/` directory rather than the working directory. A local `jobs/` directory referenced as `jobs.verify_ospf` fails with `No module named 'jobs'` unless it is installed or on `PYTHONPATH`:

```bash
PYTHONPATH=. uv run huginn run -m testing -t testbed.yaml -p test_plan.yaml
```

Use file paths for jobs that live in the project, and keep module paths for installed job packages.

### Class Selection

The `:ClassName` suffix works with both forms:

```yaml
job: jobs/verify_ospf.py:VerifyOSPFNeighbors       # File path + explicit class
job: huginn_jobs_network.ospf.verify:VerifyOSPFNeighbors  # Module path + explicit class
```

The named class must be an attribute of the module, inherit from `TestCase`, and be concrete.

When no class is specified, the framework loads the first concrete `TestCase` (or `LearningTestCase`) subclass defined in the module. Only classes whose `__module__` is that module are considered, so classes imported from elsewhere are skipped. A job class re-exported from a package's `__init__.py` must be named explicitly:

```yaml
job: huginn_jobs_network.ospf:VerifyOSPFNeighbors  # Re-exported from ospf/__init__.py
```

### Advantages Over Git References

An earlier design considered referencing jobs via git repository URLs and refs. The package-based approach is simpler and more robust:

| Concern               | Git References                 | Package References                             |
| --------------------- | ------------------------------ | ---------------------------------------------- |
| Version pinning       | `ref: v2.1.0` (custom)         | `huginn-jobs-network>=2.1.0,<3.0.0` (standard) |
| Dependency resolution | Manual, no conflict detection  | Handled by `uv`/`pip`                          |
| Installation          | Clone at runtime               | Pre-installed via `uv sync`                    |
| Offline support       | Requires network at execution  | Works after install                            |
| IDE support           | None (code not in environment) | Full (autocomplete, type checking)             |
| Reproducibility       | Depends on git state           | Lock file guarantees                           |

## Job Package Structure

A job package is a standard Python package that contains `LearningTestCase` subclasses. There is no special framework-level interface required - any installable package with importable job modules works.

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
requires-python = ">=3.10"
dependencies = [
    "huginn-framework>=0.2,<1",
    "muninn-parsers>=0.7",
]
```

Huginn is distributed as `huginn-framework` and Muninn as `muninn-parsers`, although both are imported as `huginn` and `muninn`.

### Job Implementation

Jobs in packages are identical to local jobs - they inherit from `LearningTestCase` and follow the same patterns:

```python
# src/huginn_jobs_network/ospf/verify_neighbors.py
"""OSPF neighbor validation against learned baseline."""

from typing import TypedDict

import muninn

from huginn import CommandSupportResult, Context, LearningTestCase, ResultStatus
from huginn.utils.commands import is_command_unsupported

mn = muninn.Muninn()
mn.load_builtin_parsers()

# ... TypedDict definitions, message templates, LearningTestCase subclass
# Exactly the same structure as a local job.
```

### Installing in a Project

```toml
# Project's pyproject.toml
[project]
dependencies = [
    "huginn-framework>=0.2,<1",
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
  # Package jobs - shared across projects
  "1.0.0":
    title: Verify OSPF Neighbors
    job: huginn_jobs_network.ospf.verify_neighbors

  "1.1.0":
    title: Verify BGP Peering
    job: huginn_jobs_network.bgp.verify_peering

  # Local jobs - project-specific
  "3.0.0":
    title: Apply OSPF Configuration Change
    job: jobs/apply_ospf_change.py

  "3.1.0":
    title: Verify Custom Business Logic
    job: jobs/verify_custom_logic.py
```

### Validation

Both forms are resolved the same way: the module is imported and a concrete `TestCase` subclass is selected. A reference fails to resolve when the file does not exist, the module cannot be found, the module raises an exception while it is being imported, or no matching class is found. The import case covers a job that imports a dependency that is not installed, contains a syntax error, or raises an exception at the top level.

`huginn validate` resolves every job reference in the plan and reports each failure as a `planning_error` before any test runs:

```txt
ERROR [planning_error]: 1.0.0: Unable to import job module 'huginn_jobs_network.ospf.verify_neighbors' from 'huginn_jobs_network.ospf.verify_neighbors': No module named 'huginn_jobs_network'
```

`huginn run` does not stop on an unresolvable reference. The affected test case is marked `ERRORED` with error code `planning_error`, and the remaining test cases run as normal. Run `huginn validate` first to catch broken references before a full run.

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
    "huginn-framework>=0.2,<1",
]
```

If a job package requires a newer framework version than the project uses, `uv`/`pip` will report the conflict at install time - not at test execution time.

## Working with Unreleased Fixes

A common scenario when using shared job packages: you discover bugs in multiple jobs, submit fixes via separate pull requests, and need to use those fixes in your project before they're merged and released upstream.

Python's dependency system does not support installing multiple versions of the same package simultaneously. The recommended workflow is to combine your fixes into a single branch and install from that branch temporarily.

### Workflow

**1. You have two open PRs against `huginn-jobs-network`:**

- `fix/bgp-peering-bug` - fixes a comparison error in `bgp/verify_peering.py`
- `fix/ospf-route-detection` - fixes a parsing issue in `ospf/verify_routes.py`

**2. Create a combined branch on your fork:**

```bash
cd huginn-jobs-network
git checkout main
git checkout -b combined-fixes
git merge fix/bgp-peering-bug
git merge fix/ospf-route-detection
git push origin combined-fixes
```

Since bug fixes to individual jobs are typically self-contained within a single file, these merges are almost always conflict-free.

**3. Point your project at the combined branch:**

```toml
# Project's pyproject.toml
dependencies = [
    # Temporary: your fork with both fixes
    "huginn-jobs-network @ git+https://github.com/yourfork/huginn-jobs-network@combined-fixes",
]
```

```bash
uv sync  # Installs from your fork's combined-fixes branch
```

**4. When fixes are released upstream, switch back:**

```toml
dependencies = [
    # Back to normal: released version with fixes included
    "huginn-jobs-network>=2.2.0,<3.0.0",
]
```

### Why This Works

- **Bug fixes are localized.** A fix to `bgp/verify_peering.py` and a fix to `ospf/verify_routes.py` don't touch the same files, so merging the branches is trivial.
- **Standard Python tooling.** The `@ git+https://...@branch` syntax is a standard pip/uv dependency specifier. No framework-level git cloning or special machinery needed.
- **Lock file tracks the exact commit.** `uv.lock` records the resolved commit SHA, ensuring reproducibility even when depending on a branch.
- **Clean transition.** When the upstream release lands, the only change is swapping the dependency line back to a version specifier.

### When This Gets Harder

If your fixes span many files across the same modules and create merge conflicts, the combined branch requires manual conflict resolution. In practice this is rare for job-level bug fixes but more likely for structural refactors. In that case, consider submitting a single PR with both fixes rather than maintaining separate branches.

## Related Documents

- [Test Plan Specification](test-plan.md): Test case `job` field definition
- [Future Considerations - Job Packages](../design/future.md#job-packages): Unresolved questions about job package tooling and conventions
- [Architecture](../design/architecture.md): Job loading and execution flow
- [Unit Testing Automation](../authoring/unit-testing.md): Testing patterns for jobs

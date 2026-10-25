# Catalog Import

## Overview

A catalog is a package of reusable jobs, shared by many test plans. `huginn import` selects the catalog jobs that apply to a testbed, using a scope file that lists the features found on each device. A job applies to a device when it covers one of the device's features and supports the device's operating system.

```bash
huginn import --catalog ./catalog --scope scope.yaml --phase pre-change
```

The command reads three inputs:

- The [catalog index](#catalog-index), which describes each job in the catalog.
- An optional [taxonomy](#taxonomy), which groups subfeatures into features and categories and lists operating system aliases.
- The [scope](#scope), which lists the features found on each device. It comes from a scope file or a [scope provider](#scope-providers).

It adds the selected jobs to the test plan as test cases, and reports each match and each feature that no catalog job covers (a gap). With `--dry-run` it reports the changes without making them. See [CLI Reference - import](cli.md#import) for the options.

Huginn does not decide which features a device runs. The scope comes from you, from another tool that writes a scope file, or from a scope provider plugin, for example one that reads device configurations. Import selects jobs by feature, and a learning run then shows which of them a device actually supports: run `huginn prune` afterwards to remove the rest. See [Pruning Non-Applicable Tests](prune.md).

## Catalog index

The catalog directory, or installed package, holds an index file directly inside it: `index.json`, `index.yaml` or `index.yml`, tried in that order. The index maps each job file, relative to the catalog directory, to a description of the job.

```json
{
  "routing/verify_peers_up.py": {
    "title": "Verify Peers Up",
    "operating_systems": ["alpha-os"],
    "category": "routing",
    "feature": "peering",
    "subfeature": "peer sessions",
    "archetype": "static-validation",
    "framework": "huginn"
  }
}
```

| Field               | Required | Description                                                                                                                     |
| ------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `job`               | no       | The job reference used in the test plan. Defaults to a module path derived from the key and the catalog's package name.         |
| `title`             | no       | Test case title. Defaults to the file name, with `_` turned into spaces.                                                        |
| `operating_systems` | no       | Operating systems the job supports. An entry with none is never selected.                                                       |
| `category`          | no       | Category name. Matched at the `category` level.                                                                                 |
| `feature`           | no       | Feature name. Matched at the `feature` level.                                                                                   |
| `subfeature`        | no       | Subfeature name. Matched at the `subfeature` level, and used to group and tag new test cases.                                   |
| `archetype`         | no       | `static-validation` (default), `volatile-validation`, `change` or `gate`.                                                       |
| `framework`         | no       | When present, entries whose value is not `huginn` are skipped, so one index can describe jobs for more than one test framework. |

Other fields are ignored.

### Job references

When an entry has no `job`, the reference is the catalog package name followed by the key's path, with `/` turned into `.` and the `.py` suffix removed. In a catalog package named `catalog`, the key `routing/verify_peers_up.py` becomes `catalog.routing.verify_peers_up`, which Huginn loads by import. See [Package Jobs](package-jobs.md).

The catalog must then be importable when the test plan runs, for example installed into the same environment as Huginn. A key that is not a relative `.py` path, or whose parts are not valid Python identifiers, needs an explicit `job`.

## Taxonomy

A taxonomy file makes matching broader than exact field values. Without one, a scoped feature only matches catalog entries whose `subfeature` or `feature` equals it, and operating system names must be identical.

`import` reads `taxonomy.yaml`, `taxonomy.yml` or `taxonomy.json` beside the index, or the file given with `--taxonomy`.

```yaml
categories:
  routing:
    features:
      peering: [peer sessions, route tables]
      link state: [area adjacency]
  platform:
    features:
      system: [device health]
operating_systems:
  alpha-os:
    aliases: [alphaos, alpha]
always_include:
  - device health
```

| Key                 | Description                                                                                                                                 |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `categories`        | Each category maps its `features` to lists of subfeature names.                                                                             |
| `operating_systems` | Canonical operating system names, each with optional `aliases`. Scope and catalog names are both replaced by their canonical name to match. |
| `always_include`    | Subfeatures selected on every scoped device whose operating system the job supports, whatever features the device has.                      |

## Scope

The scope file lists each device with its operating system and the features found on it.

```yaml
platform_metadata:
  - device_name: router-1
    os_type: alphaos
    features: [peering, area adjacency]
  - device_name: switch-1
    os_type: beta-os
    features: [bundling]
```

| Field         | Required | Description                                                         |
| ------------- | -------- | ------------------------------------------------------------------- |
| `device_name` | yes      | Device name. With `--target devices`, used as the test case target. |
| `os_type`     | yes      | Operating system name or alias.                                     |
| `features`    | no       | Feature, subfeature or category names found on the device.          |

Other per-device fields are ignored, so scope files produced by other tools can carry extra data.

## Scope providers

A scope provider is a plugin that returns the scope instead of a file. `--scope-provider <name>[:<config>]` selects one, in place of `--scope`:

```bash
huginn import --catalog ./catalog --scope-provider lab-configs:snapshots/2026-10 --dry-run
```

The built-in `file` provider reads a scope file, so `--scope-provider file:scope.yaml` is the same as `--scope scope.yaml`. A relative path is resolved against the current directory.

Other providers are classes registered in the `huginn.scope_providers` entry point group of an installed package:

```toml
# pyproject.toml of the package that provides the scope provider
[project.entry-points."huginn.scope_providers"]
lab-configs = "acme_scope.provider:LabConfigScopeProvider"
```

Huginn constructs the class with `config`, the text after the colon (an empty string when there is none), and calls `resolve_scope`:

```python
from pathlib import Path

from huginn.catalog_import import Scope, ScopedDevice
from huginn.models import Testbed


def find_features(config_file: Path) -> tuple[str, ...]:
    """Return the feature names found in one device configuration."""
    ...  # Your own logic: parse the file, apply your applicability rules.


class LabConfigScopeProvider:
    def __init__(self, config: str) -> None:
        self.snapshot_dir = Path(config)

    def resolve_scope(self, project_root: Path, testbed: Testbed | None) -> Scope:
        devices = []
        for device in testbed.devices.values() if testbed else []:
            features = find_features(self.snapshot_dir / f"{device.name}.cfg")
            devices.append(
                ScopedDevice(name=device.name, os=device.os, features=features)
            )
        return Scope(devices=tuple(devices))
```

`testbed` is the testbed from `--testbed` or `./testbed.yaml`, or `None` when there is none. `resolve_scope` may also be `async`. It must return a `Scope`. If it raises, or returns anything else, the import exits 1 without writing. The scope it returns is checked against the testbed the same way as a scope file; see [Targets and the testbed](#targets-and-the-testbed).

## Matching

Names are compared without regard to case, and `_` matches a space. For each device and each of its features, `import` keeps the catalog entries that support the device's operating system and have a selected archetype, then tries each level in turn:

1. **Subfeature:** entries whose `subfeature` is the feature.
2. **Feature:** entries whose `feature` is the feature, and entries under any subfeature the taxonomy lists for that feature.
3. **Category:** entries whose `category` is the feature, and entries under any subfeature of any feature the taxonomy lists for that category.

The first level with a match is used, and levels broader than `--match-level` are not tried. A feature with no match at any allowed level is a gap. Gaps are reported, and do not make the command fail.

Titles and commands are never searched, so every selection can be traced to a name in the index or the taxonomy.

By default only `static-validation` and `volatile-validation` jobs are selected. `change` and `gate` jobs alter devices or decide whether later phases run, so they are only selected when `--archetype` lists them.

## Writing the test plan

Each selected job becomes one test case:

- **ID:** the child group ID in upper case followed by a counter, for example `CATALOG-IMPORT-PEER-SESSIONS-1`, numbered after the highest counter already in the plan.
- **Target:** see [Targets and the testbed](#targets-and-the-testbed).
- **Tags:** `catalog`, the job's subfeature, and any `--tags`.
- **Group:** one child group per subfeature, named after it, inside the composite group given by `--group`.

The files written are:

| File                                    | Change                                                                                         |
| --------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `test_cases/<group>.yaml`               | New test cases are added.                                                                      |
| `groups/<group>.yaml`                   | Each child group, and the composite group that lists them in `groups`, is created or extended. |
| The file defining `--parent-group`      | The composite group is added to the parent's `groups`.                                         |
| `scenarios.yaml`                        | The composite group is added to each phase named by `--phase`, in every scenario that has it.  |
| The file defining an existing test case | Its `target.os` or `target.devices` is widened (see below).                                    |

```yaml
# groups/catalog-import.yaml
test_case_groups:
  catalog-import-peer-sessions:
    name: peer sessions
    tests:
      - CATALOG-IMPORT-PEER-SESSIONS-1
  catalog-import:
    groups:
      - catalog-import-peer-sessions

# test_cases/catalog-import.yaml
test_cases:
  CATALOG-IMPORT-PEER-SESSIONS-1:
    title: Verify Peers Up
    job: catalog.routing.verify_peers_up
    tags: [catalog, peer sessions]
    target:
      os: [alpha-os]
```

Before writing, the command checks that the plan is a directory, that the parent group is defined under `groups/`, and that a scenarios file exists when `--phase` is given. After writing, it loads the plan again, and exits 1 if it is no longer valid. Rewritten files are written with PyYAML, so comments in them are not kept.

### Existing test cases

A job the test plan already references is never added twice. When the scope selects it for operating systems or devices that its test case's `target.os` or `target.devices` does not list, those values are appended. A test case targeted only by `groups`, or with no target, is left as it is. Import never removes a test case, a target or a group.

Running the same import again on its own output changes nothing. Running it with a larger scope adds the new jobs to the existing child groups and widens the existing targets.

## Targets and the testbed

With `--target os` (the default), `target.os` lists the operating systems of the devices each job was selected for. With `--target devices`, `target.devices` lists the devices instead.

When a testbed is available, from `--testbed` or `./testbed.yaml`:

- Scoped device names are checked against it. With `--target os`, a device the testbed does not define is a warning. With `--target devices` it is an error, because the name would become a target that matches nothing.
- `target.os` uses the `os` the testbed gives each device, so test cases match the testbed even when the scope names operating systems differently. Devices the testbed does not define keep their scope name.

`--target devices` requires a testbed.

## Reports

The text report lists the matched features, the gaps, the jobs already in the plan, the target changes and the new test cases. `--format json` prints the same information as one JSON object:

```json
{
  "group": "catalog-import",
  "phases": [],
  "parent_group": null,
  "matches": [
    {"device": "router-1", "os": "alphaos", "feature": "peering", "level": "feature",
     "jobs": ["catalog.routing.verify_peers_up"]}
  ],
  "gaps": [{"feature": "telemetry", "os": "alphaos", "devices": ["router-1"]}],
  "new_test_cases": [
    {"id": "CATALOG-IMPORT-PEER-SESSIONS-1", "group": "catalog-import-peer-sessions",
     "title": "Verify Peers Up", "job": "catalog.routing.verify_peers_up",
     "tags": ["catalog", "peer sessions"], "target": {"os": ["alphaos"]}}
  ],
  "target_updates": [],
  "skipped_jobs": []
}
```

## Library use

The command is a thin layer over `huginn.catalog_import`, which other tools can call directly:

```python
from pathlib import Path

from huginn.catalog_import import (
    ImportOptions,
    apply_import_plan,
    compute_import_plan,
    load_catalog,
    load_scope,
)
from huginn.loaders import load_test_plan

plan = compute_import_plan(
    load_catalog("catalog"),
    load_scope(Path("scope.yaml")),
    load_test_plan(Path("test_plan")),
    ImportOptions(),
)
print(plan.to_dict())
apply_import_plan(Path("test_plan"), plan)
```

`compute_import_plan` reads and writes no files, so the same inputs always give the same plan. `apply_import_plan` writes it, and `check_import_plan` runs the same checks without writing. Set `ScopedDevice.target_os` to target a device's operating system by a name other than the one matched against the catalog.

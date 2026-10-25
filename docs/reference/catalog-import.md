# Catalog Import

## Overview

A catalog is a package of reusable jobs, shared by many test plans. `huginn import` selects the catalog jobs that apply to a testbed, using a scope file that lists the features found on each device. A job applies to a device when it covers one of the device's features and supports the device's operating system.

```bash
huginn import --catalog ./catalog --scope scope.yaml --dry-run
```

The command reads three inputs:

- The [catalog index](#catalog-index), which describes each job in the catalog.
- An optional [taxonomy](#taxonomy), which groups subfeatures into features and categories and lists operating system aliases.
- The [scope](#scope), which lists the features found on each device.

It reports each match, each feature that no catalog job covers (a gap), and the test cases it would create. In this release `import` only reports, so `--dry-run` is required. See [CLI Reference - import](cli.md#import) for the options.

Huginn does not decide which features a device runs. The scope file comes from you or from another tool, for example one that reads device configurations. Import selects jobs by feature, and a learning run then shows which of them a device actually supports: run `huginn prune` afterwards to remove the rest. See [Pruning Non-Applicable Tests](prune.md).

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

## Matching

Names are compared without regard to case, and `_` matches a space. For each device and each of its features, `import` keeps the catalog entries that support the device's operating system and have a selected archetype, then tries each level in turn:

1. **Subfeature:** entries whose `subfeature` is the feature.
2. **Feature:** entries whose `feature` is the feature, and entries under any subfeature the taxonomy lists for that feature.
3. **Category:** entries whose `category` is the feature, and entries under any subfeature of any feature the taxonomy lists for that category.

The first level with a match is used, and levels broader than `--match-level` are not tried. A feature with no match at any allowed level is a gap. Gaps are reported, and do not make the command fail.

Titles and commands are never searched, so every selection can be traced to a name in the index or the taxonomy.

By default only `static-validation` and `volatile-validation` jobs are selected. `change` and `gate` jobs alter devices or decide whether later phases run, so they are only selected when `--archetype` lists them.

## Planned test cases

Each selected job becomes one test case:

- **ID:** the child group ID in upper case followed by a counter, for example `CATALOG-IMPORT-PEER-SESSIONS-1`, numbered after the highest counter already in the plan.
- **Target:** `target.os` lists the operating systems of the devices the job was selected for, as the scope names them. With `--target devices`, `target.devices` lists the devices instead.
- **Tags:** `catalog`, the job's subfeature, and any `--tags`.
- **Group:** one child group per subfeature, named after it, under the composite group given by `--group`.

A job that the test plan already references is not added again. When the scope selects it for more operating systems or devices than its test case's `target.os` or `target.devices` lists, the report shows the targets that would be added. A test case targeted by `groups`, or with no target, is left as it is. Import never plans to remove a test case or a target.

Running the same import again on its own output plans no changes.

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
```

`compute_import_plan` reads and writes no files, so the same inputs always give the same plan.

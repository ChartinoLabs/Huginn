# Future Considerations

This document captures use cases, architectural questions, and enhancement ideas that are out of scope for the initial MVP but warrant future exploration.

## Production Migration Testing

### Use Case

While Huginn primarily targets pre-production testing workflows, integration with production data models opens the door to production validation scenarios. A key use case is **hardware migration validation** - verifying network state before and after replacing physical devices.

**Example scenario:**

```txt
Catalyst 6500 (192.0.2.10, hostname: core-sw-01)
    ↓ migration
Catalyst 9600 (192.0.2.20, hostname: core-sw-01-new)
```

During hardware migrations:

- The device hostname may change (temporarily or permanently)
- The management IP address may change
- Some state changes are expected (new hardware capabilities, different interface naming)
- Other state should remain consistent (BGP neighbors, OSPF adjacencies, VLAN assignments)

### Problem Statement

The current parameter storage convention keys on test case ID, which implicitly includes per-device state keyed by device name (the testbed key). If the device name changes between pre-migration and post-migration test runs, the framework cannot correlate the "before" and "after" states for comparison.

```txt
parameters/
  3.0.0-pre.json    # Contains state for "core-sw-01"
  3.0.0-post.json   # Contains state for "core-sw-01-new" - no correlation!
```

### Questions to Explore

1. **Device Identity Abstraction**

   - Should devices have a stable logical identifier separate from their testbed key/hostname?
   - How would this affect testbed YAML authoring complexity?
   - Could this be opt-in for migration scenarios only?

2. **Migration Mapping**

   - Could the test plan define explicit device mappings for migration scenarios?
   - Example: `device_mapping: { "core-sw-01": "core-sw-01-new" }`
   - How would this interact with the data model?

3. **Expected State Transformations**

   - Some state changes are expected during migration (interface naming, platform-specific features)
   - How do we express "these differences are acceptable" vs "these differences are failures"?
   - Could transformation rules be defined per-migration type?

4. **Parameter Migration Tooling**

   - Should there be CLI tooling to "migrate" parameters from one device identity to another?
   - `huginn parameters migrate --from core-sw-01 --to core-sw-01-new`

5. **Testbed Versioning**

   - Should the testbed support "before" and "after" snapshots for migration scenarios?
   - How does this interact with inventory plugins that pull live state?

### Potential Approaches

**Approach A: Logical Device Names**
Introduce an optional `logical_name` field that remains stable across migrations:

```yaml
devices:
  core-sw-01-new:
    os: iosxe
    logical_name: core-switch-1  # Stable identifier for parameter correlation
    metadata:
      replaces: core-sw-01       # Documents migration lineage
```

**Approach B: Migration-Aware Test Plans**
Add migration context to test plans:

```yaml
migration:
  mappings:
    core-sw-01: core-sw-01-new
  expected_changes:
    - interface_naming    # Platform-specific interface names may differ
    - hardware_inventory  # New hardware, different modules
```

**Approach C: External Correlation**
Keep the framework simple; handle device correlation externally via:

- Pre-processing testbed files
- Post-processing parameter files
- Custom job logic that understands migration context

### Scale Considerations (Noted, Not Addressed)

Production testing at scale introduces additional concerns:

- Connection pooling limits against production infrastructure
- Rate limiting to avoid impacting production traffic
- Rollback/abort mechanisms if tests detect critical issues
- Integration with change management systems

______________________________________________________________________

## Additional Future Items

*(Placeholder for additional considerations as they arise)*

### Authentication Mechanisms

The MVP supports username/password authentication only. Future releases should consider:

- SSH key authentication
- API token/key authentication
- Certificate-based authentication
- Integration with secrets management systems (HashiCorp Vault, AWS Secrets Manager)

### Custom Report Templates

Support for user-defined report templates was descoped from MVP. Consider:

- Jinja2 template support for HTML reports
- Custom data transformations for report output
- Integration with external reporting systems

### Inventory Plugin Merging

The MVP supports inventory plugins as a complete replacement for the static testbed YAML file. Future releases could support merging plugin inventory with a testbed file:

```toml
[tool.huginn]
inventory_plugin = "huginn-netbox"
inventory_merge = true  # Future: merge with testbed.yaml
```

**Use cases:**

- Plugin provides base device inventory from NetBox
- Testbed file adds lab-specific devices not in NetBox
- Testbed file overrides specific connection parameters for certain devices

**Questions to explore:**

- Conflict resolution strategy (plugin wins? testbed wins? error?)
- Merge granularity (device-level? field-level?)
- Credential merging behavior
- Group membership merging (union? intersection?)

______________________________________________________________________

## Related Documents

- [Overview](../concepts/overview.md): Framework philosophy and scope
- [Test Plan Specification](../reference/test-plan.md): Current test plan schema
- [Testbed Specification](../reference/testbed.md): Current testbed schema

# Test Plan Structure

A Huginn test plan organizes test automation into a hierarchy of four layers: **scenarios**, **phases**, **test case groups**, and **test cases**. Each layer serves a distinct purpose, and together they let a single test plan express complex validation workflows - including change validation with pre/post comparisons.

## The hierarchy

```
Scenario
  └── Phase
        └── Test Case Group
              └── Test Case
```

**Scenarios** define a complete end-to-end validation workflow - for example, shutting down a link and verifying the network converges correctly.

**Phases** are the ordered steps within a scenario. Each phase has dependencies on prior phases and references one or more test case groups to execute.

**Test case groups** are named collections of test cases. They are defined once and reused across phases - the same group of validation tests can run in both pre-change and post-change phases.

**Test cases** are the atomic unit of validation. Each test case has an identifier, a title, and a reference to the job (Python module) that implements it.

## A real example

This is the test plan structure from a change-validation project that shuts down a link between two routers and verifies convergence:

### Scenario

```yaml
scenarios:
  link-shutdown-r1r2:
    name: R1 to R2 Link Shutdown and Recovery
    phases:
      pre-change:
        name: Pre-Change Baseline
        test_case_groups:
          - version-baseline
          - bgp-summary-baseline
          - ospf-neighbor-baseline
          - interface-baseline
      shutdown:
        name: Shut R1 GigabitEthernet2 (R1-R2 link)
        depends_on: [pre-change]
        test_case_groups:
          - action-shut-r1r2
      gate-post-shutdown:
        name: Post-Shutdown Convergence Gate
        depends_on: [shutdown]
        test_case_groups:
          - gate-r1-r2-link-shutdown
      post-shutdown:
        name: Post-Shutdown Verification
        depends_on: [gate-post-shutdown]
        test_case_groups:
          - version-baseline
          - bgp-summary-baseline
          - ospf-neighbor-baseline
          - interface-baseline
      normalize:
        name: Normalize R1 GigabitEthernet2 (R1-R2 link)
        depends_on: [post-shutdown]
        test_case_groups:
          - action-normalize-r1r2
      post-normalize:
        name: Post-Normalize Verification
        depends_on: [normalize]
        test_case_groups:
          - version-baseline
          - bgp-summary-baseline
          - ospf-neighbor-baseline
          - interface-baseline
```

The phases form a dependency chain: `pre-change` -> `shutdown` -> `gate-post-shutdown` -> `post-shutdown` -> `normalize` -> `post-normalize`. Each phase waits for its dependencies to complete before executing.

Notice that `version-baseline`, `bgp-summary-baseline`, `ospf-neighbor-baseline`, and `interface-baseline` appear in three different phases. The test case groups and their test cases are defined once and reused wherever needed.

### Test case groups

```yaml
test_case_groups:
  ospf-neighbor-baseline:
    name: OSPF Neighbor Baseline
    tests:
      - OSPF-NEIGHBOR-EXISTENCE
      - OSPF-NEIGHBOR-STATE
      - OSPF-NEIGHBOR-INTERFACE
      - OSPF-NEIGHBOR-PRIORITY

  bgp-summary-baseline:
    name: BGP Summary Baseline
    tests:
      - BGP-SUMMARY-NEIGHBOR-EXISTENCE
      - BGP-SUMMARY-NEIGHBOR-REMOTE-AS
      - BGP-SUMMARY-NEIGHBOR-STATE
      - BGP-SUMMARY-NEIGHBOR-PREFIXES-RCVD
      - BGP-SUMMARY-ROUTER-ID

  action-shut-r1r2:
    tests:
      - ACTION-SHUT-R1-GI2

  gate-r1-r2-link-shutdown:
    name: R1-R2 Link Shutdown Convergence Gates
    tests:
      - GATE-R1-R2-LINK-SHUTDOWN-OSPF-NEIGHBOR-ABSENT
```

Groups can also nest other groups via the `groups` key, creating composite groups that aggregate multiple smaller groups into one:

```yaml
test_case_groups:
  # Feature-specific leaf groups
  ospf-neighbor-baseline:
    name: OSPF Neighbor Baseline
    tests:
      - OSPF-NEIGHBOR-EXISTENCE
      - OSPF-NEIGHBOR-STATE
      - OSPF-NEIGHBOR-INTERFACE
      - OSPF-NEIGHBOR-PRIORITY

  bgp-summary-baseline:
    name: BGP Summary Baseline
    tests:
      - BGP-SUMMARY-NEIGHBOR-EXISTENCE
      - BGP-SUMMARY-NEIGHBOR-REMOTE-AS
      - BGP-SUMMARY-NEIGHBOR-STATE

  # Composite group that includes both
  routing-baseline:
    name: All Routing Baseline Tests
    groups:
      - ospf-neighbor-baseline
      - bgp-summary-baseline
```

A phase that references `routing-baseline` executes all test cases from both child groups. This means you can add a new OSPF test case to `ospf-neighbor-baseline` once, and it automatically runs everywhere `routing-baseline` is used.

### Test cases

```yaml
test_cases:
  OSPF-NEIGHBOR-EXISTENCE:
    title: OSPF neighbor existence checks
    job: jobs/iosxe/ospf/verify_neighbor_existence.py
    tags: [ospf, existence]
  OSPF-NEIGHBOR-STATE:
    title: OSPF neighbor state matches learned baseline
    job: jobs/iosxe/ospf/verify_neighbor_state.py
    tags: [ospf, value]
  OSPF-NEIGHBOR-INTERFACE:
    title: OSPF neighbor interface matches learned baseline
    job: jobs/iosxe/ospf/verify_neighbor_address.py
    tags: [ospf, value]
  OSPF-NEIGHBOR-PRIORITY:
    title: OSPF neighbor priority matches learned baseline
    job: jobs/iosxe/ospf/verify_neighbor_priority.py
    tags: [ospf, value]
```

Each test case maps an identifier to:

- **title** - human-readable description of what the test validates
- **job** - path to the Python module that implements the test logic
- **tags** - optional labels for filtering and reporting

## File organization

A test plan can be a single YAML file or a directory of files. For large test plans, the directory approach keeps things manageable:

```
test_plan/
  scenarios.yaml          # scenario and phase definitions
  groups/
    baseline.yaml         # validation test case groups
    actions.yaml          # change action groups
    gates.yaml            # gate groups
  test_cases/
    ospf.yaml             # OSPF test case definitions
    bgp.yaml              # BGP test case definitions
    interface.yaml        # interface test case definitions
    version.yaml          # version/platform test case definitions
    actions.yaml          # change action test case definitions
    gates.yaml            # gate test case definitions
```

Huginn merges all YAML files in the directory into a single test plan at load time. Split files however makes sense for your project - by protocol, by archetype, or by functional area.

## Why this structure matters

The hierarchy enables several patterns that a flat list of tests cannot:

- **Reuse** - The same validation groups run in pre-change, post-change, and post-normalize phases without duplicating test case definitions.
- **Sequencing** - Phase dependencies guarantee that changes happen after baselines are captured, and verification happens after changes complete.
- **Gating** - Gate phases can block subsequent phases if convergence criteria aren't met, preventing validation from running against an infrastructure that hasn't stabilized.
- **Reconciliation** - After a planned change, only the affected parameters need updating. The test plan structure makes it clear which phases use which groups, so reconciliation can target just the post-change variants.
- **Scale** - A test plan with hundreds of test cases stays organized because the hierarchy provides natural grouping boundaries.

## See also

- [Execution Modes](execution-modes.md) - how learning and testing modes interact with phases.
- [Job Archetypes](archetypes.md) - the four types of jobs (validation, volatile, change, gate) that appear in a test plan.
- [Reference - Test Plan Schema](../reference/test-plan.md) - the complete YAML schema reference.

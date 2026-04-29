# Job Archetypes

Huginn jobs fall into four archetypes. Each archetype solves a different validation or orchestration problem, but all four share the same execution interface - the framework treats them uniformly.

The four archetypes are:

- [Static parameter validation](../authoring/static-validation.md)
- [Volatile parameter validation](../authoring/volatile-validation.md)
- [Change](../authoring/change.md)
- [Gate](../authoring/gate.md)

This page explains why each archetype exists, how `LearningTestCase` relates to the archetypes, and where each archetype typically appears in a test plan. For the practical conventions that apply to every archetype - filename and class naming, module layout, class metadata, result recording, applicability - see [Authoring Jobs](../authoring/index.md). For the shape and reference example specific to one archetype, follow the link to that archetype's authoring page.

## Why these four

Each archetype exists because of a distinct, recurring problem:

- **Static parameter validation** is the bread-and-butter use case Huginn was built for. The vast majority of attributes a test plan validates - interface descriptions, OSPF costs, BGP ASN configurations, device serial numbers - are deterministic. They either match a learned baseline or they don't. Most of a typical test plan is static parameter validation.
- **Volatile parameter validation** exists because some attributes change as a normal consequence of network operation. Counters increment, uptimes grow, table versions advance. Treating these as static parameters causes false failures across sequential scenarios and across repeated runs of the same plan. Volatile jobs replace "value equals baseline" with "value satisfies a comparison operator relative to the previous observation in this run."
- **Change jobs** exist because validation alone does not exercise infrastructure. A meaningful test plan introduces conditions and observes how the system responds.
- **Gate jobs** exist because validation runs faster than infrastructure converges. After a change is applied, post-change validation can race convergence and produce false failures. Gates poll until expected conditions are met, halting the plan until the testbed has stabilized.

## Inheritance and naming

Three of the four archetypes (static validation, change, gate) inherit from `LearningTestCase`. The fourth (volatile validation) inherits from `VolatileLearningTestCase`, which is itself a descendant of `LearningTestCase`.

The name `LearningTestCase` is **not an archetype label**. It defines the interface contract - capture-or-compare against learned parameters - that all four archetypes need in some form:

- A static validation job *learns* the absolute expected values and *compares* current values against them.
- A volatile validation job *learns* the comparison operator and *compares* the current observation against the most recent prior observation.
- A change job *learns* which targets are valid candidates for the action (e.g., which BGP peers are currently Established and therefore eligible to be cleared). The test author reviews and edits the resulting parameters to match the intent of the job at that point in the test plan, and the job then *acts* against those parameters when executed in testing mode.
- A gate job *learns* the expected post-change state and *polls* until current state matches.

In every case, "learning mode" captures parameters that "testing mode" subsequently uses. The verbs `gather_state` and `compare_state` describe the interface, not the semantic intent of the job. This is a common point of confusion for new authors.

## How the framework treats them

The framework does not distinguish between the four archetypes at execution time. From the framework's perspective, every job is a `TestCase` (or a subclass of one) with `check_applicability`, `setup`, `test`, and `cleanup` methods, executed inside a phase, against a target set, in either learning or testing mode.

Archetype is a **convention** - a way of organizing how authors think about jobs and how readers find them. The four archetypes have stable shapes, naming conventions, and module layouts, documented on their respective authoring pages.

## Where archetype affects test plan structure

| Archetype | Typical phase placement |
|---|---|
| Static parameter validation | Pre-change and post-change validation phases. Reused across scenarios via shared test case groups. |
| Volatile parameter validation | Pre-change and post-change validation phases. Grouped per-scenario rather than shared, because comparison operators may need scenario-specific reconciliation. See [Volatile Parameters](../09-volatile-parameters.md). |
| Change | Change phase. One or more change jobs apply the scenario's intended action. |
| Gate | Between change and post-change. Halts the plan until convergence completes, so post-change validation runs against a stable testbed. |

## See also

- [Glossary](../00-glossary.md) - formal definitions of terms used here.
- [Volatile Parameters](../09-volatile-parameters.md) - design rationale for the volatile archetype.
- [Test Plan Specification](../04-test-plan-spec.md) - phases, scenarios, and test case groups.

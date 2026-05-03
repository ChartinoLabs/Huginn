# Unit Testing Test Automation

This document describes patterns and conventions for unit testing Huginn test automation (jobs). Unit tests validate job logic in isolation, without requiring live infrastructure.

## Motivation

Huginn is designed for test plans containing thousands of atomic tests. When test automation is centralized in a reusable catalog serving multiple environments, customers, or testbeds:

- **Changes propagate widely**: A bug in one job affects every test case and environment that uses it
- **Manual verification doesn't scale**: Thousands of tests cannot be manually verified after each change
- **Complex logic requires validation**: Jobs contain non-trivial comparison logic, data model parsing, command support determination, and edge case handling

Unit testing the test automation itself provides:

- Fast feedback during development (no live infrastructure needed)
- Regression detection before deployment
- Documentation of expected behavior through test cases
- Confidence when refactoring or extending jobs

## Pattern Overview

Three complementary patterns enable effective unit testing:

| Pattern                                                         | Purpose                              | Required?                                |
| --------------------------------------------------------------- | ------------------------------------ | ---------------------------------------- |
| [Separation of Concerns](#pattern-1-separation-of-concerns)     | Structure jobs for testability       | Yes - enforced by `LearningTestCase`     |
| [Spec-Driven Test Harness](#pattern-2-spec-driven-test-harness) | Reusable assertions across many jobs | Recommended - scales to hundreds of jobs |
| [Hand-Crafted Fakes](#pattern-3-hand-crafted-fakes)             | Lightweight test doubles             | Yes - needed for any approach            |

These patterns are layered: Pattern 1 is the foundation that makes jobs testable, Pattern 2 provides reusable test infrastructure, and Pattern 3 supplies the lightweight test doubles both patterns rely on.

An optional advanced pattern, [Injectable Data Providers](#advanced-injectable-data-providers), is available for jobs with complex data gathering requirements.

## Pattern 1: Separation of Concerns

The fundamental principle: **separate data gathering from decision logic**.

### The LearningTestCase Interface

Huginn's `LearningTestCase[ParametersType]` base class enforces this separation through its three-phase interface:

```python
class LearningTestCase(Generic[ParametersType]):
    """Base class for jobs with learning/testing lifecycle."""

    async def check_command_support(self, context: Context) -> CommandSupportResult:
        """Determine which targets support the required command(s)."""
        ...

    async def gather_state(self, context: Context) -> ParametersType:
        """Collect current state from devices. Returns typed parameters."""
        ...

    async def compare_state(
        self,
        *,
        expected: ParametersType,
        current: ParametersType,
        context: Context,
    ) -> None:
        """Compare expected (learned) state against current state."""
        ...
```

Each phase has a distinct responsibility:

- **`check_command_support()`**: I/O to probe whether devices support the required command(s), returns `CommandSupportResult`
- **`gather_state()`**: I/O to collect device state, returns a strongly typed `ParametersType` dict
- **`compare_state()`**: Decision logic comparing expected vs current, reports results via `context.results`

This structure makes each phase independently testable.

### Example Job

```python
"""Atomic call-home test: rate limit should match baseline."""

from typing import Any, TypedDict

import muninn

from huginn import CommandSupportResult, Context, LearningTestCase, ResultStatus
from huginn.utils.commands import is_command_unsupported

mn = muninn.Muninn()
mn.load_local_parsers()

NOT_SUPPORTED_REASON = "Device does not support '{command}'"
MISSING_LEARNED_BASELINE = (
    "{device} is missing learned call-home rate limit baseline parameters"
)
MISSING_CURRENT_STATE = "{device} is missing current call-home rate limit state"
VALUE_MISMATCH = (
    "{device}'s call-home rate limit has drifted - we expected "
    "'{expected_value}' but found '{current_value}' instead."
)
VALUE_MATCH = (
    "{device}'s current call-home rate limit ({current_value}) matches "
    "baseline parameters ({expected_value})"
)


class CallHomeRateLimitDeviceParameters(TypedDict):
    value: str


class CallHomeRateLimitParameters(TypedDict):
    devices: dict[str, CallHomeRateLimitDeviceParameters]


class VerifyCallHomeRateLimit(LearningTestCase[CallHomeRateLimitParameters]):
    """Value check for parsed call-home rate limit."""

    DESCRIPTION = "Validate that each device's call-home rate limit remains aligned with the learned baseline."
    command = "show call-home"

    async def check_command_support(self, context: Context) -> CommandSupportResult:
        applicable = []
        not_applicable: dict[str, str] = {}
        for device in context.targets:
            result = await context.broker.execute(device, self.command)
            if is_command_unsupported(result.output):
                not_applicable[device.name] = NOT_SUPPORTED_REASON.format(
                    command=self.command
                )
                continue
            applicable.append(device)
        return CommandSupportResult(applicable=applicable, not_applicable=not_applicable)

    async def gather_state(self, context: Context) -> CallHomeRateLimitParameters:
        devices: dict[str, CallHomeRateLimitDeviceParameters] = {}
        for device in context.targets:
            result = await context.broker.execute(device, self.command)
            parsed = mn.parse(os=device.os, command=self.command, output=result.output)
            context.results.add_command_execution(
                device=device.name, command=self.command, output=result, parsed=parsed,
            )
            value: Any = parsed["settings"]["rate_limit"]
            devices[device.name] = {"value": str(value)}
        return {"devices": devices}

    async def compare_state(
        self,
        *,
        expected: CallHomeRateLimitParameters,
        current: CallHomeRateLimitParameters,
        context: Context,
    ) -> None:
        for device in context.targets:
            try:
                expected_value = expected["devices"][device.name]["value"]
            except KeyError:
                context.results.add_result(
                    ResultStatus.FAILED,
                    MISSING_LEARNED_BASELINE.format(device=device.name),
                )
                continue

            try:
                current_value = current["devices"][device.name]["value"]
            except KeyError:
                context.results.add_result(
                    ResultStatus.FAILED,
                    MISSING_CURRENT_STATE.format(device=device.name),
                )
                continue

            if current_value != expected_value:
                context.results.add_result(
                    ResultStatus.FAILED,
                    VALUE_MISMATCH.format(
                        device=device.name,
                        expected_value=expected_value,
                        current_value=current_value,
                    ),
                )
                continue

            context.results.add_result(
                ResultStatus.PASSED,
                VALUE_MATCH.format(
                    device=device.name,
                    current_value=current_value,
                    expected_value=expected_value,
                ),
            )
```

### Key Principles

1. **`LearningTestCase` enforces separation**: Data gathering (`gather_state`) and decision logic (`compare_state`) are distinct methods with distinct signatures
2. **Strongly typed parameters**: `TypedDict` subclasses define the shape of gathered state, providing type safety without runtime overhead
3. **Module-level message templates**: String constants like `VALUE_MISMATCH` live at module scope, making them easy to reference in test assertions
4. **Command support as a first-class concern**: `check_command_support()` is a separate phase, not buried inside `test()`

### Extracting Pure Validation Functions (Optional)

For additional testability, comparison logic can be extracted into a pure function that returns results rather than calling `context.results` directly:

```python
from collections import NamedTuple


class _ResultRecord(NamedTuple):
    status: ResultStatus
    message: str


def _build_value_results(
    *,
    device_name: str,
    expected: CallHomeRateLimitParameters,
    current: CallHomeRateLimitParameters,
) -> list[_ResultRecord]:
    """Pure comparison logic. No Context dependency."""
    try:
        expected_value = expected["devices"][device_name]["value"]
    except KeyError:
        return [_ResultRecord(ResultStatus.FAILED, MISSING_LEARNED_BASELINE.format(device=device_name))]

    try:
        current_value = current["devices"][device_name]["value"]
    except KeyError:
        return [_ResultRecord(ResultStatus.FAILED, MISSING_CURRENT_STATE.format(device=device_name))]

    if current_value != expected_value:
        return [_ResultRecord(
            ResultStatus.FAILED,
            VALUE_MISMATCH.format(device=device_name, expected_value=expected_value, current_value=current_value),
        )]

    return [_ResultRecord(
        ResultStatus.PASSED,
        VALUE_MATCH.format(device=device_name, current_value=current_value, expected_value=expected_value),
    )]
```

The `compare_state` method then becomes thin orchestration:

```python
async def compare_state(self, *, expected, current, context) -> None:
    for device in context.targets:
        for record in _build_value_results(
            device_name=device.name, expected=expected, current=current,
        ):
            context.results.add_result(record.status, record.message)
```

This makes the core logic testable as a synchronous pure function, while `compare_state` remains a thin wrapper. Both approaches are valid - the pure function extraction is most beneficial when the comparison logic is complex or shared across jobs.

## Pattern 2: Spec-Driven Test Harness

When a project has hundreds of structurally similar jobs, writing individual test assertions for each one creates massive duplication. The spec-driven pattern solves this: define a small data spec per job, and let shared assertion functions do the rest.

### Spec Types

Define spec dataclasses that capture the minimal data needed to test a job:

```python
# tests/jobs/support.py
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ValueJobSpec:
    """Spec for jobs that compare a single parsed value per device."""
    module_name: str
    class_name: str
    parsed_payload: dict[str, Any]  # What the parser returns
    expected_value: str             # The value extracted from parsed output
```

Different job families get different spec types:

```python
@dataclass(frozen=True)
class InventoryComponentJobSpec:
    """Spec for jobs that compare per-component inventory fields."""
    module_name: str
    class_name: str
    state_key: str
    parsed_payload: dict[str, Any]
    expected_mapping: dict[str, str]


@dataclass(frozen=True)
class InventoryCountJobSpec:
    """Spec for jobs that compare inventory component counts."""
    module_name: str
    class_name: str
    parsed_payload: dict[str, Any]
    expected_total: int
```

### Generic Assertion Functions

Shared functions test each job phase using the spec data:

```python
# tests/jobs/support.py
import asyncio
import importlib


def load_module(module_name: str):
    return importlib.import_module(module_name)


def assert_value_job_command_support(
    spec: ValueJobSpec,
    *,
    make_device,
    make_context,
    supported_output: str,
    unsupported_output: str,
) -> None:
    """Test check_command_support for any ValueJobSpec job."""
    module = load_module(spec.module_name)
    job = getattr(module, spec.class_name)()
    supported = make_device("edge-01")
    unsupported = make_device("edge-02")
    context = make_context(
        targets=[supported, unsupported],
        outputs={
            ("edge-01", job.command): supported_output,
            ("edge-02", job.command): unsupported_output,
        },
    )

    result = asyncio.run(job.check_command_support(context=context))

    assert [device.name for device in result.applicable] == ["edge-01"]
    assert result.not_applicable == {
        "edge-02": module.NOT_SUPPORTED_REASON.format(command=job.command)
    }


def assert_value_job_gather_state(
    spec: ValueJobSpec,
    *,
    make_device,
    make_context,
    fake_command_result_cls,
    monkeypatch,
    supported_output: str,
) -> None:
    """Test gather_state for any ValueJobSpec job."""
    module = load_module(spec.module_name)
    job = getattr(module, spec.class_name)()
    device = make_device("edge-01")
    context = make_context(
        targets=[device],
        outputs={("edge-01", job.command): supported_output},
    )

    parse_calls: list[tuple[str, str, str]] = []

    def fake_parse(*, os: str, command: str, output: str) -> dict[str, Any]:
        parse_calls.append((os, command, output))
        return spec.parsed_payload

    monkeypatch.setattr(module.mn, "parse", fake_parse)

    state = asyncio.run(job.gather_state(context=context))

    assert state == {"devices": {"edge-01": {"value": spec.expected_value}}}
    assert parse_calls == [("ios", job.command, supported_output)]


def assert_value_job_build_results(spec: ValueJobSpec) -> None:
    """Test the pure _build_value_results function for pass, fail, and edge cases."""
    module = load_module(spec.module_name)

    pass_results = module._build_value_results(
        device_name="edge-01",
        expected={"devices": {"edge-01": {"value": spec.expected_value}}},
        current={"devices": {"edge-01": {"value": spec.expected_value}}},
    )
    assert pass_results == [
        module._ResultRecord(
            status=ResultStatus.PASSED,
            message=module.VALUE_MATCH.format(
                device="edge-01",
                current_value=spec.expected_value,
                expected_value=spec.expected_value,
            ),
        )
    ]

    # Also tests: missing baseline, missing current, value mismatch
    # ... (similar assertions for each case)
```

### Per-Job Test Files

Each job's test file is minimal - just a spec definition and calls to shared assertions:

```python
# tests/jobs/test_verify_call_home_rate_limit.py
"""Unit tests for jobs.verify_call_home_rate_limit."""

from tests.jobs.support import (
    ValueJobSpec,
    assert_value_job_command_support,
    assert_value_job_build_results,
    assert_value_job_compare_state,
    assert_value_job_gather_state,
)

SPEC = ValueJobSpec(
    module_name="jobs.verify_call_home_rate_limit",
    class_name="VerifyCallHomeRateLimit",
    parsed_payload={"settings": {"rate_limit": "10"}},
    expected_value="10",
)


def test_build_results() -> None:
    assert_value_job_build_results(SPEC)


def test_check_command_support(
    make_device, make_context, supported_output, unsupported_output,
) -> None:
    assert_value_job_command_support(
        SPEC,
        make_device=make_device,
        make_context=make_context,
        supported_output=supported_output,
        unsupported_output=unsupported_output,
    )


def test_gather_state(
    make_device, make_context, fake_command_result_cls, monkeypatch, supported_output,
) -> None:
    assert_value_job_gather_state(
        SPEC,
        make_device=make_device,
        make_context=make_context,
        fake_command_result_cls=fake_command_result_cls,
        monkeypatch=monkeypatch,
        supported_output=supported_output,
    )


def test_compare_state(make_device, make_context) -> None:
    assert_value_job_compare_state(
        SPEC,
        make_device=make_device,
        make_context=make_context,
    )
```

### Why This Scales

This pattern enables a small number of test files to cover a large number of structurally similar jobs. Each new job that follows the same structure (e.g., single-value comparison) only requires a new spec definition and a handful of function calls - typically under 60 lines. The shared assertion functions in `support.py` handle all the boilerplate.

For jobs with unique structures (convergence gates, change actions), write custom tests that exercise their specific logic directly.

## Pattern 3: Hand-Crafted Fakes

Use simple dataclass-based fakes instead of mocking frameworks. They're easier to understand, type-safe, and sufficient for testing job logic.

Currently, each project defines its own fakes in `tests/jobs/conftest.py`. We are considering whether the core framework should ship a `huginn.testing` module with canonical fake implementations (e.g., `FakeDevice`, `FakeContext`, `FakeResults`), so that projects and plugins don't independently re-implement the same test doubles. This is an open design question - see [#83](https://github.com/ChartinoLabs/Huginn/issues/83) for the discussion.

### Fake Definitions

```python
# tests/jobs/conftest.py
from dataclasses import dataclass, field
from typing import Any

import pytest
from huginn import ResultStatus


@dataclass(frozen=True)
class FakeDevice:
    name: str
    os: str = "ios"


@dataclass(frozen=True)
class FakeCommandResult:
    output: str


@dataclass
class FakeBroker:
    outputs: dict[tuple[str, str], str]

    async def execute(self, device: FakeDevice, command: str) -> FakeCommandResult:
        return FakeCommandResult(output=self.outputs[(device.name, command)])


@dataclass
class FakeResults:
    entries: list[tuple[ResultStatus, str]] = field(default_factory=list)
    command_executions: list[dict[str, Any]] = field(default_factory=list)

    def add_result(self, status: ResultStatus, message: str) -> None:
        self.entries.append((status, message))

    def add_command_execution(self, **kwargs: Any) -> None:
        self.command_executions.append(kwargs)


@dataclass
class FakeContext:
    targets: list[FakeDevice]
    broker: FakeBroker
    results: FakeResults = field(default_factory=FakeResults)
```

### Pytest Fixtures

```python
# tests/jobs/conftest.py (continued)

@pytest.fixture
def supported_output() -> str:
    return "Current call home settings:"


@pytest.fixture
def unsupported_output() -> str:
    return "% Invalid input detected at '^' marker."


@pytest.fixture
def make_device():
    def _make_device(name: str, os: str = "ios") -> FakeDevice:
        return FakeDevice(name=name, os=os)
    return _make_device


@pytest.fixture
def make_context():
    def _make_context(
        *, targets: list[FakeDevice], outputs: dict[tuple[str, str], str],
    ) -> FakeContext:
        return FakeContext(targets=targets, broker=FakeBroker(outputs=outputs))
    return _make_context
```

### Why Not Mocking Frameworks?

- **Transparency**: Fakes are plain dataclasses - you can read exactly what they do
- **Duck typing**: Fakes only implement the interface methods jobs actually call
- **No magic**: No `Mock()`, `patch()`, or `MagicMock` - just Python objects
- **Assertion clarity**: `context.results.entries` is a real list you can inspect directly

### Monkeypatching for Parsers

When testing `gather_state()`, replace the Muninn parser with a function that returns known data:

```python
def fake_parse(*, os: str, command: str, output: str) -> dict[str, Any]:
    return spec.parsed_payload

monkeypatch.setattr(module.mn, "parse", fake_parse)
```

This avoids needing CLI output fixture files - the parser is bypassed entirely, and the test focuses on what the job does with the parsed data.

## Directory Structure

```txt
project/
├── jobs/                          # Job implementations (test automation)
│   ├── __init__.py
│   ├── verify_call_home_rate_limit.py
│   ├── verify_bgp_neighbor_existence.py
│   ├── gate_bgp_peering_status.py
│   └── change_clear_bgp_all_peers.py
│
├── tests/                         # Unit tests for job logic
│   └── jobs/
│       ├── __init__.py
│       ├── conftest.py            # Shared fakes and fixtures
│       ├── support.py             # Spec types and generic assertions
│       ├── test_verify_call_home_rate_limit.py
│       └── test_verify_bgp_neighbor_existence.py
│
├── parameters/                    # Learned baseline parameters (JSON)
│   ├── 1.0.0.json
│   └── 1.2.3.json
│
├── test_plan/                     # Test plan definitions
├── testbed.yaml
└── pyproject.toml
```

## Advanced: Injectable Data Providers

For jobs with complex data gathering requirements (multiple commands across different connection types, shared gathering patterns across jobs), define formal interfaces for data provision.

### When to Use

- Job requires multiple commands across different connection types
- Data gathering logic is itself complex and needs testing
- Multiple jobs share similar data gathering patterns

For most jobs, monkeypatching the parser in tests is simpler and sufficient. Use this pattern only when the complexity warrants it.

### Implementation

Define a protocol for data provision:

```python
from typing import Protocol


class OSPFDataProvider(Protocol):
    async def get_neighbors(self, device) -> dict: ...
    async def get_interfaces(self, device) -> dict: ...


class LiveOSPFDataProvider:
    def __init__(self, broker):
        self.broker = broker

    async def get_neighbors(self, device) -> dict:
        output = await self.broker.execute(device, "show ip ospf neighbor")
        return mn.parse(os=device.os, command="show ip ospf neighbor", output=output)

    async def get_interfaces(self, device) -> dict:
        output = await self.broker.execute(device, "show ip ospf interface")
        return mn.parse(os=device.os, command="show ip ospf interface", output=output)


class MockOSPFDataProvider:
    def __init__(self, neighbors: dict[str, dict], interfaces: dict[str, dict]):
        self._neighbors = neighbors
        self._interfaces = interfaces

    async def get_neighbors(self, device) -> dict:
        return self._neighbors.get(device.name, {})

    async def get_interfaces(self, device) -> dict:
        return self._interfaces.get(device.name, {})
```

The job accepts an optional provider, falling back to the live implementation:

```python
class VerifyOSPFState(LearningTestCase[OSPFStateParameters]):
    def __init__(self, data_provider: OSPFDataProvider | None = None):
        self._data_provider = data_provider

    def _get_provider(self, context: Context) -> OSPFDataProvider:
        if self._data_provider is not None:
            return self._data_provider
        return LiveOSPFDataProvider(context.broker)
```

## Best Practices

### 1. Test Decision Logic, Not the Framework

Unit tests should focus on your command support and validation logic, not on testing that Huginn's `Context` or broker work correctly.

```python
# Good: tests pure validation function
def test_build_results_mismatch():
    results = module._build_value_results(
        device_name="edge-01", expected=expected, current=current,
    )
    assert results[0].status == ResultStatus.FAILED

# Good: tests compare_state via FakeContext
def test_compare_state_mismatch(make_device, make_context):
    assert_value_job_compare_state(SPEC, make_device=make_device, make_context=make_context)

# Avoid: testing framework behavior
async def test_context_saves_parameters(fake_context):
    await fake_context.parameters.save({"key": "value"})
    assert await fake_context.parameters.load() == {"key": "value"}
```

### 2. Name Tests Descriptively

Test names should describe the scenario and expected outcome:

```python
# Good
def test_missing_neighbor_is_reported_as_failure():
def test_unexpected_neighbor_is_reported_as_info():
def test_empty_current_state_fails_all_expected():

# Bad
def test_validation():
def test_ospf():
def test_1():
```

### 3. Use Parametrize for Variations

Use pytest parametrization for variations of the same test:

```python
@pytest.mark.parametrize("current_state,expected_status", [
    ("FULL", ResultStatus.PASSED),
    ("INIT", ResultStatus.FAILED),
    ("DOWN", ResultStatus.FAILED),
    ("2WAY", ResultStatus.FAILED),
])
def test_neighbor_state_validation(job, current_state, expected_status):
    expected = {"spine-01": {"10.1.1.1": {"state": "FULL"}}}
    current = {"spine-01": {"10.1.1.1": {"state": current_state}}}
    results = job.validate_ospf_state(expected, current)
    assert results[0].status == expected_status
```

### 4. Use Realistic Test Data

Spec payloads should represent real parser output, including edge cases:

- Empty outputs (no data collected)
- Partial data (some devices unreachable)
- Missing keys (different software versions)

### 5. Keep Specs Close to Tests

Define specs inline in the test file rather than in separate fixture files. This keeps test data visible alongside test logic and gets full IDE support (type checking, autocomplete, refactoring).

## Integration with Development Workflow

### CI Pipeline

Include unit tests in CI alongside Huginn test runs:

```yaml
# .github/workflows/ci.yaml
jobs:
  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync
      - run: uv run pytest tests/jobs/ --cov=jobs --cov-report=xml

  # Huginn test runs execute separately against live infrastructure
  huginn-test-runs:
    needs: unit-tests  # Only run if unit tests pass
    # ...
```

## Related Documents

- [Test Authoring](05-test-authoring.md): Writing jobs with the TestCase pattern
- [Architecture](02-architecture.md): Context and adapter details

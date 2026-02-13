"""Core data models for first-slice plan execution."""

from dataclasses import dataclass, field


@dataclass
class Device:
    """A device defined in the testbed."""

    name: str
    os: str


@dataclass
class Testbed:
    """In-memory representation of a testbed file."""

    devices: dict[str, Device]


@dataclass
class TestCaseDefinition:
    """A single test case definition from a test plan."""

    test_id: str
    title: str
    job: str


@dataclass
class TestCaseGroup:
    """A group of test case identifiers from a test plan."""

    name: str
    tests: list[str]


@dataclass
class Phase:
    """A phase that references test case groups for execution."""

    name: str
    test_case_groups: list[str]


@dataclass
class TestPlan:
    """In-memory representation of a test plan file."""

    phases: dict[str, Phase]
    test_case_groups: dict[str, TestCaseGroup]
    test_cases: dict[str, TestCaseDefinition]


@dataclass
class CheckResult:
    """A single check emitted by a test case."""

    status: str
    message: str


@dataclass
class ExecutedTestCase:
    """Execution output for a single test case."""

    test_id: str
    title: str
    status: str
    checks: list[CheckResult] = field(default_factory=list)
    error: str | None = None


@dataclass
class ExecutedTestCaseGroup:
    """Execution output for a test case group."""

    name: str
    status: str
    test_cases: list[ExecutedTestCase] = field(default_factory=list)


@dataclass
class ExecutedPhase:
    """Execution output for a phase."""

    name: str
    status: str
    test_case_groups: list[ExecutedTestCaseGroup] = field(default_factory=list)


@dataclass
class RunSummary:
    """Aggregate counters and status for a run."""

    status: str
    total: int
    passed: int
    failed: int
    errored: int
    skipped: int
    blocked: int


@dataclass
class RunReport:
    """Top-level run report payload written to disk."""

    summary: RunSummary
    phases: list[ExecutedPhase]

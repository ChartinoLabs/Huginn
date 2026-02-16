"""Core data models for first-slice plan execution."""

from dataclasses import dataclass, field

from huginn.enums import ConnectionProtocol


@dataclass
class Device:
    """A device defined in the testbed."""

    name: str
    os: str
    groups: list[str] = field(default_factory=list)
    credentials: dict[str, dict[str, str]] = field(default_factory=dict)
    connections: dict[str, "ConnectionDefinition"] = field(default_factory=dict)


@dataclass
class ConnectionDefinition:
    """A named device connection from the testbed."""

    name: str
    protocol: ConnectionProtocol
    host: str
    port: int
    credential: str | None = None
    options: dict[str, object] = field(default_factory=dict)


@dataclass
class TargetDefinition:
    """Target filter subset for a test case."""

    devices: list[str] | None = None
    groups: list[str] | None = None
    os: list[str] | None = None


@dataclass
class Testbed:
    """In-memory representation of a testbed file."""

    devices: dict[str, Device]
    credentials: dict[str, dict[str, str]] = field(default_factory=dict)


@dataclass
class TestCaseDefinition:
    """A single test case definition from a test plan."""

    test_id: str
    title: str
    job: str
    tags: list[str] = field(default_factory=list)
    target: TargetDefinition | None = None


@dataclass
class TestCaseGroup:
    """A group of test case identifiers from a test plan."""

    name: str
    tests: list[str]
    tags: list[str] = field(default_factory=list)
    target: TargetDefinition | None = None


@dataclass
class Phase:
    """A phase that references test case groups for execution."""

    name: str
    test_case_groups: list[str]
    depends_on: list[str] = field(default_factory=list)
    target: TargetDefinition | None = None


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
class CommandExecution:
    """Recorded command execution details for reporting/debugging."""

    device: str
    command: str
    output: str
    parsed: dict[str, object] | None = None
    elapsed_ms: float | None = None
    cached: bool | None = None


@dataclass
class ExecutedTestCase:
    """Execution output for a single test case."""

    test_id: str
    title: str
    status: str
    checks: list[CheckResult] = field(default_factory=list)
    command_executions: list[CommandExecution] = field(default_factory=list)
    error: str | None = None
    error_code: str | None = None


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

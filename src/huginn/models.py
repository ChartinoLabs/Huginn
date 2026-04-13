"""Core data models for first-slice plan execution."""

from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from huginn.enums import ConnectionProtocol

CredentialFields: TypeAlias = dict[str, str]
CredentialMap: TypeAlias = dict[str, CredentialFields]


@dataclass(frozen=True)
class ExecutionStrategy:
    """Execution strategy for phase groups or test cases in a group."""

    mode: Literal["serial", "parallel"]
    maximum: int | None = None


@dataclass
class Device:
    """A device defined in the testbed."""

    name: str
    os: str
    groups: list[str] = field(default_factory=list)
    credentials: CredentialMap = field(default_factory=dict)
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
    credentials: CredentialMap = field(default_factory=dict)


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

    tests: list[str]
    identifier: str = ""
    name: str | None = None
    tags: list[str] = field(default_factory=list)
    target: TargetDefinition | None = None
    strategy: ExecutionStrategy = field(
        default_factory=lambda: ExecutionStrategy(mode="parallel")
    )

    def __post_init__(self) -> None:
        """Normalize identifier/name fallbacks for in-memory construction."""
        if not self.identifier:
            self.identifier = self.name or ""
        if not self.identifier:
            raise ValueError("TestCaseGroup requires an identifier or name")

    @property
    def display_name(self) -> str:
        """Return the configured display name or fall back to the identifier."""
        return self.name or self.identifier


@dataclass
class Phase:
    """A phase that references test case groups for execution."""

    test_case_groups: list[str]
    identifier: str = ""
    name: str | None = None
    depends_on: list[str] = field(default_factory=list)
    target: TargetDefinition | None = None
    strategy: ExecutionStrategy = field(
        default_factory=lambda: ExecutionStrategy(mode="parallel")
    )

    def __post_init__(self) -> None:
        """Normalize identifier/name fallbacks for in-memory construction."""
        if not self.identifier:
            self.identifier = self.name or ""
        if not self.identifier:
            raise ValueError("Phase requires an identifier or name")

    @property
    def display_name(self) -> str:
        """Return the configured display name or fall back to the identifier."""
        return self.name or self.identifier


@dataclass
class Scenario:
    """A scenario that groups ordered phases toward one testing outcome."""

    phases: dict[str, Phase]
    identifier: str = ""
    name: str | None = None

    def __post_init__(self) -> None:
        """Normalize identifier/name fallbacks for in-memory construction."""
        if not self.identifier:
            self.identifier = self.name or ""
        if not self.identifier:
            raise ValueError("Scenario requires an identifier or name")

    @property
    def display_name(self) -> str:
        """Return the configured display name or fall back to the identifier."""
        return self.name or self.identifier


@dataclass
class TestPlan:
    """In-memory representation of a test plan file."""

    scenarios: dict[str, Scenario]
    test_case_groups: dict[str, TestCaseGroup]
    test_cases: dict[str, TestCaseDefinition]


@dataclass
class CheckResult:
    """A single check emitted by a test case."""

    status: str
    message: str


@dataclass
class MetadataSection:
    """One rendered metadata section for a test case."""

    heading: str
    content: str


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

    scenario: str
    phase: str
    group: str
    test_id: str
    title: str
    status: str
    metadata_sections: list[MetadataSection] = field(default_factory=list)
    checks: list[CheckResult] = field(default_factory=list)
    command_executions: list[CommandExecution] = field(default_factory=list)
    error: str | None = None
    error_code: str | None = None
    error_traceback: str | None = None


@dataclass
class ExecutedTestCaseGroup:
    """Execution output for a test case group."""

    status: str
    identifier: str = ""
    name: str | None = None
    test_cases: list[ExecutedTestCase] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Normalize identifier/name fallbacks for execution output."""
        if not self.identifier:
            self.identifier = self.name or ""
        if not self.identifier:
            raise ValueError("ExecutedTestCaseGroup requires an identifier or name")

    @property
    def display_name(self) -> str:
        """Return the configured display name or fall back to the identifier."""
        return self.name or self.identifier


@dataclass
class ExecutedPhase:
    """Execution output for a phase."""

    status: str
    identifier: str = ""
    name: str | None = None
    test_case_groups: list[ExecutedTestCaseGroup] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Normalize identifier/name fallbacks for execution output."""
        if not self.identifier:
            self.identifier = self.name or ""
        if not self.identifier:
            raise ValueError("ExecutedPhase requires an identifier or name")

    @property
    def display_name(self) -> str:
        """Return the configured display name or fall back to the identifier."""
        return self.name or self.identifier


@dataclass
class ExecutedScenario:
    """Execution output for a scenario."""

    status: str
    identifier: str = ""
    name: str | None = None
    phases: list[ExecutedPhase] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Normalize identifier/name fallbacks for execution output."""
        if not self.identifier:
            self.identifier = self.name or ""
        if not self.identifier:
            raise ValueError("ExecutedScenario requires an identifier or name")

    @property
    def display_name(self) -> str:
        """Return the configured display name or fall back to the identifier."""
        return self.name or self.identifier


@dataclass
class RunSummary:
    """Aggregate counters and status for a run."""

    status: str
    total: int
    passed: int
    failed: int
    errored: int
    not_applicable: int
    skipped: int
    blocked: int


@dataclass
class RunResult:
    """Top-level run result payload written to disk."""

    summary: RunSummary
    scenarios: list[ExecutedScenario]
    mode: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    elapsed_seconds: float | None = None

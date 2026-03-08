"""Unit tests for LearningTestCase base class behavior."""

from dataclasses import dataclass, field
from typing import cast

import pytest

from huginn import (
    ApplicabilityResult,
    Context,
    ExecutionMode,
    LearningTestCase,
    ResultStatus,
)
from huginn.models import Device, MetadataSection


@dataclass
class _FakeParameters:
    saved_payloads: list[dict[str, object]] = field(default_factory=list)
    loaded_payload: dict[str, object] = field(
        default_factory=lambda: {"expected": True}
    )

    async def save(self, data: dict[str, object]) -> None:
        self.saved_payloads.append(data)

    async def load(self) -> dict[str, object]:
        return self.loaded_payload


@dataclass
class _FakeResults:
    entries: list[tuple[ResultStatus, str]] = field(default_factory=list)
    metadata_sections: list[MetadataSection] = field(default_factory=list)

    def add_metadata_section(self, heading: str, content: str) -> None:
        self.metadata_sections.append(MetadataSection(heading=heading, content=content))

    def add_result(self, status: ResultStatus, message: str) -> None:
        self.entries.append((status, message))


@dataclass
class _FakeContext:
    mode: ExecutionMode
    test_title: str = "Example Test"
    targets: list["_FakeDevice"] = field(default_factory=list)
    parameters: _FakeParameters = field(default_factory=_FakeParameters)
    results: _FakeResults = field(default_factory=_FakeResults)


@dataclass(frozen=True)
class _FakeDevice:
    name: str


class _ExampleLearningTest(LearningTestCase):
    gathered_state: dict[str, object] = {"current": True}
    compared: list[tuple[dict[str, object], dict[str, object]]]

    def __init__(self) -> None:
        self.compared = []

    async def gather_state(self, context: Context) -> dict[str, object]:
        return self.gathered_state

    async def compare_state(
        self,
        *,
        expected: dict[str, object],
        current: dict[str, object],
        context: Context,
    ) -> None:
        self.compared.append((expected, current))


class _ApplicabilityLearningTest(_ExampleLearningTest):
    gathered_target_names: list[str]

    def __init__(self) -> None:
        super().__init__()
        self.gathered_target_names = []

    async def check_applicability(self, context: Context) -> ApplicabilityResult:
        targets = cast(_FakeContext, context).targets
        applicable = [targets[0]]
        return ApplicabilityResult(
            applicable=cast(list[Device], applicable),
            not_applicable={targets[1].name: "feature not enabled"},
        )

    async def gather_state(self, context: Context) -> dict[str, object]:
        fake_context = cast(_FakeContext, context)
        self.gathered_target_names = [target.name for target in fake_context.targets]
        return self.gathered_state


class _NoApplicableLearningTest(_ExampleLearningTest):
    async def check_applicability(self, context: Context) -> ApplicabilityResult:
        targets = cast(_FakeContext, context).targets
        return ApplicabilityResult(
            applicable=[],
            not_applicable={
                target.name: "protocol not configured" for target in targets
            },
        )


class _MetadataLearningTest(_ExampleLearningTest):
    DESCRIPTION = "Validate expected payload for {{ parameters.device }}"
    SETUP = "Connect to {{ parameters.device }}"
    PROCEDURE = "Compare state for {{ parameters.device }}"
    PASS_FAIL_CRITERIA = "Pass when baseline matches {{ parameters.device }}"


@pytest.mark.asyncio
async def test_learning_testcase_saves_state_in_learning_mode() -> None:
    """Learning mode saves gathered state and records success check."""
    test_case = _ExampleLearningTest()
    context = _FakeContext(
        mode=ExecutionMode.LEARNING,
        targets=[_FakeDevice(name="leaf-01")],
    )

    await test_case.test(cast(Context, context))

    assert context.parameters.saved_payloads == [{"current": True}]
    assert test_case.compared == []
    assert context.results.entries == [
        (ResultStatus.PASSED, "Learned parameters saved successfully")
    ]


@pytest.mark.asyncio
async def test_learning_testcase_compares_state_in_testing_mode() -> None:
    """Testing mode loads expected parameters and runs compare_state."""
    test_case = _ExampleLearningTest()
    context = _FakeContext(
        mode=ExecutionMode.TESTING,
        targets=[_FakeDevice(name="leaf-01")],
    )

    await test_case.test(cast(Context, context))

    assert context.parameters.saved_payloads == []
    assert test_case.compared == [({"expected": True}, {"current": True})]
    assert context.results.entries == []


@pytest.mark.asyncio
async def test_learning_testcase_default_setup_and_cleanup_are_noop() -> None:
    """Base class default setup and cleanup run without side effects."""
    test_case = _ExampleLearningTest()
    context = _FakeContext(mode=ExecutionMode.TESTING)

    await test_case.setup(cast(Context, context))
    await test_case.cleanup(cast(Context, context))

    assert context.results.entries == []


@pytest.mark.asyncio
async def test_learning_testcase_filters_targets_by_applicability() -> None:
    """Applicability check narrows targets for gather/compare execution."""
    test_case = _ApplicabilityLearningTest()
    context = _FakeContext(
        mode=ExecutionMode.TESTING,
        targets=[_FakeDevice(name="leaf-01"), _FakeDevice(name="leaf-02")],
    )

    await test_case.test(cast(Context, context))

    assert test_case.gathered_target_names == ["leaf-01"]
    assert test_case.compared == [({"expected": True}, {"current": True})]
    assert context.results.entries[0] == (
        ResultStatus.NOT_APPLICABLE,
        "leaf-02: feature not enabled",
    )


@pytest.mark.asyncio
async def test_learning_testcase_skips_when_no_applicable_targets() -> None:
    """When nothing is applicable, state gather/compare is not executed."""
    test_case = _NoApplicableLearningTest()
    context = _FakeContext(
        mode=ExecutionMode.TESTING,
        targets=[_FakeDevice(name="leaf-01")],
    )

    await test_case.test(cast(Context, context))

    assert test_case.compared == []
    assert context.parameters.saved_payloads == []
    assert context.results.entries == [
        (ResultStatus.NOT_APPLICABLE, "leaf-01: protocol not configured"),
        (ResultStatus.INFO, "No applicable targets after applicability check"),
    ]


@pytest.mark.asyncio
async def test_learning_testcase_renders_metadata_in_testing_mode() -> None:
    """Testing mode renders metadata templates using expected parameters."""
    test_case = _MetadataLearningTest()
    context = _FakeContext(
        mode=ExecutionMode.TESTING,
        test_title="Rendered Metadata",
        targets=[_FakeDevice(name="leaf-01")],
        parameters=_FakeParameters(loaded_payload={"device": "leaf-01"}),
    )

    await test_case.test(cast(Context, context))

    assert test_case.compared == [({"device": "leaf-01"}, {"current": True})]
    assert context.results.entries == [
        (
            ResultStatus.INFO,
            "Test Metadata: Rendered Metadata\n"
            "\n"
            "Description:\n"
            "Validate expected payload for leaf-01\n"
            "\n"
            "Setup:\n"
            "Connect to leaf-01\n"
            "\n"
            "Procedure:\n"
            "Compare state for leaf-01\n"
            "\n"
            "Pass/Fail Criteria:\n"
            "Pass when baseline matches leaf-01",
        )
    ]
    assert context.results.metadata_sections == [
        MetadataSection(
            heading="Description",
            content="Validate expected payload for leaf-01",
        ),
        MetadataSection(
            heading="Setup",
            content="Connect to leaf-01",
        ),
        MetadataSection(
            heading="Procedure",
            content="Compare state for leaf-01",
        ),
        MetadataSection(
            heading="Pass/Fail Criteria",
            content="Pass when baseline matches leaf-01",
        ),
    ]


@pytest.mark.asyncio
async def test_learning_testcase_skips_metadata_in_learning_mode() -> None:
    """Learning mode does not emit rendered metadata output."""
    test_case = _MetadataLearningTest()
    context = _FakeContext(
        mode=ExecutionMode.LEARNING,
        targets=[_FakeDevice(name="leaf-01")],
    )

    await test_case.test(cast(Context, context))

    assert context.results.entries == [
        (ResultStatus.PASSED, "Learned parameters saved successfully")
    ]

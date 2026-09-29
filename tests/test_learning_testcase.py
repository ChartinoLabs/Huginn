"""Unit tests for LearningTestCase base class behavior."""

from dataclasses import dataclass, field
from typing import cast

import pytest

from huginn import (
    CommandSupportResult,
    Context,
    ExecutionMode,
    LearningTestCase,
    ResultStatus,
)
from huginn.models import Device, MetadataSection
from huginn.parameters import ParameterStoreError


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

    async def check_command_support(self, context: Context) -> CommandSupportResult:
        targets = cast(_FakeContext, context).targets
        applicable = [targets[0]]
        return CommandSupportResult(
            applicable=cast(list[Device], applicable),
            not_applicable={targets[1].name: "feature not enabled"},
        )

    async def gather_state(self, context: Context) -> dict[str, object]:
        fake_context = cast(_FakeContext, context)
        self.gathered_target_names = [target.name for target in fake_context.targets]
        return self.gathered_state


class _NoApplicableLearningTest(_ExampleLearningTest):
    async def check_command_support(self, context: Context) -> CommandSupportResult:
        targets = cast(_FakeContext, context).targets
        return CommandSupportResult(
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


class _GenericLearningTest(LearningTestCase[dict[str, object]]):
    async def gather_state(self, context: Context) -> dict[str, object]:
        return {"current": True}

    async def compare_state(
        self,
        *,
        expected: dict[str, object],
        current: dict[str, object],
        context: Context,
    ) -> None:
        return None


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
        (ResultStatus.INFO, "No supported targets after command support check"),
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
    assert context.results.entries == []
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


def test_learning_testcase_supports_generic_subscripts() -> None:
    """Generic subscription remains available for typed job definitions."""
    test_case = _GenericLearningTest()

    assert isinstance(test_case, LearningTestCase)


@dataclass
class _MissingParameters(_FakeParameters):
    async def load(self) -> dict[str, object]:
        raise ParameterStoreError("No learned parameters found for test 'x'")


@dataclass
class _CollectingResults(_FakeResults):
    not_applicable_devices: dict[str, str] = field(default_factory=dict)


class _CustomSchemaLearningTest(_ApplicabilityLearningTest):
    """Stores learned devices under ``nodes`` instead of ``devices``."""

    def learned_devices(self, parameters: dict[str, object]) -> set[str]:
        return set(cast(dict[str, object], parameters["nodes"]))


def _two_leaf_context(
    mode: ExecutionMode,
    parameters: _FakeParameters,
) -> _FakeContext:
    return _FakeContext(
        mode=mode,
        targets=[_FakeDevice(name="leaf-01"), _FakeDevice(name="leaf-02")],
        parameters=parameters,
        results=_CollectingResults(),
    )


@pytest.mark.asyncio
async def test_learning_testcase_reports_lost_applicability_for_learned_device() -> (
    None
):
    """An unsupported device in the learned parameters lost applicability."""
    test_case = _ApplicabilityLearningTest()
    learned: dict[str, object] = {"devices": {"leaf-01": {}, "leaf-02": {}}}
    context = _two_leaf_context(
        ExecutionMode.TESTING,
        _FakeParameters(loaded_payload=learned),
    )

    await test_case.test(cast(Context, context))

    assert context.results.entries[0] == (
        ResultStatus.LOST_APPLICABILITY,
        "leaf-02: feature not enabled, but it was supported when parameters "
        "were learned",
    )
    assert cast(_CollectingResults, context.results).not_applicable_devices == {}
    assert test_case.compared == [(learned, {"current": True})]


@pytest.mark.asyncio
async def test_learning_testcase_keeps_never_supported_device_not_applicable() -> None:
    """An unsupported device absent from the learned parameters stays N/A."""
    test_case = _ApplicabilityLearningTest()
    context = _two_leaf_context(
        ExecutionMode.TESTING,
        _FakeParameters(loaded_payload={"devices": {"leaf-01": {}}}),
    )

    await test_case.test(cast(Context, context))

    assert context.results.entries[0] == (
        ResultStatus.NOT_APPLICABLE,
        "leaf-02: feature not enabled",
    )
    assert cast(_CollectingResults, context.results).not_applicable_devices == {
        "leaf-02": "feature not enabled"
    }


@pytest.mark.asyncio
async def test_learning_testcase_learned_devices_hook_supports_custom_schema() -> None:
    """Overriding learned_devices() detects lost devices in another schema."""
    test_case = _CustomSchemaLearningTest()
    context = _two_leaf_context(
        ExecutionMode.TESTING,
        _FakeParameters(loaded_payload={"nodes": {"leaf-02": {}}}),
    )

    await test_case.test(cast(Context, context))

    assert context.results.entries[0][0] == ResultStatus.LOST_APPLICABILITY


@pytest.mark.asyncio
async def test_learning_testcase_default_hook_ignores_other_schemas() -> None:
    """Without a ``devices`` mapping, unsupported devices stay N/A."""
    test_case = _ApplicabilityLearningTest()
    context = _two_leaf_context(
        ExecutionMode.TESTING,
        _FakeParameters(loaded_payload={"nodes": {"leaf-02": {}}}),
    )

    await test_case.test(cast(Context, context))

    assert context.results.entries[0][0] == ResultStatus.NOT_APPLICABLE


@pytest.mark.asyncio
async def test_learning_testcase_never_reports_lost_applicability_when_learning() -> (
    None
):
    """Learning mode records N/A and does not read the old parameters."""
    test_case = _ApplicabilityLearningTest()
    parameters = _MissingParameters()
    context = _two_leaf_context(ExecutionMode.LEARNING, parameters)

    await test_case.test(cast(Context, context))

    assert context.results.entries == [
        (ResultStatus.NOT_APPLICABLE, "leaf-02: feature not enabled"),
        (ResultStatus.PASSED, "Learned parameters saved successfully"),
    ]
    assert parameters.saved_payloads == [{"current": True}]


@pytest.mark.asyncio
async def test_learning_testcase_missing_parameters_still_raise_after_gather() -> None:
    """Missing parameters keep raising, after gather_state() as before."""
    test_case = _ApplicabilityLearningTest()
    context = _two_leaf_context(ExecutionMode.TESTING, _MissingParameters())

    with pytest.raises(ParameterStoreError, match="No learned parameters"):
        await test_case.test(cast(Context, context))

    assert test_case.gathered_target_names == ["leaf-01"]
    assert context.results.entries == [
        (ResultStatus.NOT_APPLICABLE, "leaf-02: feature not enabled"),
    ]


@pytest.mark.asyncio
async def test_learning_testcase_all_lost_devices_skip_gather_and_compare() -> None:
    """When every target lost applicability, nothing is gathered or compared."""
    test_case = _NoApplicableLearningTest()
    context = _FakeContext(
        mode=ExecutionMode.TESTING,
        targets=[_FakeDevice(name="leaf-01")],
        parameters=_FakeParameters(loaded_payload={"devices": {"leaf-01": {}}}),
        results=_CollectingResults(),
    )

    await test_case.test(cast(Context, context))

    assert test_case.compared == []
    assert [status for status, _ in context.results.entries] == [
        ResultStatus.LOST_APPLICABILITY,
        ResultStatus.INFO,
    ]

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
from huginn.results import ResultCollector


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


class _DroppingLearningTest(LearningTestCase[dict[str, object]]):
    """Marks ``empty`` devices NOT_APPLICABLE in gather_state.

    With ``reassign`` false it leaves ``context.targets`` alone, as many jobs
    do; with it true it narrows the targets itself, as the docs used to ask.
    ``compare_state`` fails any target the learned parameters lack, the way
    a typical job reports a missing learned baseline.
    """

    def __init__(self, empty: set[str], *, reassign: bool = False) -> None:
        self.empty = empty
        self.reassign = reassign
        self.compared_targets: list[str] = []

    async def gather_state(self, context: Context) -> dict[str, object]:
        devices: dict[str, object] = {}
        remaining: list[Device] = []
        for device in context.targets:
            if device.name in self.empty:
                context.results.add_result(
                    ResultStatus.NOT_APPLICABLE,
                    f"{device.name}: 'show example' returned no data",
                )
                continue
            devices[device.name] = {"value": "up"}
            remaining.append(device)
        if self.reassign:
            context.targets = remaining
        return {"devices": devices}

    async def compare_state(
        self,
        *,
        expected: dict[str, object],
        current: dict[str, object],
        context: Context,
    ) -> None:
        learned = cast(dict[str, object], expected["devices"])
        for device in context.targets:
            self.compared_targets.append(device.name)
            if device.name not in learned:
                context.results.add_result(
                    ResultStatus.FAILED,
                    f"{device.name}: missing learned baseline",
                )
                continue
            context.results.add_result(ResultStatus.PASSED, f"{device.name}: ok")


class _CountingParameters(_FakeParameters):
    load_calls: int = 0

    async def load(self) -> dict[str, object]:
        self.load_calls += 1
        return await super().load()


def _collector_context(
    mode: ExecutionMode,
    names: list[str],
    learned: dict[str, object] | None = None,
) -> tuple[_FakeContext, ResultCollector]:
    results = ResultCollector()
    parameters = _CountingParameters(
        loaded_payload={"devices": learned if learned is not None else {}}
    )
    context = _FakeContext(
        mode=mode,
        targets=[_FakeDevice(name=name) for name in names],
        parameters=parameters,
        results=cast(_FakeResults, results),
    )
    return context, results


def _statuses(results: ResultCollector) -> list[tuple[str, str]]:
    return [(check.status, check.message) for check in results.checks]


@pytest.mark.asyncio
@pytest.mark.parametrize("reassign", [False, True])
async def test_gather_state_na_device_is_not_compared_in_testing(
    reassign: bool,
) -> None:
    """A device gather_state dropped is never compared, reassigned or not."""
    test_case = _DroppingLearningTest({"leaf-02"}, reassign=reassign)
    context, results = _collector_context(
        ExecutionMode.TESTING,
        ["leaf-01", "leaf-02"],
        learned={"leaf-01": {"value": "up"}},
    )

    await test_case.test(cast(Context, context))

    assert test_case.compared_targets == ["leaf-01"]
    assert [t.name for t in context.targets] == ["leaf-01"]
    assert _statuses(results) == [
        ("not_applicable", "leaf-02: 'show example' returned no data"),
        ("passed", "leaf-01: ok"),
    ]
    assert results.not_applicable_devices == {
        "leaf-02": "'show example' returned no data"
    }
    assert results.derive_status() == ResultStatus.PASSED


@pytest.mark.asyncio
@pytest.mark.parametrize("reassign", [False, True])
async def test_gather_state_na_device_in_baseline_lost_applicability(
    reassign: bool,
) -> None:
    """A dropped device the learned parameters contain lost applicability."""
    test_case = _DroppingLearningTest({"leaf-02"}, reassign=reassign)
    context, results = _collector_context(
        ExecutionMode.TESTING,
        ["leaf-01", "leaf-02"],
        learned={"leaf-01": {"value": "up"}, "leaf-02": {"value": "up"}},
    )

    await test_case.test(cast(Context, context))

    assert test_case.compared_targets == ["leaf-01"]
    assert (
        "lost_applicability",
        "leaf-02: 'show example' returned no data, but it was supported when "
        "parameters were learned",
    ) in _statuses(results)
    assert results.not_applicable_devices == {}
    assert results.derive_status() == ResultStatus.LOST_APPLICABILITY
    assert cast(_CountingParameters, context.parameters).load_calls == 1


@pytest.mark.asyncio
async def test_gather_state_na_learning_mode_unchanged() -> None:
    """Learning mode saves only gathered devices and never reads parameters."""
    test_case = _DroppingLearningTest({"leaf-02"})
    context, results = _collector_context(
        ExecutionMode.LEARNING,
        ["leaf-01", "leaf-02"],
        learned={"leaf-01": {}, "leaf-02": {}},
    )

    await test_case.test(cast(Context, context))

    parameters = cast(_CountingParameters, context.parameters)
    assert parameters.saved_payloads == [{"devices": {"leaf-01": {"value": "up"}}}]
    assert parameters.load_calls == 0
    assert _statuses(results) == [
        ("not_applicable", "leaf-02: 'show example' returned no data"),
    ]
    assert results.not_applicable_devices == {
        "leaf-02": "'show example' returned no data"
    }


@pytest.mark.asyncio
async def test_gather_state_na_mixed_run() -> None:
    """Dropped devices, lost devices and compared devices in one run."""
    test_case = _DroppingLearningTest({"leaf-02", "leaf-03"})
    context, results = _collector_context(
        ExecutionMode.TESTING,
        ["leaf-01", "leaf-02", "leaf-03", "leaf-04"],
        learned={"leaf-01": {}, "leaf-03": {}},
    )

    await test_case.test(cast(Context, context))

    assert test_case.compared_targets == ["leaf-01", "leaf-04"]
    statuses = _statuses(results)
    assert ("passed", "leaf-01: ok") in statuses
    assert ("failed", "leaf-04: missing learned baseline") in statuses
    assert not any(
        message.startswith("leaf-02") and status != "not_applicable"
        for status, message in statuses
    )
    assert any(
        status == "lost_applicability" and message.startswith("leaf-03")
        for status, message in statuses
    )
    assert results.not_applicable_devices == {
        "leaf-02": "'show example' returned no data"
    }


@pytest.mark.asyncio
async def test_gather_state_na_reuses_parameters_loaded_for_support() -> None:
    """Parameters loaded for the command-support check are not loaded again."""

    class _Both(_DroppingLearningTest):
        async def check_command_support(self, context: Context) -> CommandSupportResult:
            targets = list(context.targets)
            return CommandSupportResult(
                applicable=targets[:-1],
                not_applicable={targets[-1].name: "feature not enabled"},
            )

    test_case = _Both({"leaf-02"})
    context, results = _collector_context(
        ExecutionMode.TESTING,
        ["leaf-01", "leaf-02", "leaf-03"],
        learned={"leaf-01": {}, "leaf-02": {}},
    )

    await test_case.test(cast(Context, context))

    assert cast(_CountingParameters, context.parameters).load_calls == 1
    assert test_case.compared_targets == ["leaf-01"]
    assert [s for s, _ in _statuses(results)].count("lost_applicability") == 1
    assert results.not_applicable_devices == {"leaf-03": "feature not enabled"}

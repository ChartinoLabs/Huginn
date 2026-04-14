"""Unit tests for the volatile parameter base class."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import pytest

from huginn import (
    Context,
    ExecutionMode,
    Observation,
    ResultStatus,
    VolatileLearningTestCase,
)
from huginn.volatile import (
    apply_operator,
    observation_path,
    read_prior_observations,
    write_observations,
)


@dataclass
class _FakeResults:
    entries: list[tuple[ResultStatus, str]] = field(default_factory=list)

    def add_result(self, status: ResultStatus, message: str) -> None:
        self.entries.append((status, message))


@dataclass(frozen=True)
class _FakeDevice:
    name: str


@dataclass
class _DummyContext:
    """Minimal stand-in for huginn.context.Context in these tests."""

    test_id: str
    test_title: str
    mode: ExecutionMode
    targets: list[Any]
    output_dir: Path
    scenario: str
    phase: str
    test_case_group: str
    results: _FakeResults


def _make_context(
    tmp_path: Path,
    *,
    test_id: str = "vol-1",
    scenario: str = "scenario-a",
    phase: str = "pre-change",
    test_case_group: str = "baseline",
    targets: list[_FakeDevice] | None = None,
) -> Context:
    output_dir = tmp_path / "artifacts"
    output_dir.mkdir(parents=True, exist_ok=True)
    if targets is None:
        targets = [_FakeDevice(name="R1")]
    return cast(
        Context,
        _DummyContext(
            test_id=test_id,
            test_title="test",
            mode=ExecutionMode.TESTING,
            targets=targets,
            output_dir=output_dir,
            scenario=scenario,
            phase=phase,
            test_case_group=test_case_group,
            results=_FakeResults(),
        ),
    )


class _OperatorJob(VolatileLearningTestCase[dict[str, Any]]):
    """Test subclass using a simple operator-based parameter schema."""

    SERIES_PREFIX = "demo-series"

    def __init__(
        self,
        planned: list[Observation],
        default_operator: str = "gte",
    ) -> None:
        self._planned = planned
        self._default_operator = default_operator

    async def gather_state(self, context: Context) -> dict[str, Any]:
        return {"operator": self._default_operator}

    async def gather_observations(
        self,
        context: Context,
    ) -> Iterable[Observation]:
        return self._planned

    def passes_comparison(
        self,
        *,
        parameters: dict[str, Any],
        observation: Observation,
        prior: dict[str, Any],
        context: Context,
    ) -> bool:
        return apply_operator(
            parameters["operator"],
            observation.value,
            prior["value"],
        )


def test_apply_operator_gte() -> None:
    """Gte returns True when current is equal or greater than prior."""
    assert apply_operator("gte", 5, 5) is True
    assert apply_operator("gte", 6, 5) is True
    assert apply_operator("gte", 4, 5) is False


def test_apply_operator_lt() -> None:
    """Lt returns True when current is strictly less than prior."""
    assert apply_operator("lt", 3, 5) is True
    assert apply_operator("lt", 5, 5) is False
    assert apply_operator("lt", 6, 5) is False


def test_apply_operator_gt_and_lte() -> None:
    """Gt and lte behave strictly as expected."""
    assert apply_operator("gt", 6, 5) is True
    assert apply_operator("gt", 5, 5) is False
    assert apply_operator("lte", 5, 5) is True
    assert apply_operator("lte", 6, 5) is False


def test_apply_operator_rejects_unknown() -> None:
    """Unknown operators raise ValueError."""
    with pytest.raises(ValueError, match="Unsupported comparison operator"):
        apply_operator("eq", 1, 1)


def test_observation_path_uses_output_dir_and_prefix(tmp_path: Path) -> None:
    """The JSONL path is derived from output_dir and the series prefix."""
    ctx = _make_context(tmp_path)
    path = observation_path(ctx, "my-prefix")
    assert path == tmp_path / "artifacts" / "my-prefix.jsonl"


def test_read_prior_observations_empty_when_file_missing(
    tmp_path: Path,
) -> None:
    """Missing log file returns an empty dict."""
    ctx = _make_context(tmp_path)
    assert read_prior_observations(ctx, "nothing-yet") == {}


def test_write_then_read_returns_latest_per_series(tmp_path: Path) -> None:
    """Later entries for a series supersede earlier ones on read."""
    ctx = _make_context(tmp_path)
    write_observations(
        ctx,
        "demo",
        [
            {"series": "R1::a", "value": 1, "raw": "1"},
            {"series": "R1::b", "value": 10, "raw": "10"},
        ],
    )
    write_observations(
        ctx,
        "demo",
        [{"series": "R1::a", "value": 2, "raw": "2"}],
    )

    latest = read_prior_observations(ctx, "demo")
    assert latest["R1::a"]["value"] == 2
    assert latest["R1::b"]["value"] == 10


def test_subclass_missing_series_prefix_raises() -> None:
    """Concrete subclasses must declare SERIES_PREFIX."""
    with pytest.raises(TypeError, match="must define SERIES_PREFIX"):

        class _Bad(VolatileLearningTestCase[dict[str, Any]]):
            async def gather_state(self, context: Context) -> dict[str, Any]:
                return {}

            async def gather_observations(
                self,
                context: Context,
            ) -> list[Observation]:
                return []

            def passes_comparison(
                self,
                *,
                parameters: dict[str, Any],
                observation: Observation,
                prior: dict[str, Any],
                context: Context,
            ) -> bool:
                return True


def test_first_observation_records_pass_with_no_comparison(
    tmp_path: Path,
) -> None:
    """First execution writes observations and records a pass per device."""
    import asyncio

    ctx = _make_context(tmp_path)
    job = _OperatorJob(
        planned=[
            Observation(device="R1", series_key="nbr-1", value=100, raw="100"),
            Observation(device="R1", series_key="nbr-2", value=200, raw="200"),
        ],
    )

    asyncio.run(
        job.compare_state(
            expected={"operator": "gte"},
            current={"operator": "gte"},
            context=ctx,
        )
    )

    results = cast(_FakeResults, ctx.results)
    assert len(results.entries) == 1
    status, message = results.entries[0]
    assert status == ResultStatus.PASSED
    assert "first in this run" in message

    obs_file = tmp_path / "artifacts" / "demo-series.jsonl"
    records = [json.loads(line) for line in obs_file.read_text().splitlines()]
    assert [r["series"] for r in records] == ["R1::nbr-1", "R1::nbr-2"]
    for record in records:
        assert record["test_id"] == "vol-1"
        assert record["scenario"] == "scenario-a"
        assert record["phase"] == "pre-change"
        assert record["test_case_group"] == "baseline"
        assert "timestamp" in record


def test_second_observation_passes_comparison(tmp_path: Path) -> None:
    """Second execution passes when subclass comparison returns True."""
    import asyncio

    ctx1 = _make_context(tmp_path)
    asyncio.run(
        _OperatorJob(
            planned=[
                Observation(device="R1", series_key="nbr-1", value=100, raw="100"),
            ],
        ).compare_state(
            expected={"operator": "gte"},
            current={"operator": "gte"},
            context=ctx1,
        )
    )

    ctx2 = _make_context(tmp_path, phase="post-change")
    asyncio.run(
        _OperatorJob(
            planned=[
                Observation(device="R1", series_key="nbr-1", value=150, raw="150"),
            ],
        ).compare_state(
            expected={"operator": "gte"},
            current={"operator": "gte"},
            context=ctx2,
        )
    )

    results = cast(_FakeResults, ctx2.results)
    assert len(results.entries) == 1
    assert results.entries[0][0] == ResultStatus.PASSED


def test_comparison_returning_false_records_failure(tmp_path: Path) -> None:
    """A False return from passes_comparison produces a FAILED result."""
    import asyncio

    ctx1 = _make_context(tmp_path)
    asyncio.run(
        _OperatorJob(
            planned=[
                Observation(device="R1", series_key="nbr-1", value=100, raw="100"),
            ],
        ).compare_state(
            expected={"operator": "gte"},
            current={"operator": "gte"},
            context=ctx1,
        )
    )

    ctx2 = _make_context(tmp_path, phase="post-change")
    asyncio.run(
        _OperatorJob(
            planned=[
                Observation(device="R1", series_key="nbr-1", value=50, raw="50"),
            ],
        ).compare_state(
            expected={"operator": "gte"},
            current={"operator": "gte"},
            context=ctx2,
        )
    )

    results = cast(_FakeResults, ctx2.results)
    failed = [e for e in results.entries if e[0] == ResultStatus.FAILED]
    assert len(failed) == 1
    assert "failed comparison" in failed[0][1]


def test_framework_does_not_prescribe_schema(tmp_path: Path) -> None:
    """Subclasses can use completely custom parameter schemas."""
    import asyncio

    class _ToleranceJob(VolatileLearningTestCase[dict[str, Any]]):
        """Uses a tolerance band schema rather than an operator."""

        SERIES_PREFIX = "tolerance-series"

        def __init__(self, planned: list[Observation]) -> None:
            self._planned = planned

        async def gather_state(self, context: Context) -> dict[str, Any]:
            return {"tolerance": 10}

        async def gather_observations(
            self,
            context: Context,
        ) -> Iterable[Observation]:
            return self._planned

        def passes_comparison(
            self,
            *,
            parameters: dict[str, Any],
            observation: Observation,
            prior: dict[str, Any],
            context: Context,
        ) -> bool:
            tolerance = parameters["tolerance"]
            return abs(observation.value - prior["value"]) <= tolerance

    ctx1 = _make_context(tmp_path)
    asyncio.run(
        _ToleranceJob(
            planned=[
                Observation(device="R1", series_key="nbr-1", value=100, raw="100"),
            ],
        ).compare_state(
            expected={"tolerance": 10},
            current={"tolerance": 10},
            context=ctx1,
        )
    )

    # Within tolerance — passes
    ctx2 = _make_context(tmp_path, phase="post-change")
    asyncio.run(
        _ToleranceJob(
            planned=[
                Observation(device="R1", series_key="nbr-1", value=105, raw="105"),
            ],
        ).compare_state(
            expected={"tolerance": 10},
            current={"tolerance": 10},
            context=ctx2,
        )
    )
    assert cast(_FakeResults, ctx2.results).entries[0][0] == ResultStatus.PASSED

    # Outside tolerance — fails
    ctx3 = _make_context(tmp_path, phase="post-normalize")
    asyncio.run(
        _ToleranceJob(
            planned=[
                Observation(device="R1", series_key="nbr-1", value=200, raw="200"),
            ],
        ).compare_state(
            expected={"tolerance": 10},
            current={"tolerance": 10},
            context=ctx3,
        )
    )
    failed = [
        e
        for e in cast(_FakeResults, ctx3.results).entries
        if e[0] == ResultStatus.FAILED
    ]
    assert len(failed) == 1


def test_parameters_passed_to_comparison_unchanged(tmp_path: Path) -> None:
    """The parameters dict passed to passes_comparison is the full expected."""
    import asyncio

    observed_parameters: list[dict[str, Any]] = []

    class _InspectJob(VolatileLearningTestCase[dict[str, Any]]):
        SERIES_PREFIX = "inspect-series"

        async def gather_state(self, context: Context) -> dict[str, Any]:
            return {}

        async def gather_observations(
            self,
            context: Context,
        ) -> Iterable[Observation]:
            return [
                Observation(device="R1", series_key="x", value=1, raw="1"),
            ]

        def passes_comparison(
            self,
            *,
            parameters: dict[str, Any],
            observation: Observation,
            prior: dict[str, Any],
            context: Context,
        ) -> bool:
            observed_parameters.append(parameters)
            return True

    # Need a prior observation to reach the comparison call.
    ctx1 = _make_context(tmp_path)
    asyncio.run(
        _InspectJob().compare_state(
            expected={"anything": 42, "at": "all"},
            current={"anything": 42, "at": "all"},
            context=ctx1,
        )
    )
    ctx2 = _make_context(tmp_path, phase="post-change")
    asyncio.run(
        _InspectJob().compare_state(
            expected={"anything": 42, "at": "all"},
            current={"anything": 42, "at": "all"},
            context=ctx2,
        )
    )

    assert observed_parameters == [{"anything": 42, "at": "all"}]


def test_extra_fields_are_written_to_records(tmp_path: Path) -> None:
    """Subclass-supplied Observation.extra fields survive to the JSONL record."""
    import asyncio

    ctx = _make_context(tmp_path)
    job = _OperatorJob(
        planned=[
            Observation(
                device="R1",
                series_key="192.0.2.1",
                value=42,
                raw="42",
                extra={"neighbor": "192.0.2.1", "family": "ipv4-unicast"},
            ),
        ],
    )
    asyncio.run(
        job.compare_state(
            expected={"operator": "gte"},
            current={"operator": "gte"},
            context=ctx,
        )
    )

    obs_file = tmp_path / "artifacts" / "demo-series.jsonl"
    record = json.loads(obs_file.read_text().splitlines()[0])
    assert record["neighbor"] == "192.0.2.1"
    assert record["family"] == "ipv4-unicast"


def test_framework_does_not_import_parser_library() -> None:
    """The volatile module must not depend on any third-party parser."""
    import huginn.volatile as vol_mod

    forbidden = {"muninn", "textfsm", "ntc_templates", "pyats"}
    for mod in list(vol_mod.__dict__.values()):
        mod_name = getattr(mod, "__name__", "")
        for token in forbidden:
            assert not mod_name.startswith(token), (
                f"volatile module leaks parser dependency: {mod_name}"
            )

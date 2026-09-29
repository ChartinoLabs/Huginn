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


# -- OperatorVolatileLearningTestCase ----------------------------------------


def _make_operator_job(
    series_prefix: str = "operator-series",
    command: str = "show something",
    default_operator: str = "gte",
    planned: list[Observation] | None = None,
) -> type:
    """Build a concrete OperatorVolatileLearningTestCase subclass inline."""
    from huginn import OperatorVolatileLearningTestCase

    captured = list(planned or [])

    async def gather_observations(
        self: OperatorVolatileLearningTestCase,
        context: Context,
    ) -> Iterable[Observation]:
        return captured

    return type(
        "_Job",
        (OperatorVolatileLearningTestCase,),
        {
            "SERIES_PREFIX": series_prefix,
            "command": command,
            "DEFAULT_OPERATOR": default_operator,
            "gather_observations": gather_observations,
        },
    )


def test_operator_subclass_must_declare_command() -> None:
    """Concrete operator subclasses must declare a device command."""
    from huginn import OperatorVolatileLearningTestCase

    with pytest.raises(TypeError, match="must define command"):

        class _Bad(OperatorVolatileLearningTestCase):
            SERIES_PREFIX = "some-series"

            async def gather_observations(
                self, context: Context
            ) -> Iterable[Observation]:
                return []


def test_operator_passes_comparison_uses_apply_operator(tmp_path: Path) -> None:
    """Operator schema passes comparisons via apply_operator."""
    import asyncio

    cls = _make_operator_job(
        planned=[Observation(device="R1", series_key="k", value=200, raw="200")],
    )
    ctx1 = _make_context(tmp_path)
    asyncio.run(
        cls().compare_state(
            expected={"devices": {"R1": {"operator": "gte"}}},
            current={"devices": {"R1": {"operator": "gte"}}},
            context=ctx1,
        )
    )

    cls2 = _make_operator_job(
        planned=[Observation(device="R1", series_key="k", value=300, raw="300")],
    )
    ctx2 = _make_context(tmp_path, phase="post-change")
    asyncio.run(
        cls2().compare_state(
            expected={"devices": {"R1": {"operator": "gte"}}},
            current={"devices": {"R1": {"operator": "gte"}}},
            context=ctx2,
        )
    )

    results = cast(_FakeResults, ctx2.results).entries
    assert results[0][0] == ResultStatus.PASSED


def test_operator_any_always_passes(tmp_path: Path) -> None:
    """The 'any' operator records observations but always passes."""
    import asyncio

    cls = _make_operator_job(
        planned=[Observation(device="R1", series_key="k", value=500, raw="500")],
    )
    ctx1 = _make_context(tmp_path)
    asyncio.run(
        cls().compare_state(
            expected={"devices": {"R1": {"operator": "any"}}},
            current={"devices": {"R1": {"operator": "any"}}},
            context=ctx1,
        )
    )

    # A value that would fail gte (smaller than prior) still passes under 'any'.
    cls2 = _make_operator_job(
        planned=[Observation(device="R1", series_key="k", value=1, raw="1")],
    )
    ctx2 = _make_context(tmp_path, phase="post-change")
    asyncio.run(
        cls2().compare_state(
            expected={"devices": {"R1": {"operator": "any"}}},
            current={"devices": {"R1": {"operator": "any"}}},
            context=ctx2,
        )
    )

    results = cast(_FakeResults, ctx2.results).entries
    assert all(status == ResultStatus.PASSED for status, _ in results)


def test_operator_gather_state_returns_default_operator(tmp_path: Path) -> None:
    """gather_state persists the declared default operator."""
    import asyncio

    cls = _make_operator_job(default_operator="lt")
    ctx = _make_context(tmp_path, targets=[_FakeDevice(name="R1")])
    result = asyncio.run(cls().gather_state(ctx))
    assert result == {"devices": {"R1": {"operator": "lt"}}}


@dataclass(frozen=True)
class _FakeCommandResult:
    output: str


@dataclass
class _UnsupportedOnR2Broker:
    async def execute(self, device: _FakeDevice, command: str) -> _FakeCommandResult:
        output = "% Invalid input detected" if device.name == "R2" else "ok"
        return _FakeCommandResult(output=output)


@dataclass
class _StaticParameters:
    payload: dict[str, Any]

    async def load(self) -> dict[str, Any]:
        return self.payload


@dataclass
class _NaResults(_FakeResults):
    not_applicable_devices: dict[str, str] = field(default_factory=dict)


def test_operator_job_reports_lost_applicability_for_learned_device(
    tmp_path: Path,
) -> None:
    """A learned device that stops supporting the command lost applicability."""
    import asyncio

    cls = _make_operator_job(
        planned=[Observation(device="R1", series_key="k", value=1, raw="1")],
    )
    ctx = cast(
        Any, _make_context(tmp_path, targets=[_FakeDevice("R1"), _FakeDevice("R2")])
    )
    ctx.results = _NaResults()
    ctx.broker = _UnsupportedOnR2Broker()
    ctx.parameters = _StaticParameters(
        {"devices": {"R1": {"operator": "gte"}, "R2": {"operator": "gte"}}}
    )

    asyncio.run(cls().test(ctx))

    statuses = {status for status, _ in ctx.results.entries}
    assert ResultStatus.LOST_APPLICABILITY in statuses
    assert ResultStatus.NOT_APPLICABLE not in statuses
    assert ctx.results.not_applicable_devices == {}


def test_operator_job_keeps_unlearned_device_not_applicable(tmp_path: Path) -> None:
    """A device the operator parameters never covered stays NOT_APPLICABLE."""
    import asyncio

    cls = _make_operator_job(
        planned=[Observation(device="R1", series_key="k", value=1, raw="1")],
    )
    ctx = cast(
        Any, _make_context(tmp_path, targets=[_FakeDevice("R1"), _FakeDevice("R2")])
    )
    ctx.results = _NaResults()
    ctx.broker = _UnsupportedOnR2Broker()
    ctx.parameters = _StaticParameters({"devices": {"R1": {"operator": "gte"}}})

    asyncio.run(cls().test(ctx))

    statuses = {status for status, _ in ctx.results.entries}
    assert ResultStatus.NOT_APPLICABLE in statuses
    assert ResultStatus.LOST_APPLICABILITY not in statuses
    assert set(ctx.results.not_applicable_devices) == {"R2"}


def test_operator_failure_message_mentions_operator(tmp_path: Path) -> None:
    """Failure messages surface the operator framing."""
    import asyncio

    cls = _make_operator_job(
        planned=[Observation(device="R1", series_key="k", value=100, raw="100")],
    )
    ctx1 = _make_context(tmp_path)
    asyncio.run(
        cls().compare_state(
            expected={"devices": {"R1": {"operator": "gte"}}},
            current={"devices": {"R1": {"operator": "gte"}}},
            context=ctx1,
        )
    )

    cls2 = _make_operator_job(
        planned=[Observation(device="R1", series_key="k", value=50, raw="50")],
    )
    ctx2 = _make_context(tmp_path, phase="post-change")
    asyncio.run(
        cls2().compare_state(
            expected={"devices": {"R1": {"operator": "gte"}}},
            current={"devices": {"R1": {"operator": "gte"}}},
            context=ctx2,
        )
    )

    failed = [
        e
        for e in cast(_FakeResults, ctx2.results).entries
        if e[0] == ResultStatus.FAILED
    ]
    assert len(failed) == 1
    assert "failed operator comparison" in failed[0][1]


# -- parse_duration_seconds --------------------------------------------------


@pytest.mark.parametrize(
    "duration, expected",
    [
        ("5 minutes", 300),
        ("2 hours, 30 minutes", 9000),
        ("1 day, 2 hours", 93600),
        ("1 week, 2 days", 604800 + 2 * 86400),
        ("45 seconds", 45),
        (
            "3 weeks, 4 days, 5 hours, 6 minutes, 7 seconds",
            3 * 604800 + 4 * 86400 + 5 * 3600 + 6 * 60 + 7,
        ),
    ],
)
def test_parse_duration_verbose_forms(duration: str, expected: int) -> None:
    """Verbose Cisco-style durations parse to total seconds."""
    from huginn import parse_duration_seconds

    assert parse_duration_seconds(duration) == expected


_DAY = 86400
_WEEK = 7 * _DAY
_YEAR = 365 * _DAY


@pytest.mark.parametrize(
    "duration, expected",
    [
        # Single units
        ("5y", 5 * _YEAR),
        ("3w", 3 * _WEEK),
        ("4d", 4 * _DAY),
        ("7h", 7 * 3600),
        ("33m", 33 * 60),
        ("45s", 45),
        # Two-unit forms emitted by IOS-XE, NX-OS, and IOS-XR parsers
        ("1w2d", _WEEK + 2 * _DAY),
        ("02w00d", 2 * _WEEK),
        ("1d02h", _DAY + 2 * 3600),
        ("0d04h", 4 * 3600),
        ("118d18h", 118 * _DAY + 18 * 3600),
        ("1y03w", _YEAR + 3 * _WEEK),
        ("2y3w", 2 * _YEAR + 3 * _WEEK),
        # Longer forms, including non-adjacent units
        ("25d10h18m", 25 * _DAY + 10 * 3600 + 18 * 60),
        ("1y2d", _YEAR + 2 * _DAY),
        ("1h30s", 3600 + 30),
        (
            "1y2w3d4h5m6s",
            _YEAR + 2 * _WEEK + 3 * _DAY + 4 * 3600 + 5 * 60 + 6,
        ),
        # Clock form, alone or after a compact prefix
        ("00:05:00", 5 * 60),
        ("01:00:00", 3600),
        ("01:02:03", 3723),
        ("2d03:04:05", 2 * _DAY + 3 * 3600 + 4 * 60 + 5),
        ("29w5d 22:42:36", 29 * _WEEK + 5 * _DAY + 22 * 3600 + 42 * 60 + 36),
        ("  3d12h  ", 3 * _DAY + 12 * 3600),
    ],
)
def test_parse_duration_compact_forms(duration: str, expected: int) -> None:
    """Compact Cisco-style durations parse to total seconds."""
    from huginn import parse_duration_seconds

    assert parse_duration_seconds(duration) == expected


@pytest.mark.parametrize(
    "duration, expected",
    [
        # D:HH:MM:SS from IOS-XE ``show sdwan control connections`` / ``omp peers``
        ("0:00:16:22", 16 * 60 + 22),
        ("6:13:58:46", 6 * _DAY + 13 * 3600 + 58 * 60 + 46),
        ("90:21:24:08", 90 * _DAY + 21 * 3600 + 24 * 60 + 8),
        # D+HH:MM:SS from Junos ``show system processes summary`` / ``brief``
        ("41+06:26:24", 41 * _DAY + 6 * 3600 + 26 * 60 + 24),
        ("87+21:25:46", 87 * _DAY + 21 * 3600 + 25 * 60 + 46),
        # N day(s), H:MM:SS from EOS and PAN-OS
        ("2 days, 2:38:49", 2 * _DAY + 2 * 3600 + 38 * 60 + 49),
        ("68 days, 0:11:28", 68 * _DAY + 11 * 60 + 28),
        ("1 day, 0:11:28", _DAY + 11 * 60 + 28),
        # N day(s), HH:MM from Junos ``show system uptime`` is hours:minutes
        ("154 days, 19:16", 154 * _DAY + 19 * 3600 + 16 * 60),
        ("1 day, 19:16", _DAY + 19 * 3600 + 16 * 60),
        # Three fields remain HH:MM:SS
        ("0:00:16", 16),
    ],
)
def test_parse_duration_day_clock_forms(duration: str, expected: int) -> None:
    """Durations with a day count before a clock include the clock."""
    from huginn import parse_duration_seconds

    assert parse_duration_seconds(duration) == expected


@pytest.mark.parametrize(
    "duration",
    [
        "never",
        "Never",
        "",
        "N/A",
        # Units out of order
        "2h1d",
        "3d2w",
        # Unknown unit or trailing garbage must not be partially parsed
        "1d02x",
        "1d02h foo",
        "00:01:04 (3d10h ago)",
        # Incomplete clock
        "12:34",
        # Malformed day-and-clock forms
        "1:2:3:4:5",
        "41+",
        "+06:26:24",
        "41+06:26",
        "0:00:16:22 ago",
    ],
)
def test_parse_duration_unknown_returns_zero(duration: str) -> None:
    """Unparseable durations return zero rather than raising or truncating."""
    from huginn import parse_duration_seconds

    assert parse_duration_seconds(duration) == 0

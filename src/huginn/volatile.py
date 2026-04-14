"""Base class and utilities for volatile parameter jobs.

Volatile parameter jobs validate device state values that change continuously
during normal operation (uptimes, counters, version numbers). Rather than
storing absolute captured values, these jobs persist a comparison operator
and chain observations across phases via JSONL log files in the run's
``context.output_dir``.

See ``docs/09-volatile-parameters.md`` for the full design rationale.

## Usage

Subclasses implement ``gather_observations()`` to yield one
:class:`Observation` per logical object on each execution, and declare:

- ``SERIES_PREFIX`` — stable identifier that determines the JSONL filename
  and survives across reconciled test case variants.
- ``DEFAULT_OPERATOR`` — the comparison operator persisted in learning mode
  (default: ``"gte"``).

The framework-level base class is parser-agnostic. It is the subclass's
responsibility to execute device commands, parse their output, and produce
observations. Projects can build their own thin wrapper classes that add
parser-specific helpers.

## Observation schema

Each observation record written to the JSONL log includes:

- ``series`` — ``"{device}::{series_key}"`` identifying the observed object
- ``value`` — numeric value used for comparison
- ``raw`` — original representation (preserved for display)
- ``device`` — device name
- ``timestamp`` — UTC ISO-8601 timestamp of the execution
- ``test_id``, ``scenario``, ``phase``, ``test_case_group`` — execution context
- Any additional fields supplied via :attr:`Observation.extra`
"""

from __future__ import annotations

import json
from abc import abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar, TypedDict

from huginn.context import Context
from huginn.testcase import LearningTestCase

_SUPPORTED_OPERATORS = frozenset({"gte", "lt", "gt", "lte"})


class VolatileParameters(TypedDict):
    """Parameter payload persisted by volatile jobs.

    Volatile jobs persist a comparison operator rather than a captured value,
    because the value being observed changes continuously during normal
    operation. See ``docs/09-volatile-parameters.md`` for the full design.
    """

    operator: str


@dataclass
class Observation:
    """One observation of a logical object captured during a test execution.

    ``series_key`` identifies the object within a device (e.g. a BGP
    neighbor address or an interface name). The full series identity in
    the observation log is ``"{device}::{series_key}"``.

    ``extra`` carries any job-specific metadata that should be written to
    the observation record alongside the framework-supplied fields.
    """

    device: str
    series_key: str
    value: int
    raw: str
    extra: dict[str, Any] = field(default_factory=dict)


def apply_operator(operator: str, current: int, prior: int) -> bool:
    """Return whether ``current`` satisfies ``operator`` relative to ``prior``.

    Supported operators: ``"gte"``, ``"gt"``, ``"lt"``, ``"lte"``.
    """
    if operator not in _SUPPORTED_OPERATORS:
        msg = f"Unsupported comparison operator: {operator}"
        raise ValueError(msg)
    if operator == "gte":
        return current >= prior
    if operator == "gt":
        return current > prior
    if operator == "lt":
        return current < prior
    return current <= prior


def observation_path(context: Context, series_prefix: str) -> Path:
    """Return the JSONL log path for a given series prefix in this run."""
    return context.output_dir / f"{series_prefix}.jsonl"


def read_prior_observations(
    context: Context,
    series_prefix: str,
) -> dict[str, dict[str, Any]]:
    """Return the most recent observation per series from the log file.

    Later entries in the log supersede earlier ones. Returns an empty dict
    if the log file does not exist yet (e.g. first execution of a run).
    """
    path = observation_path(context, series_prefix)
    latest: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return latest
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        latest[record["series"]] = record
    return latest


def write_observations(
    context: Context,
    series_prefix: str,
    observations: list[dict[str, Any]],
) -> None:
    """Append observation records to the JSONL log."""
    path = observation_path(context, series_prefix)
    with path.open("a", encoding="utf-8") as fh:
        for obs in observations:
            fh.write(json.dumps(obs, separators=(",", ":")) + "\n")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _build_observation_metadata(context: Context) -> dict[str, Any]:
    return {
        "timestamp": _now_iso(),
        "test_id": context.test_id,
        "scenario": context.scenario,
        "phase": context.phase,
        "test_case_group": context.test_case_group,
    }


class VolatileLearningTestCase(LearningTestCase[VolatileParameters]):
    """Base class for volatile parameter jobs using observation chains.

    This class implements the observation chain lifecycle and delegates
    the parts that vary per job to :meth:`gather_observations`. In learning
    mode the persisted payload is just the comparison operator. In testing
    mode each execution reads the most recent prior observation per series
    from the JSONL log, applies the operator, and appends new observations.

    The framework class is parser-agnostic: the subclass is responsible for
    executing device commands, parsing output, and yielding observations.
    """

    SERIES_PREFIX: ClassVar[str] = ""
    DEFAULT_OPERATOR: ClassVar[str] = "gte"

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Validate required class attributes on concrete subclasses."""
        super().__init_subclass__(**kwargs)
        if getattr(cls, "__abstractmethods__", frozenset()):
            return
        if not cls.SERIES_PREFIX:
            msg = f"{cls.__name__} must define SERIES_PREFIX"
            raise TypeError(msg)

    async def gather_state(self, context: Context) -> VolatileParameters:
        """Return the comparison operator for persistence in learning mode.

        Overridable if a job computes the operator dynamically rather than
        using the class-level default.
        """
        return {"operator": self.DEFAULT_OPERATOR}

    @abstractmethod
    async def gather_observations(
        self,
        context: Context,
    ) -> Iterable[Observation]:
        """Yield current observations from devices.

        Implementations execute device commands, parse output, and yield
        one :class:`Observation` per logical object being tracked. The
        framework takes care of the observation chain from there.
        """

    def build_first_observation_message(self, device_name: str) -> str:
        """Result message for the first execution in a run (no prior)."""
        return (
            f"{device_name}: observations for {self.SERIES_PREFIX} recorded "
            "(first in this run, no prior to compare against)"
        )

    def build_success_message(self, device_name: str, operator: str) -> str:
        """Result message when current observations satisfy the operator."""
        return (
            f"{device_name}: observations for {self.SERIES_PREFIX} satisfy "
            f"operator '{operator}' relative to the prior observation"
        )

    def build_failure_message(
        self,
        *,
        device_name: str,
        series_key: str,
        operator: str,
        prior: dict[str, Any],
        current_raw: str,
    ) -> str:
        """Result message when an observation violates the operator."""
        return (
            f"{device_name}'s {self.SERIES_PREFIX} for '{series_key}' "
            f"violated operator '{operator}': prior={prior['raw']!r}, "
            f"current={current_raw!r}"
        )

    async def compare_state(
        self,
        *,
        expected: VolatileParameters,
        current: VolatileParameters,
        context: Context,
    ) -> None:
        """Run the observation chain comparison for this phase boundary."""
        from huginn.enums import ResultStatus  # local import to avoid cycles

        operator = expected["operator"]
        prior_observations = read_prior_observations(context, self.SERIES_PREFIX)
        metadata = _build_observation_metadata(context)

        observations = list(await self.gather_observations(context))

        new_records: list[dict[str, Any]] = []
        per_device_state: dict[str, dict[str, bool]] = {}

        for obs in observations:
            series = f"{obs.device}::{obs.series_key}"
            record = {
                "series": series,
                "value": obs.value,
                "raw": obs.raw,
                "device": obs.device,
                **obs.extra,
                **metadata,
            }
            new_records.append(record)

            state = per_device_state.setdefault(
                obs.device,
                {"has_prior": False, "has_failures": False},
            )

            prior = prior_observations.get(series)
            if prior is None:
                continue

            state["has_prior"] = True
            if not apply_operator(operator, obs.value, prior["value"]):
                context.results.add_result(
                    ResultStatus.FAILED,
                    self.build_failure_message(
                        device_name=obs.device,
                        series_key=obs.series_key,
                        operator=operator,
                        prior=prior,
                        current_raw=obs.raw,
                    ),
                )
                state["has_failures"] = True

        for device in context.targets:
            state = per_device_state.get(device.name)
            if state is None:
                continue
            if not state["has_prior"]:
                context.results.add_result(
                    ResultStatus.PASSED,
                    self.build_first_observation_message(device.name),
                )
            elif not state["has_failures"]:
                context.results.add_result(
                    ResultStatus.PASSED,
                    self.build_success_message(device.name, operator),
                )

        write_observations(context, self.SERIES_PREFIX, new_records)

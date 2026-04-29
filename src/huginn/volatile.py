"""Base class and utilities for volatile parameter jobs.

Volatile parameter jobs validate device state values that change continuously
during normal operation (uptimes, counters, version numbers). Rather than
storing absolute captured values, these jobs chain observations across
phases via JSONL log files in the run's ``context.output_dir`` and defer
the comparison decision to job-defined logic.

See ``docs/09-volatile-parameters.md`` for the full design rationale.

## Usage

Subclasses implement three methods:

- :meth:`gather_observations` — yield one :class:`Observation` per logical
  object on each execution.
- :meth:`gather_state` — return the parameters to persist in learning
  mode (inherited from :class:`LearningTestCase`). Schema is entirely up
  to the subclass.
- :meth:`passes_comparison` — return whether a current observation is
  acceptable given its most recent prior observation. The subclass
  interprets its own parameter schema here.

And declare:

- ``SERIES_PREFIX`` — stable identifier that determines the JSONL filename
  and survives across reconciled test case variants.

The framework-level base class is parser-agnostic and schema-agnostic.
It is the subclass's responsibility to execute device commands, parse
their output, produce observations, and decide how each observation
compares against its prior. Projects can build intermediate subclasses
that fix a particular schema (e.g. a single operator key) while leaving
parsing concerns to their own concrete jobs.

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
import re
from abc import abstractmethod
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar, Generic, TypedDict, TypeVar

from huginn.context import Context
from huginn.testcase import ApplicabilityResult, LearningTestCase
from huginn.utils.commands import is_command_unsupported

VolatileParametersT = TypeVar("VolatileParametersT", bound=Mapping[str, object])

_SUPPORTED_OPERATORS = frozenset({"gte", "lt", "gt", "lte"})
_OPERATOR_ANY = "any"

_NOT_SUPPORTED_REASON = "Device does not support '{command}'"


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

    This is a convenience helper for jobs that want to use a simple
    operator-based comparison scheme. The framework itself does not
    prescribe any particular scheme — subclasses of
    :class:`VolatileLearningTestCase` implement their own
    :meth:`~VolatileLearningTestCase.passes_comparison` and can use this
    helper or not, as they see fit.
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


class VolatileLearningTestCase(
    LearningTestCase[VolatileParametersT],
    Generic[VolatileParametersT],
):
    """Base class for volatile parameter jobs using observation chains.

    This class implements the observation chain lifecycle and delegates
    three concerns to subclasses:

    1. What parameters to persist (:meth:`gather_state`)
    2. How to produce observations (:meth:`gather_observations`)
    3. How to compare a current observation against its prior
       (:meth:`passes_comparison`)

    The parameter schema is entirely subclass-defined. The framework does
    not prescribe a particular shape — subclasses can persist a single
    operator, a per-series operator map, tolerance thresholds, or
    anything else they need to make a comparison decision.

    The framework is also parser-agnostic: the subclass is responsible
    for executing device commands, parsing output, and yielding
    observations via :meth:`gather_observations`.
    """

    SERIES_PREFIX: ClassVar[str] = ""

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Validate required class attributes on concrete subclasses.

        Intermediate abstract subclasses (those that still declare at least
        one abstract method directly, or inherit unimplemented abstract
        methods) are exempt from the check — ``__abstractmethods__`` is
        populated by ``ABCMeta.__new__`` after ``__init_subclass__`` runs,
        so we scan for abstract methods explicitly here.
        """
        super().__init_subclass__(**kwargs)
        declares_abstract = any(
            getattr(value, "__isabstractmethod__", False)
            for value in cls.__dict__.values()
        )
        if declares_abstract:
            return
        if getattr(cls, "__abstractmethods__", frozenset()):
            return
        if not cls.SERIES_PREFIX:
            msg = f"{cls.__name__} must define SERIES_PREFIX"
            raise TypeError(msg)

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

    @abstractmethod
    def passes_comparison(
        self,
        *,
        parameters: VolatileParametersT,
        observation: Observation,
        prior: dict[str, Any],
        context: Context,
    ) -> bool:
        """Return whether ``observation`` is acceptable given ``prior``.

        The subclass interprets ``parameters`` (the payload loaded from the
        parameter file) however it likes — a single operator key, a
        per-series operator map, tolerance thresholds, etc. ``prior`` is
        the most recent prior observation record for the same series,
        with the full record shape (``series``, ``value``, ``raw``,
        ``device``, metadata fields, etc.).

        Return ``True`` to record a pass for this boundary, ``False`` to
        record a fail.
        """

    def build_first_observation_message(self, device_name: str) -> str:
        """Result message for the first execution in a run (no prior)."""
        return (
            f"{device_name}: observations for {self.SERIES_PREFIX} recorded "
            "(first in this run, no prior to compare against)"
        )

    def build_success_message(self, device_name: str) -> str:
        """Result message when all current observations pass comparison."""
        return (
            f"{device_name}: observations for {self.SERIES_PREFIX} pass "
            "comparison against the prior observation"
        )

    def build_failure_message(
        self,
        *,
        device_name: str,
        series_key: str,
        prior: dict[str, Any],
        current: Observation,
    ) -> str:
        """Result message when an observation fails comparison.

        Overridable if a subclass wants to surface operator-specific or
        threshold-specific detail in the message.
        """
        return (
            f"{device_name}'s {self.SERIES_PREFIX} for '{series_key}' "
            f"failed comparison: prior={prior['raw']!r}, "
            f"current={current.raw!r}"
        )

    async def compare_state(
        self,
        *,
        expected: VolatileParametersT,
        current: VolatileParametersT,
        context: Context,
    ) -> None:
        """Run the observation chain comparison for this phase boundary."""
        from huginn.enums import ResultStatus  # local import to avoid cycles

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
            if not self.passes_comparison(
                parameters=expected,
                observation=obs,
                prior=prior,
                context=context,
            ):
                context.results.add_result(
                    ResultStatus.FAILED,
                    self.build_failure_message(
                        device_name=obs.device,
                        series_key=obs.series_key,
                        prior=prior,
                        current=obs,
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
                    self.build_success_message(device.name),
                )

        write_observations(context, self.SERIES_PREFIX, new_records)


class OperatorVolatileParameters(TypedDict):
    """Parameter schema for operator-based volatile jobs.

    The single ``operator`` key drives the comparison between a new
    observation and its prior. Supported values are ``"gte"``, ``"gt"``,
    ``"lt"``, ``"lte"``, and the special value ``"any"`` — which records
    the observation in the chain but always passes the comparison. The
    ``"any"`` operator is useful at phase boundaries where the impact on
    individual series is heterogeneous (e.g. a process restart resets
    some sessions but leaves others untouched), so a single directional
    operator cannot satisfy every series at once.
    """

    operator: str


class OperatorVolatileLearningTestCase(
    VolatileLearningTestCase[OperatorVolatileParameters],
):
    """Volatile base class using a single-operator parameter schema.

    This intermediate sits between :class:`VolatileLearningTestCase` and
    concrete jobs that follow the common pattern of:

    1. Executing a single device command (declared via :attr:`command`).
    2. Producing one or more monotonic-style observations per device.
    3. Comparing each observation against its prior using a single
       operator persisted as the parameter payload.

    Subclasses must still implement :meth:`gather_observations` — the
    parsing step is intentionally left to each subclass so the framework
    does not depend on any particular parser library.

    Typical subclass structure:

    .. code-block:: python

        class VerifyUptimeIncreased(OperatorVolatileLearningTestCase):
            SERIES_PREFIX = "version-uptime"
            command = "show version"

            async def gather_observations(self, context):
                ...
    """

    command: ClassVar[str] = ""
    DEFAULT_OPERATOR: ClassVar[str] = "gte"

    @abstractmethod
    async def gather_observations(
        self,
        context: Context,
    ) -> Iterable[Observation]:
        """Yield current observations from devices.

        Subclasses implement this to execute :attr:`command` on each
        target, parse the output with their chosen parser, and yield
        one :class:`Observation` per tracked object. The framework does
        not prescribe a parser library — this hook is the boundary.
        """

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Validate that concrete subclasses declare a device command."""
        super().__init_subclass__(**kwargs)
        declares_abstract = any(
            getattr(value, "__isabstractmethod__", False)
            for value in cls.__dict__.values()
        )
        if declares_abstract:
            return
        if getattr(cls, "__abstractmethods__", frozenset()):
            return
        if not cls.command:
            msg = f"{cls.__name__} must define command"
            raise TypeError(msg)

    async def check_applicability(
        self,
        context: Context,
    ) -> ApplicabilityResult:
        """Default applicability: target supports the configured command."""
        applicable = []
        not_applicable: dict[str, str] = {}
        for device in context.targets:
            result = await context.broker.execute(device, self.command)
            if is_command_unsupported(result.output):
                not_applicable[device.name] = _NOT_SUPPORTED_REASON.format(
                    command=self.command,
                )
                continue
            applicable.append(device)
        return ApplicabilityResult(
            applicable=applicable,
            not_applicable=not_applicable,
        )

    async def gather_state(
        self,
        context: Context,
    ) -> OperatorVolatileParameters:
        """Persist the default operator as the learned parameter payload."""
        return {"operator": self.DEFAULT_OPERATOR}

    def passes_comparison(
        self,
        *,
        parameters: OperatorVolatileParameters,
        observation: Observation,
        prior: dict[str, Any],
        context: Context,
    ) -> bool:
        """Compare current and prior via the learned operator.

        The ``"any"`` operator records the observation in the chain but
        always passes. Any other value is delegated to
        :func:`apply_operator`.
        """
        if parameters["operator"] == _OPERATOR_ANY:
            return True
        return apply_operator(
            parameters["operator"],
            observation.value,
            prior["value"],
        )

    def build_failure_message(
        self,
        *,
        device_name: str,
        series_key: str,
        prior: dict[str, Any],
        current: Observation,
    ) -> str:
        """Surface the operator framing in failure messages."""
        return (
            f"{device_name}'s {self.SERIES_PREFIX} for '{series_key}' "
            f"failed operator comparison: prior={prior['raw']!r}, "
            f"current={current.raw!r}"
        )


def parse_duration_seconds(duration: str) -> int:
    """Parse a Cisco-style duration string to total seconds.

    Handles both verbose and compact forms emitted across different IOS
    commands:

    - Verbose: ``"5 weeks, 2 days, 13 hours, 30 minutes, 45 seconds"``
    - Compact: ``"1w2d"``, optionally followed by ``"HH:MM:SS"``

    Unknown formats return ``0`` rather than raising, consistent with how
    the function is typically used for monotonic comparison values where
    a missing value should simply fail the ``gt``/``gte`` check.
    """
    total = 0
    for count_s, unit in re.findall(
        r"(\d+)\s+(week|day|hour|minute|second)s?",
        duration,
    ):
        count = int(count_s)
        if unit == "week":
            total += count * 604800
        elif unit == "day":
            total += count * 86400
        elif unit == "hour":
            total += count * 3600
        elif unit == "minute":
            total += count * 60
        else:
            total += count
    if total:
        return total
    weeks = re.search(r"(\d+)w", duration)
    if weeks:
        total += int(weeks.group(1)) * 604800
    days = re.search(r"(\d+)d", duration)
    if days:
        total += int(days.group(1)) * 86400
    hms = re.search(r"(\d+):(\d+):(\d+)", duration)
    if hms:
        total += int(hms.group(1)) * 3600 + int(hms.group(2)) * 60 + int(hms.group(3))
    return total

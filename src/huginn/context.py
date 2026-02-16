"""Execution context passed to test jobs."""

from dataclasses import dataclass
from typing import Any

from huginn.enums import ExecutionMode
from huginn.models import Device, Testbed
from huginn.parameters import ParameterManager
from huginn.results import ResultCollector


@dataclass
class Context:
    """Runtime context available to a running test case."""

    test_id: str
    test_title: str
    mode: ExecutionMode
    testbed: Testbed
    targets: list[Device]
    broker: Any  # noqa: ANN401
    parameters: ParameterManager
    results: ResultCollector
    # TODO: Implement data model loading/injection when this capability is scoped in.
    data_model: dict[str, object] | None = None

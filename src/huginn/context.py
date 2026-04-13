"""Execution context passed to test jobs."""

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from huginn.enums import ExecutionMode
from huginn.models import Device, Testbed
from huginn.parameters import ParameterManager
from huginn.results import ResultCollector

if TYPE_CHECKING:
    from huginn.output import Output


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
    output_dir: Path
    output: "Output | None" = None
    # TODO: Implement data model loading/injection when this capability is scoped in.
    data_model: dict[str, object] | None = None

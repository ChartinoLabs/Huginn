"""Execution context passed to test jobs."""

from collections.abc import Mapping
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
    scenario: str
    phase: str
    test_case_group: str
    output: "Output | None" = None
    # Merged data model shared by every job in the run, or None when none is
    # configured. Read-only: every nested dict and list rejects mutation.
    data_model: Mapping[str, object] | None = None

"""A test automation framework for infrastructure."""

from huginn._version import __version__, __version_tuple__
from huginn.cli import main
from huginn.context import Context
from huginn.enums import ExecutionMode, ResultStatus
from huginn.execute import ExecuteCommandResult, ExecuteCommandSpec, execute_commands
from huginn.output import Output
from huginn.testcase import CommandSupportResult, LearningTestCase, TestCase
from huginn.utils.commands import is_command_unsupported
from huginn.volatile import (
    Observation,
    OperatorVolatileDeviceParameters,
    OperatorVolatileLearningTestCase,
    OperatorVolatileParameters,
    VolatileLearningTestCase,
    parse_duration_seconds,
)

__all__ = [
    "__version__",
    "__version_tuple__",
    "main",
    "is_command_unsupported",
    "ExecutionMode",
    "ExecuteCommandResult",
    "ExecuteCommandSpec",
    "execute_commands",
    "ResultStatus",
    "Output",
    "Context",
    "TestCase",
    "LearningTestCase",
    "CommandSupportResult",
    "Observation",
    "VolatileLearningTestCase",
    "OperatorVolatileDeviceParameters",
    "OperatorVolatileLearningTestCase",
    "OperatorVolatileParameters",
    "parse_duration_seconds",
]

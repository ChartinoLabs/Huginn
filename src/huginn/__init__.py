"""A test automation framework for infrastructure."""

from huginn.cli import main
from huginn.context import Context
from huginn.enums import ExecutionMode, ResultStatus
from huginn.output import Output
from huginn.testcase import ApplicabilityResult, LearningTestCase, TestCase
from huginn.utils.commands import is_command_unsupported
from huginn.volatile import (
    Observation,
    OperatorVolatileLearningTestCase,
    OperatorVolatileParameters,
    VolatileLearningTestCase,
    parse_duration_seconds,
)

__all__ = [
    "main",
    "is_command_unsupported",
    "ExecutionMode",
    "ResultStatus",
    "Output",
    "Context",
    "TestCase",
    "LearningTestCase",
    "ApplicabilityResult",
    "Observation",
    "VolatileLearningTestCase",
    "OperatorVolatileLearningTestCase",
    "OperatorVolatileParameters",
    "parse_duration_seconds",
]

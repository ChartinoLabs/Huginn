"""A test automation framework for infrastructure."""

from huginn.cli import main
from huginn.command_output import is_command_unsupported
from huginn.context import Context
from huginn.enums import ExecutionMode, ResultStatus
from huginn.output import Output
from huginn.testcase import ApplicabilityResult, LearningTestCase, TestCase

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
]

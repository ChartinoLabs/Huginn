"""A test automation framework for infrastructure."""

from huginn.cli import main
from huginn.context import Context
from huginn.enums import ExecutionMode, ResultStatus
from huginn.output import Output
from huginn.testcase import ApplicabilityResult, LearningTestCase, TestCase

__all__ = [
    "main",
    "ExecutionMode",
    "ResultStatus",
    "Output",
    "Context",
    "TestCase",
    "LearningTestCase",
    "ApplicabilityResult",
]

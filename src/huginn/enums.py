"""Core enumerations for Huginn test automation framework.

This module defines the fundamental enums used throughout the framework
for execution modes and result statuses.
"""

from enum import StrEnum


class ExecutionMode(StrEnum):
    """Execution mode for a test run.

    Huginn supports two execution modes:

    - LEARNING: Execute against live infrastructure, capture current state,
      and persist it as parameters for future comparison.
    - TESTING: Execute against live infrastructure, compare current state
      against previously learned parameters (or data model), and report deviations.
    """

    LEARNING = "learning"
    TESTING = "testing"


class ResultStatus(StrEnum):
    """The outcome of a test case execution.

    Possible values:

    - PASSED: All assertions succeeded.
    - FAILED: One or more assertions did not match expected state.
    - INFO: Informational note with no impact on pass/fail.
    - ERRORED: An exception occurred during execution.
    - NOT_APPLICABLE: Check was out of scope for the target at runtime.
    - SKIPPED: The test case did not execute because it was intentionally skipped.
    - BLOCKED: The test case could not run because a dependency (phase or group) failed.

    Test cases filtered out before execution (e.g., by tags) do not appear in
    results at all.
    """

    PASSED = "passed"
    FAILED = "failed"
    INFO = "info"
    ERRORED = "errored"
    NOT_APPLICABLE = "not_applicable"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class ConnectionProtocol(StrEnum):
    """Supported connection protocol identifiers in testbed definitions."""

    SSH = "ssh"
    HTTP = "http"
    HTTPS = "https"
    REST = "rest"
    NETCONF = "netconf"


class BrokerType(StrEnum):
    """Canonical runtime broker identifiers."""

    SSH = "ssh"
    HTTP = "http"
    NETCONF = "netconf"


class ErrorCode(StrEnum):
    """Structured error categories used in reports and CLI handling."""

    CONFIGURATION_ERROR = "configuration_error"
    VALIDATION_ERROR = "validation_error"
    PLANNING_ERROR = "planning_error"
    EXECUTION_ERROR = "execution_error"
    BROKER_ERROR = "broker_error"

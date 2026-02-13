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
    - ERRORED: An exception occurred during execution.
    - SKIPPED: The test case was in scope but determined at runtime to be
      not applicable (e.g., feature not configured in data model, no matching targets).
    - BLOCKED: The test case could not run because a dependency (phase or group) failed.

    Test cases filtered out before execution (e.g., by tags) do not appear in
    results at all.
    """

    PASSED = "passed"
    FAILED = "failed"
    ERRORED = "errored"
    SKIPPED = "skipped"
    BLOCKED = "blocked"

"""Core enumerations for Huginn test automation framework.

This module defines the fundamental enums used throughout the framework
for execution modes and result statuses.
"""

import sys
from enum import Enum

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:

    class StrEnum(str, Enum):
        """Backport of StrEnum for Python 3.10."""

        def __str__(self) -> str:
            """Return the string value of the enum member."""
            return self.value


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


class IdStyle(StrEnum):
    """Test case ID generation style used by `huginn inject`.

    - PREFIX_COUNTER: `<PREFIX>-<n>`, numbered after the highest existing counter.
    """

    PREFIX_COUNTER = "prefix-counter"


class ResultStatus(StrEnum):
    """The outcome of a test case execution.

    Possible values:

    - PASSED: All assertions succeeded.
    - FAILED: One or more assertions did not match expected state.
    - INFO: Informational note with no impact on pass/fail.
    - ERRORED: An exception occurred during execution.
    - NOT_APPLICABLE: Check was out of scope for the target at runtime.
    - LOST_APPLICABILITY: In testing mode, a target no longer supports the
      job's command although the learned parameters contain it. Counts as a
      failure.
    - SKIPPED: The test case did not execute because it was intentionally skipped.
    - BLOCKED: The test case could not run because a phase it depends on failed,
      errored, or was not run in learning mode, or because a hook aborted the
      run before it started (see ``BlockKind``).

    Test cases filtered out before execution (e.g., by tags) do not appear in
    results at all.
    """

    PASSED = "passed"
    FAILED = "failed"
    INFO = "info"
    ERRORED = "errored"
    NOT_APPLICABLE = "not_applicable"
    LOST_APPLICABILITY = "lost_applicability"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class SkipKind(StrEnum):
    """Why a test case was recorded as SKIPPED.

    - NO_MATCHING_TARGETS: no device matched the test case's target selectors.
    - LEARNING_MODE_UNSUPPORTED: the run is in learning mode and the job does
      not inherit ``LearningTestCase``, so it did not run. A phase with such a
      test case blocks the phases that depend on it, because its intended
      effect (for example a change) did not happen.
    - HOOK: a hook plugin skipped the test case, its group or its phase. The
      skip reason is the hook's. Like other skips, it does not block the
      phases that depend on it.
    """

    NO_MATCHING_TARGETS = "no_matching_targets"
    LEARNING_MODE_UNSUPPORTED = "learning_mode_unsupported"
    HOOK = "hook"


class BlockKind(StrEnum):
    """Why a test case was recorded as BLOCKED.

    - DEPENDENCY_FAILED: a phase it depends on, directly or transitively,
      failed or errored.
    - DEPENDENCY_NOT_LEARNED: a phase it depends on, directly or transitively,
      was not run in learning mode (see ``SkipKind.LEARNING_MODE_UNSUPPORTED``).
    - HOOK_ABORT: a hook plugin aborted the run with ``HookAbort`` before the
      test case started. Like DEPENDENCY_FAILED, it fails the run.
    """

    DEPENDENCY_FAILED = "dependency_failed"
    DEPENDENCY_NOT_LEARNED = "dependency_not_learned"
    HOOK_ABORT = "hook_abort"


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

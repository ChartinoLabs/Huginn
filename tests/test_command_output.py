"""Unit tests for command output heuristics."""

from huginn.utils.commands import is_command_unsupported


def test_is_command_unsupported_matches_common_error_markers() -> None:
    """Known unsupported-command markers evaluate to True."""
    assert is_command_unsupported("% Invalid input detected at '^' marker.")
    assert is_command_unsupported("% Unknown command or computer name")
    assert is_command_unsupported("% Ambiguous command")


def test_is_command_unsupported_returns_false_for_normal_output() -> None:
    """Valid command output evaluates to False."""
    assert not is_command_unsupported("Gig0/1 up up")

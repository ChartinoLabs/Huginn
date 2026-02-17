"""Heuristics for interpreting raw CLI command output."""


def is_command_unsupported(output: str) -> bool:
    """Return True when output likely indicates unsupported command syntax.

    This helper intentionally uses broad, case-insensitive marker matching and
    should be treated as a heuristic.
    """
    normalized = output.lower()
    unsupported_markers = (
        "% invalid input",
        "% unknown command",
        "% ambiguous command",
        "% incomplete command",
        "unknown command",
        "invalid command",
        "syntax error",
    )
    return any(marker in normalized for marker in unsupported_markers)

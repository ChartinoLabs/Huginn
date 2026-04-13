"""Shared helper functions for optional structured logging."""

from huginn.output import Output


def log_debug(output: Output | None, message: str, **fields: object) -> None:
    """Write debug log when output logging is available."""
    if output is None:
        return
    output.log_debug_fields(message, **fields)


def log_info(output: Output | None, message: str, **fields: object) -> None:
    """Write info log when output logging is available."""
    if output is None:
        return
    output.log_info_fields(message, **fields)


def log_warning(output: Output | None, message: str, **fields: object) -> None:
    """Write warning log when output logging is available."""
    if output is None:
        return
    output.log_warning_fields(message, **fields)

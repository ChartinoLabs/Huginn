"""Unified console output and logging utilities."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from rich.console import Console


class Output:
    """Coordinate user-facing console output and diagnostic logging."""

    def __init__(
        self,
        *,
        show_logs: bool = False,
        log_level: str = "INFO",
        log_file: Path | None = None,
    ) -> None:
        """Initialize output and logging handlers.

        Args:
            show_logs: Stream logs to stderr in addition to writing file logs.
            log_level: Logger level name (DEBUG/INFO/WARNING/ERROR).
            log_file: Optional explicit file path for logs.
        """
        self.console = Console()
        self.error_console = Console(stderr=True)
        self.logger = logging.getLogger("huginn")
        self.logger.propagate = False
        self.log_file = log_file or Path.cwd() / "huginn.log"
        self._configure_logger(show_logs=show_logs, log_level=log_level)

    def status(self, message: str) -> None:
        """Print a neutral status message to stdout."""
        self.console.print(message, markup=False)

    def success(self, message: str) -> None:
        """Print a success message to stdout."""
        self.console.print(message, style="green", markup=False)

    def warning(self, message: str) -> None:
        """Print a warning message to stdout."""
        self.console.print(message, style="yellow", markup=False)

    def error(self, message: str) -> None:
        """Print an error message to stderr."""
        self.error_console.print(message, style="red", markup=False)

    def log_debug(self, message: str, *args: object) -> None:
        """Write a DEBUG log entry."""
        self.logger.debug(message, *args)

    def log_info(self, message: str, *args: object) -> None:
        """Write an INFO log entry."""
        self.logger.info(message, *args)

    def log_warning(self, message: str, *args: object) -> None:
        """Write a WARNING log entry."""
        self.logger.warning(message, *args)

    def log_error(self, message: str, *args: object) -> None:
        """Write an ERROR log entry."""
        self.logger.error(message, *args)

    def _configure_logger(self, *, show_logs: bool, log_level: str) -> None:
        """Configure logger handlers and level for current process."""
        self.logger.handlers.clear()

        resolved_level = getattr(logging, log_level.upper(), logging.INFO)
        self.logger.setLevel(resolved_level)

        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(self.log_file, encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
            )
        )
        self.logger.addHandler(file_handler)

        if not show_logs:
            return

        try:
            from rich.logging import RichHandler

            console_handler: logging.Handler = RichHandler(
                console=Console(stderr=True),
                show_time=True,
                show_path=False,
                rich_tracebacks=True,
            )
        except Exception:  # noqa: BLE001
            console_handler = logging.StreamHandler(stream=sys.stderr)

        self.logger.addHandler(console_handler)

"""Reporter plugin protocol for Huginn."""

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from huginn.models import RunResult


@runtime_checkable
class ReporterPlugin(Protocol):
    """Protocol for report generation plugins.

    Reporter plugins consume Huginn's structured RunResult and render
    output for downstream consumers (HTML dashboards, JUnit XML, Slack
    digests, etc.).

    Multiple reporters can be active simultaneously. Each generates its
    output independently.
    """

    @property
    def name(self) -> str:
        """Unique reporter identifier (e.g., 'html', 'junit')."""
        ...

    async def generate_report(
        self,
        *,
        result: RunResult,
        run_dir: Path,
        reports_dir: Path,
        test_case_result_paths: dict[str, str],
        config: dict[str, Any],
    ) -> Path | None:
        """Generate a report from run results.

        Args:
            result: The complete run result data.
            run_dir: Directory where canonical JSON artifacts were written.
            reports_dir: Base directory for report output.
            test_case_result_paths: Mapping of execution keys to their
                relative JSON artifact paths.
            config: Plugin-specific configuration from
                [tool.huginn.plugins.config.<name>].

        Returns:
            Path to the primary report file, or None if no output was
            generated.
        """
        ...

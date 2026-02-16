"""Report plugin interfaces and built-in plugin resolution."""

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from huginn.models import RunReport

if TYPE_CHECKING:
    from huginn.validation import ValidationReport


class ReportPluginError(ValueError):
    """Raised when a report plugin cannot be resolved or written."""


class ReportPlugin(Protocol):
    """Protocol for report plugins that persist run/validation artifacts."""

    @property
    def name(self) -> str:
        """Return plugin display name."""
        raise NotImplementedError

    def write_run_report(self, report: RunReport, reports_dir: Path) -> Path:
        """Persist a run report artifact and return its path."""
        raise NotImplementedError

    def write_validation_report(
        self,
        report: "ValidationReport",
        reports_dir: Path,
    ) -> Path:
        """Persist a validation report artifact and return its path."""
        raise NotImplementedError


@dataclass(frozen=True)
class JsonReportPlugin:
    """Built-in JSON report plugin preserving current artifact format."""

    run_filename: str = "run.json"
    validation_filename: str = "validate.json"

    @property
    def name(self) -> str:
        """Return plugin identifier."""
        return "json"

    def write_run_report(self, report: RunReport, reports_dir: Path) -> Path:
        """Write run report JSON artifact."""
        return _write_json(reports_dir / self.run_filename, asdict(report))

    def write_validation_report(
        self,
        report: "ValidationReport",
        reports_dir: Path,
    ) -> Path:
        """Write validation report JSON artifact."""
        return _write_json(reports_dir / self.validation_filename, asdict(report))


def resolve_report_plugins(specs: list[str] | None) -> list[ReportPlugin]:
    """Resolve report plugin specs, defaulting to the built-in JSON plugin."""
    normalized_specs = _normalize_specs(specs)
    return [_parse_report_plugin_spec(spec) for spec in normalized_specs]


def write_run_reports(
    *,
    report: RunReport,
    reports_dir: Path,
    plugins: Iterable[ReportPlugin],
) -> list[Path]:
    """Write run report artifacts through configured plugins."""
    paths: list[Path] = []
    for plugin in plugins:
        try:
            paths.append(plugin.write_run_report(report, reports_dir))
        except Exception as error:  # noqa: BLE001
            raise ReportPluginError(
                f"Report plugin '{plugin.name}' failed to write run report: {error}"
            ) from error
    return paths


def write_validation_reports(
    *,
    report: "ValidationReport",
    reports_dir: Path,
    plugins: Iterable[ReportPlugin],
) -> list[Path]:
    """Write validation report artifacts through configured plugins."""
    paths: list[Path] = []
    for plugin in plugins:
        try:
            paths.append(plugin.write_validation_report(report, reports_dir))
        except Exception as error:  # noqa: BLE001
            raise ReportPluginError(
                "Report plugin "
                f"'{plugin.name}' failed to write validation report: {error}"
            ) from error
    return paths


def _normalize_specs(specs: list[str] | None) -> list[str]:
    """Normalize plugin spec list and apply default plugin."""
    if not specs:
        return ["json"]

    normalized: list[str] = []
    seen: set[str] = set()
    for spec in specs:
        candidate = spec.strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)
    if not normalized:
        return ["json"]
    return normalized


def _parse_report_plugin_spec(spec: str) -> ReportPlugin:
    """Parse one report plugin spec string into a plugin instance."""
    if ":" in spec:
        raise ReportPluginError(
            "Report plugins currently support built-in names only. Use 'json'."
        )
    if spec == "json":
        return JsonReportPlugin()
    raise ReportPluginError(f"Unsupported report plugin '{spec}'. Supported: json")


def _write_json(path: Path, payload: object) -> Path:
    """Write JSON payload to path, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path

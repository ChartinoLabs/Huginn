"""Persistence helpers for learned test parameters."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


class ParameterStoreError(RuntimeError):
    """Raised when learned parameters cannot be loaded or persisted."""


@dataclass(frozen=True)
class ParameterManager:
    """Per-test parameter storage helper exposed on execution context."""

    parameters_dir: Path
    test_id: str

    async def save(self, payload: Mapping[str, object]) -> None:
        """Persist learned parameters for the current test case."""
        self.parameters_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._parameter_file().write_text(
                json.dumps(payload, indent=2),
                encoding="utf-8",
            )
        except TypeError as error:
            raise ParameterStoreError(
                f"Unable to serialize parameters for test '{self.test_id}': {error}"
            ) from error
        except OSError as error:
            raise ParameterStoreError(
                f"Unable to write parameters for test '{self.test_id}': {error}"
            ) from error

    async def load(self) -> dict[str, object]:
        """Load previously learned parameters for the current test case."""
        parameter_file = self._parameter_file()
        if not parameter_file.exists():
            raise ParameterStoreError(
                f"No learned parameters found for test '{self.test_id}' "
                f"at {parameter_file}"
            )

        try:
            loaded = json.loads(parameter_file.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ParameterStoreError(
                    "Learned parameters JSON must be a mapping at top level for "
                    f"test '{self.test_id}'"
                )
            return loaded
        except json.JSONDecodeError as error:
            raise ParameterStoreError(
                f"Invalid learned parameters JSON for test '{self.test_id}': {error}"
            ) from error
        except OSError as error:
            raise ParameterStoreError(
                f"Unable to read parameters for test '{self.test_id}': {error}"
            ) from error

    def _parameter_file(self) -> Path:
        """Return canonical JSON path for this test case's parameters."""
        return self.parameters_dir / f"{self.test_id}.json"


def load_test_case_parameters(
    parameters_dir: Path,
    test_id: str,
) -> dict[str, object] | None:
    """Load learned parameters for a test case, or ``None`` if absent.

    This is a synchronous read-only helper for external consumers that
    need to inspect learned parameters without running the async test
    execution engine.
    """
    parameter_file = parameters_dir / f"{test_id}.json"
    if not parameter_file.exists():
        return None
    try:
        loaded = json.loads(parameter_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise ParameterStoreError(
            f"Unable to read parameters for test '{test_id}': {error}"
        ) from error
    if not isinstance(loaded, dict):
        raise ParameterStoreError(
            f"Learned parameters JSON must be a mapping at top level for "
            f"test '{test_id}'"
        )
    return loaded


def list_available_parameters(parameters_dir: Path) -> dict[str, Path]:
    """Return ``{test_id: path}`` for every learned parameter file.

    Scans *parameters_dir* for ``*.json`` files and uses the stem as the
    test identifier.  Returns an empty dict when the directory does not
    exist.
    """
    if not parameters_dir.is_dir():
        return {}
    return {
        path.stem: path
        for path in sorted(parameters_dir.glob("*.json"))
        if path.is_file()
    }

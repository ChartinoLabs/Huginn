"""Persistence helpers for learned test parameters."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


class ParameterStoreError(RuntimeError):
    """Raised when learned parameters cannot be loaded or persisted."""


def parameter_file_path(parameters_dir: Path, test_id: str) -> Path:
    """Return the canonical JSON path for a test case's parameters."""
    return parameters_dir / f"{test_id}.json"


def load_test_case_parameters(
    parameters_dir: Path,
    test_id: str,
) -> dict[str, object] | None:
    """Load learned parameters for a test case, or ``None`` if absent."""
    path = parameter_file_path(parameters_dir, test_id)
    if not path.exists():
        return None
    return _read_parameter_file(path, test_id)


def _read_parameter_file(path: Path, test_id: str) -> dict[str, object]:
    """Read and validate a single parameter JSON file."""
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ParameterStoreError(
            f"Invalid learned parameters JSON for test '{test_id}': {error}"
        ) from error
    except OSError as error:
        raise ParameterStoreError(
            f"Unable to read parameters for test '{test_id}': {error}"
        ) from error
    if not isinstance(loaded, dict):
        raise ParameterStoreError(
            f"Learned parameters JSON must be a mapping at top level for "
            f"test '{test_id}'"
        )
    return loaded


@dataclass(frozen=True)
class ParameterManager:
    """Per-test parameter storage helper exposed on execution context."""

    parameters_dir: Path
    test_id: str

    async def save(self, payload: Mapping[str, object]) -> None:
        """Persist learned parameters for the current test case."""
        self.parameters_dir.mkdir(parents=True, exist_ok=True)
        try:
            parameter_file_path(self.parameters_dir, self.test_id).write_text(
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
        path = parameter_file_path(self.parameters_dir, self.test_id)
        if not path.exists():
            raise ParameterStoreError(
                f"No learned parameters found for test '{self.test_id}' at {path}"
            )
        return _read_parameter_file(path, self.test_id)


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

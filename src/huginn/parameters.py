"""Persistence helpers for learned test parameters."""

import json
from dataclasses import dataclass
from pathlib import Path


class ParameterStoreError(RuntimeError):
    """Raised when learned parameters cannot be loaded or persisted."""


@dataclass(frozen=True)
class ParameterManager:
    """Per-test parameter storage helper exposed on execution context."""

    parameters_dir: Path
    test_id: str

    async def save(self, payload: dict[str, object]) -> None:
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

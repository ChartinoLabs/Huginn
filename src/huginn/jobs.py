"""Job loading utilities for test case execution."""

from importlib.util import module_from_spec, spec_from_file_location
from inspect import isabstract
from pathlib import Path
from types import ModuleType

from huginn.testcase import TestCase


class JobLoadError(RuntimeError):
    """Raised when a job module or test class cannot be resolved."""


def load_test_case_class(job: str, project_root: Path) -> type[TestCase]:
    """Load a test case class from job path syntax.

    Supported formats:
    - ``path/to/file.py`` (first TestCase subclass in module)
    - ``path/to/file.py:ClassName`` (specific class)
    """
    module_path, explicit_class_name = _split_job(job)
    resolved_module_path = (project_root / module_path).resolve()

    if not resolved_module_path.exists():
        raise JobLoadError(f"Job module not found: {resolved_module_path}")

    module = _load_module_from_path(resolved_module_path)
    if explicit_class_name is not None:
        return _load_explicit_class(module, explicit_class_name, job)
    return _load_first_test_case_class(module, job)


def _split_job(job: str) -> tuple[str, str | None]:
    if ":" not in job:
        return job, None
    module_path, class_name = job.rsplit(":", maxsplit=1)
    if not module_path or not class_name:
        raise JobLoadError(
            "Job format must be 'path/to/file.py' or 'path/to/file.py:ClassName'"
        )
    return module_path, class_name


def _load_module_from_path(path: Path) -> ModuleType:
    module_name = f"huginn_user_job_{path.stem}"
    spec = spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise JobLoadError(f"Unable to load job module from path: {path}")

    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_explicit_class(
    module: ModuleType,
    class_name: str,
    raw_job: str,
) -> type[TestCase]:
    class_obj = getattr(module, class_name, None)
    if class_obj is None:
        raise JobLoadError(f"Job class '{class_name}' not found in '{raw_job}'")
    if not isinstance(class_obj, type) or not issubclass(class_obj, TestCase):
        raise JobLoadError(
            f"Job class '{class_name}' in '{raw_job}' must inherit from TestCase"
        )
    if isabstract(class_obj):
        raise JobLoadError(f"Job class '{class_name}' in '{raw_job}' must be concrete")
    return class_obj


def _load_first_test_case_class(module: ModuleType, raw_job: str) -> type[TestCase]:
    candidates: list[type[TestCase]] = []
    for value in vars(module).values():
        if (
            isinstance(value, type)
            and issubclass(value, TestCase)
            and value is not TestCase
            and value.__module__ == module.__name__
            and not isabstract(value)
        ):
            candidates.append(value)

    if not candidates:
        raise JobLoadError(f"No TestCase subclass found in '{raw_job}'")
    return candidates[0]

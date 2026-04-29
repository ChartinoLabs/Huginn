"""Job loading utilities for test case execution."""

from importlib import import_module
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
    - ``package.module.path`` (first TestCase subclass in imported module)
    - ``package.module.path:ClassName`` (specific class from imported module)

    File paths are resolved relative to ``project_root``. Module paths are
    resolved via Python's import system, so the package must be installed
    in the active environment.
    """
    reference, explicit_class_name = _split_job(job)

    if _is_module_path(reference):
        module = _load_module_from_import(reference, job)
    else:
        resolved_module_path = (project_root / reference).resolve()
        if not resolved_module_path.exists():
            raise JobLoadError(f"Job module not found: {resolved_module_path}")
        module = _load_module_from_path(resolved_module_path)

    if explicit_class_name is not None:
        return _load_explicit_class(module, explicit_class_name, job)
    return _load_first_test_case_class(module, job)


def _is_module_path(reference: str) -> bool:
    """Return True for dot-delimited package module paths.

    A module path contains no path separators and no ``.py`` suffix.
    Any other form is treated as a filesystem path relative to the
    project root.
    """
    if "/" in reference or reference.endswith(".py"):
        return False
    return "." in reference or reference.isidentifier()


def _split_job(job: str) -> tuple[str, str | None]:
    if ":" not in job:
        return job, None
    reference, class_name = job.rsplit(":", maxsplit=1)
    if not reference or not class_name:
        raise JobLoadError(
            "Job format must be 'path/to/file.py[:ClassName]' or "
            "'package.module.path[:ClassName]'"
        )
    return reference, class_name


def _load_module_from_path(path: Path) -> ModuleType:
    module_name = f"huginn_user_job_{path.stem}"
    spec = spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise JobLoadError(f"Unable to load job module from path: {path}")

    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_module_from_import(dotted_path: str, raw_job: str) -> ModuleType:
    try:
        return import_module(dotted_path)
    except ImportError as exc:
        raise JobLoadError(
            f"Unable to import job module '{dotted_path}' from '{raw_job}': {exc}"
        ) from exc
    except ValueError as exc:
        raise JobLoadError(
            f"Invalid job module path '{dotted_path}' in '{raw_job}': {exc}"
        ) from exc


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

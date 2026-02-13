"""Unit tests for job loading helpers."""

from pathlib import Path

import pytest

from huginn.jobs import JobLoadError, _split_job, load_test_case_class


def test_split_job_without_explicit_class() -> None:
    """Split returns module path with no explicit class."""
    module_path, class_name = _split_job("jobs/verify.py")
    assert module_path == "jobs/verify.py"
    assert class_name is None


@pytest.mark.parametrize("job", [":MyCase", "jobs/verify.py:"])
def test_split_job_invalid_format_raises(job: str) -> None:
    """Invalid split syntax raises a clear job format error."""
    with pytest.raises(JobLoadError, match="Job format must be"):
        _split_job(job)


def test_load_test_case_class_implicit_subclass(tmp_path: Path) -> None:
    """Loader finds first TestCase subclass when class is omitted."""
    _write_job_module(
        tmp_path,
        "verify.py",
        """
from huginn import TestCase


class VerifySomething(TestCase):
    async def setup(self, context) -> None:
        return None

    async def test(self, context) -> None:
        return None

    async def cleanup(self, context) -> None:
        return None
""",
    )

    loaded = load_test_case_class(job="verify.py", project_root=tmp_path)
    assert loaded.__name__ == "VerifySomething"


def test_load_test_case_class_explicit_subclass(tmp_path: Path) -> None:
    """Loader resolves an explicitly named TestCase subclass."""
    _write_job_module(
        tmp_path,
        "verify.py",
        """
from huginn import TestCase


class FirstCase(TestCase):
    async def setup(self, context) -> None:
        return None

    async def test(self, context) -> None:
        return None

    async def cleanup(self, context) -> None:
        return None


class SecondCase(TestCase):
    async def setup(self, context) -> None:
        return None

    async def test(self, context) -> None:
        return None

    async def cleanup(self, context) -> None:
        return None
""",
    )

    loaded = load_test_case_class(job="verify.py:SecondCase", project_root=tmp_path)
    assert loaded.__name__ == "SecondCase"


def test_load_test_case_class_missing_module_raises(tmp_path: Path) -> None:
    """Missing job module path raises a not found error."""
    with pytest.raises(JobLoadError, match="Job module not found"):
        load_test_case_class(job="missing.py", project_root=tmp_path)


def test_load_test_case_class_missing_explicit_class_raises(tmp_path: Path) -> None:
    """Missing explicit class name raises a class-not-found error."""
    _write_job_module(
        tmp_path,
        "verify.py",
        """
from huginn import TestCase


class VerifySomething(TestCase):
    async def setup(self, context) -> None:
        return None

    async def test(self, context) -> None:
        return None

    async def cleanup(self, context) -> None:
        return None
""",
    )

    with pytest.raises(JobLoadError, match="Job class 'Nope' not found"):
        load_test_case_class(job="verify.py:Nope", project_root=tmp_path)


def test_load_test_case_class_explicit_class_must_inherit(tmp_path: Path) -> None:
    """Explicit class must inherit from TestCase."""
    _write_job_module(
        tmp_path,
        "verify.py",
        """
class NotATestCase:
    pass
""",
    )

    with pytest.raises(JobLoadError, match="must inherit from TestCase"):
        load_test_case_class(job="verify.py:NotATestCase", project_root=tmp_path)


def test_load_test_case_class_no_subclasses_raises(tmp_path: Path) -> None:
    """Module with no TestCase subclasses raises a clear error."""
    _write_job_module(
        tmp_path,
        "verify.py",
        """
VALUE = 1
""",
    )

    with pytest.raises(JobLoadError, match="No TestCase subclass found"):
        load_test_case_class(job="verify.py", project_root=tmp_path)


def _write_job_module(tmp_path: Path, filename: str, body: str) -> None:
    """Write a temporary Python module for loader tests."""
    (tmp_path / filename).write_text(body.strip() + "\n", encoding="utf-8")

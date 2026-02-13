"""Unit tests for job loading helpers."""

from pathlib import Path

import pytest

from huginn.jobs import JobLoadError, _split_job, load_test_case_class

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "jobs"


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


def test_load_test_case_class_implicit_subclass() -> None:
    """Loader finds first TestCase subclass when class is omitted."""
    loaded = load_test_case_class(job="test_verify_single.py", project_root=FIXTURES)
    assert loaded.__name__ == "VerifySomething"


def test_load_test_case_class_explicit_subclass() -> None:
    """Loader resolves an explicitly named TestCase subclass."""
    loaded = load_test_case_class(
        job="test_verify_multiple.py:SecondCase",
        project_root=FIXTURES,
    )
    assert loaded.__name__ == "SecondCase"


def test_load_test_case_class_missing_module_raises(tmp_path: Path) -> None:
    """Missing job module path raises a not found error."""
    with pytest.raises(JobLoadError, match="Job module not found"):
        load_test_case_class(job="missing.py", project_root=tmp_path)


def test_load_test_case_class_missing_explicit_class_raises() -> None:
    """Missing explicit class name raises a class-not-found error."""
    with pytest.raises(JobLoadError, match="Job class 'Nope' not found"):
        load_test_case_class(job="test_verify_single.py:Nope", project_root=FIXTURES)


def test_load_test_case_class_explicit_class_must_inherit() -> None:
    """Explicit class must inherit from TestCase."""
    with pytest.raises(JobLoadError, match="must inherit from TestCase"):
        load_test_case_class(
            job="test_non_testcase.py:NotATestCase",
            project_root=FIXTURES,
        )


def test_load_test_case_class_no_subclasses_raises() -> None:
    """Module with no TestCase subclasses raises a clear error."""
    with pytest.raises(JobLoadError, match="No TestCase subclass found"):
        load_test_case_class(job="test_no_subclasses.py", project_root=FIXTURES)

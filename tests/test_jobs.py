"""Unit tests for job loading helpers."""

import sys
from pathlib import Path

import pytest

from huginn.jobs import (
    JobLoadError,
    _is_module_path,
    _split_job,
    load_test_case_class,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "jobs"
PACKAGE_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "packages"


@pytest.fixture
def importable_fake_package(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the fixture package importable for module-path loader tests."""
    monkeypatch.syspath_prepend(str(PACKAGE_FIXTURES))
    for mod in list(sys.modules):
        if mod == "fake_job_package" or mod.startswith("fake_job_package."):
            monkeypatch.delitem(sys.modules, mod, raising=False)


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


@pytest.mark.parametrize(
    "reference, expected",
    [
        ("jobs/verify.py", False),
        ("jobs/subdir/verify.py", False),
        ("verify.py", False),
        ("huginn_jobs_network.bgp.verify_peering", True),
        ("fake_job_package.verify_thing", True),
        ("single_module", True),
    ],
)
def test_is_module_path(reference: str, expected: bool) -> None:
    """Detection distinguishes filesystem paths from dotted module paths."""
    assert _is_module_path(reference) is expected


def test_load_test_case_class_from_module_path(
    importable_fake_package: None,
) -> None:
    """Loader imports module paths and returns the first TestCase subclass."""
    loaded = load_test_case_class(
        job="fake_job_package.verify_thing",
        project_root=Path("/nonexistent"),
    )
    assert loaded.__name__ == "VerifyThing"


def test_load_test_case_class_from_nested_module_path_with_class(
    importable_fake_package: None,
) -> None:
    """Loader resolves explicit class names from nested package modules."""
    loaded = load_test_case_class(
        job="fake_job_package.subpkg.verify_nested:SecondNestedCase",
        project_root=Path("/nonexistent"),
    )
    assert loaded.__name__ == "SecondNestedCase"


def test_load_test_case_class_module_path_import_error_raises() -> None:
    """Unimportable module paths raise a clear job load error."""
    with pytest.raises(JobLoadError, match="Unable to import job module"):
        load_test_case_class(
            job="definitely_not_a_real_package.verify",
            project_root=Path("/nonexistent"),
        )


def test_load_test_case_class_module_path_missing_class_raises(
    importable_fake_package: None,
) -> None:
    """Missing explicit class name in a module path raises a class-not-found error."""
    with pytest.raises(JobLoadError, match="Job class 'Nope' not found"):
        load_test_case_class(
            job="fake_job_package.verify_thing:Nope",
            project_root=Path("/nonexistent"),
        )

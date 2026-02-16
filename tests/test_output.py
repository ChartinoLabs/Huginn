"""Unit tests for output and logging coordination."""

from pathlib import Path

from huginn.output import Output


def test_output_writes_logs_to_file(tmp_path: Path) -> None:
    """Output logger writes diagnostic entries to configured log file."""
    log_path = tmp_path / "huginn.log"
    output = Output(log_file=log_path, log_level="INFO", show_logs=False)

    output.log_info("hello %s", "world")

    contents = log_path.read_text(encoding="utf-8")
    assert "INFO" in contents
    assert "hello world" in contents


def test_output_status_methods_emit_without_error(tmp_path: Path) -> None:
    """Console output helpers run without raising exceptions."""
    output = Output(log_file=tmp_path / "huginn.log")

    output.status("status")
    output.success("success")
    output.warning("warning")
    output.error("error")


def test_output_error_preserves_bracketed_error_codes(tmp_path: Path) -> None:
    """Bracketed error codes are printed as plain text."""
    output = Output(log_file=tmp_path / "huginn.log")

    with output.error_console.capture() as capture:
        output.error("ERROR [configuration_error]: bad input")

    assert "[configuration_error]" in capture.get()


def test_output_logs_structured_fields_in_stable_format(tmp_path: Path) -> None:
    """Structured field helpers append deterministic key/value tokens."""
    log_path = tmp_path / "huginn.log"
    output = Output(log_file=log_path, log_level="DEBUG", show_logs=False)

    output.log_info_fields(
        "Run starting",
        mode="testing",
        plan=Path("test_plan.yaml"),
        empty="",
        enabled=True,
        retries=2,
        notes="hello world",
        optional=None,
    )

    contents = log_path.read_text(encoding="utf-8")
    assert "Run starting" in contents
    assert 'empty=""' in contents
    assert "enabled=true" in contents
    assert "mode=testing" in contents
    assert 'notes="hello world"' in contents
    assert "optional=none" in contents
    assert "plan=test_plan.yaml" in contents
    assert "retries=2" in contents

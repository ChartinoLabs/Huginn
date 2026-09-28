"""Tests for the CLI version command."""

from typer.testing import CliRunner

from huginn import __version__
from huginn.cli import app


def test_version_prints_installed_version() -> None:
    """Version command exits cleanly and prints the package version."""
    result = CliRunner().invoke(app, ["version"], catch_exceptions=False)

    assert result.exit_code == 0
    assert result.output.strip() == f"huginn v{__version__}"

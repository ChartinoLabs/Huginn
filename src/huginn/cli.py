"""CLI interface for Huginn test automation framework.

This module provides the command-line interface for executing test plans
against infrastructure testbeds.
"""

import asyncio
from importlib.metadata import version as get_version
from pathlib import Path
from typing import Annotated

import typer

from huginn.enums import ExecutionMode
from huginn.preflight import validate_inputs
from huginn.runner import RunExecutionError, run_test_plan

app = typer.Typer(
    name="huginn",
    help="Async-first test automation framework for network infrastructure.",
    no_args_is_help=True,
)


@app.command()
def run(
    plan: Annotated[
        Path,
        typer.Option(
            "--plan",
            "-p",
            help="Path to test plan YAML file defining test organization.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
        ),
    ],
    mode: Annotated[
        ExecutionMode,
        typer.Option(
            "--mode",
            "-m",
            help="Execution mode: 'learning' captures current state as baseline, "
            "'testing' compares against learned parameters.",
        ),
    ],
    testbed: Annotated[
        Path | None,
        typer.Option(
            "--testbed",
            "-t",
            help="Path to testbed YAML file defining device inventory.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
        ),
    ] = None,
    tags: Annotated[
        list[str] | None,
        typer.Option(
            "--tags",
            help="Filter test cases by tags. Only matching test cases will run.",
        ),
    ] = None,
    data_model: Annotated[
        Path | None,
        typer.Option(
            "--data-model",
            "-d",
            help="Path to data model directory containing YAML files representing "
            "intended infrastructure state.",
            exists=True,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ] = None,
    inventory_plugin: Annotated[
        str | None,
        typer.Option(
            "--inventory-plugin",
            "-i",
            help="Use an inventory plugin instead of a static testbed YAML file.",
        ),
    ] = None,
) -> None:
    """Execute a test plan against infrastructure.

    Run test cases defined in a test plan against devices specified in a testbed.
    In learning mode, current device state is captured as baseline parameters.
    In testing mode, current state is compared against learned parameters.

    Examples:
        huginn run -m testing -t testbed.yaml -p test_plan.yaml
        huginn run -m learning -t testbed.yaml -p test_plan.yaml --tags ospf
        huginn run -m testing -p test_plan.yaml -i huginn-netbox
    """
    testbed_path = _resolve_testbed_option(
        testbed=testbed,
        inventory_plugin=inventory_plugin,
        tags=tags,
        data_model=data_model,
    )

    try:
        report = asyncio.run(
            run_test_plan(
                mode=mode,
                testbed_path=testbed_path,
                plan_path=plan,
                project_root=Path.cwd(),
                reports_dir=Path.cwd() / "reports",
            )
        )
    except RunExecutionError as error:
        typer.secho(f"Configuration error: {error}", fg=typer.colors.RED)
        raise typer.Exit(code=2) from error

    typer.echo(f"Run status: {report.summary.status}")
    typer.echo("Report written to reports/run.json")
    if report.summary.status != "passed":
        raise typer.Exit(code=1)


@app.command()
def validate(
    plan: Annotated[
        Path,
        typer.Option(
            "--plan",
            "-p",
            help="Path to test plan YAML file to validate.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
        ),
    ],
    testbed: Annotated[
        Path | None,
        typer.Option(
            "--testbed",
            "-t",
            help="Path to testbed YAML file defining device inventory.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
        ),
    ] = None,
    tags: Annotated[
        list[str] | None,
        typer.Option(
            "--tags",
            help="Reserved for future filtering support.",
        ),
    ] = None,
    data_model: Annotated[
        Path | None,
        typer.Option(
            "--data-model",
            "-d",
            help="Reserved for future data model support.",
            exists=True,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ] = None,
    inventory_plugin: Annotated[
        str | None,
        typer.Option(
            "--inventory-plugin",
            "-i",
            help="Reserved for future inventory plugin support.",
        ),
    ] = None,
) -> None:
    """Validate testbed/plan inputs without executing tests."""
    testbed_path = _resolve_testbed_option(
        testbed=testbed,
        inventory_plugin=inventory_plugin,
        tags=tags,
        data_model=data_model,
    )

    report = validate_inputs(
        testbed_path=testbed_path,
        plan_path=plan,
        project_root=Path.cwd(),
        reports_dir=Path.cwd() / "reports",
    )
    typer.echo(f"Validation status: {'passed' if report.valid else 'failed'}")
    typer.echo("Report written to reports/validate.json")

    if not report.valid:
        for error in report.errors:
            typer.secho(f"ERROR: {error}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    for warning in report.warnings:
        typer.secho(f"WARNING: {warning}", fg=typer.colors.YELLOW)


def _resolve_testbed_option(
    *,
    testbed: Path | None,
    inventory_plugin: str | None,
    tags: list[str] | None,
    data_model: Path | None,
) -> Path:
    """Validate first-slice options and return required testbed path."""
    if testbed is None:
        if inventory_plugin is None:
            raise typer.BadParameter(
                "Either --testbed or --inventory-plugin must be specified."
            )
        raise typer.BadParameter(
            "--inventory-plugin is not supported in this implementation slice. "
            "Use --testbed."
        )

    if inventory_plugin is not None:
        raise typer.BadParameter(
            "--testbed and --inventory-plugin are mutually exclusive."
        )
    if tags is not None:
        raise typer.BadParameter("--tags filtering is not implemented yet.")
    if data_model is not None:
        raise typer.BadParameter("--data-model is not implemented yet.")
    return testbed


@app.command()
def version() -> None:
    """Display the Huginn version."""
    typer.echo(f"huginn v{get_version('huginn')}")


def main() -> None:
    """Entry point for the Huginn CLI."""
    app()

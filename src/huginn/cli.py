"""CLI interface for Huginn test automation framework.

This module provides the command-line interface for executing test plans
against infrastructure testbeds.
"""

import asyncio
from importlib.metadata import version as get_version
from pathlib import Path
from typing import Annotated

import typer

from huginn.enums import ErrorCode, ExecutionMode
from huginn.plan_filtering import PlanFilterOptions
from huginn.runner import RunExecutionError, run_test_plan
from huginn.validation import validate_inputs

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
    exclude_tags: Annotated[
        list[str] | None,
        typer.Option(
            "--exclude-tags",
            help="Exclude test cases with matching tags.",
        ),
    ] = None,
    phase: Annotated[
        list[str] | None,
        typer.Option(
            "--phase",
            help="Run only specified phases.",
        ),
    ] = None,
    test_case_group: Annotated[
        list[str] | None,
        typer.Option(
            "--test-case-group",
            help="Run only specified test case groups.",
        ),
    ] = None,
    test_id: Annotated[
        list[str] | None,
        typer.Option(
            "--test-id",
            help="Run only specified test case IDs.",
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
        data_model=data_model,
    )

    try:
        filters = _build_plan_filters(
            tags=tags,
            exclude_tags=exclude_tags,
            phases=phase,
            test_case_groups=test_case_group,
            test_ids=test_id,
        )
        report = asyncio.run(
            run_test_plan(
                mode=mode,
                testbed_path=testbed_path,
                inventory_plugin=inventory_plugin,
                plan_path=plan,
                filters=filters,
                project_root=Path.cwd(),
                parameters_dir=Path.cwd() / "parameters",
                reports_dir=Path.cwd() / "reports",
            )
        )
    except RunExecutionError as error:
        typer.secho(
            f"ERROR [{error.code.value}]: {error}",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=_exit_code_for_run_error(error.code)) from error

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
            help="Filter validation set by tags.",
        ),
    ] = None,
    exclude_tags: Annotated[
        list[str] | None,
        typer.Option(
            "--exclude-tags",
            help="Exclude validation set by tags.",
        ),
    ] = None,
    phase: Annotated[
        list[str] | None,
        typer.Option(
            "--phase",
            help="Validate only specified phases.",
        ),
    ] = None,
    test_case_group: Annotated[
        list[str] | None,
        typer.Option(
            "--test-case-group",
            help="Validate only specified test case groups.",
        ),
    ] = None,
    test_id: Annotated[
        list[str] | None,
        typer.Option(
            "--test-id",
            help="Validate only specified test case IDs.",
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
            help="Use an inventory plugin instead of a static testbed YAML file.",
        ),
    ] = None,
) -> None:
    """Validate testbed/plan inputs without executing tests."""
    testbed_path = _resolve_testbed_option(
        testbed=testbed,
        inventory_plugin=inventory_plugin,
        data_model=data_model,
    )

    report = asyncio.run(
        validate_inputs(
            testbed_path=testbed_path,
            inventory_plugin=inventory_plugin,
            plan_path=plan,
            filters=_build_plan_filters(
                tags=tags,
                exclude_tags=exclude_tags,
                phases=phase,
                test_case_groups=test_case_group,
                test_ids=test_id,
            ),
            project_root=Path.cwd(),
            reports_dir=Path.cwd() / "reports",
        )
    )
    typer.echo(f"Validation status: {'passed' if report.valid else 'failed'}")
    typer.echo("Report written to reports/validate.json")

    if not report.valid:
        for error in report.errors:
            typer.secho(
                f"ERROR [{error.code}]: {error.message}",
                fg=typer.colors.RED,
            )
        raise typer.Exit(code=3)

    for warning in report.warnings:
        typer.secho(
            f"WARNING [{warning.code}]: {warning.message}",
            fg=typer.colors.YELLOW,
        )


def _exit_code_for_run_error(code: ErrorCode) -> int:
    """Map structured run errors to deterministic CLI exit codes."""
    if code in {
        ErrorCode.CONFIGURATION_ERROR,
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.PLANNING_ERROR,
    }:
        return 2
    return 1


def _resolve_testbed_option(
    *,
    testbed: Path | None,
    inventory_plugin: str | None,
    data_model: Path | None,
) -> Path | None:
    """Validate first-slice options and return required testbed path."""
    if testbed is not None and inventory_plugin is not None:
        raise typer.BadParameter(
            "--testbed and --inventory-plugin are mutually exclusive."
        )

    if testbed is None and inventory_plugin is None:
        raise typer.BadParameter(
            "Either --testbed or --inventory-plugin must be specified."
        )

    if data_model is not None:
        raise typer.BadParameter("--data-model is not implemented yet.")
    return testbed


def _build_plan_filters(
    *,
    tags: list[str] | None,
    exclude_tags: list[str] | None,
    phases: list[str] | None,
    test_case_groups: list[str] | None,
    test_ids: list[str] | None,
) -> PlanFilterOptions:
    """Normalize CLI filter values into a single plan-filter object."""
    return PlanFilterOptions(
        tags=_split_csv_option_values(tags),
        exclude_tags=_split_csv_option_values(exclude_tags),
        phases=_split_csv_option_values(phases),
        test_case_groups=_split_csv_option_values(test_case_groups),
        test_ids=_split_csv_option_values(test_ids),
    )


def _split_csv_option_values(values: list[str] | None) -> list[str] | None:
    """Split comma-separated CLI option values while preserving order."""
    if not values:
        return None

    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        for raw_item in value.split(","):
            item = raw_item.strip()
            if not item or item in seen:
                continue
            seen.add(item)
            normalized.append(item)
    return normalized or None


@app.command()
def version() -> None:
    """Display the Huginn version."""
    typer.echo(f"huginn v{get_version('huginn')}")


def main() -> None:
    """Entry point for the Huginn CLI."""
    app()

"""CLI interface for Huginn test automation framework.

This module provides the command-line interface for executing test plans
against infrastructure testbeds.
"""

import asyncio
import tomllib
from importlib.metadata import version as get_version
from pathlib import Path
from typing import Annotated

import typer

from huginn.enums import ErrorCode, ExecutionMode
from huginn.execute import (
    ExecuteCommandResult,
    ExecuteCommandSpec,
    execute_commands,
    load_command_specs,
)
from huginn.inject import InjectPlan
from huginn.loaders import ConfigurationError, load_test_plan
from huginn.output import Output
from huginn.plan_filtering import PlanFilterOptions
from huginn.plugin_registry import PluginConfig, PluginRegistry
from huginn.prune import (
    PruneError,
    PruneInput,
    PrunePlan,
    apply_prune_plan,
    compute_prune_plan,
    find_latest_learning_results,
    parse_applicability_from_run,
    validate_after_prune,
)
from huginn.reconcile import (
    ReconcileError,
    apply_reconcile_plan,
    compute_reconcile_plan,
    copy_parameter_files,
    find_latest_testing_results,
    parse_failures_from_run,
    validate_after_reconcile,
)
from huginn.relearn import RelearnError, RelearnInput, parse_failed_test_ids
from huginn.runner import RunExecutionError, run_test_plan
from huginn.validation import validate_inputs

app = typer.Typer(
    name="huginn",
    help="Async-first test automation framework for network infrastructure.",
    no_args_is_help=True,
)


@app.command()
def run(
    mode: Annotated[
        ExecutionMode,
        typer.Option(
            "--mode",
            "-m",
            help="Execution mode: 'learning' captures current state as baseline, "
            "'testing' compares against learned parameters.",
            envvar="HUGINN_MODE",
        ),
    ],
    plan: Annotated[
        Path | None,
        typer.Option(
            "--plan",
            "-p",
            help="Path to test plan YAML file or directory of YAML files "
            "(default: ./test_plan).",
            exists=True,
            file_okay=True,
            dir_okay=True,
            resolve_path=True,
            envvar="HUGINN_PLAN",
        ),
    ] = None,
    testbed: Annotated[
        Path | None,
        typer.Option(
            "--testbed",
            "-t",
            help="Path to testbed YAML file defining device inventory "
            "(default: ./testbed.yaml).",
            exists=True,
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
            envvar="HUGINN_TESTBED",
        ),
    ] = None,
    tags: Annotated[
        list[str] | None,
        typer.Option(
            "--tags",
            help="Filter test cases by tags. Only matching test cases will run.",
            envvar="HUGINN_TAGS",
        ),
    ] = None,
    exclude_tags: Annotated[
        list[str] | None,
        typer.Option(
            "--exclude-tags",
            help="Exclude test cases with matching tags.",
            envvar="HUGINN_EXCLUDE_TAGS",
        ),
    ] = None,
    scenario: Annotated[
        list[str] | None,
        typer.Option(
            "--scenario",
            help="Run only specified scenarios.",
            envvar="HUGINN_SCENARIO",
        ),
    ] = None,
    phase: Annotated[
        list[str] | None,
        typer.Option(
            "--phase",
            help="Run only specified phases.",
            envvar="HUGINN_PHASE",
        ),
    ] = None,
    test_case_group: Annotated[
        list[str] | None,
        typer.Option(
            "--test-case-group",
            help="Run only specified test case groups.",
            envvar="HUGINN_TEST_CASE_GROUP",
        ),
    ] = None,
    test_id: Annotated[
        list[str] | None,
        typer.Option(
            "--test-id",
            help="Run only specified test case IDs.",
            envvar="HUGINN_TEST_ID",
        ),
    ] = None,
    test_id_pattern: Annotated[
        str | None,
        typer.Option(
            "--test-id-pattern",
            help="Regex pattern to filter test case IDs (e.g. '-post-shutdown$').",
            envvar="HUGINN_TEST_ID_PATTERN",
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
            envvar="HUGINN_DATA_MODEL",
        ),
    ] = None,
    inventory_plugin: Annotated[
        str | None,
        typer.Option(
            "--inventory-plugin",
            "-i",
            help="Use an inventory plugin instead of a static testbed YAML file.",
            envvar="HUGINN_INVENTORY_PLUGIN",
        ),
    ] = None,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            help="Enable DEBUG-level logging.",
            envvar="HUGINN_DEBUG",
        ),
    ] = False,
    log_level: Annotated[
        str,
        typer.Option(
            "--log-level",
            help="Logging level (DEBUG, INFO, WARNING, ERROR).",
            envvar="HUGINN_LOG_LEVEL",
        ),
    ] = "INFO",
    show_logs: Annotated[
        bool,
        typer.Option(
            "--show-logs",
            help="Stream logs to console in addition to file.",
            envvar="HUGINN_SHOW_LOGS",
        ),
    ] = False,
    log_file: Annotated[
        Path | None,
        typer.Option(
            "--log-file",
            help="Path to log file (default: ./huginn.log).",
            envvar="HUGINN_LOG_FILE",
        ),
    ] = None,
    results_dir: Annotated[
        Path | None,
        typer.Option(
            "--results-dir",
            help="Path to results directory (default: ./results/).",
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
            envvar="HUGINN_RESULTS_DIR",
        ),
    ] = None,
    parameters_dir: Annotated[
        Path | None,
        typer.Option(
            "--parameters-dir",
            help="Path to parameters directory (default: ./parameters/).",
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
            envvar="HUGINN_PARAMETERS_DIR",
        ),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            help="Path to output directory for run artifacts "
            "(default: <run-dir>/artifacts/).",
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
            envvar="HUGINN_OUTPUT_DIR",
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
    plan = _resolve_plan_option(plan)
    resolved_results_dir = results_dir or Path.cwd() / "results"
    resolved_parameters_dir = parameters_dir or Path.cwd() / "parameters"

    testbed_path = _resolve_testbed_option(
        testbed=testbed,
        inventory_plugin=inventory_plugin,
        data_model=data_model,
    )

    output = _build_output(
        debug=debug,
        log_level=log_level,
        show_logs=show_logs,
        log_file=log_file,
    )
    output.status(f"Starting run in {mode.value} mode")
    output.log_debug_fields(
        "CLI run options",
        plan=plan,
        testbed=testbed_path,
        inventory_plugin=inventory_plugin,
        tags=tags,
        exclude_tags=exclude_tags,
        scenario=scenario,
        phase=phase,
        test_case_group=test_case_group,
        test_id=test_id,
        log_level="DEBUG" if debug else log_level,
        show_logs=show_logs,
        log_file=log_file,
        results_dir=resolved_results_dir,
        output_dir=output_dir,
    )

    try:
        filters = _build_plan_filters(
            tags=tags,
            exclude_tags=exclude_tags,
            scenarios=scenario,
            phases=phase,
            test_case_groups=test_case_group,
            test_ids=test_id,
            test_id_pattern=test_id_pattern,
        )
        plugin_registry = _load_plugin_registry(project_root=Path.cwd())
        result = asyncio.run(
            run_test_plan(
                mode=mode,
                testbed_path=testbed_path,
                inventory_plugin=inventory_plugin,
                plan_path=plan,
                filters=filters,
                project_root=Path.cwd(),
                parameters_dir=resolved_parameters_dir,
                results_dir=resolved_results_dir,
                output_dir=output_dir,
                output=output,
                registry=plugin_registry,
            )
        )
    except ConfigurationError as error:
        output.error(f"ERROR: {error}")
        raise typer.Exit(code=1) from error
    except RunExecutionError as error:
        output.error(f"ERROR [{error.code.value}]: {error}")
        if error.traceback_text:
            output.error(error.traceback_text)
        raise typer.Exit(code=_exit_code_for_run_error(error.code)) from error

    output.status(f"Run status: {result.summary.status}")
    output.status(
        "Summary: "
        f"total={result.summary.total} "
        f"passed={result.summary.passed} "
        f"failed={result.summary.failed} "
        f"errored={result.summary.errored} "
        f"not_applicable={result.summary.not_applicable} "
        f"skipped={result.summary.skipped} "
        f"blocked={result.summary.blocked}"
    )
    if result.summary.total == 0:
        output.warning("No test cases were selected for execution")
    output.status("Run artifacts written to results/")
    output.status("Run report written to reports/latest/")
    if result.summary.status != "passed":
        raise typer.Exit(code=1)


@app.command()
def validate(
    plan: Annotated[
        Path,
        typer.Option(
            "--plan",
            "-p",
            help="Path to test plan YAML file or directory of YAML files to validate.",
            exists=True,
            file_okay=True,
            dir_okay=True,
            resolve_path=True,
            envvar="HUGINN_PLAN",
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
            envvar="HUGINN_TESTBED",
        ),
    ] = None,
    tags: Annotated[
        list[str] | None,
        typer.Option(
            "--tags",
            help="Filter validation set by tags.",
            envvar="HUGINN_TAGS",
        ),
    ] = None,
    exclude_tags: Annotated[
        list[str] | None,
        typer.Option(
            "--exclude-tags",
            help="Exclude validation set by tags.",
            envvar="HUGINN_EXCLUDE_TAGS",
        ),
    ] = None,
    scenario: Annotated[
        list[str] | None,
        typer.Option(
            "--scenario",
            help="Validate only specified scenarios.",
            envvar="HUGINN_SCENARIO",
        ),
    ] = None,
    phase: Annotated[
        list[str] | None,
        typer.Option(
            "--phase",
            help="Validate only specified phases.",
            envvar="HUGINN_PHASE",
        ),
    ] = None,
    test_case_group: Annotated[
        list[str] | None,
        typer.Option(
            "--test-case-group",
            help="Validate only specified test case groups.",
            envvar="HUGINN_TEST_CASE_GROUP",
        ),
    ] = None,
    test_id: Annotated[
        list[str] | None,
        typer.Option(
            "--test-id",
            help="Validate only specified test case IDs.",
            envvar="HUGINN_TEST_ID",
        ),
    ] = None,
    test_id_pattern: Annotated[
        str | None,
        typer.Option(
            "--test-id-pattern",
            help="Regex pattern to filter test case IDs (e.g. '-post-shutdown$').",
            envvar="HUGINN_TEST_ID_PATTERN",
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
            envvar="HUGINN_DATA_MODEL",
        ),
    ] = None,
    inventory_plugin: Annotated[
        str | None,
        typer.Option(
            "--inventory-plugin",
            "-i",
            help="Use an inventory plugin instead of a static testbed YAML file.",
            envvar="HUGINN_INVENTORY_PLUGIN",
        ),
    ] = None,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            help="Enable DEBUG-level logging.",
            envvar="HUGINN_DEBUG",
        ),
    ] = False,
    log_level: Annotated[
        str,
        typer.Option(
            "--log-level",
            help="Logging level (DEBUG, INFO, WARNING, ERROR).",
            envvar="HUGINN_LOG_LEVEL",
        ),
    ] = "INFO",
    show_logs: Annotated[
        bool,
        typer.Option(
            "--show-logs",
            help="Stream logs to console in addition to file.",
            envvar="HUGINN_SHOW_LOGS",
        ),
    ] = False,
    log_file: Annotated[
        Path | None,
        typer.Option(
            "--log-file",
            help="Path to log file (default: ./huginn.log).",
            envvar="HUGINN_LOG_FILE",
        ),
    ] = None,
) -> None:
    """Validate testbed/plan inputs without executing tests."""
    testbed_path = _resolve_testbed_option(
        testbed=testbed,
        inventory_plugin=inventory_plugin,
        data_model=data_model,
    )

    output = _build_output(
        debug=debug,
        log_level=log_level,
        show_logs=show_logs,
        log_file=log_file,
    )
    output.status("Starting validation")
    output.log_debug_fields(
        "CLI validate options",
        plan=plan,
        testbed=testbed_path,
        inventory_plugin=inventory_plugin,
        tags=tags,
        exclude_tags=exclude_tags,
        scenario=scenario,
        phase=phase,
        test_case_group=test_case_group,
        test_id=test_id,
        log_level="DEBUG" if debug else log_level,
        show_logs=show_logs,
        log_file=log_file,
    )
    try:
        result = asyncio.run(
            validate_inputs(
                testbed_path=testbed_path,
                inventory_plugin=inventory_plugin,
                plan_path=plan,
                filters=_build_plan_filters(
                    tags=tags,
                    exclude_tags=exclude_tags,
                    scenarios=scenario,
                    phases=phase,
                    test_case_groups=test_case_group,
                    test_ids=test_id,
                    test_id_pattern=test_id_pattern,
                ),
                project_root=Path.cwd(),
                results_dir=Path.cwd() / "results",
                output=output,
            )
        )
    except ConfigurationError as error:
        output.error(f"ERROR: {error}")
        raise typer.Exit(code=1) from error
    output.status(f"Validation status: {'passed' if result.valid else 'failed'}")
    output.status(
        "Summary: "
        f"test_cases={len(result.test_cases)} "
        f"warnings={len(result.warnings)} "
        f"errors={len(result.errors)}"
    )
    output.status("Validation artifacts written to results/")

    if not result.valid:
        for error in result.errors:
            output.error(f"ERROR [{error.code}]: {error.message}")
        raise typer.Exit(code=3)

    for warning in result.warnings:
        output.warning(f"WARNING [{warning.code}]: {warning.message}")


def _exit_code_for_run_error(code: ErrorCode) -> int:
    """Map structured run errors to deterministic CLI exit codes."""
    if code in {
        ErrorCode.CONFIGURATION_ERROR,
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.PLANNING_ERROR,
    }:
        return 2
    return 1


def _resolve_plan_option(plan: Path | None) -> Path:
    """Apply default plan path when the user omits --plan."""
    if plan is not None:
        return plan
    default = Path.cwd() / "test_plan"
    if default.exists():
        return default.resolve()
    raise typer.BadParameter("No --plan specified and default ./test_plan not found.")


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
        default = Path.cwd() / "testbed.yaml"
        if default.exists():
            testbed = default.resolve()
        else:
            raise typer.BadParameter(
                "Either --testbed or --inventory-plugin must be specified "
                "(no default ./testbed.yaml found)."
            )

    if data_model is not None:
        raise typer.BadParameter("--data-model is not implemented yet.")
    return testbed


def _build_plan_filters(
    *,
    tags: list[str] | None,
    exclude_tags: list[str] | None,
    scenarios: list[str] | None,
    phases: list[str] | None,
    test_case_groups: list[str] | None,
    test_ids: list[str] | None,
    test_id_pattern: str | None = None,
) -> PlanFilterOptions:
    """Normalize CLI filter values into a single plan-filter object."""
    normalized_scenarios = _split_csv_option_values(scenarios)
    normalized_phases = _split_csv_option_values(phases)
    if normalized_phases and not normalized_scenarios:
        raise typer.BadParameter("--phase requires --scenario to be specified.")

    return PlanFilterOptions(
        tags=_split_csv_option_values(tags),
        exclude_tags=_split_csv_option_values(exclude_tags),
        scenarios=normalized_scenarios,
        phases=normalized_phases,
        test_case_groups=_split_csv_option_values(test_case_groups),
        test_ids=_split_csv_option_values(test_ids),
        test_id_pattern=test_id_pattern,
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


def _build_output(
    *,
    debug: bool,
    log_level: str,
    show_logs: bool,
    log_file: Path | None,
) -> Output:
    """Build output coordinator for console and logging streams."""
    resolved_log_level = "DEBUG" if debug else log_level
    return Output(
        show_logs=show_logs,
        log_level=resolved_log_level,
        log_file=log_file,
    )


@app.command()
def reconcile(
    plan: Annotated[
        Path,
        typer.Option(
            "--plan",
            "-p",
            help="Path to test plan YAML file or directory of YAML files.",
            exists=True,
            file_okay=True,
            dir_okay=True,
            resolve_path=True,
            envvar="HUGINN_PLAN",
        ),
    ],
    phase: Annotated[
        str,
        typer.Option(
            "--phase",
            help="Phase whose failures to reconcile. Also used as suffix for "
            "new test case IDs and group names.",
            envvar="HUGINN_PHASE",
        ),
    ],
    scenario: Annotated[
        str | None,
        typer.Option(
            "--scenario",
            help="Reconcile only the specified scenario. "
            "If omitted, all scenarios with the target phase are processed.",
            envvar="HUGINN_SCENARIO",
        ),
    ] = None,
    results_dir: Annotated[
        Path | None,
        typer.Option(
            "--results-dir",
            help="Path to results directory (default: ./results/).",
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
            envvar="HUGINN_RESULTS_DIR",
        ),
    ] = None,
    parameters_dir: Annotated[
        Path | None,
        typer.Option(
            "--parameters-dir",
            help="Path to parameters directory (default: ./parameters/).",
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
            envvar="HUGINN_PARAMETERS_DIR",
        ),
    ] = None,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            help="Enable DEBUG-level logging.",
            envvar="HUGINN_DEBUG",
        ),
    ] = False,
    log_level: Annotated[
        str,
        typer.Option(
            "--log-level",
            help="Logging level (DEBUG, INFO, WARNING, ERROR).",
            envvar="HUGINN_LOG_LEVEL",
        ),
    ] = "INFO",
    show_logs: Annotated[
        bool,
        typer.Option(
            "--show-logs",
            help="Stream logs to console in addition to file.",
            envvar="HUGINN_SHOW_LOGS",
        ),
    ] = False,
    log_file: Annotated[
        Path | None,
        typer.Option(
            "--log-file",
            help="Path to log file (default: ./huginn.log).",
            envvar="HUGINN_LOG_FILE",
        ),
    ] = None,
) -> None:
    """Reconcile failing test cases into new test case groups.

    After running a post-change phase in testing mode, some tests may fail
    because the golden parameters reflect pre-change state. This command
    creates new test case definitions and groups for the failing tests so
    they can be re-learned with post-change parameters.

    Examples:
        huginn reconcile -p test_plan.yaml --phase post-change
        huginn reconcile -p plans/ --phase post-change --scenario migration
    """
    resolved_results_dir = results_dir or Path.cwd() / "results"
    resolved_parameters_dir = parameters_dir or Path.cwd() / "parameters"

    output = _build_output(
        debug=debug,
        log_level=log_level,
        show_logs=show_logs,
        log_file=log_file,
    )
    output.status(f"Reconciling failures for phase '{phase}'")
    output.log_debug_fields(
        "CLI reconcile options",
        plan=plan,
        phase=phase,
        scenario=scenario,
        results_dir=resolved_results_dir,
        parameters_dir=resolved_parameters_dir,
        log_level="DEBUG" if debug else log_level,
    )

    try:
        run_json_path = find_latest_testing_results(resolved_results_dir)
        output.status(f"Using results from {run_json_path.parent.name}")

        reconcile_input = parse_failures_from_run(
            run_json_path, phase, scenario_filter=scenario
        )

        if not reconcile_input.failing_tests:
            output.success(
                f"No failures found in phase '{phase}' -- nothing to reconcile"
            )
            return

        output.status(
            f"Found {len(reconcile_input.failing_tests)} failing test case(s) "
            f"across {len(reconcile_input.affected_group_ids)} group(s)"
        )

        test_plan = load_test_plan(plan)
        plan_result = compute_reconcile_plan(reconcile_input, test_plan, phase)

        if not plan_result.new_test_cases and not plan_result.new_groups:
            output.success("Reconciliation already applied -- no changes needed")
            if plan_result.skipped_existing:
                output.warning(
                    f"Skipped {len(plan_result.skipped_existing)} existing "
                    "ID(s) (already reconciled)"
                )
            return

        apply_reconcile_plan(
            plan_path=plan,
            reconcile_plan=plan_result,
            phase_name=phase,
            output=output,
        )

        copied = copy_parameter_files(
            parameters_dir=resolved_parameters_dir,
            copies=plan_result.parameter_copies,
            output=output,
        )

        validate_after_reconcile(plan)

        output.success(
            f"Reconciliation complete: "
            f"{len(plan_result.new_test_cases)} new test case(s), "
            f"{len(plan_result.new_groups)} new group(s), "
            f"{copied} parameter file(s) copied"
        )
        if plan_result.skipped_existing:
            output.warning(
                f"Skipped {len(plan_result.skipped_existing)} existing "
                "ID(s) (already reconciled)"
            )

    except (ReconcileError, ConfigurationError) as error:
        output.error(f"ERROR: {error}")
        raise typer.Exit(code=1) from error


@app.command()
def relearn(
    plan: Annotated[
        Path | None,
        typer.Option(
            "--plan",
            "-p",
            help="Path to test plan YAML file or directory of YAML files "
            "(default: ./test_plan).",
            exists=True,
            file_okay=True,
            dir_okay=True,
            resolve_path=True,
            envvar="HUGINN_PLAN",
        ),
    ] = None,
    testbed: Annotated[
        Path | None,
        typer.Option(
            "--testbed",
            "-t",
            help="Path to testbed YAML file defining device inventory "
            "(default: ./testbed.yaml).",
            exists=True,
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
            envvar="HUGINN_TESTBED",
        ),
    ] = None,
    scenario: Annotated[
        str | None,
        typer.Option(
            "--scenario",
            help="Re-learn only failures from the specified scenario.",
            envvar="HUGINN_SCENARIO",
        ),
    ] = None,
    phase: Annotated[
        str | None,
        typer.Option(
            "--phase",
            help="Re-learn only failures from the specified phase.",
            envvar="HUGINN_PHASE",
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
            envvar="HUGINN_DATA_MODEL",
        ),
    ] = None,
    inventory_plugin: Annotated[
        str | None,
        typer.Option(
            "--inventory-plugin",
            "-i",
            help="Use an inventory plugin instead of a static testbed YAML file.",
            envvar="HUGINN_INVENTORY_PLUGIN",
        ),
    ] = None,
    results_dir: Annotated[
        Path | None,
        typer.Option(
            "--results-dir",
            help="Path to results directory (default: ./results/).",
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
            envvar="HUGINN_RESULTS_DIR",
        ),
    ] = None,
    parameters_dir: Annotated[
        Path | None,
        typer.Option(
            "--parameters-dir",
            help="Path to parameters directory (default: ./parameters/).",
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
            envvar="HUGINN_PARAMETERS_DIR",
        ),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            help="Path to output directory for run artifacts "
            "(default: <run-dir>/artifacts/).",
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
            envvar="HUGINN_OUTPUT_DIR",
        ),
    ] = None,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            help="Enable DEBUG-level logging.",
            envvar="HUGINN_DEBUG",
        ),
    ] = False,
    log_level: Annotated[
        str,
        typer.Option(
            "--log-level",
            help="Logging level (DEBUG, INFO, WARNING, ERROR).",
            envvar="HUGINN_LOG_LEVEL",
        ),
    ] = "INFO",
    show_logs: Annotated[
        bool,
        typer.Option(
            "--show-logs",
            help="Stream logs to console in addition to file.",
            envvar="HUGINN_SHOW_LOGS",
        ),
    ] = False,
    log_file: Annotated[
        Path | None,
        typer.Option(
            "--log-file",
            help="Path to log file (default: ./huginn.log).",
            envvar="HUGINN_LOG_FILE",
        ),
    ] = None,
) -> None:
    """Re-learn parameters for failed tests from the latest testing run.

    Analyzes the most recent testing run results, identifies failed and
    errored test cases, then re-runs only those tests in learning mode to
    refresh their baseline parameters. Automatically scopes execution to
    only the scenarios and phases that contained failures.

    Examples:
        huginn relearn -p test_plan -t testbed.yaml
        huginn relearn -p test_plan -t testbed.yaml --scenario link-shutdown-r1r2
        huginn relearn -p test_plan -t testbed.yaml --phase pre-change
    """
    resolved_plan = _resolve_plan_option(plan)
    resolved_results_dir = results_dir or Path.cwd() / "results"
    resolved_parameters_dir = parameters_dir or Path.cwd() / "parameters"

    testbed_path = _resolve_testbed_option(
        testbed=testbed,
        inventory_plugin=inventory_plugin,
        data_model=data_model,
    )

    output = _build_output(
        debug=debug,
        log_level=log_level,
        show_logs=show_logs,
        log_file=log_file,
    )
    output.status("Analyzing latest testing run for failures")
    output.log_debug_fields(
        "CLI relearn options",
        plan=resolved_plan,
        testbed=testbed_path,
        scenario=scenario,
        phase=phase,
        results_dir=resolved_results_dir,
        parameters_dir=resolved_parameters_dir,
    )

    try:
        relearn_input = _resolve_relearn_targets(
            resolved_results_dir, phase, scenario, output
        )
        if relearn_input is None:
            return

        _execute_relearn(
            relearn_input=relearn_input,
            plan_path=resolved_plan,
            testbed_path=testbed_path,
            inventory_plugin=inventory_plugin,
            parameters_dir=resolved_parameters_dir,
            results_dir=resolved_results_dir,
            output_dir=output_dir,
            output=output,
        )

    except (RelearnError, ReconcileError, ConfigurationError) as error:
        output.error(f"ERROR: {error}")
        raise typer.Exit(code=1) from error
    except RunExecutionError as error:
        output.error(f"ERROR [{error.code.value}]: {error}")
        if error.traceback_text:
            output.error(error.traceback_text)
        raise typer.Exit(code=_exit_code_for_run_error(error.code)) from error


def _resolve_relearn_targets(
    results_dir: Path,
    phase_filter: str | None,
    scenario_filter: str | None,
    output: Output,
) -> RelearnInput | None:
    """Find the latest testing run and parse failed test IDs.

    Returns None if no failures are found (and logs a success message).
    """
    run_json_path = find_latest_testing_results(results_dir)
    output.status(f"Using results from {run_json_path.parent.name}")

    relearn_input = parse_failed_test_ids(
        run_json_path,
        phase_filter=phase_filter,
        scenario_filter=scenario_filter,
    )

    if not relearn_input.test_ids:
        scope_parts = []
        if scenario_filter:
            scope_parts.append(f"scenario '{scenario_filter}'")
        if phase_filter:
            scope_parts.append(f"phase '{phase_filter}'")
        scope = " in " + ", ".join(scope_parts) if scope_parts else ""
        output.success(f"No failures found{scope} -- nothing to re-learn")
        return None

    output.status(
        f"Re-learning {len(relearn_input.test_ids)} failed test(s) "
        f"in {len(relearn_input.scenario_ids)} scenario(s), "
        f"{len(relearn_input.phase_ids)} phase(s): " + ", ".join(relearn_input.test_ids)
    )
    return relearn_input


def _execute_relearn(
    *,
    relearn_input: RelearnInput,
    plan_path: Path,
    testbed_path: Path | None,
    inventory_plugin: str | None,
    parameters_dir: Path,
    results_dir: Path,
    output_dir: Path | None,
    output: Output,
) -> None:
    """Run the failed tests in learning mode and report results."""
    filters = PlanFilterOptions(
        test_ids=relearn_input.test_ids,
        scenarios=relearn_input.scenario_ids,
        phases=relearn_input.phase_ids,
    )
    plugin_registry = _load_plugin_registry(project_root=Path.cwd())

    result = asyncio.run(
        run_test_plan(
            mode=ExecutionMode.LEARNING,
            testbed_path=testbed_path,
            inventory_plugin=inventory_plugin,
            plan_path=plan_path,
            filters=filters,
            project_root=Path.cwd(),
            parameters_dir=parameters_dir,
            results_dir=results_dir,
            output_dir=output_dir,
            output=output,
            registry=plugin_registry,
        )
    )

    output.status(
        f"Re-learn complete: "
        f"total={result.summary.total} "
        f"passed={result.summary.passed} "
        f"failed={result.summary.failed} "
        f"errored={result.summary.errored} "
        f"not_applicable={result.summary.not_applicable}"
    )

    if result.summary.failed > 0 or result.summary.errored > 0:
        output.error(
            "Some tests failed during re-learning -- "
            "parameters may not have been updated"
        )
        raise typer.Exit(code=1)

    output.success(
        f"Successfully re-learned parameters for {result.summary.passed} test(s)"
    )


def _display_prune_input(prune_input: PruneInput, output: Output) -> None:
    """Log a summary of the parsed applicability data."""
    output.status(
        f"Found {len(prune_input.partial_tests)} partially applicable "
        f"and {len(prune_input.full_tests)} fully non-applicable test(s)"
    )

    if prune_input.partial_tests:
        output.status("Partially applicable tests (exclude_devices):")
        for entry in prune_input.partial_tests:
            na_devs = ", ".join(sorted(entry.not_applicable_devices.keys()))
            output.status(f"  {entry.test_id}: exclude {na_devs}")

    if prune_input.full_tests:
        output.status("Fully non-applicable tests (remove from groups):")
        for entry in prune_input.full_tests:
            output.status(f"  {entry.test_id}")


def _execute_prune_plan(
    plan_result: PrunePlan,
    plan: Path,
    dry_run: bool,
    output: Output,
) -> None:
    """Display, optionally apply, and summarize the prune plan."""
    has_changes = (
        plan_result.exclude_devices_updates
        or plan_result.exclude_from_groups
        or plan_result.orphaned_test_cases
    )
    if not has_changes:
        output.success("Pruning already applied -- no changes needed")
        if plan_result.skipped_already_pruned:
            output.warning(
                f"Skipped {len(plan_result.skipped_already_pruned)} "
                "already-pruned test(s)"
            )
        return

    _display_prune_plan_details(plan_result, output)
    counts = _prune_plan_counts(plan_result)

    if dry_run:
        _report_prune_dry_run(counts, output)
        return

    apply_prune_plan(plan_path=plan, prune_plan=plan_result, output=output)
    validate_after_prune(plan)
    _report_prune_applied(counts, plan_result, output)


def _display_prune_plan_details(plan_result: PrunePlan, output: Output) -> None:
    """Log detailed info about planned prune changes."""
    if plan_result.exclude_devices_updates:
        output.status("Applying exclude_devices to test cases:")
        for test_id, devices in sorted(plan_result.exclude_devices_updates.items()):
            output.status(f"  {test_id}: exclude_devices={devices}")

    if plan_result.exclude_from_groups:
        output.status("Removing tests from groups:")
        for group_id, test_ids in sorted(plan_result.exclude_from_groups.items()):
            for tid in test_ids:
                output.status(f"  {tid} from {group_id}")

    if plan_result.orphaned_test_cases:
        output.status("Removing orphaned test case definitions:")
        for tid in plan_result.orphaned_test_cases:
            output.status(f"  {tid}")


def _prune_plan_counts(
    plan_result: PrunePlan,
) -> tuple[int, int, int]:
    """Return (device_updates, group_updates, orphan_count)."""
    device_updates = len(plan_result.exclude_devices_updates)
    group_updates = sum(len(tids) for tids in plan_result.exclude_from_groups.values())
    orphan_count = len(plan_result.orphaned_test_cases)
    return device_updates, group_updates, orphan_count


def _report_prune_dry_run(counts: tuple[int, int, int], output: Output) -> None:
    """Report a dry-run prune summary."""
    device_updates, group_updates, orphan_count = counts
    parts = [
        f"{device_updates} test(s) would get exclude_devices",
        f"{group_updates} test(s) would be removed from groups",
    ]
    if orphan_count:
        parts.append(f"{orphan_count} test case definition(s) would be removed")
    output.success(f"Dry run complete: {', '.join(parts)}")


def _report_prune_applied(
    counts: tuple[int, int, int],
    plan_result: PrunePlan,
    output: Output,
) -> None:
    """Report a completed prune summary."""
    device_updates, group_updates, orphan_count = counts
    parts = [
        f"{device_updates} test(s) with exclude_devices",
        f"{group_updates} test(s) removed from groups",
    ]
    if orphan_count:
        parts.append(f"{orphan_count} test case definition(s) removed")
    output.success(f"Prune complete: {', '.join(parts)}")
    if plan_result.skipped_already_pruned:
        output.warning(
            f"Skipped {len(plan_result.skipped_already_pruned)} already-pruned test(s)"
        )


@app.command()
def prune(
    plan: Annotated[
        Path,
        typer.Option(
            "--plan",
            "-p",
            help="Path to test plan YAML file or directory of YAML files.",
            exists=True,
            file_okay=True,
            dir_okay=True,
            resolve_path=True,
            envvar="HUGINN_PLAN",
        ),
    ],
    results_dir: Annotated[
        Path | None,
        typer.Option(
            "--results-dir",
            help="Path to results directory (default: ./results/).",
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
            envvar="HUGINN_RESULTS_DIR",
        ),
    ] = None,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            help="Enable DEBUG-level logging.",
            envvar="HUGINN_DEBUG",
        ),
    ] = False,
    log_level: Annotated[
        str,
        typer.Option(
            "--log-level",
            help="Logging level (DEBUG, INFO, WARNING, ERROR).",
            envvar="HUGINN_LOG_LEVEL",
        ),
    ] = "INFO",
    show_logs: Annotated[
        bool,
        typer.Option(
            "--show-logs",
            help="Stream logs to console in addition to file.",
            envvar="HUGINN_SHOW_LOGS",
        ),
    ] = False,
    log_file: Annotated[
        Path | None,
        typer.Option(
            "--log-file",
            help="Path to log file (default: ./huginn.log).",
            envvar="HUGINN_LOG_FILE",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Show what would be pruned without modifying the test plan.",
        ),
    ] = False,
    remove_orphans: Annotated[
        bool,
        typer.Option(
            "--remove-orphans",
            help=(
                "Remove test case definitions that are no longer"
                " referenced by any group after pruning."
            ),
        ),
    ] = False,
) -> None:
    """Prune non-applicable tests and device targets from the test plan.

    After running in learning mode, some tests return NOT_APPLICABLE for
    certain devices. This command reads the latest learning results and:

    - For tests where SOME devices are non-applicable: adds exclude_devices
      to the test case's target definition.
    - For tests where ALL devices are non-applicable: removes the test
      from its test case group(s) via exclude_tests.

    Examples:
        huginn prune -p test_plan/
        huginn prune -p test_plan/ --dry-run
        huginn prune -p test_plan.yaml --results-dir ./results/
    """
    resolved_results_dir = results_dir or Path.cwd() / "results"

    output = _build_output(
        debug=debug,
        log_level=log_level,
        show_logs=show_logs,
        log_file=log_file,
    )
    output.status("Pruning non-applicable tests from test plan")
    output.log_debug_fields(
        "CLI prune options",
        plan=plan,
        results_dir=resolved_results_dir,
        log_level="DEBUG" if debug else log_level,
    )

    try:
        run_json_path = find_latest_learning_results(resolved_results_dir)
        output.status(f"Using results from {run_json_path.parent.name}")

        prune_input = parse_applicability_from_run(run_json_path)

        total_na = len(prune_input.partial_tests) + len(prune_input.full_tests)
        if total_na == 0:
            output.success("No non-applicable tests found -- nothing to prune")
            return

        _display_prune_input(prune_input, output)

        test_plan_obj = load_test_plan(plan)
        plan_result = compute_prune_plan(
            prune_input,
            test_plan_obj,
            remove_orphans=remove_orphans,
        )

        _execute_prune_plan(plan_result, plan, dry_run, output)

    except (PruneError, ConfigurationError) as error:
        output.error(f"ERROR: {error}")
        raise typer.Exit(code=1) from error


def _render_execute_results(
    results: list[ExecuteCommandResult],
    output: Output,
    *,
    show_prompt: bool = True,
) -> None:
    """Render execute results in a human-readable, copy-friendly format."""
    from rich.rule import Rule
    from rich.text import Text

    console = output.console

    for result in results:
        meta_parts = []
        if result.device_os:
            meta_parts.append(f"os={result.device_os}")
        meta_parts.append(f"broker={result.broker}")
        if result.elapsed_ms is not None:
            meta_parts.append(f"{result.elapsed_ms:.0f}ms")

        header = Text()
        if result.error is not None:
            header.append(result.device, style="bold red")
        else:
            header.append(result.device, style="bold cyan")
        header.append("  ", style="default")
        header.append(" | ".join(meta_parts), style="dim")

        console.print(Rule(header))

        if show_prompt:
            prompt = Text()
            prompt.append(
                f"{result.device}# ",
                style="bold green",
            )
            prompt.append(result.command, style="bold")
            console.print(prompt)

        body = result.raw_output or ""
        if body:
            console.print(body, highlight=False)
        elif result.error is None:
            console.print(Text("(no output)", style="dim italic"))

        if result.error is not None:
            console.print(Text(f"\n{result.error}", style="red"))

        console.print()


def _resolve_execute_specs(
    *,
    device: str | None,
    command: str | None,
    commands: Path | None,
    broker: str,
) -> list[ExecuteCommandSpec]:
    """Validate execute CLI options and build the spec list."""
    if commands is not None:
        _reject_single_with_batch(device, command)
        return load_command_specs(commands)

    if device is not None and command is not None:
        return [ExecuteCommandSpec(device=device, command=command, broker=broker)]

    if device is not None or command is not None:
        raise typer.BadParameter(
            "--device and --command must both be specified together."
        )

    raise typer.BadParameter(
        "Either --device/--command or --commands must be specified."
    )


def _reject_single_with_batch(
    device: str | None,
    command: str | None,
) -> None:
    """Raise if single-command options are mixed with batch mode."""
    if device is not None or command is not None:
        raise typer.BadParameter(
            "--device/--command and --commands are mutually exclusive."
        )


def _check_execute_errors(
    results: list[ExecuteCommandResult],
    output: Output,
) -> None:
    """Check for errors in execute results and exit if any found."""
    has_errors = any(r.error is not None for r in results)
    if has_errors:
        error_count = sum(1 for r in results if r.error is not None)
        output.warning(f"{error_count} of {len(results)} command(s) had errors")
        raise typer.Exit(code=1)
    output.success(f"All {len(results)} command(s) succeeded")


@app.command()
def execute(
    testbed: Annotated[
        Path,
        typer.Option(
            "--testbed",
            "-t",
            help="Path to testbed YAML file defining device inventory.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
            envvar="HUGINN_TESTBED",
        ),
    ],
    device: Annotated[
        str | None,
        typer.Option(
            "--device",
            help="Device name from the testbed to execute against.",
        ),
    ] = None,
    command: Annotated[
        str | None,
        typer.Option(
            "--command",
            "-c",
            help="Command string or API path to execute on the device.",
        ),
    ] = None,
    commands: Annotated[
        Path | None,
        typer.Option(
            "--commands",
            help="Path to a YAML file defining batch command executions.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
        ),
    ] = None,
    broker: Annotated[
        str,
        typer.Option(
            "--broker",
            "-b",
            help="Broker type: ssh, http, or netconf (default: ssh).",
        ),
    ] = "ssh",
    no_prompt: Annotated[
        bool,
        typer.Option(
            "--no-prompt",
            help="Hide the simulated device prompt line above command output.",
        ),
    ] = False,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            help="Enable DEBUG-level logging.",
            envvar="HUGINN_DEBUG",
        ),
    ] = False,
    log_level: Annotated[
        str,
        typer.Option(
            "--log-level",
            help="Logging level (DEBUG, INFO, WARNING, ERROR).",
            envvar="HUGINN_LOG_LEVEL",
        ),
    ] = "INFO",
    show_logs: Annotated[
        bool,
        typer.Option(
            "--show-logs",
            help="Stream logs to console in addition to file.",
            envvar="HUGINN_SHOW_LOGS",
        ),
    ] = False,
    log_file: Annotated[
        Path | None,
        typer.Option(
            "--log-file",
            help="Path to log file (default: ./huginn.log).",
            envvar="HUGINN_LOG_FILE",
        ),
    ] = None,
) -> None:
    """Execute ad-hoc commands on testbed devices.

    Run one or more commands against devices defined in a testbed file.
    Results are displayed in a human-readable format. Programmatic
    consumers should use the SDK directly (``huginn.execute``).

    Single-command mode requires both --device and --command.
    Batch mode uses --commands with a YAML file of command specifications.

    Examples:
        huginn execute -t testbed.yaml --device spine-01 -c "show version"
        huginn execute -t testbed.yaml --device ctrl-01 -c "/api/v1/status" -b http
        huginn execute -t testbed.yaml --commands commands.yaml
    """
    specs = _resolve_execute_specs(
        device=device,
        command=command,
        commands=commands,
        broker=broker,
    )
    output = _build_output(
        debug=debug,
        log_level=log_level,
        show_logs=show_logs,
        log_file=log_file,
    )

    try:
        from huginn.loaders import load_testbed

        loaded_testbed = load_testbed(testbed)
        output.status(f"Executing {len(specs)} command(s)")
        results = asyncio.run(
            execute_commands(
                testbed=loaded_testbed,
                specs=specs,
                output=output,
            )
        )

        _render_execute_results(results, output, show_prompt=not no_prompt)
        _check_execute_errors(results, output)

    except ConfigurationError as error:
        output.error(f"ERROR: {error}")
        raise typer.Exit(code=1) from error


inject_app = typer.Typer(
    name="inject",
    help="Inject job files into the test plan as new test cases.",
    no_args_is_help=True,
)
app.add_typer(inject_app)


@inject_app.command("new")
def inject_new(
    path: Annotated[
        Path,
        typer.Argument(
            help="Directory of job files or a single .py file.",
            exists=True,
            resolve_path=True,
        ),
    ],
    phase: Annotated[
        list[str] | None,
        typer.Option(
            "--phase",
            help="Phase(s) to wire the new group into directly.",
        ),
    ] = None,
    parent_group: Annotated[
        str | None,
        typer.Option(
            "--parent-group",
            help="Existing composite group to nest the new group under.",
        ),
    ] = None,
    plan: Annotated[
        Path | None,
        typer.Option(
            "--plan",
            "-p",
            help="Path to test plan directory (default: ./test_plan).",
            exists=True,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
            envvar="HUGINN_PLAN",
        ),
    ] = None,
    id_style: Annotated[
        str,
        typer.Option(
            "--id-style",
            help="ID generation style.",
        ),
    ] = "prefix-counter",
    target_groups: Annotated[
        list[str] | None,
        typer.Option(
            "--target-groups",
            help="Device groups for targeting (comma-separated).",
        ),
    ] = None,
    tags: Annotated[
        list[str] | None,
        typer.Option(
            "--tags",
            help="Additional tags to apply (comma-separated).",
        ),
    ] = None,
    group: Annotated[
        str | None,
        typer.Option(
            "--group",
            help="Explicit group identifier (default: derived from path).",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Preview changes without writing.",
        ),
    ] = False,
) -> None:
    """Create a new test case group from job files.

    Discovers job files in PATH, creates test case entries with auto-allocated
    IDs, and creates a new group. Use --phase to wire directly into a scenario
    phase, or --parent-group to nest under an existing composite group.

    Examples:
        huginn inject new jobs/iosxe/cdp/ --phase pre-change
        huginn inject new jobs/iosxe/vrf/ --parent-group state-baseline
        huginn inject new jobs/iosxe/bgp/ --parent-group state-baseline --dry-run
    """
    from huginn.inject import (
        InjectError,
        apply_inject_plan,
        compute_inject_plan,
    )

    if not phase and not parent_group:
        output = Output()
        output.error("Provide --phase or --parent-group (or both)")
        raise typer.Exit(code=1)

    plan_path = plan or Path.cwd() / "test_plan"
    project_root = plan_path.parent
    output = Output()

    resolved_target_groups = _split_csv_option_values(target_groups)
    resolved_tags = _split_csv_option_values(tags)
    resolved_phases = _split_csv_option_values(phase)

    try:
        test_plan = load_test_plan(plan_path)
    except ConfigurationError as exc:
        output.error(f"Failed to load test plan: {exc}")
        raise typer.Exit(code=1) from exc

    try:
        inject_plan = compute_inject_plan(
            job_path=path,
            project_root=project_root,
            test_plan=test_plan,
            group_id=group,
            is_new_group=True,
            target_groups=resolved_target_groups,
            tags=resolved_tags,
            phases=resolved_phases,
            parent_group=parent_group,
            id_style=id_style,
        )
    except InjectError as exc:
        output.error(str(exc))
        raise typer.Exit(code=1) from exc

    _display_inject_plan(inject_plan, output)

    if dry_run:
        output.status("Dry run — no changes written")
        return

    try:
        apply_inject_plan(plan_path=plan_path, inject_plan=inject_plan)
    except InjectError as exc:
        output.error(f"Failed to apply: {exc}")
        raise typer.Exit(code=1) from exc

    output.success(
        f"Injected {len(inject_plan.new_test_cases)} test case(s) "
        f"into new group '{inject_plan.group_id}'"
    )


@inject_app.command("into")
def inject_into(
    group: Annotated[
        str,
        typer.Argument(
            help="Existing group identifier to inject into.",
        ),
    ],
    path: Annotated[
        Path,
        typer.Argument(
            help="Directory of job files or a single .py file.",
            exists=True,
            resolve_path=True,
        ),
    ],
    plan: Annotated[
        Path | None,
        typer.Option(
            "--plan",
            "-p",
            help="Path to test plan directory (default: ./test_plan).",
            exists=True,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
            envvar="HUGINN_PLAN",
        ),
    ] = None,
    id_style: Annotated[
        str,
        typer.Option(
            "--id-style",
            help="ID generation style.",
        ),
    ] = "prefix-counter",
    target_groups: Annotated[
        list[str] | None,
        typer.Option(
            "--target-groups",
            help="Device groups for targeting (comma-separated).",
        ),
    ] = None,
    tags: Annotated[
        list[str] | None,
        typer.Option(
            "--tags",
            help="Additional tags to apply (comma-separated).",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Preview changes without writing.",
        ),
    ] = False,
) -> None:
    """Add job files to an existing test case group.

    Discovers job files in PATH, creates test case entries with auto-allocated
    IDs, and appends them to the specified existing group.

    Examples:
        huginn inject into cdp-global-baseline jobs/iosxe/cdp_global/
        huginn inject into iosxe-vrf-detail jobs/iosxe/vrf_detail/new_job.py
    """
    from huginn.inject import (
        InjectError,
        apply_inject_plan,
        compute_inject_plan,
    )

    plan_path = plan or Path.cwd() / "test_plan"
    project_root = plan_path.parent
    output = Output()

    resolved_target_groups = _split_csv_option_values(target_groups)
    resolved_tags = _split_csv_option_values(tags)

    try:
        test_plan = load_test_plan(plan_path)
    except ConfigurationError as exc:
        output.error(f"Failed to load test plan: {exc}")
        raise typer.Exit(code=1) from exc

    if group not in test_plan.test_case_groups:
        output.error(f"Group '{group}' not found in test plan")
        raise typer.Exit(code=1)

    try:
        inject_plan = compute_inject_plan(
            job_path=path,
            project_root=project_root,
            test_plan=test_plan,
            group_id=group,
            is_new_group=False,
            target_groups=resolved_target_groups,
            tags=resolved_tags,
            id_style=id_style,
        )
    except InjectError as exc:
        output.error(str(exc))
        raise typer.Exit(code=1) from exc

    _display_inject_plan(inject_plan, output)

    if dry_run:
        output.status("Dry run — no changes written")
        return

    try:
        apply_inject_plan(plan_path=plan_path, inject_plan=inject_plan)
    except InjectError as exc:
        output.error(f"Failed to apply: {exc}")
        raise typer.Exit(code=1) from exc

    output.success(
        f"Injected {len(inject_plan.new_test_cases)} test case(s) "
        f"into existing group '{inject_plan.group_id}'"
    )


def _display_inject_plan(inject_plan: "InjectPlan", output: Output) -> None:
    """Display the inject plan to the user."""
    if inject_plan.skipped_jobs:
        output.status(f"Skipped {len(inject_plan.skipped_jobs)} job(s) already in plan")

    if not inject_plan.new_test_cases:
        output.status("No new jobs to inject")
        return

    action = "Creating new" if inject_plan.is_new_group else "Appending to"
    output.status(f"{action} group: {inject_plan.group_id}")
    if inject_plan.group_name:
        output.status(f"  Display name: {inject_plan.group_name}")

    output.status(f"  New test cases: {len(inject_plan.new_test_cases)}")
    for test_id, tc_entry in inject_plan.new_test_cases.items():
        output.status(f"    {test_id}: {tc_entry.get('title', '?')}")

    if inject_plan.parent_group:
        output.status(f"  Nesting under parent group: {inject_plan.parent_group}")
    if inject_plan.phase_updates:
        output.status(f"  Wiring into phase(s): {', '.join(inject_plan.phase_updates)}")


@app.command()
def version() -> None:
    """Display the Huginn version."""
    typer.echo(f"huginn v{get_version('huginn')}")


def _load_plugin_registry(project_root: Path) -> PluginRegistry:
    """Load plugin configuration and construct a registry.

    Reads [tool.huginn.plugins] from the project's pyproject.toml if
    present, otherwise returns a default registry with no filtering.
    """
    pyproject_path = project_root / "pyproject.toml"
    if not pyproject_path.exists():
        return PluginRegistry()

    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    plugins_section = data.get("tool", {}).get("huginn", {}).get("plugins", {})
    if not plugins_section:
        return PluginRegistry()

    config = PluginConfig(
        brokers=plugins_section.get("brokers"),
        reporters=plugins_section.get("reporters"),
        hooks=plugins_section.get("hooks"),
        plugin_options=plugins_section.get("config", {}),
    )
    return PluginRegistry(config=config)


def main() -> None:
    """Entry point for the Huginn CLI."""
    app()

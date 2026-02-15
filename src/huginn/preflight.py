"""Preflight validation for testbed and test plan inputs."""

from dataclasses import asdict, dataclass
from pathlib import Path

from huginn.enums import BrokerType
from huginn.jobs import JobLoadError, load_test_case_class
from huginn.loaders import ConfigurationError, load_test_plan, load_testbed
from huginn.models import TestPlan
from huginn.runner import _resolve_targets
from huginn.runtime_broker import RuntimeBrokerError, normalize_broker_key
from huginn.testcase import TestCase


@dataclass
class PreflightCase:
    """Validation details for one phase/group/test-case execution node."""

    phase: str
    group: str
    test_id: str
    title: str
    required_brokers: list[str]
    targets: list[str]


@dataclass
class PreflightReport:
    """Top-level preflight validation report."""

    valid: bool
    phase_order: list[str]
    required_brokers: list[str]
    test_cases: list[PreflightCase]
    warnings: list[str]
    errors: list[str]


def validate_inputs(
    *,
    testbed_path: Path,
    plan_path: Path,
    project_root: Path,
    reports_dir: Path,
) -> PreflightReport:
    """Validate configuration and emit a preflight report."""
    warnings: list[str] = []
    errors: list[str] = []

    try:
        testbed = load_testbed(testbed_path)
        test_plan = load_test_plan(plan_path)
    except ConfigurationError as error:
        report = PreflightReport(
            valid=False,
            phase_order=[],
            required_brokers=[],
            test_cases=[],
            warnings=[],
            errors=[str(error)],
        )
        _write_report(report=report, reports_dir=reports_dir)
        return report

    phase_order, order_errors = _resolve_phase_order(test_plan)
    errors.extend(order_errors)

    required_by_case = _collect_required_brokers(
        test_plan=test_plan,
        project_root=project_root,
        errors=errors,
    )

    test_cases: list[PreflightCase] = []
    for phase_name in phase_order:
        phase = test_plan.phases[phase_name]
        for group_name in phase.test_case_groups:
            group = test_plan.test_case_groups[group_name]
            for test_id in group.tests:
                case = test_plan.test_cases[test_id]
                targets, target_error = _resolve_targets(
                    testbed=testbed,
                    phase=phase,
                    group=group,
                    test_case=case,
                )
                if target_error is not None:
                    errors.append(target_error)
                    target_names: list[str] = []
                else:
                    target_names = [device.name for device in targets]
                    if not target_names:
                        warnings.append(
                            f"{phase.name}/{group.name}/{case.test_id} "
                            "has no matched targets"
                        )

                test_cases.append(
                    PreflightCase(
                        phase=phase.name,
                        group=group.name,
                        test_id=case.test_id,
                        title=case.title,
                        required_brokers=sorted(
                            required_by_case.get(case.test_id, set())
                        ),
                        targets=target_names,
                    )
                )

    all_required = sorted({b for req in required_by_case.values() for b in req})
    report = PreflightReport(
        valid=not errors,
        phase_order=phase_order,
        required_brokers=all_required,
        test_cases=test_cases,
        warnings=warnings,
        errors=errors,
    )
    _write_report(report=report, reports_dir=reports_dir)
    return report


def _resolve_phase_order(test_plan: TestPlan) -> tuple[list[str], list[str]]:
    """Topologically sort phases by dependency order."""
    resolved: list[str] = []
    errors: list[str] = []
    pending = set(test_plan.phases.keys())

    while pending:
        progressed = False
        for phase_name in list(pending):
            phase = test_plan.phases[phase_name]
            if all(dep in resolved for dep in phase.depends_on):
                resolved.append(phase_name)
                pending.remove(phase_name)
                progressed = True
        if not progressed:
            errors.append(
                f"Unable to resolve phase dependencies for: {sorted(pending)}"
            )
            break

    return resolved, errors


def _collect_required_brokers(
    *,
    test_plan: TestPlan,
    project_root: Path,
    errors: list[str],
) -> dict[str, set[str]]:
    """Load each job class and collect declared broker requirements."""
    required: dict[str, set[str]] = {}
    for test_case in test_plan.test_cases.values():
        try:
            test_case_class = load_test_case_class(
                job=test_case.job,
                project_root=project_root,
            )
            required[test_case.test_id] = _normalize_required_brokers(
                test_case_class,
            )
        except (JobLoadError, RuntimeBrokerError) as error:
            errors.append(f"{test_case.test_id}: {error}")
            required[test_case.test_id] = {BrokerType.SSH.value}
    return required


def _normalize_required_brokers(test_case_class: type[TestCase]) -> set[str]:
    """Normalize a test class required_brokers declaration."""
    raw_required = getattr(test_case_class, "required_brokers", {BrokerType.SSH})
    if not isinstance(raw_required, set) or not raw_required:
        raise RuntimeBrokerError(
            f"{test_case_class.__name__}.required_brokers must be a non-empty set"
        )

    normalized: set[str] = set()
    for broker in raw_required:
        if not isinstance(broker, str):
            raise RuntimeBrokerError(
                f"{test_case_class.__name__}.required_brokers values must be strings"
            )
        normalized.add(normalize_broker_key(broker).value)
    return normalized


def _write_report(report: PreflightReport, reports_dir: Path) -> None:
    """Persist preflight report as JSON artifact."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    import json

    report_path = reports_dir / "validate.json"
    report_path.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")

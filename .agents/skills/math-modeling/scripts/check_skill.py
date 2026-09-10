#!/usr/bin/env python
"""Run the release-quality gate for the bundled mathematical-modeling skill."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from _diagnostics import attach_diagnostics, diagnostic
from _json_schema import validate_schema
from prepare_workflow_migration_review_package import validate_limitation_aggregation
from verify_tesseract_recovery import verify_recovery_manifest


SKILL_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILL_DIR / "scripts"
SCHEMAS_DIR = SKILL_DIR / "schemas"
UNITTEST_TIMEOUT_SECONDS = 600
TESTS_DIR = SKILL_DIR / "tests"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=SKILL_DIR.parents[2],
        help="Root whose direct child workflow.json files are checked read-only",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip unittest discovery; intended for the gate's own tests",
    )
    parser.add_argument(
        "--skip-historical",
        action="store_true",
        help="Skip read-only checks of existing cases",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    return parser.parse_args()


def run_json(command: list[str], timeout: int = 60) -> tuple[int, dict | None, str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        timeout=timeout,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = None
    evidence = completed.stderr.strip() or completed.stdout.strip()
    return completed.returncode, payload, evidence


def check_schemas(checks: list[dict], entries: list[dict]) -> None:
    paths = sorted(SCHEMAS_DIR.glob("*.schema.json"))
    failures = []
    for path in paths:
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
            validate_schema(schema)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            failures.append(f"{path.name}: {exc}")
    checks.append(
        {
            "name": "json_schemas",
            "status": "passed" if not failures else "failed",
            "count": len(paths),
            "failures": failures,
        }
    )
    for message in failures:
        entries.append(
            diagnostic(
                "error",
                "schema_invalid",
                "static_validation",
                message,
                remediation=["Repair the bundled Draft 2020-12 schema"],
            )
        )


def check_python_ast(checks: list[dict], entries: list[dict]) -> None:
    paths = sorted(SKILL_DIR.rglob("*.py"))
    failures = []
    for path in paths:
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as exc:
            failures.append(f"{path.relative_to(SKILL_DIR)}: {exc}")
    checks.append(
        {
            "name": "python_ast",
            "status": "passed" if not failures else "failed",
            "count": len(paths),
            "failures": failures,
        }
    )
    for message in failures:
        entries.append(
            diagnostic(
                "error",
                "python_syntax_invalid",
                "static_validation",
                message,
                remediation=["Correct the Python syntax error"],
            )
        )


def check_tesseract_recovery(
    workspace_root: Path, checks: list[dict], entries: list[dict]
) -> dict | None:
    recovery_root = workspace_root / ".skill-audit" / "tool-cache" / "tesseract"
    manifest = recovery_root / "recovery-manifest.json"
    if not recovery_root.exists():
        checks.append(
            {"name": "tesseract_recovery", "status": "not_applicable", "count": 0}
        )
        return None
    try:
        report = verify_recovery_manifest(manifest, workspace_root)
    except (OSError, ValueError) as exc:
        report = {"passed": False, "verified_files": [], "errors": [str(exc)]}
    checks.append(
        {
            "name": "tesseract_recovery",
            "status": "passed" if report["passed"] else "failed",
            "count": len(report.get("verified_files", [])),
            "manifest": str(manifest.resolve()),
        }
    )
    for message in report.get("errors", []):
        entries.append(
            diagnostic(
                "error",
                "tesseract_recovery_invalid",
                "static_validation",
                message,
                remediation=["Restore the pinned files or regenerate the reviewed recovery manifest"],
            )
        )
    return report


def check_tests(checks: list[dict], entries: list[dict]) -> None:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            str(TESTS_DIR),
            "-p",
            "test_*.py",
            "-v",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        timeout=UNITTEST_TIMEOUT_SECONDS,
    )
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    match = re.search(r"Ran (\d+) tests?", output)
    checks.append(
        {
            "name": "unittest",
            "status": "passed" if completed.returncode == 0 else "failed",
            "count": int(match.group(1)) if match else None,
            "output_tail": "\n".join(output.strip().splitlines()[-20:]),
        }
    )
    if completed.returncode != 0:
        entries.append(
            diagnostic(
                "error",
                "tests_failed",
                "tests",
                "The mathematical-modeling unittest suite failed",
                remediation=["Inspect checks.unittest.output_tail and repair the regression"],
            )
        )


def historical_cases(workspace_root: Path) -> list[Path]:
    if not workspace_root.is_dir():
        return []
    return sorted(
        path.parent
        for path in workspace_root.glob("*/workflow.json")
        if path.is_file()
    )


def tree_metadata(root: Path) -> dict[str, tuple[int, int]]:
    """Capture enough metadata to detect writes by passive historical checks."""
    snapshot = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            stat = path.stat()
            snapshot[str(path.relative_to(root))] = (stat.st_size, stat.st_mtime_ns)
    return snapshot


def check_historical_cases(
    workspace_root: Path, checks: list[dict], entries: list[dict]
) -> list[dict]:
    cases = historical_cases(workspace_root)
    results = []
    manifest_failures = 0
    migration_failures = 0
    rehearsal_failures = 0
    review_preview_failures = 0
    acceptance_preview_failures = 0
    for case_dir in cases:
        before = tree_metadata(case_dir)
        validate_code, validate_report, validate_evidence = run_json(
            [
                sys.executable,
                str(SCRIPTS_DIR / "run_pipeline.py"),
                "--case-dir",
                str(case_dir),
                "--validate-only",
                "--json",
            ]
        )
        manifest_valid = bool(
            validate_code == 0
            and isinstance(validate_report, dict)
            and validate_report.get("valid")
        )
        if not manifest_valid:
            manifest_failures += 1
            message = (
                "; ".join(validate_report.get("errors", []))
                if isinstance(validate_report, dict)
                else validate_evidence or "validator did not emit JSON"
            )
            entries.append(
                diagnostic(
                    "error",
                    "historical_manifest_invalid",
                    "historical_validation",
                    f"{case_dir.name}: {message}",
                    remediation=["Repair the historical workflow manifest explicitly"],
                )
            )

        doctor_code, doctor_report, doctor_evidence = run_json(
            [
                sys.executable,
                str(SCRIPTS_DIR / "doctor.py"),
                "--case-dir",
                str(case_dir),
                "--phase",
                "build",
                "--json",
            ]
        )
        doctor_valid = bool(
            isinstance(doctor_report, dict)
            and doctor_report.get("mode") == "passive_read_only"
        )
        child_diagnostics = doctor_report.get("diagnostics", []) if doctor_valid else []
        if not doctor_valid:
            entries.append(
                diagnostic(
                    "error",
                    "historical_doctor_invalid",
                    "historical_diagnostics",
                    f"{case_dir.name}: {doctor_evidence or 'doctor did not emit a passive report'}",
                    remediation=["Repair doctor.py or the case diagnostic invocation"],
                )
            )
        elif doctor_code != 0:
            codes = sorted(
                {
                    str(item.get("code"))
                    for item in child_diagnostics
                    if item.get("severity") == "error"
                }
            )
            entries.append(
                diagnostic(
                    "warning",
                    "historical_case_findings",
                    "historical_diagnostics",
                    f"{case_dir.name}: {', '.join(codes) or 'doctor reported findings'}",
                    remediation=["Review the case findings before reusing or finalizing that case"],
                )
            )

        plan_code, plan_report, plan_evidence = run_json(
            [
                sys.executable,
                str(SCRIPTS_DIR / "run_pipeline.py"),
                "--case-dir",
                str(case_dir),
                "--plan",
                "--json",
            ]
        )
        plan_valid = bool(
            plan_code == 0
            and isinstance(plan_report, dict)
            and plan_report.get("phase") == "plan"
            and plan_report.get("mode") == "passive_read_only"
            and plan_report.get("files_written") is False
            and plan_report.get("case_steps_executed") is False
        )
        if not plan_valid:
            entries.append(
                diagnostic(
                    "error",
                    "historical_plan_invalid",
                    "historical_planning",
                    f"{case_dir.name}: {plan_evidence or 'planner did not emit a valid passive report'}",
                    remediation=["Repair the passive execution planner"],
                )
            )

        migration_code, migration_report, migration_evidence = run_json(
            [
                sys.executable,
                str(SCRIPTS_DIR / "analyze_workflow_migration.py"),
                "--case-dir",
                str(case_dir),
                "--json",
            ]
        )
        migration_valid = bool(
            migration_code == 0
            and isinstance(migration_report, dict)
            and migration_report.get("command") == "analyze_workflow_migration"
            and migration_report.get("mode") == "passive_read_only"
            and migration_report.get("files_written") is False
            and migration_report.get("case_steps_executed") is False
            and (
                migration_report.get("source_schema_version") != 1
                or migration_report.get("candidate_valid") is True
            )
        )
        if not migration_valid:
            migration_failures += 1
            entries.append(
                diagnostic(
                    "error",
                    "historical_migration_analysis_invalid",
                    "historical_migration",
                    f"{case_dir.name}: {migration_evidence or 'migration analyzer did not emit a valid passive report'}",
                    remediation=["Repair the passive workflow migration analyzer"],
                )
            )

        rehearsal_code, rehearsal_report, rehearsal_evidence = run_json(
            [
                sys.executable,
                str(SCRIPTS_DIR / "rehearse_workflow_migration.py"),
                "--case-dir",
                str(case_dir),
                "--json",
            ]
        )
        rehearsal_valid = bool(
            rehearsal_code == 0
            and isinstance(rehearsal_report, dict)
            and rehearsal_report.get("command") == "rehearse_workflow_migration"
            and rehearsal_report.get("rehearsal_passed") is True
            and rehearsal_report.get("source_files_written") is False
            and rehearsal_report.get("source_unchanged") is True
            and rehearsal_report.get("case_steps_executed") is False
            and rehearsal_report.get("external_tools_started") is False
            and (
                rehearsal_report.get("status") == "not_applicable"
                or (
                    rehearsal_report.get("status") == "passed"
                    and rehearsal_report.get("candidate_valid_in_isolation") is True
                    and rehearsal_report.get("temporary_workspace_created") is True
                    and rehearsal_report.get("temporary_workspace_removed") is True
                    and not rehearsal_report.get("isolated_plan", {}).get(
                        "blocked_steps"
                    )
                )
            )
        )
        if not rehearsal_valid:
            rehearsal_failures += 1
            entries.append(
                diagnostic(
                    "error",
                    "historical_migration_rehearsal_invalid",
                    "historical_migration",
                    f"{case_dir.name}: {rehearsal_evidence or 'migration rehearsal did not emit a valid isolated report'}",
                    remediation=["Repair the isolated workflow migration rehearsal"],
                )
            )
        review_code, review_report, review_evidence = run_json(
            [
                sys.executable,
                str(SCRIPTS_DIR / "review_workflow_migration.py"),
                "--case-dir",
                str(case_dir),
                "--json",
            ]
        )
        review_preview_valid = bool(
            review_code == 0
            and isinstance(review_report, dict)
            and review_report.get("command") == "review_workflow_migration"
            and review_report.get("mode") == "preview"
            and review_report.get("source_manifest_unchanged") is True
            and review_report.get("rehearsal_passed") is True
            and review_report.get("case_steps_executed") is False
            and review_report.get("external_tools_started") is False
            and not review_report.get("files_written")
            and (
                review_report.get("status") == "not_applicable"
                or (
                    review_report.get("status") == "preview_ready"
                    and isinstance(review_report.get("review_template"), dict)
                    and review_report.get("base_candidate_sha256")
                )
            )
        )
        if not review_preview_valid:
            review_preview_failures += 1
            entries.append(
                diagnostic(
                    "error",
                    "historical_migration_review_preview_invalid",
                    "historical_migration",
                    f"{case_dir.name}: {review_evidence or 'migration reviewer did not emit a valid passive preview'}",
                    remediation=["Repair the hash-bound migration review preview"],
                )
            )
        acceptance_code, acceptance_report, acceptance_evidence = run_json(
            [
                sys.executable,
                str(SCRIPTS_DIR / "audit_workflow_migration_candidate.py"),
                "--case-dir",
                str(case_dir),
                "--json",
            ]
        )
        expected_acceptance_status = (
            "evidence_required"
            if migration_valid and migration_report.get("source_schema_version") == 1
            else "not_applicable"
        )
        acceptance_preview_valid = bool(
            acceptance_code == 0
            and isinstance(acceptance_report, dict)
            and acceptance_report.get("command")
            == "audit_workflow_migration_candidate"
            and acceptance_report.get("mode") == "passive_read_only"
            and acceptance_report.get("source_unchanged") is True
            and acceptance_report.get("case_files_written") is False
            and acceptance_report.get("case_steps_executed") is False
            and acceptance_report.get("external_tools_started") is False
            and acceptance_report.get("rehearsal_passed") is True
            and acceptance_report.get("status") == expected_acceptance_status
            and acceptance_report.get("accepted") is False
        )
        if not acceptance_preview_valid:
            acceptance_preview_failures += 1
            entries.append(
                diagnostic(
                    "error",
                    "historical_migration_acceptance_preview_invalid",
                    "historical_migration",
                    f"{case_dir.name}: {acceptance_evidence or 'migration acceptance auditor did not emit a valid passive preview'}",
                    remediation=["Repair the hash-bound migration acceptance preview"],
                )
            )
        after = tree_metadata(case_dir)
        unchanged = before == after
        if not unchanged:
            entries.append(
                diagnostic(
                    "error",
                    "historical_read_only_violation",
                    "historical_validation",
                    f"{case_dir.name}: passive checks changed the case file tree",
                    remediation=["Remove side effects from validate-only, doctor, plan, and migration-analysis modes"],
                )
            )
        results.append(
            {
                "case": case_dir.name,
                "manifest_valid": manifest_valid,
                "doctor_report_valid": doctor_valid,
                "execution_plan_valid": plan_valid,
                "migration_analysis_valid": migration_valid,
                "migration_rehearsal_valid": rehearsal_valid,
                "migration_rehearsal_status": (
                    rehearsal_report.get("status") if rehearsal_valid else None
                ),
                "migration_rehearsal_summary": (
                    rehearsal_report.get("summary") if rehearsal_valid else None
                ),
                "migration_review_preview_valid": review_preview_valid,
                "migration_review_status": (
                    review_report.get("status") if review_preview_valid else None
                ),
                "migration_review_python_steps": (
                    len(review_report.get("review_template", {}).get("steps", []))
                    if review_preview_valid
                    and isinstance(review_report.get("review_template"), dict)
                    else 0
                ),
                "migration_acceptance_preview_valid": acceptance_preview_valid,
                "migration_acceptance_status": (
                    acceptance_report.get("status")
                    if acceptance_preview_valid
                    else None
                ),
                "migration_acceptance_expected_candidate_sha256": (
                    acceptance_report.get("bindings", {}).get(
                        "expected_candidate_sha256"
                    )
                    if acceptance_preview_valid
                    else None
                ),
                "migration_applicable": (
                    migration_report.get("applicable") if migration_valid else None
                ),
                "migration_summary": (
                    migration_report.get("summary") if migration_valid else None
                ),
                "read_only_unchanged": unchanged,
                "healthy": doctor_report.get("healthy") if doctor_valid else None,
                "diagnostic_summary": (
                    doctor_report.get("diagnostic_summary") if doctor_valid else None
                ),
                "diagnostic_codes": sorted(
                    {str(item.get("code")) for item in child_diagnostics}
                ),
                "plan_summary": plan_report.get("summary") if plan_valid else None,
                "plan_reason_codes": (
                    sorted(
                        {str(step.get("reason_code")) for step in plan_report.get("steps", [])}
                    )
                    if plan_valid
                    else []
                ),
            }
        )
    checks.append(
        {
            "name": "historical_read_only",
            "status": (
                "passed"
                if manifest_failures == 0
                and migration_failures == 0
                and rehearsal_failures == 0
                and review_preview_failures == 0
                and acceptance_preview_failures == 0
                and all(
                    item["execution_plan_valid"]
                    and item["migration_analysis_valid"]
                    and item["migration_rehearsal_valid"]
                    and item["migration_review_preview_valid"]
                    and item["migration_acceptance_preview_valid"]
                    and item["read_only_unchanged"]
                    for item in results
                )
                else "failed"
            ),
            "count": len(cases),
            "manifest_failures": manifest_failures,
            "migration_failures": migration_failures,
            "rehearsal_failures": rehearsal_failures,
            "review_preview_failures": review_preview_failures,
            "acceptance_preview_failures": acceptance_preview_failures,
            "doctor_findings": sum(not bool(item["healthy"]) for item in results),
        }
    )
    return results


def check_migration_readiness(
    workspace_root: Path,
    expected_case_count: int,
    checks: list[dict],
    entries: list[dict],
) -> dict | None:
    code, report, evidence = run_json(
        [
            sys.executable,
            str(SCRIPTS_DIR / "summarize_workflow_migration_readiness.py"),
            "--workspace-root",
            str(workspace_root),
            "--json",
        ]
    )
    ready_cases = (
        [
            item
            for item in report.get("cases", [])
            if item.get("status") == "ready_for_human_review"
        ]
        if isinstance(report, dict)
        else []
    )
    recommended = report.get("recommended_case") if isinstance(report, dict) else None
    recommendation_valid = (
        recommended is None and not ready_cases
    ) or any(
        item.get("case") == recommended and item.get("rank") == 1
        for item in ready_cases
    )
    valid = bool(
        code == 0
        and isinstance(report, dict)
        and report.get("command")
        == "summarize_workflow_migration_readiness"
        and report.get("mode") == "passive_read_only"
        and report.get("status") in {"ready", "no_applicable_cases"}
        and report.get("files_written") is False
        and report.get("case_steps_executed") is False
        and report.get("external_tools_started") is False
        and report.get("summary", {}).get("cases_total") == expected_case_count
        and report.get("summary", {}).get("blocked") == 0
        and all(item.get("source_unchanged") is True for item in report.get("cases", []))
        and recommendation_valid
    )
    checks.append(
        {
            "name": "migration_readiness",
            "status": "passed" if valid else "failed",
            "count": len(report.get("cases", [])) if isinstance(report, dict) else 0,
            "recommended_case": recommended if valid else None,
        }
    )
    if not valid:
        entries.append(
            diagnostic(
                "error",
                "migration_readiness_invalid",
                "historical_migration",
                evidence or "migration readiness did not emit a valid passive report",
                remediation=["Repair the cross-case migration readiness summarizer"],
            )
        )
    return report if valid else None


def check_recommended_review_package(
    workspace_root: Path,
    readiness: dict | None,
    checks: list[dict],
    entries: list[dict],
) -> dict | None:
    if not readiness or readiness.get("recommended_case") is None:
        checks.append(
            {
                "name": "migration_review_package",
                "status": "not_applicable",
                "count": 0,
                "case": None,
            }
        )
        return None
    recommended = readiness["recommended_case"]
    selected = next(
        item for item in readiness["cases"] if item.get("case") == recommended
    )
    code, report, evidence = run_json(
        [
            sys.executable,
            str(SCRIPTS_DIR / "prepare_workflow_migration_review_package.py"),
            "--case-dir",
            str(workspace_root / recommended),
            "--expected-source-sha256",
            selected["source_manifest"]["sha256"],
            "--expected-candidate-sha256",
            selected["expected_candidate_sha256"],
            "--json",
        ]
    )
    checklist = (
        [check for step in report.get("steps", []) for check in step.get("checklist", [])]
        if isinstance(report, dict)
        else []
    )
    provenance = (
        [
            item
            for step in report.get("steps", [])
            for evidence_item in step.get("path_evidence", [])
            for item in evidence_item.get("provenance", [])
        ]
        if isinstance(report, dict)
        else []
    )
    support_modules = (
        report.get("bindings", {}).get("support_modules", [])
        if isinstance(report, dict)
        else []
    )
    limitations = (
        [
            item
            for step in report.get("steps", [])
            for item in step.get("trace_limitations", [])
        ]
        if isinstance(report, dict)
        else []
    )
    limitation_groups = (
        [
            (step.get("name"), item)
            for step in report.get("steps", [])
            for item in step.get("trace_limitation_groups", [])
        ]
        if isinstance(report, dict)
        else []
    )
    limitation_codes = {
        "helper_cycle_detected",
        "helper_depth_limit_reached",
        "dynamic_import_unresolved",
        "star_import_unresolved",
        "helper_name_rebound",
        "path_parameter_transformed",
        "trace_budget_exhausted",
    }
    semantic_valid = False
    if isinstance(report, dict):
        try:
            validate_limitation_aggregation(report)
            semantic_valid = True
        except (KeyError, TypeError, ValueError):
            semantic_valid = False
    valid = bool(
        code == 0
        and semantic_valid
        and isinstance(report, dict)
        and report.get("command")
        == "prepare_workflow_migration_review_package"
        and report.get("mode") == "passive_read_only"
        and report.get("status") == "ready_for_human_review"
        and report.get("applicable") is True
        and report.get("files_written") is False
        and report.get("case_steps_executed") is False
        and report.get("external_tools_started") is False
        and report.get("review_record_created") is False
        and report.get("candidate_exported") is False
        and report.get("cache_enabled") is False
        and report.get("source_unchanged") is True
        and report.get("bindings", {}).get("source_manifest", {}).get("sha256")
        == selected["source_manifest"]["sha256"]
        and report.get("bindings", {}).get("base_candidate_sha256")
        == selected["expected_candidate_sha256"]
        and bool(checklist)
        and all(check.get("status") == "pending_human_review" for check in checklist)
        and report.get("summary", {}).get("pending_checklist_items") == len(checklist)
        and report.get("summary", {}).get("cache_enable_recommended") == 0
        and bool(provenance)
        and report.get("summary", {}).get("provenance_chains") == len(provenance)
        and report.get("summary", {}).get("direct_provenance_chains")
        == sum(item.get("kind") == "direct" for item in provenance)
        and report.get("summary", {}).get("local_helper_provenance_chains")
        == sum(item.get("kind") == "local_helper" for item in provenance)
        and report.get("summary", {}).get("imported_helper_provenance_chains")
        == sum(item.get("kind") == "imported_helper" for item in provenance)
        and report.get("summary", {}).get("trace_limitations")
        == len(limitations)
        and report.get("summary", {}).get("unique_trace_limitations")
        == len(limitations)
        and isinstance(
            report.get("summary", {}).get("trace_limitation_occurrences"), int
        )
        and report.get("summary", {}).get("trace_limitation_occurrences")
        >= len(limitations)
        and report.get("summary", {}).get("trace_limitation_groups")
        == len(limitation_groups)
        and sum(group.get("occurrences", 0) for _, group in limitation_groups)
        == report.get("summary", {}).get("trace_limitation_occurrences")
        and sum(group.get("unique_call_chains", 0) for _, group in limitation_groups)
        == len(limitations)
        and len(
            {
                (
                    step_name,
                    group.get("code"),
                    group.get("module"),
                    group.get("function"),
                    group.get("line"),
                    group.get("callee"),
                )
                for step_name, group in limitation_groups
            }
        )
        == len(limitation_groups)
        and all(
            group.get("code") in limitation_codes
            and group.get("status") == "review_required"
            and isinstance(group.get("occurrences"), int)
            and group.get("occurrences") >= 1
            and isinstance(group.get("unique_call_chains"), int)
            and group.get("unique_call_chains") >= 1
            and group.get("unique_call_chains")
            == sum(
                item.get("code") == group.get("code")
                and item.get("module") == group.get("module")
                and item.get("function") == group.get("function")
                and item.get("line") == group.get("line")
                and item.get("callee") == group.get("callee")
                for step in report.get("steps", [])
                if step.get("name") == step_name
                for item in step.get("trace_limitations", [])
            )
            for step_name, group in limitation_groups
        )
        and all(
            item.get("code") in limitation_codes
            and item.get("status") == "review_required"
            and isinstance(item.get("module"), str)
            and bool(item.get("module"))
            and isinstance(item.get("function"), str)
            and bool(item.get("function"))
            and isinstance(item.get("line"), int)
            and item.get("line") >= 1
            and isinstance(item.get("callee"), str)
            and bool(item.get("callee"))
            and isinstance(item.get("message"), str)
            and bool(item.get("message"))
            and isinstance(item.get("call_chain"), list)
            and 1 <= len(item.get("call_chain", [])) <= 5
            and all(
                isinstance(frame.get("module"), str)
                and bool(frame.get("module"))
                and isinstance(frame.get("function"), str)
                and bool(frame.get("function"))
                and isinstance(frame.get("line"), int)
                and frame.get("line") >= 1
                and isinstance(frame.get("callee"), str)
                and bool(frame.get("callee"))
                for frame in item.get("call_chain", [])
            )
            and item.get("call_chain", [])[-1]
            == {
                key: item.get(key)
                for key in ("module", "function", "line", "callee")
            }
            for item in limitations
        )
        and all(
            isinstance(item.get("path"), str)
            and re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256")))
            for item in support_modules
        )
    )
    checks.append(
        {
            "name": "migration_review_package",
            "status": "passed" if valid else "failed",
            "count": len(report.get("steps", [])) if isinstance(report, dict) else 0,
            "case": recommended if valid else None,
        }
    )
    if not valid:
        entries.append(
            diagnostic(
                "error",
                "migration_review_package_invalid",
                "historical_migration",
                evidence or "recommended review package did not emit a valid passive report",
                remediation=["Repair the hash-bound migration review package generator"],
            )
        )
    return report if valid else None


def check_recommended_review_markdown(
    workspace_root: Path,
    readiness: dict | None,
    package: dict | None,
    checks: list[dict],
    entries: list[dict],
) -> dict | None:
    if not readiness or not package or readiness.get("recommended_case") is None:
        checks.append(
            {
                "name": "migration_review_markdown",
                "status": "not_applicable",
                "count": 0,
                "case": None,
            }
        )
        return None
    recommended = readiness["recommended_case"]
    case_dir = workspace_root / recommended
    before = tree_metadata(case_dir)
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "render_workflow_migration_review_package.py"),
            "--case-dir",
            str(case_dir),
            "--expected-source-sha256",
            package["bindings"]["source_manifest"]["sha256"],
            "--expected-candidate-sha256",
            package["bindings"]["base_candidate_sha256"],
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        timeout=60,
    )
    after = tree_metadata(case_dir)
    markdown = completed.stdout
    checklist = [
        check for step in package["steps"] for check in step.get("checklist", [])
    ]
    hashes = [
        package["bindings"]["source_manifest"]["sha256"],
        package["bindings"]["base_candidate_sha256"],
        *[binding["sha256"] for binding in package["bindings"]["python_scripts"]],
        *[binding["sha256"] for binding in package["bindings"]["support_modules"]],
    ]
    provenance_kinds = {
        item["kind"]
        for step in package["steps"]
        for evidence_item in step["path_evidence"]
        for item in evidence_item["provenance"]
    }
    limitation_codes = {
        item["code"]
        for step in package["steps"]
        for item in step["trace_limitations"]
    }
    limitation_chains = {
        " -> ".join(
            f"{frame['module']}:{frame['function']}:{frame['line']}:{frame['callee']}"
            for frame in item["call_chain"]
        )
        for step in package["steps"]
        for item in step["trace_limitations"]
    }
    valid = bool(
        completed.returncode == 0
        and before == after
        and markdown.startswith("# Workflow Migration Human Review Work Package\n")
        and "> Status: `ready_for_human_review`" in markdown
        and "read-only evidence view, not a completed review record or migration approval"
        in markdown
        and all(value in markdown for value in hashes)
        and markdown.count("- [ ]") == len(checklist)
        and markdown.count("`pending_human_review`") == len(checklist)
        and "- Files written: `false`" in markdown
        and "- Case steps executed: `false`" in markdown
        and "- External tools started: `false`" in markdown
        and "- Review record created: `false`" in markdown
        and "- Candidate exported: `false`" in markdown
        and "- Cache enabled: `false`" in markdown
        and "- Cache-enable recommendations: 0" in markdown
        and f"- Trace limitations: {package['summary']['trace_limitations']}"
        in markdown
        and f"- Trace limitation occurrences: {package['summary']['trace_limitation_occurrences']}"
        in markdown
        and f"- Unique trace limitations: {package['summary']['unique_trace_limitations']}"
        in markdown
        and f"- Trace limitation groups: {package['summary']['trace_limitation_groups']}"
        in markdown
        and all(f"Provenance `{kind}`:" in markdown for kind in provenance_kinds)
        and all(f"`{code}`" in markdown for code in limitation_codes)
        and all(chain in markdown for chain in limitation_chains)
        and all(
            f"##### Stop `{group['module']}:{group['function']}:{group['line']}:{group['callee']}`"
            in markdown
            and f"- Occurrences: {group['occurrences']}" in markdown
            and f"- Unique call chains: {group['unique_call_chains']}" in markdown
            for step in package["steps"]
            for group in step["trace_limitation_groups"]
        )
        and (not limitation_codes or "## Trace Limitations" in markdown)
    )
    checks.append(
        {
            "name": "migration_review_markdown",
            "status": "passed" if valid else "failed",
            "count": len(checklist),
            "case": recommended if valid else None,
        }
    )
    if not valid:
        entries.append(
            diagnostic(
                "error",
                "migration_review_markdown_invalid",
                "historical_migration",
                completed.stderr.strip()
                or "recommended review Markdown was incomplete or changed its source case",
                remediation=["Repair the stdout-only human review renderer"],
            )
        )
        return None
    return {
        "case": recommended,
        "status": "rendered",
        "stdout_only": True,
        "source_unchanged": True,
        "bytes": len(markdown.encode("utf-8")),
        "pending_checklist_items": len(checklist),
    }


def run_gate(args: argparse.Namespace) -> dict:
    workspace_root = args.workspace_root.expanduser().resolve()
    checks: list[dict] = []
    entries: list[dict] = []
    check_schemas(checks, entries)
    check_python_ast(checks, entries)
    tesseract_recovery = check_tesseract_recovery(workspace_root, checks, entries)
    if args.skip_tests:
        checks.append({"name": "unittest", "status": "skipped", "count": None})
    else:
        check_tests(checks, entries)
    historical = []
    migration_readiness = None
    migration_review_package = None
    migration_review_markdown = None
    if args.skip_historical:
        checks.append(
            {"name": "historical_read_only", "status": "skipped", "count": 0}
        )
        checks.append(
            {"name": "migration_readiness", "status": "skipped", "count": 0}
        )
        checks.append(
            {"name": "migration_review_package", "status": "skipped", "count": 0}
        )
        checks.append(
            {"name": "migration_review_markdown", "status": "skipped", "count": 0}
        )
    else:
        historical = check_historical_cases(workspace_root, checks, entries)
        migration_readiness = check_migration_readiness(
            workspace_root, len(historical), checks, entries
        )
        migration_review_package = check_recommended_review_package(
            workspace_root, migration_readiness, checks, entries
        )
        migration_review_markdown = check_recommended_review_markdown(
            workspace_root,
            migration_readiness,
            migration_review_package,
            checks,
            entries,
        )
    report = {
        "schema_version": 1,
        "command": "check_skill",
        "skill_dir": str(SKILL_DIR),
        "workspace_root": str(workspace_root),
        "passed": not any(entry["severity"] == "error" for entry in entries),
        "checks": checks,
        "historical_cases": historical,
        "migration_readiness": migration_readiness,
        "migration_review_package": migration_review_package,
        "migration_review_markdown": migration_review_markdown,
        "tesseract_recovery": tesseract_recovery,
    }
    return attach_diagnostics(report, entries)


def print_human(report: dict) -> None:
    print(f"passed={str(report['passed']).lower()}")
    for check in report["checks"]:
        print(f"{check['name']}={check['status']} ({check.get('count', 0)})")
    for entry in report["diagnostics"]:
        print(f"{entry['severity']}.{entry['code']}: {entry['message']}")


def main() -> int:
    args = parse_args()
    try:
        report = run_gate(args)
    except (OSError, subprocess.SubprocessError) as exc:
        report = attach_diagnostics(
            {
                "schema_version": 1,
                "command": "check_skill",
                "passed": False,
                "checks": [],
                "historical_cases": [],
                "migration_readiness": None,
                "migration_review_package": None,
                "migration_review_markdown": None,
            },
            [
                diagnostic(
                    "error",
                    "quality_gate_execution_failed",
                    "quality_gate",
                    str(exc),
                    remediation=["Correct the local environment and rerun the quality gate"],
                )
            ],
        )
    if args.json:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        print_human(report)
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

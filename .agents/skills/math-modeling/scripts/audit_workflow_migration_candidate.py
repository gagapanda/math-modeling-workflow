#!/usr/bin/env python
"""Audit a reviewed workflow v2 candidate without installing or executing it."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from _diagnostics import attach_diagnostics, diagnostic
from _json_schema import load_and_validate
from _workflow_common import resolve_path_inside, sha256_file
from analyze_workflow_migration import analyze, relative_manifest_path
from rehearse_workflow_migration import candidate_digest, rehearse, tree_metadata
from review_workflow_migration import (
    load_review,
    review_template,
    validate_candidate,
    validate_migration_output_ownership,
    validate_review,
)
from run_pipeline import execution_plan, load_manifest


REPORT_SCHEMA = (
    Path(__file__).resolve().parent.parent
    / "schemas"
    / "workflow-migration-acceptance.schema.json"
)
PYTHON_METADATA = ("inputs", "outputs", "timeout_seconds", "cache")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args()
    if (args.review is None) != (args.candidate is None):
        parser.error("--review and --candidate must be provided together")
    return args


def empty_plan_comparison() -> dict:
    return {
        "source_plan_valid": False,
        "candidate_plan_valid": False,
        "structure_equivalent": False,
        "source_postprocessing_planned": None,
        "candidate_postprocessing_planned": None,
        "source_steps": [],
        "candidate_steps": [],
        "action_changes": [],
        "candidate_blocked_steps": [],
    }


def base_report(case_dir: Path, manifest_path: Path) -> dict:
    return {
        "schema_version": 1,
        "command": "audit_workflow_migration_candidate",
        "mode": "passive_read_only",
        "case_dir": str(case_dir),
        "source_manifest_path": str(manifest_path),
        "status": "failed",
        "accepted": False,
        "applicable": False,
        "source_unchanged": False,
        "case_files_written": False,
        "case_steps_executed": False,
        "external_tools_started": False,
        "rehearsal_passed": False,
        "review_valid": False,
        "candidate_valid": False,
        "bindings": {
            "source_manifest": {"path": str(manifest_path), "sha256": "0" * 64},
            "review_record": None,
            "candidate_manifest": None,
            "python_scripts": [],
            "expected_candidate_sha256": None,
            "actual_candidate_sha256": None,
        },
        "invariants": [],
        "authorized_changes": [],
        "unauthorized_changes": [],
        "plan_comparison": empty_plan_comparison(),
        "summary": {
            "invariants_passed": 0,
            "invariants_failed": 0,
            "authorized_changes": 0,
            "unauthorized_changes": 0,
            "plan_action_changes": 0,
            "candidate_blocked_steps": 0,
        },
        "errors": [],
        "warnings": [],
    }


def json_value(value: object, *, absent: bool = False) -> str:
    if absent:
        return "<absent>"
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def escape_pointer(value: object) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


def recursive_differences(expected: object, actual: object, pointer: str = "") -> list[dict]:
    if isinstance(expected, dict) and isinstance(actual, dict):
        differences = []
        for key in sorted(set(expected) | set(actual)):
            child = f"{pointer}/{escape_pointer(key)}"
            if key not in expected:
                differences.append(
                    {
                        "json_pointer": child,
                        "expected_json": "<absent>",
                        "actual_json": json_value(actual[key]),
                        "message": "candidate contains a field not authorized by the review",
                    }
                )
            elif key not in actual:
                differences.append(
                    {
                        "json_pointer": child,
                        "expected_json": json_value(expected[key]),
                        "actual_json": "<absent>",
                        "message": "candidate omits a field required by the reviewed migration",
                    }
                )
            else:
                differences.extend(recursive_differences(expected[key], actual[key], child))
        return differences
    if isinstance(expected, list) and isinstance(actual, list):
        differences = []
        for index in range(max(len(expected), len(actual))):
            child = f"{pointer}/{index}"
            if index >= len(expected):
                differences.append(
                    {
                        "json_pointer": child,
                        "expected_json": "<absent>",
                        "actual_json": json_value(actual[index]),
                        "message": "candidate contains an array item not authorized by the review",
                    }
                )
            elif index >= len(actual):
                differences.append(
                    {
                        "json_pointer": child,
                        "expected_json": json_value(expected[index]),
                        "actual_json": "<absent>",
                        "message": "candidate omits an array item required by the reviewed migration",
                    }
                )
            else:
                differences.extend(recursive_differences(expected[index], actual[index], child))
        return differences
    if type(expected) is not type(actual) or expected != actual:
        return [
            {
                "json_pointer": pointer or "/",
                "expected_json": json_value(expected),
                "actual_json": json_value(actual),
                "message": "candidate value differs from the current reviewed migration",
            }
        ]
    return []


def authorized_changes(source: dict, expected: dict) -> list[dict]:
    changes = [
        {
            "json_pointer": "/schema_version",
            "before_json": json_value(source["schema_version"]),
            "after_json": json_value(expected["schema_version"]),
            "authorization": "target_schema_version",
        },
        {
            "json_pointer": "/profile",
            "before_json": json_value(None, absent=True),
            "after_json": json_value(expected["profile"]),
            "authorization": "preserve_practice_profile",
        },
    ]
    for index, step in enumerate(source["steps"]):
        if step.get("type", "python") != "python":
            continue
        migrated = expected["steps"][index]
        for field in PYTHON_METADATA:
            changes.append(
                {
                    "json_pointer": f"/steps/{index}/{field}",
                    "before_json": json_value(None, absent=True),
                    "after_json": json_value(migrated[field]),
                    "authorization": "reviewed_python_metadata",
                }
            )
    return changes


def add_invariant(report: dict, code: str, passed: bool, message: str) -> None:
    report["invariants"].append(
        {"code": code, "status": "passed" if passed else "failed", "message": message}
    )


def plan_step_summary(step: dict) -> dict:
    return {
        "name": step["name"],
        "type": step["type"],
        "runner": step.get("runner"),
        "action": step["action"],
        "reason_code": step["reason_code"],
    }


def compare_plans(source_plan: dict, candidate_plan: dict) -> dict:
    source_steps = [plan_step_summary(step) for step in source_plan["steps"]]
    candidate_steps = [plan_step_summary(step) for step in candidate_plan["steps"]]
    source_structure = [
        (step["name"], step["type"], step["runner"]) for step in source_steps
    ]
    candidate_structure = [
        (step["name"], step["type"], step["runner"]) for step in candidate_steps
    ]
    structure_equivalent = (
        source_structure == candidate_structure
        and source_plan["postprocessing_planned"]
        == candidate_plan["postprocessing_planned"]
    )
    action_changes = []
    for source, candidate in zip(source_steps, candidate_steps):
        if (source["action"], source["reason_code"]) != (
            candidate["action"], candidate["reason_code"]
        ):
            action_changes.append(
                {
                    "step": source["name"],
                    "source_action": source["action"],
                    "source_reason_code": source["reason_code"],
                    "candidate_action": candidate["action"],
                    "candidate_reason_code": candidate["reason_code"],
                }
            )
    return {
        "source_plan_valid": True,
        "candidate_plan_valid": True,
        "structure_equivalent": structure_equivalent,
        "source_postprocessing_planned": source_plan["postprocessing_planned"],
        "candidate_postprocessing_planned": candidate_plan["postprocessing_planned"],
        "source_steps": source_steps,
        "candidate_steps": candidate_steps,
        "action_changes": action_changes,
        "candidate_blocked_steps": [
            step["name"] for step in candidate_steps if step["action"] == "blocked"
        ],
    }


def load_candidate(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read migration candidate: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("migration candidate must be a JSON object")
    return payload


def update_summary(report: dict) -> None:
    report["summary"] = {
        "invariants_passed": sum(
            item["status"] == "passed" for item in report["invariants"]
        ),
        "invariants_failed": sum(
            item["status"] == "failed" for item in report["invariants"]
        ),
        "authorized_changes": len(report["authorized_changes"]),
        "unauthorized_changes": len(report["unauthorized_changes"]),
        "plan_action_changes": len(report["plan_comparison"]["action_changes"]),
        "candidate_blocked_steps": len(
            report["plan_comparison"]["candidate_blocked_steps"]
        ),
    }


def audit(
    case_dir: Path,
    manifest_path: Path,
    review_value: Path | None,
    candidate_value: Path | None,
) -> dict:
    before = tree_metadata(case_dir)
    report = base_report(case_dir, manifest_path)
    entries = []
    try:
        report["bindings"]["source_manifest"] = {
            "path": str(manifest_path),
            "sha256": sha256_file(manifest_path),
        }
        analysis = analyze(case_dir, manifest_path)
        report["applicable"] = analysis["applicable"]
        rehearsal = rehearse(case_dir, manifest_path)
        report["rehearsal_passed"] = rehearsal["rehearsal_passed"]
        if not rehearsal["rehearsal_passed"]:
            raise ValueError(
                "migration rehearsal failed: " + "; ".join(rehearsal["errors"])
            )
        if not analysis["applicable"]:
            report["status"] = "not_applicable"
            report["warnings"].append(
                "The source manifest already uses workflow schema version 2."
            )
        elif review_value is None:
            template = review_template(case_dir, manifest_path, analysis)
            report["bindings"]["python_scripts"] = template["source_scripts"]
            report["bindings"]["expected_candidate_sha256"] = template[
                "base_candidate_sha256"
            ]
            report["status"] = "evidence_required"
            report["warnings"].append(
                "A completed review record and exported candidate are required for acceptance."
            )
        else:
            review_path = resolve_path_inside(case_dir, review_value, "migration review")
            candidate_path = resolve_path_inside(
                case_dir, candidate_value, "migration candidate"
            )
            if len({manifest_path, review_path, candidate_path}) != 3:
                raise ValueError(
                    "source manifest, review record, and candidate must be distinct files"
                )
            review = load_review(review_path)
            template = review_template(case_dir, manifest_path, analysis)
            expected = validate_review(
                case_dir, manifest_path, analysis, template, review
            )
            expected_normalized = validate_candidate(case_dir, expected)
            validate_migration_output_ownership(
                case_dir, expected_normalized, {manifest_path, review_path, candidate_path}
            )
            report["review_valid"] = True
            report["bindings"]["review_record"] = {
                "path": str(review_path),
                "sha256": sha256_file(review_path),
            }
            report["bindings"]["python_scripts"] = review["source_scripts"]
            report["bindings"]["expected_candidate_sha256"] = candidate_digest(expected)

            candidate = load_candidate(candidate_path)
            actual_normalized = load_manifest(case_dir, candidate_path)
            validate_migration_output_ownership(
                case_dir, actual_normalized, {manifest_path, review_path, candidate_path}
            )
            report["candidate_valid"] = True
            report["bindings"]["candidate_manifest"] = {
                "path": str(candidate_path),
                "sha256": sha256_file(candidate_path),
            }
            report["bindings"]["actual_candidate_sha256"] = candidate_digest(candidate)
            report["authorized_changes"] = authorized_changes(
                json.loads(manifest_path.read_text(encoding="utf-8")), expected
            )
            report["unauthorized_changes"] = recursive_differences(expected, candidate)

            source_normalized = load_manifest(case_dir, manifest_path)
            source_plan = execution_plan(case_dir, source_normalized)
            candidate_plan = execution_plan(case_dir, actual_normalized)
            report["plan_comparison"] = compare_plans(source_plan, candidate_plan)

            exact_candidate = not report["unauthorized_changes"]
            plan_equivalent = report["plan_comparison"]["structure_equivalent"]
            no_blocked = not report["plan_comparison"]["candidate_blocked_steps"]
            add_invariant(
                report,
                "source_schema_v1",
                analysis["source_schema_version"] == 1,
                "The migration source uses workflow schema version 1.",
            )
            add_invariant(
                report,
                "practice_profile_preserved",
                candidate.get("profile") == "practice",
                "The candidate preserves historical practice semantics.",
            )
            add_invariant(
                report,
                "review_exact_candidate",
                exact_candidate,
                "The candidate exactly matches the manifest derived from the current review.",
            )
            add_invariant(
                report,
                "plan_structure_equivalent",
                plan_equivalent,
                "Step order, types, runners, and post-processing intent are unchanged.",
            )
            add_invariant(
                report,
                "candidate_plan_unblocked",
                no_blocked,
                "The passive candidate plan contains no blocked steps.",
            )
            accepted = exact_candidate and plan_equivalent and no_blocked
            report["accepted"] = accepted
            report["status"] = "accepted" if accepted else "failed"
            if not exact_candidate:
                report["errors"].append(
                    "candidate contains changes not authorized by the current review"
                )
            if not plan_equivalent:
                report["errors"].append(
                    "candidate execution-plan structure differs from the source"
                )
            if not no_blocked:
                report["errors"].append(
                    "candidate execution plan contains blocked steps: "
                    + ", ".join(report["plan_comparison"]["candidate_blocked_steps"])
                )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        report["status"] = "failed"
        report["accepted"] = False
        report["errors"].append(str(exc))
    finally:
        report["source_unchanged"] = before == tree_metadata(case_dir)
        if not report["source_unchanged"]:
            report["status"] = "failed"
            report["accepted"] = False
            report["errors"].append(
                "case file metadata changed during the passive migration audit"
            )

    update_summary(report)
    if report["errors"]:
        entries.append(
            diagnostic(
                "error",
                "migration_candidate_acceptance_failed",
                "workflow_migration_acceptance",
                "; ".join(report["errors"]),
                remediation=[
                    "Regenerate the review and candidate from the current source, then rerun the audit"
                ],
            )
        )
    elif report["status"] == "evidence_required":
        entries.append(
            diagnostic(
                "warning",
                "migration_acceptance_evidence_required",
                "workflow_migration_acceptance",
                report["warnings"][0],
                remediation=[
                    "Complete the hash-bound review and explicitly export a candidate before acceptance"
                ],
            )
        )
    report = attach_diagnostics(report, entries)
    load_and_validate(report, REPORT_SCHEMA, "workflow migration acceptance report")
    return report


def print_human(report: dict) -> None:
    print(f"status={report['status']}")
    print(f"accepted={str(report['accepted']).lower()}")
    print(f"source_unchanged={str(report['source_unchanged']).lower()}")
    for error in report["errors"]:
        print(f"error: {error}")


def main() -> int:
    args = parse_args()
    case_dir = args.case_dir.expanduser().resolve()
    manifest_path = case_dir / "workflow.json"
    try:
        if not case_dir.is_dir():
            raise ValueError(f"case directory does not exist: {case_dir}")
        manifest_path = relative_manifest_path(case_dir, args.manifest)
        report = audit(
            case_dir, manifest_path, args.review, args.candidate
        )
    except (OSError, ValueError) as exc:
        report = base_report(case_dir, manifest_path)
        report["errors"] = [str(exc)]
        report = attach_diagnostics(
            report,
            [
                diagnostic(
                    "error",
                    "migration_candidate_acceptance_failed",
                    "workflow_migration_acceptance",
                    str(exc),
                    remediation=["Repair the case path or invocation and rerun"],
                )
            ],
        )
    if args.json:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        print_human(report)
    return 0 if report["status"] in {"accepted", "evidence_required", "not_applicable"} else 2


if __name__ == "__main__":
    raise SystemExit(main())

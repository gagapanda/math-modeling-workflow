#!/usr/bin/env python
"""Summarize workflow v1-to-v2 migration readiness across sibling cases."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from _diagnostics import attach_diagnostics, diagnostic
from _json_schema import load_and_validate
from _workflow_common import sha256_file
from analyze_workflow_migration import analyze
from doctor import diagnose
from rehearse_workflow_migration import candidate_digest, tree_metadata


REPORT_SCHEMA = (
    Path(__file__).resolve().parent.parent
    / "schemas"
    / "workflow-migration-readiness.schema.json"
)
RANKING_FIELDS = [
    "diagnostic_errors",
    "source_analysis_unavailable_steps",
    "python_steps",
    "human_review_items",
    "steps_without_static_hints",
    "matlab_steps",
    "case",
]
METRIC_FIELDS = [
    "diagnostic_errors",
    "python_steps",
    "matlab_steps",
    "human_review_items",
    "static_input_hints",
    "static_output_hints",
    "source_analysis_unavailable_steps",
    "steps_without_static_hints",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace-root",
        type=Path,
        required=True,
        help="Root whose direct child workflow.json files are summarized",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    return parser.parse_args()


def historical_cases(workspace_root: Path) -> list[Path]:
    return sorted(
        path.parent
        for path in workspace_root.glob("*/workflow.json")
        if path.is_file()
    )


def empty_metrics() -> dict:
    return {field: 0 for field in METRIC_FIELDS}


def summarize_steps(steps: list[dict]) -> tuple[list[dict], dict]:
    summaries = []
    unavailable = 0
    without_hints = 0
    for step in steps:
        hints = step["static_path_hints"]
        input_count = sum(item["access"] == "input" for item in hints)
        output_count = sum(item["access"] == "output" for item in hints)
        available = "source_analysis_unavailable" not in step["review_reason_codes"]
        if step["type"] == "python":
            unavailable += not available
            without_hints += not hints
        summaries.append(
            {
                "name": step["name"],
                "type": step["type"],
                "static_input_hints": input_count,
                "static_output_hints": output_count,
                "static_hint_paths": sorted({item["path"] for item in hints}),
                "review_reason_codes": step["review_reason_codes"],
                "source_analysis_available": available,
            }
        )
    return summaries, {
        "source_analysis_unavailable_steps": unavailable,
        "steps_without_static_hints": without_hints,
    }


def summarize_case(case_dir: Path) -> dict:
    manifest_path = case_dir / "workflow.json"
    before = tree_metadata(case_dir)
    result = {
        "rank": None,
        "case": case_dir.name,
        "case_dir": str(case_dir),
        "status": "blocked",
        "source_schema_version": None,
        "source_manifest": None,
        "expected_candidate_sha256": None,
        "metrics": empty_metrics(),
        "diagnostic_codes": [],
        "steps": [],
        "ranking_key": None,
        "source_unchanged": False,
        "errors": [],
        "warnings": [],
    }
    try:
        result["source_manifest"] = {
            "path": str(manifest_path),
            "sha256": sha256_file(manifest_path),
        }
        doctor_report = diagnose(case_dir, manifest_path, "build")
        result["metrics"]["diagnostic_errors"] = doctor_report[
            "diagnostic_summary"
        ]["error"]
        result["diagnostic_codes"] = sorted(
            {str(item["code"]) for item in doctor_report["diagnostics"]}
        )
        analysis = analyze(case_dir, manifest_path)
        result["source_schema_version"] = analysis["source_schema_version"]
        result["warnings"] = analysis["warnings"]
        if not analysis["applicable"]:
            result["status"] = "not_applicable"
            return result
        steps, derived = summarize_steps(analysis["steps"])
        result["steps"] = steps
        result["metrics"] = {
            "diagnostic_errors": result["metrics"]["diagnostic_errors"],
            "python_steps": analysis["summary"]["python_steps"],
            "matlab_steps": analysis["summary"]["matlab_steps"],
            "human_review_items": analysis["summary"]["human_review_items"],
            "static_input_hints": analysis["summary"]["static_input_hints"],
            "static_output_hints": analysis["summary"]["static_output_hints"],
            **derived,
        }
        result["expected_candidate_sha256"] = candidate_digest(
            analysis["candidate_manifest"]
        )
        result["status"] = "ready_for_human_review"
        result["ranking_key"] = [
            result["metrics"][field] for field in RANKING_FIELDS[:-1]
        ] + [case_dir.name]
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        result["errors"].append(str(exc))
    finally:
        result["source_unchanged"] = before == tree_metadata(case_dir)
        if not result["source_unchanged"]:
            result["status"] = "blocked"
            result["errors"].append("readiness analysis changed the case file tree")
    return result


def summarize(workspace_root: Path) -> dict:
    entries = []
    cases = [summarize_case(case_dir) for case_dir in historical_cases(workspace_root)]
    ranked = sorted(
        (item for item in cases if item["status"] == "ready_for_human_review"),
        key=lambda item: tuple(item["ranking_key"]),
    )
    for rank, item in enumerate(ranked, start=1):
        item["rank"] = rank
    cases.sort(
        key=lambda item: (
            item["rank"] is None,
            item["rank"] or 0,
            item["case"],
        )
    )
    blocked = [item for item in cases if item["status"] == "blocked"]
    for item in blocked:
        message = f"{item['case']}: {'; '.join(item['errors']) or 'readiness analysis failed'}"
        entries.append(
            diagnostic(
                "error",
                "migration_readiness_case_blocked",
                "workflow_migration_readiness",
                message,
                remediation=["Repair the case manifest or source-read failure, then rerun readiness analysis"],
            )
        )
    if ranked:
        entries.append(
            diagnostic(
                "info",
                "migration_review_candidate_recommended",
                "workflow_migration_readiness",
                f"{ranked[0]['case']} has no fewer passive diagnostic errors and the smallest subsequent review-workload key",
                remediation=["Treat the recommendation as review triage, not migration approval"],
            )
        )
    totals = {
        "cases_total": len(cases),
        "ready_for_human_review": len(ranked),
        "not_applicable": sum(item["status"] == "not_applicable" for item in cases),
        "blocked": len(blocked),
        **{
            field: sum(item["metrics"][field] for item in cases)
            for field in METRIC_FIELDS
        },
    }
    status = (
        "failed"
        if blocked
        else "ready"
        if ranked
        else "no_applicable_cases"
    )
    report = {
        "schema_version": 1,
        "command": "summarize_workflow_migration_readiness",
        "mode": "passive_read_only",
        "workspace_root": str(workspace_root),
        "status": status,
        "files_written": False,
        "case_steps_executed": False,
        "external_tools_started": False,
        "cases": cases,
        "recommended_case": ranked[0]["case"] if ranked else None,
        "ranking_policy": {
            "method": "ascending_lexicographic",
            "fields": RANKING_FIELDS,
            "meaning": "Prioritizes fewer current passive diagnostic errors, then mechanically measured human-review workload and static-analysis availability.",
            "not_assessed": [
                "model_correctness",
                "paper_quality",
                "migration_approval",
                "cache_safety",
            ],
        },
        "summary": totals,
        "errors": [message for item in blocked for message in item["errors"]],
        "warnings": [
            "Static path hints are incomplete evidence and are never dependency declarations."
        ] if ranked else [],
    }
    report = attach_diagnostics(report, entries)
    load_and_validate(report, REPORT_SCHEMA, "workflow migration readiness")
    return report


def failure_report(workspace_root: Path, message: str) -> dict:
    report = {
        "schema_version": 1,
        "command": "summarize_workflow_migration_readiness",
        "mode": "passive_read_only",
        "workspace_root": str(workspace_root),
        "status": "failed",
        "files_written": False,
        "case_steps_executed": False,
        "external_tools_started": False,
        "cases": [],
        "recommended_case": None,
        "ranking_policy": {
            "method": "ascending_lexicographic",
            "fields": RANKING_FIELDS,
            "meaning": "Prioritizes fewer current passive diagnostic errors, then mechanically measured human-review workload and static-analysis availability.",
            "not_assessed": [
                "model_correctness", "paper_quality", "migration_approval", "cache_safety"
            ],
        },
        "summary": {
            "cases_total": 0,
            "ready_for_human_review": 0,
            "not_applicable": 0,
            "blocked": 0,
            **empty_metrics(),
        },
        "errors": [message],
        "warnings": [],
    }
    return attach_diagnostics(
        report,
        [
            diagnostic(
                "error",
                "migration_readiness_failed",
                "workflow_migration_readiness",
                message,
                remediation=["Provide an existing workspace root and rerun the command"],
            )
        ],
    )


def print_human(report: dict) -> None:
    print(f"status={report['status']}")
    print(f"recommended_case={report['recommended_case'] or 'none'}")
    for item in report["cases"]:
        print(
            f"case.{item['case']}={item['status']} "
            f"rank={item['rank'] or '-'} review_items={item['metrics']['human_review_items']}"
        )
    for error in report["errors"]:
        print(f"error: {error}")


def main() -> int:
    args = parse_args()
    workspace_root = args.workspace_root.expanduser().resolve()
    try:
        if not workspace_root.is_dir():
            raise ValueError(f"workspace root does not exist: {workspace_root}")
        report = summarize(workspace_root)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        report = failure_report(workspace_root, str(exc))
    if args.json:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        print_human(report)
    return 0 if report["status"] != "failed" else 2


if __name__ == "__main__":
    raise SystemExit(main())

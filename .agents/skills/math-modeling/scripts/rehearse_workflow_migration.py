#!/usr/bin/env python
"""Rehearse a workflow v1-to-v2 migration in an isolated temporary case."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True

from _diagnostics import attach_diagnostics, diagnostic
from _json_schema import load_and_validate
from _workflow_common import resolve_inside, sha256_file
from analyze_workflow_migration import analyze, relative_manifest_path
from run_pipeline import execution_plan, load_manifest


REPORT_SCHEMA = (
    Path(__file__).resolve().parent.parent
    / "schemas"
    / "workflow-migration-rehearsal.schema.json"
)
REVIEW_CHECKS = (
    ("confirm_declared_inputs", "Confirm all files and state that can change this step's result."),
    ("confirm_declared_outputs", "Confirm every output required to prove successful completion."),
    ("confirm_timeout", "Replace the 300 second default when observed runtime requires it."),
    ("confirm_determinism", "Confirm seeds, clocks, environment, network, and external state are controlled."),
    ("decide_cache_enablement", "Keep cache disabled until dependency closure and determinism are verified."),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    return parser.parse_args()


def tree_metadata(root: Path) -> dict[str, tuple[int, int]]:
    snapshot = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            stat = path.stat()
            snapshot[str(path.relative_to(root)).replace("\\", "/")] = (
                stat.st_size,
                stat.st_mtime_ns,
            )
    return snapshot


def candidate_digest(candidate: dict) -> str:
    encoded = json.dumps(
        candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def required_shadow_files(case_dir: Path, candidate: dict) -> dict[Path, set[str]]:
    required: dict[Path, set[str]] = {}

    def add(value: str, purpose: str) -> None:
        path = resolve_inside(case_dir, value, purpose)
        required.setdefault(path, set()).add(purpose)

    for step in candidate["steps"]:
        name = step["name"]
        step_type = step.get("type", "python")
        add(step["script"], f"step:{name}:script")
        if step_type != "matlab":
            continue
        if step.get("test"):
            add(step["test"], f"step:{name}:test")
        for dependency in step.get("dependencies", []):
            add(dependency, f"step:{name}:dependency")
        for output in step.get("outputs", []):
            add(output, f"step:{name}:output")
        if step.get("runner", "mcp-evidence") == "mcp-evidence":
            add(
                step.get("evidence", f"results/matlab-validation-{name}.json"),
                f"step:{name}:evidence",
            )
    return required


def copy_shadow_files(
    case_dir: Path, shadow_dir: Path, required: dict[Path, set[str]]
) -> list[dict]:
    copied = []
    for source, purposes in sorted(required.items(), key=lambda item: str(item[0])):
        if not source.is_file():
            relative = str(source.relative_to(case_dir)).replace("\\", "/")
            raise ValueError(f"required rehearsal file is missing: {relative}")
        relative_path = source.relative_to(case_dir)
        target = shadow_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        source_hash = sha256_file(source)
        if sha256_file(target) != source_hash:
            raise ValueError(f"rehearsal copy hash mismatch: {relative_path}")
        copied.append(
            {
                "path": str(relative_path).replace("\\", "/"),
                "sha256": source_hash,
                "purposes": sorted(purposes),
            }
        )
    return copied


def review_checklist(analysis: dict) -> list[dict]:
    checklist = []
    for step in analysis["steps"]:
        is_python = step["type"] == "python"
        checklist.append(
            {
                "step": step["name"],
                "type": step["type"],
                "status": "pending_human_review" if is_python else "not_applicable",
                "static_path_hints": step["static_path_hints"],
                "checks": [
                    {
                        "code": code,
                        "status": "pending_human_review" if is_python else "not_applicable",
                        "message": message,
                    }
                    for code, message in REVIEW_CHECKS
                    if is_python
                ],
            }
        )
    return checklist


def base_report(case_dir: Path, manifest_path: Path) -> dict:
    return {
        "schema_version": 1,
        "command": "rehearse_workflow_migration",
        "mode": "isolated_temporary_rehearsal",
        "source_case_dir": str(case_dir),
        "source_manifest_path": str(manifest_path),
        "source_files_written": False,
        "source_unchanged": False,
        "case_steps_executed": False,
        "external_tools_started": False,
        "applicable": False,
        "status": "failed",
        "rehearsal_passed": False,
        "analysis_valid": False,
        "candidate_valid_in_isolation": False,
        "candidate_sha256": None,
        "temporary_workspace_created": False,
        "temporary_workspace_removed": False,
        "copied_files": [],
        "isolated_plan": {
            "validated": False, "summary": None, "reason_codes": [], "blocked_steps": []
        },
        "review_checklist": [],
        "summary": {
            "copied_files": 0,
            "python_steps_pending_review": 0,
            "matlab_steps_unchanged": 0,
            "static_path_hints": 0,
            "blocked_plan_steps": 0,
            "cache_enable_recommended": 0,
        },
        "errors": [],
        "warnings": [],
    }


def remove_shadow_dir(shadow_dir: Path) -> bool:
    resolved = shadow_dir.resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    try:
        resolved.relative_to(temp_root)
    except ValueError as exc:
        raise ValueError(
            f"refusing to remove rehearsal directory outside the system temporary root: {resolved}"
        ) from exc
    if not resolved.name.startswith("math-modeling-migration-"):
        raise ValueError(f"refusing to remove unexpected rehearsal directory: {resolved}")
    shutil.rmtree(resolved)
    return not resolved.exists()


def rehearse(case_dir: Path, manifest_path: Path) -> dict:
    before = tree_metadata(case_dir)
    report = base_report(case_dir, manifest_path)
    entries = []
    shadow_dir = None
    try:
        analysis = analyze(case_dir, manifest_path)
        report["analysis_valid"] = True
        report["applicable"] = analysis["applicable"]
        report["review_checklist"] = review_checklist(analysis)
        if not analysis["applicable"]:
            report["status"] = "not_applicable"
            report["rehearsal_passed"] = True
            report["warnings"].append(
                "The manifest already uses workflow schema version 2; no temporary rehearsal was needed."
            )
        else:
            candidate = analysis["candidate_manifest"]
            report["candidate_sha256"] = candidate_digest(candidate)
            shadow_dir = Path(
                tempfile.mkdtemp(prefix="math-modeling-migration-")
            ).resolve()
            report["temporary_workspace_created"] = True
            required = required_shadow_files(case_dir, candidate)
            report["copied_files"] = copy_shadow_files(case_dir, shadow_dir, required)
            shadow_manifest = shadow_dir / "workflow.json"
            shadow_manifest.write_text(
                json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            normalized = load_manifest(shadow_dir, shadow_manifest)
            report["candidate_valid_in_isolation"] = True
            plan = execution_plan(shadow_dir, normalized)
            blocked = [
                step["name"] for step in plan["steps"] if step["action"] == "blocked"
            ]
            report["isolated_plan"] = {
                "validated": True,
                "summary": plan["summary"],
                "reason_codes": sorted({step["reason_code"] for step in plan["steps"]}),
                "blocked_steps": blocked,
            }
            if blocked:
                raise ValueError(
                    f"isolated candidate plan contains blocked steps: {', '.join(blocked)}"
                )
            report["status"] = "passed"
            report["rehearsal_passed"] = True
            entries.append(
                diagnostic(
                    "warning",
                    "migration_review_pending",
                    "workflow_migration_rehearsal",
                    "The isolated candidate passed, but Python dependency and cache decisions remain pending human review",
                    remediation=["Complete every review_checklist item before editing the source manifest"],
                )
            )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        report["errors"].append(str(exc))
        entries.append(
            diagnostic(
                "error",
                "migration_rehearsal_failed",
                "workflow_migration_rehearsal",
                str(exc),
                remediation=["Repair the source manifest or declared rehearsal files and rerun"],
            )
        )
    finally:
        if shadow_dir is not None:
            try:
                report["temporary_workspace_removed"] = remove_shadow_dir(shadow_dir)
            except (OSError, ValueError) as exc:
                report["temporary_workspace_removed"] = False
                report["rehearsal_passed"] = False
                report["status"] = "failed"
                report["errors"].append(f"cannot remove temporary rehearsal workspace: {exc}")
        report["source_unchanged"] = before == tree_metadata(case_dir)
        if not report["source_unchanged"]:
            report["rehearsal_passed"] = False
            report["status"] = "failed"
            report["errors"].append("source case file metadata changed during rehearsal")

    python_pending = sum(
        item["type"] == "python" for item in report["review_checklist"]
    )
    matlab_unchanged = sum(
        item["type"] == "matlab" for item in report["review_checklist"]
    )
    hint_count = sum(
        len(item["static_path_hints"]) for item in report["review_checklist"]
    )
    blocked_count = len(report["isolated_plan"]["blocked_steps"])
    report["summary"] = {
        "copied_files": len(report["copied_files"]),
        "python_steps_pending_review": python_pending,
        "matlab_steps_unchanged": matlab_unchanged,
        "static_path_hints": hint_count,
        "blocked_plan_steps": blocked_count,
        "cache_enable_recommended": 0,
    }
    report = attach_diagnostics(report, entries)
    load_and_validate(report, REPORT_SCHEMA, "workflow migration rehearsal")
    return report


def print_human(report: dict) -> None:
    print(f"status={report['status']}")
    print(f"rehearsal_passed={str(report['rehearsal_passed']).lower()}")
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
        report = rehearse(case_dir, manifest_path)
    except (OSError, ValueError) as exc:
        report = base_report(case_dir, manifest_path)
        report["errors"] = [str(exc)]
        report = attach_diagnostics(
            report,
            [diagnostic("error", "migration_rehearsal_failed", "workflow_migration_rehearsal", str(exc), remediation=["Repair the case path or manifest and rerun"])],
        )
    if args.json:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        print_human(report)
    return 0 if report["rehearsal_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

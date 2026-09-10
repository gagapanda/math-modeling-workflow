#!/usr/bin/env python
"""Validate human migration decisions and export a reviewed workflow v2 candidate."""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.dont_write_bytecode = True

from _diagnostics import attach_diagnostics, diagnostic
from _json_schema import load_and_validate
from _workflow_common import resolve_path_inside, sha256_file
from analyze_workflow_migration import analyze, relative_manifest_path
from rehearse_workflow_migration import candidate_digest, rehearse
from run_pipeline import load_manifest


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"
REVIEW_SCHEMA = SCHEMAS_DIR / "workflow-migration-review.schema.json"
RESULT_SCHEMA = SCHEMAS_DIR / "workflow-migration-review-result.schema.json"
PLACEHOLDERS = ("required", "todo", "pending", "placeholder")
CONFIRMATIONS = (
    "confirm_declared_inputs",
    "confirm_declared_outputs",
    "confirm_timeout",
    "confirm_determinism",
    "decide_cache_enablement",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument(
        "--write-review-template",
        type=Path,
        help="Write a new human-review template inside the case",
    )
    parser.add_argument(
        "--review", type=Path, help="Validate a completed review record inside the case"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write a new reviewed workflow v2 candidate; requires --review",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args()
    if args.write_review_template is not None and (
        args.review is not None or args.output is not None
    ):
        parser.error("--write-review-template cannot be combined with --review or --output")
    if args.output is not None and args.review is None:
        parser.error("--output requires --review")
    return args


def mode_for(args: argparse.Namespace) -> str:
    if args.write_review_template is not None:
        return "write_review_template"
    if args.output is not None:
        return "export_candidate"
    if args.review is not None:
        return "validate_review"
    return "preview"


def base_report(case_dir: Path, manifest_path: Path, mode: str) -> dict:
    return {
        "schema_version": 1,
        "command": "review_workflow_migration",
        "mode": mode,
        "case_dir": str(case_dir),
        "source_manifest_path": str(manifest_path),
        "source_manifest_sha256": None,
        "source_manifest_unchanged": False,
        "applicable": False,
        "status": "failed",
        "rehearsal_passed": False,
        "case_steps_executed": False,
        "external_tools_started": False,
        "review_complete": False,
        "base_candidate_sha256": None,
        "final_candidate_sha256": None,
        "review_template": None,
        "candidate_manifest": None,
        "files_written": [],
        "output_path": None,
        "errors": [],
        "warnings": [],
    }


def contains_placeholder(value: str) -> bool:
    normalized = value.strip().casefold()
    return not normalized or any(token in normalized for token in PLACEHOLDERS)


def review_template(case_dir: Path, manifest_path: Path, analysis: dict) -> dict:
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw_steps = {step["name"]: step for step in raw["steps"]}
    source_scripts = []
    reviewed_steps = []
    for step in analysis["steps"]:
        if step["type"] != "python":
            continue
        raw_step = raw_steps[step["name"]]
        script = resolve_path_inside(
            case_dir, Path(raw_step["script"]), f"step {step['name']} script"
        )
        source_scripts.append(
            {
                "step": step["name"],
                "path": raw_step["script"].replace("\\", "/"),
                "sha256": sha256_file(script),
            }
        )
        reviewed_steps.append(
            {
                "name": step["name"],
                "inputs": [],
                "outputs": [],
                "timeout_seconds": 300,
                "deterministic": False,
                "cache": False,
                "confirm_declared_inputs": False,
                "confirm_declared_outputs": False,
                "confirm_timeout": False,
                "confirm_determinism": False,
                "decide_cache_enablement": False,
                "decision_notes": "REQUIRED: explain dependency and cache decisions",
                "static_path_hints": step["static_path_hints"],
            }
        )
    template = {
        "schema_version": 1,
        "source_manifest_sha256": sha256_file(manifest_path),
        "base_candidate_sha256": candidate_digest(analysis["candidate_manifest"]),
        "reviewer": "REQUIRED",
        "reviewed_at": "REQUIRED: ISO-8601 timestamp with timezone",
        "source_scripts": source_scripts,
        "steps": reviewed_steps,
    }
    load_and_validate(template, REVIEW_SCHEMA, "workflow migration review template")
    return template


def load_review(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read migration review: {exc}") from exc
    load_and_validate(payload, REVIEW_SCHEMA, "workflow migration review")
    return payload


def validate_review(
    case_dir: Path, manifest_path: Path, analysis: dict, expected: dict, review: dict
) -> dict:
    if review["source_manifest_sha256"] != sha256_file(manifest_path):
        raise ValueError("migration review source manifest hash is stale")
    if review["base_candidate_sha256"] != candidate_digest(analysis["candidate_manifest"]):
        raise ValueError("migration review base candidate hash is stale")
    if review["source_scripts"] != expected["source_scripts"]:
        raise ValueError("migration review source script hashes are stale or incomplete")
    if contains_placeholder(review["reviewer"]):
        raise ValueError("migration review requires an explicit reviewer")
    if contains_placeholder(review["reviewed_at"]):
        raise ValueError("migration review requires an explicit reviewed_at timestamp")
    try:
        reviewed_at = datetime.fromisoformat(review["reviewed_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("migration review reviewed_at must be an ISO-8601 timestamp") from exc
    if reviewed_at.tzinfo is None or reviewed_at.utcoffset() is None:
        raise ValueError("migration review reviewed_at must include a timezone")

    expected_steps = {step["name"]: step for step in expected["steps"]}
    reviewed_steps = review["steps"]
    names = [step["name"] for step in reviewed_steps]
    if len(set(names)) != len(names):
        raise ValueError("migration review step names must be distinct")
    if set(names) != set(expected_steps):
        raise ValueError("migration review must contain exactly every Python step")

    candidate = copy.deepcopy(analysis["candidate_manifest"])
    candidate_steps = {step["name"]: step for step in candidate["steps"]}
    for reviewed in reviewed_steps:
        name = reviewed["name"]
        if reviewed["static_path_hints"] != expected_steps[name]["static_path_hints"]:
            raise ValueError(f"migration review static path hints changed for step {name}")
        missing = [field for field in CONFIRMATIONS if reviewed[field] is not True]
        if missing:
            raise ValueError(
                f"migration review step {name} has unconfirmed decisions: {', '.join(missing)}"
            )
        if contains_placeholder(reviewed["decision_notes"]):
            raise ValueError(f"migration review step {name} requires decision notes")
        if reviewed["cache"] and not reviewed["deterministic"]:
            raise ValueError(
                f"migration review step {name} cannot enable cache without determinism"
            )
        if reviewed["cache"] and not reviewed["outputs"]:
            raise ValueError(
                f"migration review step {name} cannot enable cache without outputs"
            )
        candidate_steps[name].update(
            {
                "inputs": reviewed["inputs"],
                "outputs": reviewed["outputs"],
                "timeout_seconds": reviewed["timeout_seconds"],
                "cache": reviewed["cache"],
            }
        )

    validate_candidate(case_dir, candidate)
    return candidate


def validate_candidate(case_dir: Path, candidate: dict) -> dict:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".json", delete=False
        ) as stream:
            json.dump(candidate, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            temporary = Path(stream.name)
        return load_manifest(case_dir, temporary)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def protected_candidate_paths(normalized: dict) -> set[Path]:
    protected = set(normalized["artifacts"].values())
    if normalized["compliance"] is not None:
        protected.add(normalized["compliance"])
    for step in normalized["steps"]:
        protected.add(step["script"])
        protected.update(step.get("inputs", []))
        protected.update(step.get("outputs", []))
        if step["type"] == "matlab":
            protected.update(step.get("dependencies", []))
            if step.get("test") is not None:
                protected.add(step["test"])
            protected.add(step["evidence"])
    return protected


def validate_migration_output_ownership(
    case_dir: Path, normalized: dict, protected_records: set[Path]
) -> None:
    protected = set(protected_records)
    for step in normalized["steps"]:
        protected.add(step["script"])
        if step["type"] == "matlab":
            protected.update(step.get("dependencies", []))
            if step.get("test") is not None:
                protected.add(step["test"])
            protected.add(step["evidence"])
    for step in normalized["steps"]:
        for output in step.get("outputs", []):
            if output in protected:
                raise ValueError(
                    f"step {step['name']} output would overwrite migration evidence or source code: "
                    f"{output.relative_to(case_dir)}"
                )


def new_json_path(case_dir: Path, value: Path, label: str) -> Path:
    path = resolve_path_inside(case_dir, value, label)
    if path.suffix.casefold() != ".json":
        raise ValueError(f"{label} must end in .json")
    if path.exists():
        raise ValueError(f"{label} already exists; refusing to overwrite: {path}")
    return path


def write_new_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            temporary = Path(stream.name)
        os.link(temporary, path)
    except FileExistsError as exc:
        raise ValueError(f"output already exists; refusing to overwrite: {path}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def run(
    case_dir: Path,
    manifest_path: Path,
    mode: str,
    template_value: Path | None,
    review_value: Path | None,
    output_value: Path | None,
) -> dict:
    report = base_report(case_dir, manifest_path, mode)
    entries = []
    source_hash = None
    try:
        source_hash = sha256_file(manifest_path)
        report["source_manifest_sha256"] = source_hash
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
                "The manifest already uses workflow schema version 2; no review or export is needed."
            )
        else:
            template = review_template(case_dir, manifest_path, analysis)
            report["base_candidate_sha256"] = template["base_candidate_sha256"]
            report["review_template"] = template
            normalized_base = validate_candidate(case_dir, analysis["candidate_manifest"])
            if mode == "preview":
                report["status"] = "preview_ready"
            elif mode == "write_review_template":
                target = new_json_path(case_dir, template_value, "review template output")
                if target == manifest_path or target in protected_candidate_paths(normalized_base):
                    raise ValueError(
                        "review template output must be distinct from the source manifest, scripts, dependencies, outputs, evidence, compliance, and artifacts"
                    )
                write_new_json(target, template)
                report["files_written"] = [str(target)]
                report["output_path"] = str(target)
                report["status"] = "template_written"
            else:
                review_path = resolve_path_inside(case_dir, review_value, "migration review")
                if review_path == manifest_path:
                    raise ValueError("migration review must be distinct from the source manifest")
                review = load_review(review_path)
                candidate = validate_review(case_dir, manifest_path, analysis, template, review)
                normalized = validate_candidate(case_dir, candidate)
                validate_migration_output_ownership(
                    case_dir, normalized, {manifest_path, review_path}
                )
                report["review_complete"] = True
                report["candidate_manifest"] = candidate
                report["final_candidate_sha256"] = candidate_digest(candidate)
                if mode == "validate_review":
                    report["status"] = "review_validated"
                else:
                    target = new_json_path(case_dir, output_value, "candidate output")
                    if target in {manifest_path, review_path} or target in protected_candidate_paths(normalized):
                        raise ValueError(
                            "candidate output must be distinct from the source manifest, review, scripts, dependencies, inputs, outputs, evidence, compliance, and artifacts"
                        )
                    write_new_json(target, candidate)
                    report["files_written"] = [str(target)]
                    report["output_path"] = str(target)
                    report["status"] = "candidate_written"
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        report["status"] = "failed"
        report["errors"].append(str(exc))
        entries.append(
            diagnostic(
                "error",
                "migration_review_failed",
                "workflow_migration_review",
                str(exc),
                remediation=[
                    "Regenerate the review template, complete every confirmation, and retry with a new output path"
                ],
            )
        )
    finally:
        report["source_manifest_unchanged"] = bool(
            source_hash is not None
            and manifest_path.is_file()
            and sha256_file(manifest_path) == source_hash
        )
        if not report["source_manifest_unchanged"] and not report["errors"]:
            report["status"] = "failed"
            report["errors"].append("source manifest changed during migration review")
            entries.append(
                diagnostic(
                    "error",
                    "migration_source_changed",
                    "workflow_migration_review",
                    "source manifest changed during migration review",
                    remediation=["Discard the result and restart from a fresh analysis"],
                )
            )
    report = attach_diagnostics(report, entries)
    load_and_validate(report, RESULT_SCHEMA, "workflow migration review result")
    return report


def print_human(report: dict) -> None:
    print(f"status={report['status']}")
    print(f"review_complete={str(report['review_complete']).lower()}")
    print(f"source_manifest_unchanged={str(report['source_manifest_unchanged']).lower()}")
    if report["output_path"]:
        print(f"output={report['output_path']}")
    for error in report["errors"]:
        print(f"error: {error}")


def main() -> int:
    args = parse_args()
    case_dir = args.case_dir.expanduser().resolve()
    manifest_path = case_dir / "workflow.json"
    mode = mode_for(args)
    try:
        if not case_dir.is_dir():
            raise ValueError(f"case directory does not exist: {case_dir}")
        manifest_path = relative_manifest_path(case_dir, args.manifest)
        report = run(
            case_dir,
            manifest_path,
            mode,
            args.write_review_template,
            args.review,
            args.output,
        )
    except (OSError, ValueError) as exc:
        report = base_report(case_dir, manifest_path, mode)
        report["errors"] = [str(exc)]
        report = attach_diagnostics(
            report,
            [
                diagnostic(
                    "error",
                    "migration_review_failed",
                    "workflow_migration_review",
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
    return 0 if report["status"] != "failed" else 2


if __name__ == "__main__":
    raise SystemExit(main())

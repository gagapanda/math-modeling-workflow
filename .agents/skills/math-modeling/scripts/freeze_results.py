#!/usr/bin/env python
"""Prepare, finalize, and verify an F1 result-freeze manifest.

The tool records a supplied human decision; it never makes or signs that decision.
Accepted manifests are immutable evidence. A later frozen-scope change requires a new
freeze ID and an F1_THAW record in CURRENT-STATE.md rather than editing the old file.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path, PurePosixPath

sys.dont_write_bytecode = True

from _json_schema import load_and_validate
from _workflow_common import atomic_write_text, resolve_path_inside, sha256_file


SKILL_DIR = Path(__file__).resolve().parent.parent
PLAN_SCHEMA = SKILL_DIR / "schemas" / "result-freeze-plan.schema.json"
MANIFEST_SCHEMA = SKILL_DIR / "schemas" / "result-freeze-manifest.schema.json"
PLACEHOLDERS = ("TODO", "REPLACE", "UNSET", "PLACEHOLDER")
AI_REVIEWER_NAMES = {"codex", "ai", "assistant"}
ACCEPTED = {"F1_ACCEPTED", "F1_ACCEPTED_WITH_LIMITATIONS"}
DECISION_TO_STATUS = {
    "accepted": "F1_ACCEPTED",
    "accepted_with_limitations": "F1_ACCEPTED_WITH_LIMITATIONS",
    "rejected": "F1_REJECTED",
}


def timestamp_value(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset")
    return parsed


def parse_timestamp(value: str, label: str) -> str:
    timestamp_value(value, label)
    return value


def load_json(path: Path, label: str) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def relative_path(case_dir: Path, path: Path) -> str:
    return path.resolve().relative_to(case_dir.resolve()).as_posix()


def reject_symlink_components(case_dir: Path, raw: PurePosixPath, label: str) -> None:
    current = case_dir
    for part in raw.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{label} must not be a symlink or traverse one: {raw.as_posix()}")


def resolve_regular_file(case_dir: Path, value: str, label: str) -> Path:
    raw = PurePosixPath(value)
    if raw.is_absolute() or ".." in raw.parts:
        raise ValueError(f"{label} must be a case-relative path without '..': {value}")
    reject_symlink_components(case_dir, raw, label)
    path = resolve_path_inside(case_dir, Path(*raw.parts), label)
    if not path.is_file():
        raise ValueError(f"{label} is not a regular file: {value}")
    return path


def output_path(case_dir: Path, value: str, label: str) -> Path:
    raw = PurePosixPath(value)
    if raw.is_absolute() or ".." in raw.parts:
        raise ValueError(f"{label} must be a case-relative path without '..': {value}")
    reject_symlink_components(case_dir, raw.parent, label)
    path = resolve_path_inside(case_dir, Path(*raw.parts), label)
    if path.exists():
        raise FileExistsError(f"{label} already exists; use a new freeze ID/path: {path}")
    if path.parent.exists() and not path.parent.is_dir():
        raise ValueError(f"{label} parent is not a directory: {path.parent}")
    return path


def file_binding(case_dir: Path, path: Path, kind: str) -> dict:
    return {
        "path": relative_path(case_dir, path),
        "kind": kind,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def validate_plan_semantics(case_dir: Path, plan: dict, output: Path) -> tuple[list[dict], Path]:
    freeze_id = plan["freeze_id"].strip()
    if not freeze_id or any(token in freeze_id.upper() for token in PLACEHOLDERS):
        raise ValueError("freeze_id must be a real versioned identifier, not a placeholder")
    paths = [entry["path"] for entry in plan["files"]]
    if not paths:
        raise ValueError("freeze plan must declare at least one frozen file")
    if len(paths) != len(set(paths)):
        raise ValueError("freeze plan contains duplicate file paths")
    register_value = plan["result_register"]
    matching = [entry for entry in plan["files"] if entry["path"] == register_value]
    if len(matching) != 1 or matching[0]["kind"] != "result-register":
        raise ValueError("result_register must appear exactly once with kind=result-register")
    replay = plan["replay_evidence"]
    if len(replay) < 2 or len(replay) != len(set(replay)):
        raise ValueError("F1 requires at least two distinct replay evidence files")
    kinds = {entry["path"]: entry["kind"] for entry in plan["files"]}
    missing_replay = [value for value in replay if kinds.get(value) != "replay"]
    if missing_replay:
        raise ValueError(
            "every replay_evidence path must be declared with kind=replay: "
            + ", ".join(missing_replay)
        )
    bound = []
    for index, entry in enumerate(plan["files"]):
        path = resolve_regular_file(case_dir, entry["path"], f"files[{index}].path")
        if path.resolve() == output.resolve():
            raise ValueError("freeze output must not be included in its own frozen file set")
        bound.append(file_binding(case_dir, path, entry["kind"]))
    register = resolve_regular_file(case_dir, register_value, "result_register")
    return bound, register


def prepare(case_dir: Path, plan_value: str, output_value: str, generated_at: str) -> dict:
    case_dir = case_dir.resolve()
    plan_path = resolve_regular_file(case_dir, plan_value, "freeze plan")
    output = output_path(case_dir, output_value, "freeze candidate output")
    plan = load_json(plan_path, "freeze plan")
    load_and_validate(plan, PLAN_SCHEMA, "result freeze plan")
    files, register = validate_plan_semantics(case_dir, plan, output)
    manifest = {
        "schema_version": 1,
        "freeze_id": plan["freeze_id"],
        "status": "F1_PENDING_HUMAN",
        "paper_authoritative": False,
        "generated_at": parse_timestamp(generated_at, "generated_at"),
        "source_plan": {"path": relative_path(case_dir, plan_path), "sha256": sha256_file(plan_path)},
        "source_candidate": {"path": "", "sha256": ""},
        "result_register": {"path": relative_path(case_dir, register), "sha256": sha256_file(register)},
        "replay_evidence": list(plan["replay_evidence"]),
        "limitations": list(plan["limitations"]),
        "unresolved": list(plan["unresolved"]),
        "files": files,
        "human_decision": {
            "decision": "not_reviewed",
            "reviewer": "",
            "review_start": "",
            "review_end": "",
            "signed_at": "",
            "objections": "",
            "resolution": "",
            "confirmation": "NOT_CONFIRMED",
        },
    }
    load_and_validate(manifest, MANIFEST_SCHEMA, "result freeze candidate")
    atomic_write_text(output, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def verify_payload(case_dir: Path, manifest: dict, manifest_path: Path | None = None) -> dict:
    load_and_validate(manifest, MANIFEST_SCHEMA, "result freeze manifest")
    errors: list[str] = []
    parsed_generated_at: datetime | None = None
    try:
        parsed_generated_at = timestamp_value(manifest["generated_at"], "generated_at")
    except ValueError as exc:
        errors.append(str(exc))

    source_plan = manifest["source_plan"]
    try:
        source_plan_path = resolve_regular_file(case_dir, source_plan["path"], "source_plan.path")
        if sha256_file(source_plan_path) != source_plan["sha256"]:
            errors.append("source plan SHA-256 mismatch")
    except ValueError as exc:
        errors.append(str(exc))

    seen: set[str] = set()
    for entry in manifest["files"]:
        value = entry["path"]
        if value in seen:
            errors.append(f"duplicate frozen path: {value}")
            continue
        seen.add(value)
        try:
            path = resolve_regular_file(case_dir, value, f"frozen file {value}")
            if path.stat().st_size != entry["bytes"]:
                errors.append(f"size mismatch: {value}")
            if sha256_file(path) != entry["sha256"]:
                errors.append(f"SHA-256 mismatch: {value}")
        except ValueError as exc:
            errors.append(str(exc))
    register_entries = [
        entry for entry in manifest["files"]
        if entry["path"] == manifest["result_register"]["path"] and entry["kind"] == "result-register"
    ]
    if len(register_entries) != 1:
        errors.append("result_register is not bound exactly once as kind=result-register")
    elif register_entries[0]["sha256"] != manifest["result_register"]["sha256"]:
        errors.append("result_register binding disagrees with files entry")
    replay_set = set(manifest["replay_evidence"])
    replay_files = {entry["path"] for entry in manifest["files"] if entry["kind"] == "replay"}
    if len(replay_set) < 2 or not replay_set.issubset(replay_files):
        errors.append("at least two replay_evidence paths must be hash-bound with kind=replay")

    status = manifest["status"]
    decision = manifest["human_decision"]
    expected_decision = {
        "F1_PENDING_HUMAN": "not_reviewed",
        "F1_ACCEPTED": "accepted",
        "F1_ACCEPTED_WITH_LIMITATIONS": "accepted_with_limitations",
        "F1_REJECTED": "rejected",
    }[status]
    if decision["decision"] != expected_decision:
        errors.append("status and human_decision.decision disagree")
    should_authorize = status in ACCEPTED
    if manifest["paper_authoritative"] != should_authorize:
        errors.append("paper_authoritative disagrees with F1 status")

    if status == "F1_PENDING_HUMAN":
        if any(decision[key] for key in ("reviewer", "review_start", "review_end", "signed_at")):
            errors.append("pending candidate must not contain a completed human signature")
        if decision["confirmation"] != "NOT_CONFIRMED":
            errors.append("pending candidate cannot confirm human review")
        if manifest["source_candidate"] != {"path": "", "sha256": ""}:
            errors.append("pending candidate must have an empty source_candidate binding")
    else:
        reviewer = decision["reviewer"].strip()
        if not reviewer:
            errors.append("final F1 decision is missing human_decision.reviewer")
        elif reviewer.lower() in AI_REVIEWER_NAMES:
            errors.append("human_decision.reviewer must identify the actual human operator, not AI/Codex")

        parsed_human_times: dict[str, datetime] = {}
        for key in ("review_start", "review_end", "signed_at"):
            if not decision[key].strip():
                errors.append(f"final F1 decision is missing human_decision.{key}")
                continue
            try:
                parsed_human_times[key] = timestamp_value(
                    decision[key], f"human_decision.{key}"
                )
            except ValueError as exc:
                errors.append(str(exc))
        if all(key in parsed_human_times for key in ("review_start", "review_end", "signed_at")):
            if not (
                parsed_human_times["review_start"]
                <= parsed_human_times["review_end"]
                <= parsed_human_times["signed_at"]
            ):
                errors.append("human review timestamps must satisfy review_start <= review_end <= signed_at")
            if parsed_generated_at is not None and parsed_human_times["signed_at"] > parsed_generated_at:
                errors.append("final manifest generated_at must be at or after human_decision.signed_at")
        if decision["confirmation"] != "I_REVIEWED_THE_LISTED_EVIDENCE":
            errors.append("final F1 decision lacks explicit human-review confirmation")

        candidate = manifest["source_candidate"]
        try:
            candidate_path = resolve_regular_file(case_dir, candidate["path"], "source_candidate.path")
            if sha256_file(candidate_path) != candidate["sha256"]:
                errors.append("source candidate SHA-256 mismatch")
            candidate_payload = load_json(candidate_path, "source candidate")
            if candidate_payload.get("status") != "F1_PENDING_HUMAN":
                errors.append("source candidate must have status F1_PENDING_HUMAN")
            else:
                candidate_report = verify_payload(case_dir, candidate_payload, candidate_path)
                if not candidate_report["passed"]:
                    errors.extend(
                        f"source candidate invalid: {error}"
                        for error in candidate_report["errors"]
                    )
                for key in (
                    "freeze_id",
                    "source_plan",
                    "result_register",
                    "replay_evidence",
                    "limitations",
                    "unresolved",
                    "files",
                ):
                    if manifest[key] != candidate_payload[key]:
                        errors.append(f"final manifest changed candidate-bound field: {key}")
                if "review_start" in parsed_human_times:
                    try:
                        candidate_generated_at = timestamp_value(
                            candidate_payload["generated_at"], "source candidate generated_at"
                        )
                        if candidate_generated_at > parsed_human_times["review_start"]:
                            errors.append("human review_start must be at or after source candidate generation")
                    except ValueError as exc:
                        errors.append(str(exc))
        except ValueError as exc:
            errors.append(str(exc))

    if status == "F1_ACCEPTED" and manifest["unresolved"]:
        errors.append("F1_ACCEPTED requires unresolved=[]; use accepted-with-limitations or reject")
    if status == "F1_ACCEPTED_WITH_LIMITATIONS" and not manifest["limitations"]:
        errors.append("F1_ACCEPTED_WITH_LIMITATIONS requires at least one limitation")
    return {
        "schema_version": 1,
        "manifest": relative_path(case_dir, manifest_path) if manifest_path else "",
        "freeze_id": manifest["freeze_id"],
        "status": status,
        "passed": not errors,
        "paper_authoritative": should_authorize and not errors,
        "errors": errors,
    }


def finalize(case_dir: Path, candidate_value: str, output_value: str, args: argparse.Namespace) -> dict:
    case_dir = case_dir.resolve()
    candidate_path = resolve_regular_file(case_dir, candidate_value, "freeze candidate")
    output = output_path(case_dir, output_value, "freeze manifest output")
    candidate = load_json(candidate_path, "freeze candidate")
    candidate_report = verify_payload(case_dir, candidate, candidate_path)
    if not candidate_report["passed"] or candidate["status"] != "F1_PENDING_HUMAN":
        raise ValueError("candidate does not pass pending-state verification: " + "; ".join(candidate_report["errors"]))
    if not args.confirm_human_reviewed:
        raise ValueError("finalization requires --confirm-human-reviewed after the real human review")
    reviewer = args.reviewer.strip()
    if not reviewer or reviewer.lower() in AI_REVIEWER_NAMES:
        raise ValueError("reviewer must identify the actual responsible human operator, not AI/Codex")
    review_start = timestamp_value(args.review_start, "review_start")
    review_end = timestamp_value(args.review_end, "review_end")
    signed_at = timestamp_value(args.signed_at, "signed_at")
    generated_at = timestamp_value(args.generated_at, "generated_at")
    if not (review_start <= review_end <= signed_at <= generated_at):
        raise ValueError(
            "timestamps must satisfy review_start <= review_end <= signed_at <= generated_at"
        )
    candidate_generated_at = timestamp_value(candidate["generated_at"], "candidate.generated_at")
    if candidate_generated_at > review_start:
        raise ValueError("review_start must be at or after candidate.generated_at")
    status = DECISION_TO_STATUS[args.decision]
    final = json.loads(json.dumps(candidate))
    final["status"] = status
    final["paper_authoritative"] = status in ACCEPTED
    final["generated_at"] = args.generated_at
    final["source_candidate"] = {
        "path": relative_path(case_dir, candidate_path),
        "sha256": sha256_file(candidate_path),
    }
    final["human_decision"] = {
        "decision": args.decision,
        "reviewer": reviewer,
        "review_start": args.review_start,
        "review_end": args.review_end,
        "signed_at": args.signed_at,
        "objections": args.objections,
        "resolution": args.resolution,
        "confirmation": "I_REVIEWED_THE_LISTED_EVIDENCE",
    }
    report = verify_payload(case_dir, final)
    if not report["passed"]:
        raise ValueError("final manifest semantics failed: " + "; ".join(report["errors"]))
    atomic_write_text(output, json.dumps(final, ensure_ascii=False, indent=2) + "\n")
    return final


def verify(case_dir: Path, manifest_value: str) -> dict:
    case_dir = case_dir.resolve()
    path = resolve_regular_file(case_dir, manifest_value, "freeze manifest")
    manifest = load_json(path, "freeze manifest")
    return verify_payload(case_dir, manifest, path)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare", help="Create a hash-bound F1_PENDING_HUMAN candidate")
    prepare_parser.add_argument("--case-dir", type=Path, required=True)
    prepare_parser.add_argument("--plan", required=True)
    prepare_parser.add_argument("--output", required=True)
    prepare_parser.add_argument("--generated-at", required=True)
    finalize_parser = sub.add_parser("finalize", help="Record an actual human F1 decision in a new immutable manifest")
    finalize_parser.add_argument("--case-dir", type=Path, required=True)
    finalize_parser.add_argument("--candidate", required=True)
    finalize_parser.add_argument("--output", required=True)
    finalize_parser.add_argument("--decision", choices=sorted(DECISION_TO_STATUS), required=True)
    finalize_parser.add_argument("--reviewer", required=True)
    finalize_parser.add_argument("--review-start", required=True)
    finalize_parser.add_argument("--review-end", required=True)
    finalize_parser.add_argument("--signed-at", required=True)
    finalize_parser.add_argument("--generated-at", required=True)
    finalize_parser.add_argument("--objections", default="NONE")
    finalize_parser.add_argument("--resolution", default="NONE")
    finalize_parser.add_argument("--confirm-human-reviewed", action="store_true")
    verify_parser = sub.add_parser("verify", help="Recheck schema, semantics, candidate binding, and all frozen hashes")
    verify_parser.add_argument("--case-dir", type=Path, required=True)
    verify_parser.add_argument("--manifest", required=True)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "prepare":
            payload = prepare(args.case_dir, args.plan, args.output, args.generated_at)
            report = {"passed": True, "status": payload["status"], "freeze_id": payload["freeze_id"], "paper_authoritative": False}
        elif args.command == "finalize":
            payload = finalize(args.case_dir, args.candidate, args.output, args)
            report = {"passed": True, "status": payload["status"], "freeze_id": payload["freeze_id"], "paper_authoritative": payload["paper_authoritative"]}
        else:
            report = verify(args.case_dir, args.manifest)
    except (OSError, ValueError) as exc:
        report = {"passed": False, "errors": [str(exc)]}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())


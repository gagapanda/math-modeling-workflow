#!/usr/bin/env python
"""Bind the local M7 delivery candidate to the real-human F2 upload receipt.

M7 precheck and review remain local delivery gates. Only a verified accepted M7
manifest, an unchanged selected package, an actual official upload, a non-empty
receipt, and explicit human confirmation can create F2_COMPLETE.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True

from _json_schema import load_and_validate
from _workflow_common import atomic_write_text, resolve_inside, resolve_path_inside, sha256_file


SKILL_DIR = Path(__file__).resolve().parent.parent
PLAN_SCHEMA = SKILL_DIR / "schemas" / "m7-f2-plan.schema.json"
PRECHECK_SCHEMA = SKILL_DIR / "schemas" / "m7-precheck-report.schema.json"
M7_SCHEMA = SKILL_DIR / "schemas" / "m7-review-manifest.schema.json"
F2_SCHEMA = SKILL_DIR / "schemas" / "f2-submission-manifest.schema.json"
PACKAGE_SCHEMA = SKILL_DIR / "schemas" / "submission-package-report.schema.json"
FINALIZATION_SCHEMA = SKILL_DIR / "schemas" / "finalization-report.schema.json"
SMOKE_SCHEMA = SKILL_DIR / "schemas" / "support-smoke-report.schema.json"
PLACEHOLDER = re.compile(r"(?:\b(?:todo|tbd|placeholder|pending|undecided|unset|replace)\b|no entries yet)", re.I)
AI_OPERATOR = re.compile(r"(?:^|[^a-z0-9])(?:codex|chatgpt|openai|claude|gemini|copilot|assistant|artificial intelligence|large language model|llm|ai)(?:$|[^a-z0-9])", re.I)
M7_ACCEPTED = {"M7_ACCEPTED", "M7_ACCEPTED_WITH_LIMITATIONS"}
DECISION_TO_STATUS = {
    "accepted": "M7_ACCEPTED",
    "accepted_with_limitations": "M7_ACCEPTED_WITH_LIMITATIONS",
    "rejected": "M7_REJECTED",
}
TECHNICAL_SCOPE = [
    "selected_package_integrity",
    "bound_finalization_ready_for_submission",
    "packaged_paper_source_equality",
    "support_package_smoke_replay",
    "official_upload_plan_sanity",
]


def read_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def timestamp(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset")
    return parsed


def substantive(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and not PLACEHOLDER.search(value)


def human_name(value: str, label: str) -> str:
    cleaned = value.strip()
    if not cleaned or AI_OPERATOR.search(cleaned):
        raise ValueError(f"{label} must identify the responsible human, not Codex/AI")
    return cleaned


def relative(case_dir: Path, path: Path) -> str:
    return path.resolve().relative_to(case_dir.resolve()).as_posix()


def resolve_regular(case_dir: Path, value: str | Path, label: str, *, nonempty: bool = False) -> Path:
    path = resolve_path_inside(case_dir, Path(value), label) if isinstance(value, Path) else (
        resolve_path_inside(case_dir, Path(value), label) if Path(value).is_absolute() else resolve_inside(case_dir, value, label)
    )
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} must be a regular non-symlink file: {value}")
    if nonempty and path.stat().st_size <= 0:
        raise ValueError(f"{label} must be non-empty: {value}")
    return path


def resolve_new(case_dir: Path, value: str | Path, label: str) -> Path:
    path = resolve_path_inside(case_dir, Path(value), label)
    if path.suffix.casefold() != ".json":
        raise ValueError(f"{label} must use a .json path")
    if path.exists():
        raise ValueError(f"{label} already exists and is immutable: {path}")
    return path


def binding(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": sha256_file(path)}


def check_binding(case_dir: Path, item: object, label: str) -> Path:
    if not isinstance(item, dict):
        raise ValueError(f"{label} binding must be an object")
    path = resolve_regular(case_dir, str(item.get("path", "")), label)
    expected = item.get("sha256")
    if not isinstance(expected, str) or sha256_file(path) != expected:
        raise ValueError(f"{label} SHA-256 mismatch")
    return path


def same_evidence(first: object, second: object) -> bool:
    return isinstance(first, dict) and isinstance(second, dict) and first == second


def load_plan(case_dir: Path, plan_value: str | Path) -> tuple[Path, dict, dict[str, Path]]:
    case_dir = case_dir.expanduser().resolve()
    if not case_dir.is_dir():
        raise ValueError(f"case directory does not exist: {case_dir}")
    plan_path = resolve_regular(case_dir, plan_value, "M7/F2 plan")
    plan = read_json(plan_path, "M7/F2 plan")
    load_and_validate(plan, PLAN_SCHEMA, "M7/F2 plan")
    if not substantive(plan["official_upload"]["competition"]):
        raise ValueError("official upload competition remains a placeholder")
    if not substantive(plan["official_upload"]["platform"]):
        raise ValueError("official upload platform remains a placeholder")
    if any(not substantive(name) for name in plan["required_smoke_tests"]):
        raise ValueError("required_smoke_tests must be substantive and placeholder-free")
    suffixes = [item.casefold() for item in plan["official_upload"]["allowed_receipt_suffixes"]]
    if len(suffixes) != len(set(suffixes)):
        raise ValueError("allowed receipt suffixes must be unique case-insensitively")
    receipt = resolve_inside(case_dir, plan["official_upload"]["receipt"], "official receipt")
    if receipt.suffix.casefold() not in suffixes:
        raise ValueError("official receipt suffix is not allowlisted by the plan")
    m7_path = resolve_inside(case_dir, plan["human_gate"]["m7_manifest"], "M7 manifest")
    f2_path = resolve_inside(case_dir, plan["human_gate"]["f2_manifest"], "F2 manifest")
    if m7_path.suffix.casefold() != ".json" or f2_path.suffix.casefold() != ".json":
        raise ValueError("M7 and F2 manifest paths must end with .json")
    if m7_path == f2_path:
        raise ValueError("M7 and F2 manifest paths must be different")
    return plan_path, plan, {"receipt": receipt, "m7": m7_path, "f2": f2_path}


def precheck(case_dir: Path, plan_value: str | Path) -> dict:
    case_dir = case_dir.expanduser().resolve()
    plan_path, plan, planned = load_plan(case_dir, plan_value)
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "m7_precheck_only",
        "m7_precheck_passed": False,
        "official_submission_status": "NOT_FORMAL_F2",
        "paths": {"plan": str(plan_path)},
        "checks": {},
        "package": {},
        "support_smoke": {},
        "evidence_sha256": {},
        "errors": [],
    }
    evidence: dict[str, Path] = {"m7_f2_plan": plan_path}

    def add(name: str, passed: bool, detail: str) -> None:
        report["checks"][name] = bool(passed)
        if not passed:
            report["errors"].append(detail)

    package_report_path = resolve_regular(case_dir, plan["package_report"], "submission package report")
    evidence["submission_package_report"] = package_report_path
    package = read_json(package_report_path, "submission package report")
    load_and_validate(package, PACKAGE_SCHEMA, "submission package report")
    report["paths"]["package_report"] = str(package_report_path)
    add("package_report_passed", package.get("packaged") is True and not package.get("errors"), "submission package report is not a clean packaged=true report")
    add("package_case_matches", Path(package["case_dir"]).resolve() == case_dir, "submission package report belongs to a different case")

    bound_paths: dict[str, Path] = {}
    for name in ("plan", "finalization_report", "source_paper"):
        try:
            bound_paths[name] = check_binding(case_dir, package["bindings"][name], f"package {name}")
            add(f"package_binding_{name}", True, "")
            evidence[f"package_{name}"] = bound_paths[name]
        except ValueError as exc:
            add(f"package_binding_{name}", False, str(exc))
    finalization = None
    if "finalization_report" in bound_paths:
        finalization = read_json(bound_paths["finalization_report"], "finalization report")
        load_and_validate(finalization, FINALIZATION_SCHEMA, "finalization report")
        add("finalization_ready_for_submission", finalization.get("ready_for_submission") is True, "bound finalization report is not ready_for_submission=true")
        add("finalization_case_matches", Path(finalization["case_dir"]).resolve() == case_dir, "bound finalization report belongs to a different case")

    outputs: dict[str, Path] = {}
    for name in ("paper", "support"):
        try:
            item = package["outputs"][name]
            path = resolve_regular(case_dir, item["path"], f"packaged {name}", nonempty=True)
            outputs[name] = path
            evidence[f"packaged_{name}"] = path
            add(f"packaged_{name}_hash", sha256_file(path) == item["sha256"], f"packaged {name} SHA-256 mismatch")
            add(f"packaged_{name}_size", path.stat().st_size == item["size_bytes"] and item["size_bytes"] <= item["max_bytes"], f"packaged {name} size binding or limit failed")
        except (KeyError, TypeError, ValueError) as exc:
            add(f"packaged_{name}_binding", False, str(exc))
    if "paper" in outputs and "source_paper" in bound_paths:
        add("packaged_paper_equals_source", sha256_file(outputs["paper"]) == sha256_file(bound_paths["source_paper"]), "packaged PDF differs from the finalized source paper")

    smoke_path = resolve_regular(case_dir, plan["support_smoke_report"], "support smoke report")
    evidence["support_smoke_report"] = smoke_path
    smoke = read_json(smoke_path, "support smoke report")
    load_and_validate(smoke, SMOKE_SCHEMA, "support smoke report")
    report["paths"]["support_smoke_report"] = str(smoke_path)
    add("support_smoke_passed", smoke.get("passed") is True and not smoke.get("errors"), "support smoke report is not a clean passed=true report")
    if "support" in outputs:
        add("support_smoke_package_path", Path(smoke["package"]).resolve() == outputs["support"], "support smoke report does not name the selected support ZIP")
        add("support_smoke_package_hash", smoke.get("package_sha256") == sha256_file(outputs["support"]), "support smoke report package SHA-256 differs from selected support ZIP")
        add("support_smoke_package_size", smoke.get("package_bytes") == outputs["support"].stat().st_size, "support smoke report package size differs from selected support ZIP")
    try:
        smoke_plan = resolve_regular(case_dir, smoke["plan"], "support smoke plan")
        evidence["support_smoke_plan"] = smoke_plan
        add("support_smoke_plan_present", True, "")
    except ValueError as exc:
        add("support_smoke_plan_present", False, str(exc))

    tests = smoke.get("tests", [])
    names = [item.get("name") for item in tests if isinstance(item, dict)]
    add("smoke_test_names_unique", len(names) == len(set(names)), "support smoke report contains duplicate test names")
    indexed = {item.get("name"): item for item in tests if isinstance(item, dict)}
    for required in plan["required_smoke_tests"]:
        item = indexed.get(required)
        passed = bool(item) and item.get("exit_code") == 0 and item.get("timed_out") is False and item.get("missing_outputs") == [] and item.get("errors") == []
        add(f"required_smoke_test:{required}", passed, f"required support smoke test did not pass cleanly: {required}")

    add("manifest_paths_distinct", planned["m7"] != planned["f2"], "M7 and F2 manifest paths collide")
    report["package"] = {
        "report": str(package_report_path),
        "generated_at": package.get("generated_at"),
        "paper": package.get("outputs", {}).get("paper", {}),
        "support": package.get("outputs", {}).get("support", {}),
        "finalization_ready_for_submission": bool(finalization and finalization.get("ready_for_submission")),
    }
    report["support_smoke"] = {
        "report": str(smoke_path),
        "generated_at": smoke.get("generated_at"),
        "passed": smoke.get("passed"),
        "required_tests": list(plan["required_smoke_tests"]),
    }
    report["evidence_sha256"] = {name: binding(path) for name, path in evidence.items()}
    report["m7_precheck_passed"] = not report["errors"] and all(report["checks"].values())
    load_and_validate(report, PRECHECK_SCHEMA, "M7 precheck report")
    return report


def pending_manifest(case_dir: Path, plan_path: Path, report: dict, generated_at: str, review_id: str) -> dict:
    timestamp(generated_at, "generated_at")
    if not substantive(review_id):
        raise ValueError("review_id must be substantive")
    return {
        "schema_version": 1,
        "review_id": review_id.strip(),
        "status": "M7_PENDING_HUMAN",
        "m7_approved": False,
        "official_submission_status": "NOT_FORMAL_F2",
        "generated_at": generated_at,
        "source_plan": {"path": relative(case_dir, plan_path), "sha256": sha256_file(plan_path)},
        "source_candidate": {"path": "", "sha256": ""},
        "evidence_sha256": report["evidence_sha256"],
        "technical_scope": TECHNICAL_SCOPE,
        "human_decision": {
            "decision": "not_reviewed", "reviewer": "", "review_mode": "not_reviewed",
            "review_start": "", "review_end": "", "signed_at": "", "objections": "",
            "resolution": "", "confirmation": "NOT_CONFIRMED",
        },
    }


def prepare_m7(case_dir: Path, plan_value: str | Path, output_value: str | Path, generated_at: str, review_id: str) -> dict:
    case_dir = case_dir.expanduser().resolve()
    plan_path, plan, planned = load_plan(case_dir, plan_value)
    output = resolve_new(case_dir, output_value, "M7 candidate")
    if output == planned["m7"]:
        raise ValueError("M7 candidate path must differ from the immutable final M7 manifest path")
    report = precheck(case_dir, plan_path)
    if not report["m7_precheck_passed"]:
        raise ValueError("M7 precheck failed: " + "; ".join(report["errors"]))
    payload = pending_manifest(case_dir, plan_path, report, generated_at, review_id)
    load_and_validate(payload, M7_SCHEMA, "M7 candidate manifest")
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return payload


def load_m7(case_dir: Path, manifest_value: str | Path) -> tuple[Path, dict, Path, dict, dict[str, Path]]:
    manifest_path = resolve_regular(case_dir, manifest_value, "M7 manifest")
    payload = read_json(manifest_path, "M7 manifest")
    load_and_validate(payload, M7_SCHEMA, "M7 manifest")
    plan_path = resolve_regular(case_dir, payload["source_plan"]["path"], "M7 source plan")
    if sha256_file(plan_path) != payload["source_plan"]["sha256"]:
        raise ValueError("M7 source plan SHA-256 mismatch")
    current_plan, plan, planned = load_plan(case_dir, plan_path)
    return manifest_path, payload, current_plan, plan, planned


def finalize_m7(case_dir: Path, candidate_value: str | Path, output_value: str | Path, args: argparse.Namespace) -> dict:
    case_dir = case_dir.expanduser().resolve()
    if not args.confirm_human_reviewed:
        raise ValueError("finalize-m7 requires --confirm-human-reviewed from the responsible human")
    candidate, source, plan_path, plan, planned = load_m7(case_dir, candidate_value)
    if source["status"] != "M7_PENDING_HUMAN" or source["human_decision"]["decision"] != "not_reviewed":
        raise ValueError("M7 candidate is not M7_PENDING_HUMAN")
    output = resolve_new(case_dir, output_value, "final M7 manifest")
    if output != planned["m7"]:
        raise ValueError("final M7 output must equal the plan-selected m7_manifest path")
    reviewer = human_name(args.reviewer, "M7 reviewer")
    start = timestamp(args.review_start, "review_start")
    end = timestamp(args.review_end, "review_end")
    signed = timestamp(args.signed_at, "signed_at")
    generated = timestamp(args.generated_at, "generated_at")
    if not start <= end <= signed <= generated:
        raise ValueError("timestamps must satisfy review_start <= review_end <= signed_at <= generated_at")
    if timestamp(source["generated_at"], "candidate.generated_at") > start:
        raise ValueError("review_start must be at or after candidate.generated_at")
    if args.decision == "accepted_with_limitations" and (not substantive(args.objections) or not substantive(args.resolution) or args.objections.strip().casefold() == "none" or args.resolution.strip().casefold() == "none"):
        raise ValueError("accepted_with_limitations requires substantive objections and resolution")
    if args.decision == "rejected" and not substantive(args.objections):
        raise ValueError("rejected M7 requires a substantive objection")
    current = precheck(case_dir, plan_path)
    if not current["m7_precheck_passed"]:
        raise ValueError("M7 evidence no longer passes precheck")
    if not same_evidence(source["evidence_sha256"], current["evidence_sha256"]):
        raise ValueError("M7 technical evidence changed during human review")
    status = DECISION_TO_STATUS[args.decision]
    payload = json.loads(json.dumps(source))
    payload.update({
        "status": status,
        "m7_approved": status in M7_ACCEPTED,
        "generated_at": args.generated_at,
        "source_candidate": {"path": relative(case_dir, candidate), "sha256": sha256_file(candidate)},
    })
    payload["human_decision"] = {
        "decision": args.decision, "reviewer": reviewer, "review_mode": "single_operator_review",
        "review_start": args.review_start, "review_end": args.review_end, "signed_at": args.signed_at,
        "objections": args.objections, "resolution": args.resolution,
        "confirmation": "I_REVIEWED_THE_M7_DELIVERY_CANDIDATE",
    }
    load_and_validate(payload, M7_SCHEMA, "final M7 manifest")
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return payload


def verify_m7(case_dir: Path, manifest_value: str | Path) -> dict:
    case_dir = case_dir.expanduser().resolve()
    manifest_path, payload, plan_path, plan, planned = load_m7(case_dir, manifest_value)
    errors: list[str] = []
    if manifest_path != planned["m7"]:
        errors.append("M7 manifest is not the plan-selected final manifest")
    if payload["status"] == "M7_PENDING_HUMAN":
        errors.append("M7 remains pending human review")
    approved = payload["status"] in M7_ACCEPTED and payload["m7_approved"] is True
    decision = payload["human_decision"]
    if payload["technical_scope"] != TECHNICAL_SCOPE:
        errors.append("M7 technical_scope differs from the required gate scope")
    if payload["status"] == "M7_PENDING_HUMAN":
        if payload["m7_approved"] or decision["decision"] != "not_reviewed":
            errors.append("pending M7 status/decision semantics are inconsistent")
    else:
        expected_status = DECISION_TO_STATUS.get(decision["decision"])
        if expected_status != payload["status"]:
            errors.append("M7 status does not match the recorded human decision")
        if payload["m7_approved"] is not (payload["status"] in M7_ACCEPTED):
            errors.append("M7 approval flag does not match status")
    if payload["status"] != "M7_PENDING_HUMAN":
        try:
            human_name(decision["reviewer"], "M7 reviewer")
            if decision["review_mode"] != "single_operator_review":
                errors.append("M7 review_mode must be single_operator_review")
            if decision["confirmation"] != "I_REVIEWED_THE_M7_DELIVERY_CANDIDATE":
                errors.append("M7 human confirmation is missing")
            start, end, signed, generated = (timestamp(decision["review_start"], "review_start"), timestamp(decision["review_end"], "review_end"), timestamp(decision["signed_at"], "signed_at"), timestamp(payload["generated_at"], "generated_at"))
            if not start <= end <= signed <= generated:
                errors.append("M7 timestamps are out of order")
            candidate = check_binding(case_dir, payload["source_candidate"], "M7 source candidate")
            candidate_payload = read_json(candidate, "M7 source candidate")
            load_and_validate(candidate_payload, M7_SCHEMA, "M7 source candidate")
            if candidate_payload["status"] != "M7_PENDING_HUMAN" or candidate_payload["human_decision"]["decision"] != "not_reviewed":
                errors.append("M7 source candidate is not the pending manifest finalized by this review")
            for field in ("review_id", "source_plan", "evidence_sha256", "technical_scope"):
                if payload[field] != candidate_payload[field]:
                    errors.append(f"M7 final manifest changed candidate-bound field: {field}")
            if timestamp(candidate_payload["generated_at"], "candidate.generated_at") > start:
                errors.append("M7 review began before candidate generation")
        except ValueError as exc:
            errors.append(str(exc))
    if payload["status"] == "M7_ACCEPTED_WITH_LIMITATIONS" and (not substantive(decision["objections"]) or not substantive(decision["resolution"]) or decision["objections"].strip().casefold() == "none" or decision["resolution"].strip().casefold() == "none"):
        errors.append("accepted_with_limitations lacks substantive objections or resolution")
    try:
        current = precheck(case_dir, plan_path)
        if not current["m7_precheck_passed"]:
            errors.extend(current["errors"])
        elif not same_evidence(payload["evidence_sha256"], current["evidence_sha256"]):
            errors.append("M7 evidence differs from the current selected package evidence")
    except ValueError as exc:
        errors.append(str(exc))
    return {
        "passed": not errors,
        "status": payload["status"],
        "m7_approved": approved,
        "official_submission_status": "NOT_FORMAL_F2",
        "manifest": str(manifest_path),
        "errors": errors,
    }


def record_f2(case_dir: Path, plan_value: str | Path, output_value: str | Path, args: argparse.Namespace) -> dict:
    case_dir = case_dir.expanduser().resolve()
    if not args.confirm_official_upload:
        raise ValueError("record-f2 requires --confirm-official-upload from the responsible human")
    plan_path, plan, planned = load_plan(case_dir, plan_value)
    output = resolve_new(case_dir, output_value, "F2 manifest")
    if output != planned["f2"]:
        raise ValueError("F2 output must equal the plan-selected f2_manifest path")
    m7_result = verify_m7(case_dir, planned["m7"])
    if not m7_result["passed"] or not m7_result["m7_approved"]:
        raise ValueError("F2 requires a verified accepted M7 manifest")
    m7_path, m7, _, _, _ = load_m7(case_dir, planned["m7"])
    current = precheck(case_dir, plan_path)
    if not current["m7_precheck_passed"] or not same_evidence(m7["evidence_sha256"], current["evidence_sha256"]):
        raise ValueError("selected package changed after M7 review")
    receipt = resolve_regular(case_dir, planned["receipt"], "official upload receipt", nonempty=True)
    if receipt.suffix.casefold() not in {item.casefold() for item in plan["official_upload"]["allowed_receipt_suffixes"]}:
        raise ValueError("official receipt suffix is not allowlisted")
    operator = human_name(args.operator, "official upload operator")
    if not substantive(args.submission_id) or not substantive(args.portal_submission_identifier):
        raise ValueError("submission_id and portal_submission_identifier must be substantive")
    upload_start = timestamp(args.upload_start, "upload_start")
    upload_end = timestamp(args.upload_end, "upload_end")
    receipt_at = timestamp(args.receipt_recorded_at, "receipt_recorded_at")
    generated = timestamp(args.generated_at, "generated_at")
    m7_signed = timestamp(m7["human_decision"]["signed_at"], "M7 signed_at")
    if not m7_signed <= upload_start <= upload_end <= receipt_at <= generated:
        raise ValueError("timestamps must satisfy M7 signed_at <= upload_start <= upload_end <= receipt_recorded_at <= generated_at")
    evidence = dict(current["evidence_sha256"])
    evidence["official_upload_receipt"] = binding(receipt)
    payload = {
        "schema_version": 1,
        "submission_id": args.submission_id.strip(),
        "status": "F2_COMPLETE",
        "official_submission_complete": True,
        "generated_at": args.generated_at,
        "source_plan": {"path": relative(case_dir, plan_path), "sha256": sha256_file(plan_path)},
        "source_m7_manifest": {"path": relative(case_dir, m7_path), "sha256": sha256_file(m7_path)},
        "evidence_sha256": evidence,
        "upload": {
            "competition": plan["official_upload"]["competition"],
            "platform": plan["official_upload"]["platform"],
            "portal_submission_identifier": args.portal_submission_identifier.strip(),
            "operator": operator,
            "review_mode": "single_operator_review",
            "upload_start": args.upload_start,
            "upload_end": args.upload_end,
            "receipt_recorded_at": args.receipt_recorded_at,
            "confirmation": "I_COMPLETED_THE_OFFICIAL_UPLOAD_AND_CAPTURED_RECEIPT",
        },
    }
    load_and_validate(payload, F2_SCHEMA, "F2 submission manifest")
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return payload


def verify_f2(case_dir: Path, manifest_value: str | Path) -> dict:
    case_dir = case_dir.expanduser().resolve()
    manifest_path = resolve_regular(case_dir, manifest_value, "F2 manifest")
    payload = read_json(manifest_path, "F2 manifest")
    load_and_validate(payload, F2_SCHEMA, "F2 submission manifest")
    errors: list[str] = []
    try:
        plan_path = check_binding(case_dir, payload["source_plan"], "F2 source plan")
        _, plan, planned = load_plan(case_dir, plan_path)
        if manifest_path != planned["f2"]:
            errors.append("F2 manifest is not the plan-selected final manifest")
        m7_path = check_binding(case_dir, payload["source_m7_manifest"], "F2 source M7 manifest")
        if m7_path != planned["m7"]:
            errors.append("F2 does not bind the plan-selected M7 manifest")
        m7_result = verify_m7(case_dir, m7_path)
        if not m7_result["passed"] or not m7_result["m7_approved"]:
            errors.append("F2 source M7 manifest is not a verified accepted M7")
        _, m7, _, _, _ = load_m7(case_dir, m7_path)
        current = precheck(case_dir, plan_path)
        expected = dict(current["evidence_sha256"])
        receipt = resolve_regular(case_dir, planned["receipt"], "official upload receipt", nonempty=True)
        expected["official_upload_receipt"] = binding(receipt)
        if not current["m7_precheck_passed"]:
            errors.extend(current["errors"])
        if not same_evidence(payload["evidence_sha256"], expected):
            errors.append("F2 evidence differs from current package or receipt evidence")
        human_name(payload["upload"]["operator"], "official upload operator")
        m7_signed = timestamp(m7["human_decision"]["signed_at"], "M7 signed_at")
        start = timestamp(payload["upload"]["upload_start"], "upload_start")
        end = timestamp(payload["upload"]["upload_end"], "upload_end")
        receipt_at = timestamp(payload["upload"]["receipt_recorded_at"], "receipt_recorded_at")
        generated = timestamp(payload["generated_at"], "generated_at")
        if not m7_signed <= start <= end <= receipt_at <= generated:
            errors.append("F2 timestamps are out of order")
        if payload["upload"]["competition"] != plan["official_upload"]["competition"] or payload["upload"]["platform"] != plan["official_upload"]["platform"]:
            errors.append("F2 upload competition/platform differs from the plan")
    except ValueError as exc:
        errors.append(str(exc))
    return {
        "passed": not errors,
        "status": payload["status"],
        "official_submission_complete": payload["official_submission_complete"] and not errors,
        "manifest": str(manifest_path),
        "errors": errors,
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    for command in ("precheck", "prepare-m7"):
        item = sub.add_parser(command)
        item.add_argument("--case-dir", type=Path, required=True)
        item.add_argument("--plan", type=Path, required=True)
        if command == "prepare-m7":
            item.add_argument("--output", type=Path, required=True)
            item.add_argument("--generated-at", required=True)
            item.add_argument("--review-id", required=True)
        item.add_argument("--json", action="store_true")
    final = sub.add_parser("finalize-m7")
    final.add_argument("--case-dir", type=Path, required=True)
    final.add_argument("--candidate", type=Path, required=True)
    final.add_argument("--output", type=Path, required=True)
    final.add_argument("--decision", choices=sorted(DECISION_TO_STATUS), required=True)
    final.add_argument("--reviewer", required=True)
    final.add_argument("--review-start", required=True)
    final.add_argument("--review-end", required=True)
    final.add_argument("--signed-at", required=True)
    final.add_argument("--generated-at", required=True)
    final.add_argument("--objections", default="NONE")
    final.add_argument("--resolution", default="NONE")
    final.add_argument("--confirm-human-reviewed", action="store_true")
    final.add_argument("--json", action="store_true")
    verify_m7_parser = sub.add_parser("verify-m7")
    verify_m7_parser.add_argument("--case-dir", type=Path, required=True)
    verify_m7_parser.add_argument("--manifest", type=Path, required=True)
    verify_m7_parser.add_argument("--json", action="store_true")
    record = sub.add_parser("record-f2")
    record.add_argument("--case-dir", type=Path, required=True)
    record.add_argument("--plan", type=Path, required=True)
    record.add_argument("--output", type=Path, required=True)
    record.add_argument("--submission-id", required=True)
    record.add_argument("--portal-submission-identifier", required=True)
    record.add_argument("--operator", required=True)
    record.add_argument("--upload-start", required=True)
    record.add_argument("--upload-end", required=True)
    record.add_argument("--receipt-recorded-at", required=True)
    record.add_argument("--generated-at", required=True)
    record.add_argument("--confirm-official-upload", action="store_true")
    record.add_argument("--json", action="store_true")
    verify_f2_parser = sub.add_parser("verify-f2")
    verify_f2_parser.add_argument("--case-dir", type=Path, required=True)
    verify_f2_parser.add_argument("--manifest", type=Path, required=True)
    verify_f2_parser.add_argument("--json", action="store_true")
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "precheck":
            report = precheck(args.case_dir, args.plan)
            passed = report["m7_precheck_passed"]
        elif args.command == "prepare-m7":
            payload = prepare_m7(args.case_dir, args.plan, args.output, args.generated_at, args.review_id)
            report = {"passed": True, "status": payload["status"], "m7_approved": False, "official_submission_status": "NOT_FORMAL_F2"}
            passed = True
        elif args.command == "finalize-m7":
            payload = finalize_m7(args.case_dir, args.candidate, args.output, args)
            report = {"passed": True, "status": payload["status"], "m7_approved": payload["m7_approved"], "official_submission_status": "NOT_FORMAL_F2"}
            passed = True
        elif args.command == "verify-m7":
            report = verify_m7(args.case_dir, args.manifest)
            passed = report["passed"]
        elif args.command == "record-f2":
            payload = record_f2(args.case_dir, args.plan, args.output, args)
            report = {"passed": True, "status": payload["status"], "official_submission_complete": True}
            passed = True
        else:
            report = verify_f2(args.case_dir, args.manifest)
            passed = report["passed"]
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        report = {"passed": False, "errors": [str(exc)]}
        passed = False
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

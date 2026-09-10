#!/usr/bin/env python
"""Prepare, finalize, verify, and audit the complete M6 compliance gate.

The technical audit binds rules, anonymity, sources/licenses, and AI disclosure.
It never makes or signs the responsible human's M6 decision. A full pass requires
an accepted, hash-bound human manifest created with an explicit confirmation.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True

from _json_schema import load_and_validate
from _workflow_common import (
    atomic_write_text,
    extract_docx_text,
    extract_pdf_text,
    hash_evidence,
    resolve_inside,
    resolve_path_inside,
    sha256_file,
    verify_evidence_hashes,
)
from audit_paper_quality_gates import inspect_docx_metadata, inspect_pdf_metadata
from audit_submission_compliance import audit as audit_legacy
from package_submission import extract_scannable_text, resolve_regular_source


SKILL_DIR = Path(__file__).resolve().parent.parent
PLAN_SCHEMA = SKILL_DIR / "schemas" / "m6-compliance-plan.schema.json"
SOURCE_SCHEMA = SKILL_DIR / "schemas" / "m6-source-register.schema.json"
MANIFEST_SCHEMA = SKILL_DIR / "schemas" / "m6-review-manifest.schema.json"
REPORT_SCHEMA = SKILL_DIR / "schemas" / "m6-compliance-report.schema.json"
PACKAGE_SCHEMA = SKILL_DIR / "schemas" / "submission-package-plan.schema.json"
PLACEHOLDER = re.compile(r"(?:\b(?:todo|tbd|placeholder|pending|undecided|unset|replace)\b|no entries yet)", re.I)
AI_REVIEWERS = {"codex", "ai", "assistant", "chatgpt"}
ACCEPTED = {"M6_ACCEPTED", "M6_ACCEPTED_WITH_LIMITATIONS"}
DECISION_TO_STATUS = {
    "accepted": "M6_ACCEPTED",
    "accepted_with_limitations": "M6_ACCEPTED_WITH_LIMITATIONS",
    "rejected": "M6_REJECTED",
}
TECHNICAL_SCOPE = [
    "official_rules_snapshot",
    "anonymity_precheck",
    "citations_external_data_software_licenses",
    "ai_disclosure_content",
    "support_material_allowlist",
]


def read_json(path: Path, label: str) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def substantive(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and not PLACEHOLDER.search(value)


def normalized(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def timestamp(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset")
    return parsed


def relative(case_dir: Path, path: Path) -> str:
    return path.resolve().relative_to(case_dir.resolve()).as_posix()


def resolve_file(case_dir: Path, value: str, label: str) -> Path:
    path = resolve_inside(case_dir, value, label)
    if not path.is_file():
        raise ValueError(f"{label} is not a regular file: {value}")
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink: {value}")
    return path


def add_check(report: dict, name: str, passed: bool, detail: str) -> None:
    report["checks"][name] = bool(passed)
    if not passed:
        report["errors"].append(detail)


def contains_all(text: str, markers: list[str]) -> tuple[bool, list[str]]:
    value = normalized(text)
    missing = [marker for marker in markers if normalized(marker) not in value]
    return not missing, missing


def source_register_audit(case_dir: Path, path: Path, package_plan: dict, evidence: dict[str, Path]) -> dict:
    data = read_json(path, "M6 source register")
    load_and_validate(data, SOURCE_SCHEMA, "M6 source register")
    errors: list[str] = []
    status = data["status"]
    entries = data["entries"]
    if status == "pending":
        errors.append("source register remains pending")
    if status in {"complete", "not_applicable"}:
        try:
            timestamp(data["reviewed_at"], "source register reviewed_at")
        except ValueError as exc:
            errors.append(str(exc))
    if status == "not_applicable":
        if entries:
            errors.append("not_applicable source register must have no entries")
        if not substantive(data["not_applicable_reason"]):
            errors.append("not_applicable source register requires a substantive reason")
    if status == "complete":
        if not entries:
            errors.append("complete source register must contain at least one entry")
    ids: set[str] = set()
    support_sources = {item["source"].replace("\\", "/") for item in package_plan["support"]["files"]}
    for index, entry in enumerate(entries):
        prefix = f"source entry {index}"
        entry_id = entry["id"].strip()
        if not substantive(entry_id) or entry_id in ids:
            errors.append(f"{prefix} id must be substantive and unique")
        ids.add(entry_id)
        if entry["license_status"] in {"unknown", "prohibited"}:
            errors.append(f"{prefix} has blocking license_status={entry['license_status']}")
        for field in ("source", "citation_or_paper_locator", "purpose", "limitations"):
            if not substantive(entry[field]):
                errors.append(f"{prefix}.{field} must be substantive")
        local = entry["local_evidence"]
        if local:
            try:
                local_path = resolve_file(case_dir, local, f"{prefix} local_evidence")
            except ValueError as exc:
                errors.append(str(exc))
            else:
                evidence[f"source_{entry_id}_local_evidence"] = local_path
        if entry["support_required"]:
            support = entry["support_path"].replace("\\", "/")
            if not support:
                errors.append(f"{prefix} requires support_path")
            elif support not in support_sources:
                errors.append(f"{prefix} support_path is absent from submission package allowlist: {support}")
        elif entry["support_path"]:
            errors.append(f"{prefix} declares support_path while support_required=false")
    return {"passed": not errors, "status": status, "entry_count": len(entries), "errors": errors}


def anonymity_audit(case_dir: Path, plan: dict, package_plan: dict, docx: Path, pdf: Path, evidence: dict[str, Path]) -> dict:
    errors: list[str] = []
    metadata = {"docx": inspect_docx_metadata(docx), "pdf": inspect_pdf_metadata(pdf)}
    allowed = {normalized(item) for item in plan["anonymity"]["allowed_anonymous_values"]}
    safe_allowed = {normalized(item) for item in ("", "Anonymous", "匿名", "匿名作者")}
    if not allowed.issubset(safe_allowed):
        errors.append("allowed_anonymous_values may contain only blank/Anonymous/匿名/匿名作者")
    for kind, block in metadata.items():
        errors.extend(block.get("errors", []))
        for label, value in block.get("values", {}).items():
            key = normalized(label).replace(" ", "")
            if key in {"creator", "lastmodifiedby", "author", "/author", "modifiedby", "xmp:dc_creator"} and normalized(value) not in allowed:
                errors.append(f"metadata identity field is not anonymous: {kind}:{label}")
    named_texts: list[tuple[str, str]] = [
        (relative(case_dir, docx), extract_docx_text(docx)),
        (relative(case_dir, pdf), extract_pdf_text(pdf)),
    ]
    package_files = package_plan["support"]["files"]
    for index, item in enumerate(package_files):
        try:
            source = resolve_regular_source(case_dir, item["source"], f"support file {index}")
        except ValueError as exc:
            errors.append(str(exc))
            continue
        evidence[f"support_{index}"] = source
        named_texts.append((item["source"], item["archive_path"]))
        try:
            extracted = extract_scannable_text(source)
        except ValueError as exc:
            errors.append(str(exc))
        else:
            if extracted:
                named_texts.append((item["source"], extracted))
    scan = "\n".join(f"{name}\n{text}" for name, text in named_texts)
    forbidden_terms = package_plan["anonymity"]["forbidden_terms"]
    if not forbidden_terms or any(not substantive(term) for term in forbidden_terms):
        errors.append("submission package anonymity forbidden_terms must be substantive and non-empty for full M6")
    for term in forbidden_terms:
        if normalized(term) in normalized(scan):
            errors.append(f"forbidden anonymity term found: {term}")
    for pattern in plan["anonymity"]["forbidden_path_patterns"]:
        try:
            matched = re.search(pattern, scan, flags=re.I)
        except re.error as exc:
            errors.append(f"invalid anonymity path pattern {pattern!r}: {exc}")
        else:
            if matched:
                errors.append(f"forbidden anonymity path pattern found: {pattern}")
    return {"passed": not errors, "metadata": metadata, "support_files_scanned": len(package_files), "errors": errors}


def technical_audit(case_dir: Path, plan_path: Path, docx: Path, pdf: Path, as_of: date | None = None) -> dict:
    case_dir = case_dir.expanduser().resolve()
    plan_path = resolve_path_inside(case_dir, plan_path, "M6 plan")
    docx = resolve_path_inside(case_dir, docx, "final DOCX")
    pdf = resolve_path_inside(case_dir, pdf, "final PDF")
    plan = read_json(plan_path, "M6 plan")
    load_and_validate(plan, PLAN_SCHEMA, "M6 plan")
    if any(not substantive(marker) for marker in plan["ai"]["usage_log_required_markers"] + plan["ai"]["detail_pdf_required_markers"]):
        raise ValueError("M6 AI required markers must be substantive and placeholder-free")
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "required": True,
        "scope": "full_m6",
        "technical_passed": False,
        "passed": False,
        "full_m6_proven": False,
        "paths": {"plan": str(plan_path), "docx": str(docx), "pdf": str(pdf)},
        "checks": {},
        "legacy_submission_compliance": {},
        "anonymity": {},
        "sources": {},
        "ai_content": {},
        "human_gate": {"status": "M6_PENDING_HUMAN", "passed": False, "errors": ["human M6 decision has not been verified"]},
        "evidence_sha256": {},
        "errors": [],
    }
    evidence: dict[str, Path] = {"m6_plan": plan_path, "final_docx": docx, "final_pdf": pdf}
    legacy_path = resolve_file(case_dir, plan["legacy_submission_compliance"], "legacy submission compliance")
    evidence["legacy_submission_compliance"] = legacy_path
    legacy = audit_legacy(case_dir, legacy_path, docx, pdf, as_of=as_of)
    legacy["scope"] = "rules_and_ai_technical_only"
    legacy["full_m6_proven"] = False
    report["legacy_submission_compliance"] = legacy
    add_check(report, "legacy_rules_and_ai", bool(legacy.get("passed")), "legacy rules-and-AI technical audit failed")

    rules = plan["official_rules"]
    snapshot = resolve_file(case_dir, rules["snapshot"], "official rules snapshot")
    evidence["official_rules_snapshot"] = snapshot
    add_check(report, "rules_snapshot_sha256", sha256_file(snapshot) == rules["snapshot_sha256"], "official rules snapshot SHA-256 does not match the plan")
    try:
        verified = date.fromisoformat(rules["verified_at"])
    except ValueError:
        verified = None
    current = as_of or date.today()
    fresh = verified is not None and 0 <= (current - verified).days <= rules["max_age_days"]
    add_check(report, "rules_snapshot_freshness", fresh, "official rules snapshot is stale or verified_at is invalid")
    legacy_data = read_json(legacy_path, "legacy submission compliance")
    add_check(report, "rules_sources_agree", set(rules["sources"]) == set(legacy_data["rules"]["sources"]), "M6 official source URLs disagree with legacy compliance evidence")
    add_check(report, "rules_verified_at_agrees", rules["verified_at"] == legacy_data["rules"]["verified_at"], "M6 verified_at disagrees with legacy compliance evidence")
    add_check(report, "rules_impact_steps", all(substantive(x) for x in rules["impact_steps"]), "official rules impact_steps must be substantive")

    package_path = resolve_file(case_dir, plan["anonymity"]["submission_package_plan"], "submission package plan")
    evidence["submission_package_plan"] = package_path
    package_plan = read_json(package_path, "submission package plan")
    load_and_validate(package_plan, PACKAGE_SCHEMA, "submission package plan")
    report["anonymity"] = anonymity_audit(case_dir, plan, package_plan, docx, pdf, evidence)
    if not report["anonymity"]["passed"]:
        report["errors"].extend(f"anonymity: {error}" for error in report["anonymity"]["errors"])
    report["checks"]["anonymity_precheck"] = report["anonymity"]["passed"]

    source_path = resolve_file(case_dir, plan["sources"]["register"], "M6 source register")
    evidence["source_register"] = source_path
    report["sources"] = source_register_audit(case_dir, source_path, package_plan, evidence)
    if not report["sources"]["passed"]:
        report["errors"].extend(f"sources: {error}" for error in report["sources"]["errors"])
    report["checks"]["sources_and_licenses"] = report["sources"]["passed"]

    ai = legacy_data["ai"]
    usage_path = resolve_file(case_dir, ai["usage_log"], "AI usage log")
    evidence["ai_usage_log"] = usage_path
    usage_text = usage_path.read_text(encoding="utf-8-sig")
    usage_ok, usage_missing = contains_all(usage_text, plan["ai"]["usage_log_required_markers"])
    detail_ok = True
    detail_missing: list[str] = []
    if ai["status"] == "used":
        detail_path = resolve_file(case_dir, ai["detail_pdf"], "AI detail PDF")
        evidence["ai_detail_pdf"] = detail_path
        detail_text = extract_pdf_text(detail_path)
        detail_ok, detail_missing = contains_all(detail_text, plan["ai"]["detail_pdf_required_markers"])
        support_sources = {item["source"].replace("\\", "/") for item in package_plan["support"]["files"]}
        if ai["detail_pdf"].replace("\\", "/") not in support_sources:
            detail_ok = False
            detail_missing.append("AI detail PDF absent from support allowlist")
    report["ai_content"] = {"status": ai["status"], "usage_log_markers_passed": usage_ok, "usage_log_missing": usage_missing, "detail_pdf_markers_passed": detail_ok, "detail_pdf_missing": detail_missing, "passed": usage_ok and detail_ok}
    if not report["ai_content"]["passed"]:
        if usage_missing:
            report["errors"].append("AI usage log missing markers: " + ", ".join(usage_missing))
        if detail_missing:
            report["errors"].append("AI detail PDF missing markers: " + ", ".join(detail_missing))
    report["checks"]["ai_content"] = report["ai_content"]["passed"]

    report["evidence_sha256"] = hash_evidence(evidence)
    report["technical_passed"] = not report["errors"]
    return report


def verify_manifest(case_dir: Path, manifest_value: str, expected_evidence: dict | None = None, expected_plan: Path | None = None) -> dict:
    case_dir = case_dir.resolve()
    path = resolve_file(case_dir, manifest_value, "M6 review manifest")
    payload = read_json(path, "M6 review manifest")
    load_and_validate(payload, MANIFEST_SCHEMA, "M6 review manifest")
    errors: list[str] = []
    if payload["status"] in ACCEPTED and not payload["full_m6_approved"]:
        errors.append("accepted M6 manifest must set full_m6_approved=true")
    if payload["status"] not in ACCEPTED and payload["full_m6_approved"]:
        errors.append("non-accepted M6 manifest must set full_m6_approved=false")
    decision = payload["human_decision"]
    expected_decision = {
        "M6_PENDING_HUMAN": "not_reviewed",
        "M6_ACCEPTED": "accepted",
        "M6_ACCEPTED_WITH_LIMITATIONS": "accepted_with_limitations",
        "M6_REJECTED": "rejected",
    }[payload["status"]]
    if decision["decision"] != expected_decision:
        errors.append("M6 status and human_decision.decision disagree")
    if payload["status"] in ACCEPTED:
        if decision["confirmation"] != "I_REVIEWED_THE_M6_EVIDENCE":
            errors.append("accepted M6 manifest lacks explicit human confirmation")
        if not substantive(decision["reviewer"]) or decision["reviewer"].strip().casefold() in AI_REVIEWERS:
            errors.append("M6 reviewer must be the responsible human, not Codex/AI")
        try:
            start = timestamp(decision["review_start"], "human_decision.review_start")
            end = timestamp(decision["review_end"], "human_decision.review_end")
            signed = timestamp(decision["signed_at"], "human_decision.signed_at")
            generated = timestamp(payload["generated_at"], "generated_at")
            if not start <= end <= signed <= generated:
                errors.append("M6 timestamps must satisfy review_start <= review_end <= signed_at <= generated_at")
        except ValueError as exc:
            errors.append(str(exc))
        if payload["status"] == "M6_ACCEPTED_WITH_LIMITATIONS" and (not substantive(decision["objections"]) or not substantive(decision["resolution"])):
            errors.append("accepted_with_limitations requires substantive objections and resolution")
    candidate_binding = payload["source_candidate"]
    if payload["status"] == "M6_PENDING_HUMAN":
        if candidate_binding != {"path": "", "sha256": ""}:
            errors.append("pending M6 manifest must not name a source candidate")
    else:
        try:
            candidate_path = resolve_file(case_dir, candidate_binding["path"], "M6 source candidate")
        except ValueError as exc:
            errors.append(str(exc))
        else:
            if sha256_file(candidate_path) != candidate_binding["sha256"]:
                errors.append("M6 source candidate hash is stale")
            else:
                candidate = read_json(candidate_path, "M6 source candidate")
                try:
                    load_and_validate(candidate, MANIFEST_SCHEMA, "M6 source candidate")
                except ValueError as exc:
                    errors.append(str(exc))
                else:
                    if candidate["status"] != "M6_PENDING_HUMAN":
                        errors.append("M6 source candidate is not pending-human")
                    for field in ("review_id", "source_plan", "evidence_sha256", "technical_scope"):
                        if candidate[field] != payload[field]:
                            errors.append(f"M6 source candidate disagrees on {field}")
    errors.extend(verify_evidence_hashes(payload["evidence_sha256"]))
    if expected_evidence is not None and payload["evidence_sha256"] != expected_evidence:
        errors.append("M6 manifest evidence does not match the current technical audit")
    if expected_plan is not None:
        binding = payload["source_plan"]
        if Path(binding["path"]).resolve() != expected_plan.resolve() or binding["sha256"] != sha256_file(expected_plan):
            errors.append("M6 manifest source_plan binding is stale or points elsewhere")
    return {"path": str(path), "sha256": sha256_file(path), "status": payload["status"], "full_m6_approved": payload["full_m6_approved"], "passed": not errors and payload["status"] in ACCEPTED, "errors": errors}


def audit(case_dir: Path, plan_path: Path, docx: Path, pdf: Path, as_of: date | None = None) -> dict:
    report = technical_audit(case_dir, plan_path, docx, pdf, as_of=as_of)
    case_dir = case_dir.expanduser().resolve()
    plan_path = resolve_path_inside(case_dir, plan_path, "M6 plan")
    plan = read_json(plan_path, "M6 plan")
    try:
        human = verify_manifest(case_dir, plan["human_gate"]["manifest"], report["evidence_sha256"], plan_path)
    except (OSError, ValueError) as exc:
        human = {"status": "M6_PENDING_HUMAN", "passed": False, "full_m6_approved": False, "errors": [str(exc)]}
    report["human_gate"] = human
    if human.get("path"):
        report["paths"]["human_manifest"] = human["path"]
        report["evidence_sha256"]["human_m6_manifest"] = {"path": human["path"], "sha256": human["sha256"]}
    if not human.get("passed"):
        report["errors"].extend(f"human M6 gate: {error}" for error in human.get("errors", []))
    report["passed"] = bool(report["technical_passed"] and human.get("passed"))
    report["full_m6_proven"] = report["passed"]
    load_and_validate(report, REPORT_SCHEMA, "M6 compliance report")
    return report


def prepare(case_dir: Path, plan_path: Path, docx: Path, pdf: Path, output: Path, generated_at: str, review_id: str) -> dict:
    timestamp(generated_at, "generated_at")
    if not substantive(review_id):
        raise ValueError("review_id must be substantive")
    case_dir = case_dir.expanduser().resolve()
    output = resolve_path_inside(case_dir, output, "M6 candidate output")
    if output.exists():
        raise ValueError("M6 candidate output already exists; review manifests are immutable")
    technical = technical_audit(case_dir, plan_path, docx, pdf)
    if not technical["technical_passed"]:
        raise ValueError("M6 technical audit failed: " + "; ".join(technical["errors"]))
    plan_resolved = resolve_path_inside(case_dir, plan_path, "M6 plan")
    payload = {
        "schema_version": 1, "review_id": review_id, "status": "M6_PENDING_HUMAN", "full_m6_approved": False,
        "generated_at": generated_at,
        "source_plan": {"path": str(plan_resolved), "sha256": sha256_file(plan_resolved)},
        "source_candidate": {"path": "", "sha256": ""},
        "evidence_sha256": technical["evidence_sha256"], "technical_scope": TECHNICAL_SCOPE,
        "human_decision": {"decision": "not_reviewed", "reviewer": "", "review_start": "", "review_end": "", "signed_at": "", "objections": "", "resolution": "", "confirmation": "NOT_CONFIRMED"},
    }
    load_and_validate(payload, MANIFEST_SCHEMA, "M6 candidate manifest")
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return payload


def finalize(case_dir: Path, candidate: Path, output: Path, args: argparse.Namespace) -> dict:
    if not args.confirm_human_reviewed:
        raise ValueError("refusing to record M6 decision without --confirm-human-reviewed")
    case_dir = case_dir.expanduser().resolve()
    candidate = resolve_path_inside(case_dir, candidate, "M6 candidate")
    output = resolve_path_inside(case_dir, output, "M6 final output")
    if output.exists():
        raise ValueError("M6 final output already exists; accepted manifests are immutable")
    source = read_json(candidate, "M6 candidate")
    load_and_validate(source, MANIFEST_SCHEMA, "M6 candidate")
    if source["status"] != "M6_PENDING_HUMAN":
        raise ValueError("M6 candidate status must be M6_PENDING_HUMAN")
    reviewer = args.reviewer.strip()
    if not reviewer or reviewer.casefold() in AI_REVIEWERS:
        raise ValueError("M6 reviewer must be the responsible human, not Codex/AI")
    start, end, signed, generated = (timestamp(args.review_start, "review_start"), timestamp(args.review_end, "review_end"), timestamp(args.signed_at, "signed_at"), timestamp(args.generated_at, "generated_at"))
    if not start <= end <= signed <= generated:
        raise ValueError("timestamps must satisfy review_start <= review_end <= signed_at <= generated_at")
    if timestamp(source["generated_at"], "candidate.generated_at") > start:
        raise ValueError("review_start must be at or after candidate.generated_at")
    status = DECISION_TO_STATUS[args.decision]
    payload = json.loads(json.dumps(source))
    payload.update({"status": status, "full_m6_approved": status in ACCEPTED, "generated_at": args.generated_at, "source_candidate": {"path": relative(case_dir, candidate), "sha256": sha256_file(candidate)}})
    payload["human_decision"] = {"decision": args.decision, "reviewer": reviewer, "review_start": args.review_start, "review_end": args.review_end, "signed_at": args.signed_at, "objections": args.objections, "resolution": args.resolution, "confirmation": "I_REVIEWED_THE_M6_EVIDENCE"}
    load_and_validate(payload, MANIFEST_SCHEMA, "M6 final manifest")
    checked = verify_evidence_hashes(payload["evidence_sha256"])
    if checked:
        raise ValueError("M6 evidence changed during human review: " + "; ".join(checked))
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return payload


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    for command in ("technical", "audit", "prepare"):
        item = sub.add_parser(command)
        item.add_argument("--case-dir", type=Path, required=True); item.add_argument("--plan", type=Path, required=True)
        item.add_argument("--docx", type=Path, required=True); item.add_argument("--pdf", type=Path, required=True)
        item.add_argument("--as-of", type=date.fromisoformat, help=argparse.SUPPRESS)
        if command == "prepare":
            item.add_argument("--output", type=Path, required=True); item.add_argument("--generated-at", required=True); item.add_argument("--review-id", required=True)
        item.add_argument("--json", action="store_true")
    finalize_parser = sub.add_parser("finalize")
    finalize_parser.add_argument("--case-dir", type=Path, required=True); finalize_parser.add_argument("--candidate", type=Path, required=True); finalize_parser.add_argument("--output", type=Path, required=True)
    finalize_parser.add_argument("--decision", choices=sorted(DECISION_TO_STATUS), required=True); finalize_parser.add_argument("--reviewer", required=True)
    finalize_parser.add_argument("--review-start", required=True); finalize_parser.add_argument("--review-end", required=True); finalize_parser.add_argument("--signed-at", required=True); finalize_parser.add_argument("--generated-at", required=True)
    finalize_parser.add_argument("--objections", default="NONE"); finalize_parser.add_argument("--resolution", default="NONE"); finalize_parser.add_argument("--confirm-human-reviewed", action="store_true"); finalize_parser.add_argument("--json", action="store_true")
    verify_parser = sub.add_parser("verify"); verify_parser.add_argument("--case-dir", type=Path, required=True); verify_parser.add_argument("--manifest", required=True); verify_parser.add_argument("--json", action="store_true")
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "technical":
            report = technical_audit(args.case_dir, args.plan, args.docx, args.pdf, args.as_of)
            load_and_validate(report, REPORT_SCHEMA, "M6 technical report")
        elif args.command == "audit":
            report = audit(args.case_dir, args.plan, args.docx, args.pdf, args.as_of)
        elif args.command == "prepare":
            payload = prepare(args.case_dir, args.plan, args.docx, args.pdf, args.output, args.generated_at, args.review_id)
            report = {"passed": True, "status": payload["status"], "review_id": payload["review_id"], "full_m6_approved": False}
        elif args.command == "finalize":
            payload = finalize(args.case_dir, args.candidate, args.output, args)
            report = {"passed": True, "status": payload["status"], "review_id": payload["review_id"], "full_m6_approved": payload["full_m6_approved"]}
        else:
            report = verify_manifest(args.case_dir, args.manifest)
    except (OSError, UnicodeError, ValueError) as exc:
        report = {"passed": False, "errors": [str(exc)]}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())


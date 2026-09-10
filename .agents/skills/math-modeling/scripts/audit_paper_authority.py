#!/usr/bin/env python
"""Audit whether paper artifacts may be treated as M5-authoritative.

Draft mode proves only that the paper is visibly non-authoritative. Authoritative
mode requires a currently valid accepted F1 manifest plus an agreeing
CURRENT-STATE.md pointer. The tool verifies recorded evidence; it does not make or
sign the human F1 decision.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

sys.dont_write_bytecode = True

from _json_schema import load_and_validate
from _workflow_common import extract_docx_text, extract_pdf_text, sha256_file
from freeze_results import verify as verify_freeze


SKILL_DIR = Path(__file__).resolve().parent.parent
PLAN_SCHEMA = SKILL_DIR / "schemas" / "paper-authority-plan.schema.json"
REPORT_SCHEMA = SKILL_DIR / "schemas" / "paper-authority-report.schema.json"
ACCEPTED = {"F1_ACCEPTED", "F1_ACCEPTED_WITH_LIMITATIONS"}


def reject_symlink_components(case_dir: Path, raw: PurePosixPath, label: str) -> None:
    current = case_dir
    for part in raw.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{label} must not be a symlink or traverse one: {raw.as_posix()}")


def resolve_case_file(case_dir: Path, value: str, label: str) -> Path:
    supplied = Path(value).expanduser()
    if supplied.is_absolute():
        path = supplied.resolve()
        try:
            relative_value = path.relative_to(case_dir)
        except ValueError as exc:
            raise ValueError(f"{label} escapes the case directory: {value}") from exc
        raw = PurePosixPath(relative_value.as_posix())
    else:
        raw = PurePosixPath(value.replace("\\", "/"))
        if raw.is_absolute() or ".." in raw.parts:
            raise ValueError(f"{label} must stay inside the case directory: {value}")
        path = (case_dir / Path(*raw.parts)).resolve()
        try:
            path.relative_to(case_dir)
        except ValueError as exc:
            raise ValueError(f"{label} escapes the case directory: {value}") from exc
    reject_symlink_components(case_dir, raw, label)
    if not path.is_file():
        raise ValueError(f"{label} is not a regular file: {value}")
    return path


def relative(case_dir: Path, path: Path | None) -> str:
    if path is None:
        return ""
    return path.resolve().relative_to(case_dir).as_posix()


def load_json(path: Path, label: str) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def clean_cell(value: str) -> str:
    cleaned = value.strip()
    if cleaned.startswith("`") and cleaned.endswith("`") and len(cleaned) >= 2:
        cleaned = cleaned[1:-1].strip()
    return cleaned


def parse_current_state(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        match = re.fullmatch(r"\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", line)
        if not match:
            continue
        field = clean_cell(match.group(1))
        value = clean_cell(match.group(2))
        if field in {"Field", "---"} or set(field) == {"-"}:
            continue
        fields[field] = value
    return fields


def text_for_artifact(path: Path, label: str) -> str:
    if label == "docx":
        return extract_docx_text(path)
    if label == "pdf":
        return extract_pdf_text(path)
    raise ValueError(f"unsupported paper artifact label: {label}")


def run_audit(
    case_dir: Path,
    plan_value: str,
    docx_value: str | None = None,
    pdf_value: str | None = None,
) -> dict:
    case_dir = case_dir.expanduser().resolve()
    if not case_dir.is_dir():
        raise ValueError(f"case directory does not exist: {case_dir}")
    plan_path = resolve_case_file(case_dir, plan_value, "paper authority plan")
    plan = load_json(plan_path, "paper authority plan")
    load_and_validate(plan, PLAN_SCHEMA, "paper authority plan")

    current_state_path = resolve_case_file(case_dir, plan["current_state"], "current_state")
    register_path = resolve_case_file(case_dir, plan["result_register"], "result_register")
    source_path = resolve_case_file(case_dir, plan["paper_source"], "paper_source")
    docx_path = resolve_case_file(case_dir, docx_value, "docx") if docx_value else None
    pdf_path = resolve_case_file(case_dir, pdf_value, "pdf") if pdf_value else None
    marker = plan["draft_marker"]
    source_text = source_path.read_text(encoding="utf-8-sig")
    marker_checks: dict[str, bool | None] = {
        "paper_source_contains_draft_marker": marker in source_text,
        "docx_contains_draft_marker": None,
        "pdf_contains_draft_marker": None,
    }
    for label, path in (("docx", docx_path), ("pdf", pdf_path)):
        if path is not None:
            marker_checks[f"{label}_contains_draft_marker"] = marker in text_for_artifact(path, label)

    current_state_text = current_state_path.read_text(encoding="utf-8-sig")
    current_fields = parse_current_state(current_state_text)
    errors: list[str] = []
    f1_verification: dict = {
        "passed": False,
        "status": "NOT_CHECKED",
        "paper_authoritative": False,
        "errors": [],
    }
    freeze_path: Path | None = None

    if plan["mode"] == "draft":
        if not marker_checks["paper_source_contains_draft_marker"]:
            errors.append("draft paper source must contain NON_AUTHORITATIVE REVIEW DRAFT")
        for label in ("docx", "pdf"):
            present = marker_checks[f"{label}_contains_draft_marker"]
            if present is False:
                errors.append(f"draft {label} must contain NON_AUTHORITATIVE REVIEW DRAFT")
        errors.append("draft mode is not paper-authoritative and cannot pass M5 finalization")
    else:
        freeze_path = resolve_case_file(
            case_dir, plan["freeze_manifest"], "freeze_manifest"
        )
        f1_verification = verify_freeze(case_dir, plan["freeze_manifest"])
        if not f1_verification.get("passed"):
            errors.extend(
                f"F1 verification: {error}"
                for error in f1_verification.get("errors", [])
            )
        freeze = load_json(freeze_path, "freeze manifest")
        if freeze.get("status") not in ACCEPTED:
            errors.append("paper authority requires an accepted F1 manifest")
        if not freeze.get("paper_authoritative"):
            errors.append("F1 manifest does not authorize paper claims")
        if freeze.get("result_register", {}).get("path") != plan["result_register"]:
            errors.append("paper authority result_register disagrees with the F1 manifest")

        expected_fields = {
            "Pointer status": "ACTIVE",
            "Canonical result register": plan["result_register"],
            "F1 status": str(freeze.get("status", "")),
            "F1 accepted manifest": plan["freeze_manifest"],
            "F1 verification": "PASSED",
            "Paper authoritative": "true",
            "Authoritative paper source": plan["paper_source"],
            "Human approval": "SIGNED",
        }
        for field, expected in expected_fields.items():
            actual = current_fields.get(field)
            if actual != expected:
                errors.append(
                    f"CURRENT-STATE {field!r} must be {expected!r}, found {actual!r}"
                )
        if current_fields.get("Pointer status") == "AUTHORITY_UNRESOLVED":
            errors.append("CURRENT-STATE authority is unresolved")
        for key, present in marker_checks.items():
            if present:
                errors.append(
                    f"authoritative paper artifact still contains draft marker: {key}"
                )

    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "required": True,
        "mode": plan["mode"],
        "passed": plan["mode"] == "authoritative" and not errors,
        "paper_authoritative": plan["mode"] == "authoritative" and not errors,
        "paths": {
            "plan": relative(case_dir, plan_path),
            "current_state": relative(case_dir, current_state_path),
            "result_register": relative(case_dir, register_path),
            "freeze_manifest": relative(case_dir, freeze_path),
            "paper_source": relative(case_dir, source_path),
            "docx": relative(case_dir, docx_path),
            "pdf": relative(case_dir, pdf_path),
        },
        "sha256": {
            "plan": sha256_file(plan_path),
            "current_state": sha256_file(current_state_path),
            "result_register": sha256_file(register_path),
            "freeze_manifest": sha256_file(freeze_path) if freeze_path else None,
            "paper_source": sha256_file(source_path),
            "docx": sha256_file(docx_path) if docx_path else None,
            "pdf": sha256_file(pdf_path) if pdf_path else None,
        },
        "current_state_fields": current_fields,
        "f1_verification": f1_verification,
        "marker_checks": marker_checks,
        "errors": errors,
    }
    load_and_validate(report, REPORT_SCHEMA, "paper authority report")
    return report


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--case-dir", type=Path, required=True)
    result.add_argument("--plan", required=True)
    result.add_argument("--docx")
    result.add_argument("--pdf")
    result.add_argument("--json", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        report = run_audit(args.case_dir, args.plan, args.docx, args.pdf)
    except (OSError, UnicodeError, ValueError) as exc:
        report = {
            "schema_version": 1,
            "required": True,
            "mode": "invalid",
            "passed": False,
            "paper_authoritative": False,
            "errors": [str(exc)],
        }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"paper_authoritative={str(report.get('paper_authoritative', False)).lower()}")
        for error in report.get("errors", []):
            print(f"error: {error}")
    return 0 if report.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""Audit rule freshness and AI disclosure for a submission-profile case."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from _diagnostics import enrich_legacy_report
from _json_schema import load_and_validate
from _workflow_common import (
    extract_docx_text,
    extract_pdf_text,
    hash_evidence,
    resolve_inside,
    resolve_path_inside,
    same_existing_file,
)


PLACEHOLDER = re.compile(
    r"(?:\b(?:todo|tbd|placeholder|pending|undecided)\b|no entries yet)",
    re.IGNORECASE,
)
STATUS_LINE = re.compile(r"^\s*Status\s*:\s*(used|not-used)\s*$", re.IGNORECASE | re.MULTILINE)
COMPLIANCE_SCHEMA = (
    Path(__file__).resolve().parent.parent
    / "schemas"
    / "submission-compliance.schema.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--compliance", type=Path, required=True)
    parser.add_argument("--docx", type=Path, required=True)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--as-of", type=date.fromisoformat, help=argparse.SUPPRESS)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def substantive(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and not PLACEHOLDER.search(value)


def normalized(value: str) -> str:
    return re.sub(r"\s+", "", value)


def add_check(report: dict, name: str, passed: bool, detail: str) -> None:
    report["checks"][name] = {"passed": passed, "detail": detail}
    if not passed:
        report["errors"].append(detail)


def load_compliance(path: Path, report: dict) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        report["errors"].append(f"cannot read submission compliance JSON: {exc}")
        return None
    if not isinstance(data, dict):
        report["errors"].append("submission compliance must be a JSON object")
        return None
    try:
        load_and_validate(data, COMPLIANCE_SCHEMA, "submission compliance")
    except ValueError as exc:
        report["errors"].append(str(exc))
        return None
    return data


def valid_https_source(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme.casefold() == "https" and bool(parsed.netloc)


def audit(
    case_dir: Path,
    compliance_path: Path,
    docx: Path,
    pdf: Path,
    *,
    as_of: date | None = None,
) -> dict:
    case_dir = case_dir.expanduser().resolve()
    compliance_path = resolve_path_inside(
        case_dir, compliance_path, "submission compliance"
    )
    docx = resolve_path_inside(case_dir, docx, "final DOCX")
    pdf = resolve_path_inside(case_dir, pdf, "final PDF")
    audit_date = as_of or date.today()
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "passed": False,
        "scope": "rules_and_ai_technical_only",
        "full_m6_proven": False,
        "case_dir": str(case_dir),
        "compliance": str(compliance_path),
        "as_of": audit_date.isoformat(),
        "checks": {},
        "errors": [],
        "warnings": [],
    }
    data = load_compliance(compliance_path, report)
    if data is None:
        return report

    add_check(
        report,
        "schema",
        data.get("schema_version") == 1,
        "submission compliance schema_version must be 1",
    )
    competition = data.get("competition")
    add_check(
        report,
        "competition",
        substantive(competition),
        "competition must be substantive and contain no placeholder",
    )
    year = data.get("year")
    valid_year = not isinstance(year, bool) and isinstance(year, int) and 2000 <= year <= 2100
    add_check(report, "year", valid_year, "year must be an integer from 2000 to 2100")

    rules = data.get("rules")
    if not isinstance(rules, dict):
        report["errors"].append("rules must be an object")
    else:
        verified_at = rules.get("verified_at")
        max_age = rules.get("max_age_days")
        valid_max_age = (
            not isinstance(max_age, bool) and isinstance(max_age, int) and 1 <= max_age <= 365
        )
        add_check(
            report,
            "rules.max_age_days",
            valid_max_age,
            "rules.max_age_days must be an integer from 1 to 365",
        )
        try:
            verified_date = date.fromisoformat(verified_at) if isinstance(verified_at, str) else None
        except ValueError:
            verified_date = None
        if verified_date is None:
            add_check(
                report,
                "rules.freshness",
                False,
                "rules.verified_at must be an ISO date",
            )
        elif valid_max_age:
            age = audit_date - verified_date
            fresh = 0 <= age.days <= max_age
            add_check(
                report,
                "rules.freshness",
                fresh,
                (
                    f"rules verification age is {age.days} days; allowed range is 0 to {max_age}"
                ),
            )
        sources = rules.get("sources")
        valid_sources = (
            isinstance(sources, list)
            and bool(sources)
            and all(valid_https_source(source) for source in sources)
        )
        add_check(
            report,
            "rules.sources",
            valid_sources,
            "rules.sources must contain at least one valid HTTPS URL",
        )

    evidence_paths = {
        "compliance": compliance_path,
        "docx": docx,
        "pdf": pdf,
    }
    ai = data.get("ai")
    if not isinstance(ai, dict):
        report["errors"].append("ai must be an object")
    else:
        status = ai.get("status")
        add_check(
            report,
            "ai.status",
            status in {"used", "not-used"},
            "ai.status must be used or not-used",
        )
        usage_log = None
        try:
            usage_log = resolve_inside(case_dir, ai.get("usage_log"), "AI usage log")
        except ValueError as exc:
            report["errors"].append(str(exc))
        if usage_log is not None:
            evidence_paths["ai_usage_log"] = usage_log
            try:
                usage_text = usage_log.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                report["errors"].append(f"cannot read AI usage log: {exc}")
            else:
                status_match = STATUS_LINE.search(usage_text)
                log_status = status_match.group(1).casefold() if status_match else None
                valid_log = (
                    len(usage_text.strip()) >= 40
                    and not PLACEHOLDER.search(usage_text)
                    and log_status == status
                )
                add_check(
                    report,
                    "ai.usage_log",
                    valid_log,
                    "AI usage log must be substantive, placeholder-free, and match ai.status",
                )

        statement = ai.get("paper_statement")
        valid_statement = substantive(statement)
        add_check(
            report,
            "ai.paper_statement",
            valid_statement,
            "ai.paper_statement must be substantive and contain no placeholder",
        )
        if valid_statement:
            for kind, artifact, extractor in (
                ("DOCX", docx, extract_docx_text),
                ("PDF", pdf, extract_pdf_text),
            ):
                try:
                    text = extractor(artifact)
                except ValueError as exc:
                    report["errors"].append(str(exc))
                else:
                    present = normalized(statement) in normalized(text)
                    add_check(
                        report,
                        f"ai.paper_statement_{kind.casefold()}",
                        present,
                        f"AI paper statement is missing from final {kind}",
                    )

        detail_value = ai.get("detail_pdf")
        if status == "used":
            detail_pdf = None
            try:
                detail_pdf = resolve_inside(case_dir, detail_value, "AI detail PDF")
            except ValueError as exc:
                report["errors"].append(str(exc))
            if detail_pdf is not None:
                evidence_paths["ai_detail_pdf"] = detail_pdf
                protected_evidence = (compliance_path, docx, pdf, usage_log)
                valid_detail = (
                    detail_pdf.suffix.casefold() == ".pdf"
                    and detail_pdf.is_file()
                    and detail_pdf not in protected_evidence
                    and not any(
                        other is not None and same_existing_file(detail_pdf, other)
                        for other in protected_evidence
                    )
                )
                if valid_detail:
                    try:
                        from pypdf import PdfReader

                        valid_detail = len(PdfReader(detail_pdf).pages) > 0
                    except Exception:
                        valid_detail = False
                add_check(
                    report,
                    "ai.detail_pdf",
                    valid_detail,
                    "used AI requires a distinct, readable, nonempty detail_pdf inside the case",
                )
        elif status == "not-used":
            add_check(
                report,
                "ai.detail_pdf",
                detail_value is None or detail_value == "",
                "not-used AI status must not declare a detail_pdf",
            )

    try:
        report["evidence_sha256"] = hash_evidence(evidence_paths)
    except OSError as exc:
        report["errors"].append(f"cannot hash submission evidence: {exc}")
        report["evidence_sha256"] = {}
    report["passed"] = not report["errors"]
    return report


def print_human(report: dict) -> None:
    print(f"passed={str(report['passed']).lower()}")
    print(f"compliance={report['compliance']}")
    for error in report["errors"]:
        print(f"error: {error}")


def main() -> int:
    args = parse_args()
    try:
        report = audit(
            args.case_dir, args.compliance, args.docx, args.pdf, as_of=args.as_of
        )
    except (OSError, ValueError) as exc:
        report = {"passed": False, "errors": [str(exc)]}
    enrich_legacy_report(
        report,
        stage="submission_compliance",
        error_code="rules_or_ai_compliance_failed",
    )
    if args.json:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        print_human(report)
    return 0 if report.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())

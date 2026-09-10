#!/usr/bin/env python
"""Audit material model-definition ambiguities and their mitigation evidence."""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path


PLACEHOLDER = re.compile(r"\b(?:todo|placeholder|pending)\b", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--register", type=Path)
    parser.add_argument("--docx", type=Path)
    parser.add_argument("--pdf", type=Path)
    parser.add_argument(
        "--structure-only",
        action="store_true",
        help="Validate the register contract without requiring generated evidence files",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def resolve_inside(case_dir: Path, value: str, label: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        raise ValueError(f"{label} must be relative to the case directory")
    resolved = (case_dir / candidate).resolve()
    try:
        resolved.relative_to(case_dir)
    except ValueError as exc:
        raise ValueError(f"{label} escapes the case directory: {value}") from exc
    return resolved


def meaningful_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and not PLACEHOLDER.search(value)


def normalized(value: str) -> str:
    return re.sub(r"\s+", "", value)


def docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as package:
        xml = package.read("word/document.xml").decode("utf-8", errors="replace")
    return "".join(re.findall(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", xml, re.DOTALL))


def pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)


def audit(
    case_dir: Path,
    register_path: Path,
    docx: Path | None,
    pdf: Path | None,
    *,
    structure_only: bool = False,
) -> dict:
    report = {
        "schema_version": 1,
        "passed": False,
        "scope": "structure-only" if structure_only else "full",
        "register": str(register_path),
        "ambiguity_count": 0,
        "material_ambiguity_count": 0,
        "ambiguities": [],
        "errors": [],
    }
    try:
        data = json.loads(register_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        report["errors"].append(f"cannot read model-definition register: {exc}")
        return report
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        report["errors"].append("model-definition register schema_version must be 1")
        return report
    if data.get("assessment_status") != "completed":
        report["errors"].append("assessment_status must be completed")
    if not meaningful_text(data.get("assessment_evidence")):
        report["errors"].append("assessment_evidence must be substantive and contain no placeholder")
    ambiguities = data.get("ambiguities")
    if not isinstance(ambiguities, list):
        report["errors"].append("ambiguities must be an array")
        return report
    report["ambiguity_count"] = len(ambiguities)
    if not ambiguities and not meaningful_text(data.get("no_material_ambiguity_rationale")):
        report["errors"].append(
            "empty ambiguities require a substantive no_material_ambiguity_rationale"
        )

    docx_content = ""
    pdf_content = ""
    if docx is not None:
        try:
            docx_content = normalized(docx_text(docx))
        except (OSError, KeyError, zipfile.BadZipFile) as exc:
            report["errors"].append(f"cannot inspect DOCX disclosure text: {exc}")
    if pdf is not None:
        try:
            pdf_content = normalized(pdf_text(pdf))
        except (OSError, ValueError) as exc:
            report["errors"].append(f"cannot inspect PDF disclosure text: {exc}")

    seen: set[str] = set()
    for index, item in enumerate(ambiguities):
        prefix = f"ambiguity {index}"
        item_report = {"index": index, "id": None, "material_difference": None, "errors": []}
        if not isinstance(item, dict):
            item_report["errors"].append("entry must be an object")
            report["ambiguities"].append(item_report)
            continue
        identifier = item.get("id")
        item_report["id"] = identifier
        if not isinstance(identifier, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", identifier) is None:
            item_report["errors"].append("id must use letters, digits, dot, underscore, or hyphen")
        elif identifier in seen:
            item_report["errors"].append("id must be unique")
        else:
            seen.add(identifier)
        for field in ("question", "primary_definition", "alternative_definition"):
            if not meaningful_text(item.get(field)):
                item_report["errors"].append(f"{field} must be substantive and contain no placeholder")

        comparison = item.get("comparison")
        if not isinstance(comparison, dict):
            item_report["errors"].append("comparison must be an object")
            comparison = {}
        if comparison.get("status") != "completed":
            item_report["errors"].append("comparison.status must be completed")
        material = comparison.get("material_difference")
        item_report["material_difference"] = material
        if not isinstance(material, bool):
            item_report["errors"].append("comparison.material_difference must be boolean")
        elif material:
            report["material_ambiguity_count"] += 1
        if not meaningful_text(comparison.get("materiality_rationale")):
            item_report["errors"].append("comparison.materiality_rationale must be substantive")
        evidence = comparison.get("evidence_files")
        if not isinstance(evidence, list) or not evidence:
            item_report["errors"].append("comparison.evidence_files must be a non-empty array")
        else:
            for evidence_index, relative in enumerate(evidence):
                try:
                    if not isinstance(relative, str) or not relative.strip():
                        raise ValueError("path must be a non-empty string")
                    path = resolve_inside(case_dir, relative, f"{prefix} comparison evidence {evidence_index}")
                    if not structure_only and not path.is_file():
                        item_report["errors"].append(f"comparison evidence is missing: {relative}")
                except ValueError as exc:
                    item_report["errors"].append(str(exc))

        reoptimization = item.get("alternative_reoptimization")
        if not isinstance(reoptimization, dict):
            item_report["errors"].append("alternative_reoptimization must be an object")
            reoptimization = {}
        expected_status = "completed" if material is True else "not-required"
        if reoptimization.get("status") != expected_status:
            item_report["errors"].append(
                f"alternative_reoptimization.status must be {expected_status}"
            )
        if material is True:
            reopt_evidence = reoptimization.get("evidence_files")
            if not isinstance(reopt_evidence, list) or not reopt_evidence:
                item_report["errors"].append(
                    "material ambiguity requires alternative_reoptimization.evidence_files"
                )
            else:
                for evidence_index, relative in enumerate(reopt_evidence):
                    try:
                        if not isinstance(relative, str) or not relative.strip():
                            raise ValueError("path must be a non-empty string")
                        path = resolve_inside(case_dir, relative, f"{prefix} reoptimization evidence {evidence_index}")
                        if not structure_only and not path.is_file():
                            item_report["errors"].append(f"reoptimization evidence is missing: {relative}")
                    except ValueError as exc:
                        item_report["errors"].append(str(exc))

        disclosure = item.get("paper_disclosure")
        if not isinstance(disclosure, dict):
            item_report["errors"].append("paper_disclosure must be an object")
            disclosure = {}
        disclosure_required = material is True
        expected_disclosure = "completed" if disclosure_required else "not-required"
        if disclosure.get("status") != expected_disclosure:
            item_report["errors"].append(f"paper_disclosure.status must be {expected_disclosure}")
        if disclosure_required:
            disclosure_text = disclosure.get("paper_text")
            if not meaningful_text(disclosure_text):
                item_report["errors"].append("material ambiguity requires paper_disclosure.paper_text")
            else:
                needle = normalized(disclosure_text)
                occurrences = {
                    "docx": docx_content.count(needle) if docx is not None else None,
                    "pdf": pdf_content.count(needle) if pdf is not None else None,
                }
                item_report["paper_occurrences"] = occurrences
                if docx is not None and occurrences["docx"] == 0:
                    item_report["errors"].append("paper disclosure text is missing from DOCX")
                if pdf is not None and occurrences["pdf"] == 0:
                    item_report["errors"].append("paper disclosure text is missing from PDF")

        report["ambiguities"].append(item_report)
        report["errors"].extend(
            f"{prefix} ({identifier or 'unidentified'}): {error}"
            for error in item_report["errors"]
        )
    report["passed"] = not report["errors"]
    return report


def main() -> int:
    args = parse_args()
    case_dir = args.case_dir.expanduser().resolve()
    register = (
        args.register.expanduser().resolve()
        if args.register
        else case_dir / "problem" / "model-definition-register.json"
    )
    try:
        register.relative_to(case_dir)
    except ValueError:
        report = {"schema_version": 1, "passed": False, "errors": ["register must stay inside case directory"]}
    else:
        report = audit(
            case_dir,
            register,
            args.docx.expanduser().resolve() if args.docx else None,
            args.pdf.expanduser().resolve() if args.pdf else None,
            structure_only=args.structure_only,
        )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"passed={str(report.get('passed', False)).lower()}")
        for error in report.get("errors", []):
            print(f"error: {error}")
    return 0 if report.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())

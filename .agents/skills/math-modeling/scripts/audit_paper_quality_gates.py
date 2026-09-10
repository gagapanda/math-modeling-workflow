#!/usr/bin/env python
"""Audit declaration-driven paper and delivery quality gates without modifying artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from _json_schema import load_and_validate
from _workflow_common import resolve_inside, sha256_file

PLAN_SCHEMA = Path(__file__).resolve().parent.parent / "schemas" / "paper-quality-gate-plan.schema.json"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
DC_NS = "http://purl.org/dc/elements/1.1/"
CP_NS = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def read_json(path: Path, label: str):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label}: {exc}") from exc


def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text).casefold()


def stringify_metadata_value(value: object) -> str:
    """Return stable text without turning a one-item XMP sequence into a Python repr."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        if len(value) == 1:
            return stringify_metadata_value(value[0])
        return json.dumps(
            [stringify_metadata_value(item) for item in value],
            ensure_ascii=False,
            separators=(",", ":"),
        )
    if isinstance(value, dict):
        return json.dumps(
            {str(key): stringify_metadata_value(item) for key, item in value.items()},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    return str(value)


def has_marker(text: str, marker: str) -> bool:
    return normalized(marker) in normalized(text)


MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*$")
RESULT_ID_REFERENCE_RE = re.compile(
    r"(?:结果\s*ID|result[_\s-]*id)\s*[:：=]\s*[`\"']?"
    r"([A-Za-z][A-Za-z0-9_.-]*[A-Za-z0-9_-])"
)
FIGURE_REFERENCE_RE = re.compile(r"!\[[^\]]*\]\(\s*<?([^)>\s]+)>?")
BOLD_NUMBERED_CAPTION_RE = re.compile(
    r"^\s*(?:\*\*|__)\s*(图|表|figure|table)\s*([0-9]+)(?![0-9]).*?(?:\*\*|__)\s*$",
    flags=re.IGNORECASE,
)
PLAIN_NUMBERED_CAPTION_RE = re.compile(
    r"^\s*(图|表|figure|table)\s*([0-9]+)(?![0-9])\s*[:：.-]\s*.+$",
    flags=re.IGNORECASE,
)
NUMBERED_BODY_REFERENCE_RE = re.compile(
    r"(?:(?P<english>figure|table)\s*(?P<english_number>[0-9]+)\b|"
    r"(?P<chinese>图|表)\s*(?P<chinese_number>[0-9]+)(?![0-9]))",
    flags=re.IGNORECASE,
)


def markdown_headings(text: str) -> list[tuple[int, int, str, str]]:
    headings = []
    for index, line in enumerate(text.splitlines()):
        match = MARKDOWN_HEADING_RE.match(line)
        if match:
            headings.append((index, len(match.group(1)), match.group(2).strip(), line.strip()))
    return headings


def extract_heading_region(text: str, marker: str, label: str) -> tuple[str, dict]:
    lines = text.splitlines()
    expected = normalized(marker)
    matches = [
        (index, level, title, raw)
        for index, level, title, raw in markdown_headings(text)
        if normalized(raw).startswith(expected)
    ]
    if len(matches) != 1:
        if not matches:
            raise ValueError(f"{label} heading not found: {marker}")
        raise ValueError(f"{label} heading is ambiguous: {marker}")
    start, level, _title, _raw = matches[0]
    end = len(lines)
    for index, next_level, _next_title, _next_raw in markdown_headings(text):
        if index > start and next_level <= level:
            end = index
            break
    return "\n".join(lines[start:end]), {"start_line": start + 1, "end_line": end}


def extract_abstract_region(text: str) -> tuple[str, dict]:
    headings = markdown_headings(text)
    candidates = [
        (index, level, title, raw)
        for index, level, title, raw in headings
        if normalized(title).strip(" :：") in {"摘要", "abstract", "summary"}
    ]
    if len(candidates) != 1:
        if not candidates:
            raise ValueError("abstract boundary cannot be determined: missing 摘要/Abstract heading")
        raise ValueError("abstract boundary cannot be determined: multiple abstract headings")
    start, _level, _title, _raw = candidates[0]
    lines = text.splitlines()
    end = len(lines)
    for index, _next_level, _next_title, _next_raw in headings:
        if index > start:
            end = index
            break
    return "\n".join(lines[start + 1:end]), {"start_line": start + 1, "end_line": end}


def body_text_without_appendix(text: str) -> str:
    lines = text.splitlines()
    for index, _level, title, _raw in markdown_headings(text):
        if normalized(title).strip().startswith("附录") or normalized(title).strip().startswith("appendix"):
            lines = lines[:index]
            break
    body = "\n".join(lines)
    return re.sub(r"(?ms)^```.*?^```[ \t]*\n?", "", body)


def extract_result_id_references(text: str) -> list[str]:
    return [match.group(1) for match in RESULT_ID_REFERENCE_RE.finditer(body_text_without_appendix(text))]


def relative_case_path(case_dir: Path, path: Path) -> str:
    return path.resolve().relative_to(case_dir.resolve()).as_posix()


def extract_body_figure_references(case_dir: Path, paper_dir: Path, paper_text: str) -> list[str]:
    references: list[str] = []
    for raw in FIGURE_REFERENCE_RE.findall(body_text_without_appendix(paper_text)):
        if re.match(r"(?:[A-Za-z][A-Za-z0-9+.-]*:|//)", raw):
            continue
        candidate = (paper_dir / raw.split("#", 1)[0].split("?", 1)[0]).resolve()
        try:
            references.append(relative_case_path(case_dir, candidate))
        except ValueError:
            references.append(f"<outside-case>:{raw}")
    return references


def add_error(report: dict, section: dict, message: str) -> None:
    section.setdefault("errors", []).append(message)
    report["errors"].append(message)


def add_warning(report: dict, section: dict, message: str) -> None:
    section.setdefault("warnings", []).append(message)
    report["warnings"].append(message)


def finish_section(section: dict) -> dict:
    if section.get("errors"):
        section["status"] = "failed"
    elif section.get("warnings"):
        section["status"] = "warning"
    else:
        section["status"] = "passed"
    return section


def load_plan(case_dir: Path, plan_path: Path) -> dict:
    plan = read_json(plan_path, "paper quality gate plan")
    load_and_validate(plan, PLAN_SCHEMA, "paper quality gate plan")
    return plan


def resolve_declared(case_dir: Path, value: str, label: str) -> Path:
    return resolve_inside(case_dir, value, label)


def load_result_ids(path: Path) -> tuple[set[str], list[str]]:
    data = read_json(path, "result register")
    errors: list[str] = []
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        return set(), ["result register must be a schema version 1 object"]
    entries = data.get("results")
    if not isinstance(entries, list):
        return set(), ["result register results must be an array"]
    ids: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not entry["id"].strip():
            errors.append(f"result register entry {index} has no valid id")
            continue
        if entry["id"] in ids:
            errors.append(f"result register duplicate id: {entry['id']}")
        ids.add(entry["id"])
    return ids, errors


def pdf_page_count(path: Path) -> int:
    try:
        from pypdf import PdfReader
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise ValueError("PDF is encrypted")
        pages = len(reader.pages)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"cannot read PDF: {exc}") from exc
    if pages < 1:
        raise ValueError("PDF has no pages")
    return pages


def inspect_docx_metadata(path: Path) -> dict:
    values: dict[str, str] = {}
    errors: list[str] = []
    try:
        with zipfile.ZipFile(path) as package:
            if "docProps/core.xml" not in package.namelist():
                return {"values": values, "errors": [], "missing_core_properties": True}
            root = ET.fromstring(package.read("docProps/core.xml"))
    except (OSError, zipfile.BadZipFile, ET.ParseError) as exc:
        return {"values": values, "errors": [f"cannot inspect DOCX metadata: {exc}"]}
    names = {
        "creator": f"{{{DC_NS}}}creator",
        "lastModifiedBy": f"{{{CP_NS}}}lastModifiedBy",
        "title": f"{{{DC_NS}}}title",
        "subject": f"{{{DC_NS}}}subject",
        "description": f"{{{DC_NS}}}description",
        "keywords": f"{{{CP_NS}}}keywords",
        "comments": f"{{{CP_NS}}}contentStatus",
    }
    for label, tag in names.items():
        node = root.find(tag)
        values[label] = (node.text or "").strip() if node is not None else ""
    return {"values": values, "errors": errors, "missing_core_properties": False}


def inspect_pdf_metadata(path: Path) -> dict:
    try:
        from pypdf import PdfReader
        reader = PdfReader(path)
        info = reader.metadata or {}
        values = {str(key): stringify_metadata_value(value) for key, value in info.items()}
        xmp = reader.xmp_metadata
        if xmp is not None:
            for label in ("dc_creator", "dc_title", "dc_description", "xmp_modify_date", "xmp_create_date"):
                try:
                    value = getattr(xmp, label, None)
                except Exception:
                    value = None
                if value:
                    values[f"xmp:{label}"] = stringify_metadata_value(value)
        return {"values": values, "errors": []}
    except Exception as exc:
        return {"values": {}, "errors": [f"cannot inspect PDF metadata: {exc}"]}


def inspect_rendered_pages(path: Path, expected_pages: int, report: dict) -> dict:
    section = {"path": str(path), "png_count": 0, "page_pngs": [], "unexpected_pngs": [], "errors": []}
    if not path.is_dir():
        add_error(report, section, f"rendered pages directory does not exist: {path}")
        return finish_section(section)
    files = sorted(item for item in path.glob("*.png") if item.is_file())
    section["png_count"] = len(files)
    numbers = []
    for item in files:
        if item.stat().st_size == 0:
            add_error(report, section, f"rendered pages empty PNG: {item.name}")
        try:
            from audit_paper import inspect_png
            inspect_png(item)
        except Exception as exc:
            add_error(report, section, f"rendered pages invalid PNG {item.name}: {exc}")
        match = re.fullmatch(r"page-(\d+)\.png", item.name, re.IGNORECASE)
        if match is None:
            section["unexpected_pngs"].append(item.name)
            add_error(report, section, f"rendered pages unexpected PNG filename: {item.name}")
        else:
            number = int(match.group(1))
            numbers.append(number)
            section["page_pngs"].append(item.name)
    if sorted(numbers) != list(range(1, len(files) + 1)):
        add_error(report, section, "rendered pages must contain unique continuous page-1..page-N PNGs")
    if len(files) != expected_pages:
        add_error(report, section, f"rendered pages count {len(files)} does not match PDF pages {expected_pages}")
    return finish_section(section)


def find_symbols_heading(text: str) -> tuple[int, int, str, str] | None:
    candidates = []
    for item in markdown_headings(text):
        title = normalized(item[2])
        has_symbol = "符号" in title or "symbol" in title
        has_unit = "单位" in title or "unit" in title
        if has_symbol and has_unit:
            candidates.append(item)
    if not candidates:
        return None
    return candidates[0]


def markdown_table_shape(region: str) -> dict:
    lines = region.splitlines()
    for index in range(len(lines) - 2):
        header = lines[index].strip()
        separator = lines[index + 1].strip()
        if not (header.startswith("|") and header.endswith("|")):
            continue
        if not re.match(r"^\|?(?:\s*:?-{3,}:?\s*\|)+\s*$", separator):
            continue
        rows = []
        for row in lines[index + 2 :]:
            stripped = row.strip()
            if not (stripped.startswith("|") and stripped.endswith("|")):
                break
            rows.append(stripped)
        headers = [cell.strip() for cell in header.strip("|").split("|")]
        return {
            "found": True,
            "columns": len(headers),
            "headers": headers,
            "data_rows": len(rows),
            "start_offset": index + 1,
        }
    return {"found": False, "columns": 0, "headers": [], "data_rows": 0}


def check_symbols_and_units(paper_text: str, report: dict) -> dict:
    section = {"errors": [], "warnings": []}
    heading = find_symbols_heading(paper_text)
    if heading is None:
        add_warning(
            report,
            section,
            "paper has no standalone Symbols and Units / 符号与单位 heading; legacy-compatible warning, but new full-paper scaffolds require one",
        )
        return finish_section(section)
    _index, _level, _title, raw = heading
    section["heading"] = raw
    try:
        region, boundary = extract_heading_region(paper_text, raw, "symbols and units section")
        section["boundary"] = boundary
    except ValueError as exc:
        add_warning(report, section, str(exc))
        return finish_section(section)
    shape = markdown_table_shape(region)
    section["table"] = shape
    if not shape["found"]:
        add_warning(
            report,
            section,
            "symbols and units section has no Markdown table; verify an equivalent readable table in the final DOCX/PDF",
        )
        return finish_section(section)
    if shape["columns"] < 3 or shape["data_rows"] < 1:
        add_warning(
            report,
            section,
            "symbols and units table should contain at least three columns and one populated data row",
        )
    header_text = normalized(" ".join(shape["headers"]))
    if not any(marker in header_text for marker in ("单位", "取值域", "unit", "domain")):
        add_warning(
            report,
            section,
            "symbols and units table has no Unit/Domain or 单位/取值域 header",
        )
    return finish_section(section)


def extract_numbered_captions(text: str) -> list[dict]:
    captions = []
    for line_number, line in enumerate(body_text_without_appendix(text).splitlines(), start=1):
        match = BOLD_NUMBERED_CAPTION_RE.match(line) or PLAIN_NUMBERED_CAPTION_RE.match(line)
        if not match:
            continue
        raw_kind = match.group(1).casefold()
        kind = "figure" if raw_kind in {"图", "figure"} else "table"
        captions.append(
            {"kind": kind, "number": int(match.group(2)), "line": line_number, "text": line.strip()}
        )
    return captions


def extract_numbered_body_references(text: str, caption_lines: set[int]) -> list[dict]:
    references = []
    for line_number, line in enumerate(body_text_without_appendix(text).splitlines(), start=1):
        if line_number in caption_lines:
            continue
        for match in NUMBERED_BODY_REFERENCE_RE.finditer(line):
            raw_kind = (match.group("english") or match.group("chinese") or "").casefold()
            raw_number = match.group("english_number") or match.group("chinese_number")
            kind = "figure" if raw_kind in {"图", "figure"} else "table"
            references.append(
                {"kind": kind, "number": int(raw_number), "line": line_number, "text": line.strip()}
            )
    return references


def check_figure_table_numbering(paper_text: str, report: dict) -> dict:
    section = {"errors": [], "warnings": []}
    body = body_text_without_appendix(paper_text)
    captions = extract_numbered_captions(paper_text)
    caption_lines = {item["line"] for item in captions}
    references = extract_numbered_body_references(paper_text, caption_lines)
    section["captions"] = captions
    section["references"] = references
    section["markdown_image_count"] = len(FIGURE_REFERENCE_RE.findall(body))

    available: dict[str, set[int]] = {"figure": set(), "table": set()}
    for caption in captions:
        kind = caption["kind"]
        number = caption["number"]
        if number in available[kind]:
            add_error(report, section, f"duplicate explicit {kind} number: {number}")
        available[kind].add(number)

    image_count = section["markdown_image_count"]
    available["figure"].update(range(1, image_count + 1))
    section["available_numbers"] = {
        kind: sorted(numbers) for kind, numbers in available.items()
    }

    for kind in ("figure", "table"):
        explicit = [item["number"] for item in captions if item["kind"] == kind]
        if explicit and explicit != sorted(explicit):
            add_warning(report, section, f"explicit {kind} captions are not in increasing numeric order")
        unique = sorted(set(explicit))
        if unique and unique != list(range(unique[0], unique[-1] + 1)):
            add_warning(report, section, f"explicit {kind} caption numbers contain a gap: {unique}")

    missing = []
    for reference in references:
        if reference["number"] not in available[reference["kind"]]:
            missing.append(reference)
    section["unresolved_references"] = missing
    if missing:
        details = ", ".join(
            f"{item['kind']} {item['number']} at line {item['line']}" for item in missing[:8]
        )
        add_warning(
            report,
            section,
            "numbered body references could not be reconciled from Markdown captions/images; verify final DOCX/PDF numbering: "
            + details,
        )

    near_caption_mismatches = []
    for reference in references:
        already_defined = any(
            caption["kind"] == reference["kind"]
            and caption["number"] == reference["number"]
            and caption["line"] < reference["line"]
            for caption in captions
        )
        if already_defined:
            continue
        following = [
            caption
            for caption in captions
            if caption["kind"] == reference["kind"]
            and 0 < caption["line"] - reference["line"] <= 4
        ]
        if following and following[0]["number"] != reference["number"]:
            near_caption_mismatches.append(
                {"reference": reference, "following_caption": following[0]}
            )
    section["near_caption_mismatches"] = near_caption_mismatches
    if near_caption_mismatches:
        details = ", ".join(
            f"{item['reference']['kind']} {item['reference']['number']} at line "
            f"{item['reference']['line']} precedes caption {item['following_caption']['number']} "
            f"at line {item['following_caption']['line']}"
            for item in near_caption_mismatches[:8]
        )
        add_warning(
            report,
            section,
            "a numbered reference immediately before a caption uses a different number; reconcile source and rendered paper: "
            + details,
        )
    return finish_section(section)


def check_summary(plan: dict, paper_text: str, report: dict) -> dict:
    section = {"required_subproblem_ids": plan["summary"]["required_subproblem_ids"], "errors": []}
    try:
        abstract_text, boundary = extract_abstract_region(paper_text)
        section["boundary"] = boundary
    except ValueError as exc:
        add_error(report, section, str(exc))
        return finish_section(section)
    for marker in plan["summary"]["markers"]:
        if not has_marker(abstract_text, marker):
            add_error(report, section, f"summary missing marker inside abstract: {marker}")
    abstract_pages = next((r for r in plan["page_regions"] if r["name"].casefold() == "abstract"), None)
    if abstract_pages is not None:
        pages = abstract_pages["end"] - abstract_pages["start"] + 1
        section["abstract_pages"] = pages
        if pages > plan["summary"]["max_pages"]:
            add_error(report, section, f"summary spans {pages} pages, maximum is {plan['summary']['max_pages']}")
    return finish_section(section)


def check_subproblems(plan: dict, paper_text: str, result_ids: set[str], report: dict) -> list[dict]:
    output = []
    for item in plan["subproblems"]:
        section = {"id": item["id"], "errors": []}
        try:
            subproblem_text, boundary = extract_heading_region(paper_text, item["heading"], f"{item['id']} section")
            section["boundary"] = boundary
        except ValueError as exc:
            add_error(report, section, str(exc))
            output.append(finish_section(section))
            continue
        for marker in item["required_markers"]:
            if not has_marker(subproblem_text, marker):
                add_error(report, section, f"{item['id']} missing required structure marker in its section: {marker}")
        categories = (
            ("method", item.get("method_markers", [])),
            ("result", item.get("result_markers", [])),
            ("validation", item.get("validation_markers", [])),
            ("boundary", item.get("boundary_markers", [])),
        )
        for category, markers in categories:
            for marker in markers:
                if not has_marker(subproblem_text, marker):
                    add_error(report, section, f"{item['id']} missing {category} marker in its section: {marker}")
        for result_id in item["headline_result_ids"]:
            if result_id not in result_ids:
                add_error(report, section, f"{item['id']} references unknown result id: {result_id}")
        output.append(finish_section(section))
    return output


def check_page_regions(plan: dict, pdf_pages: int, report: dict) -> dict:
    section = {"regions": plan["page_regions"], "pdf_pages": pdf_pages, "errors": []}
    regions = sorted(plan["page_regions"], key=lambda value: value["start"])
    expected = 1
    names = set()
    for region in regions:
        if region["name"] in names:
            add_error(report, section, f"duplicate page region: {region['name']}")
        names.add(region["name"])
        if region["start"] > region["end"]:
            add_error(report, section, f"page region has start after end: {region['name']}")
        if region["start"] != expected:
            add_error(report, section, f"page regions are not continuous before {region['name']}")
        expected = region["end"] + 1
    if expected != pdf_pages + 1:
        add_error(report, section, f"page regions end at {expected - 1}, PDF has {pdf_pages} pages")
    return finish_section(section)


def check_sources(plan: dict, case_dir: Path, paper_text: str, report: dict) -> list[dict]:
    output = []
    for item in plan["source_appendix"]:
        section = {"path": item["path"], "errors": []}
        try:
            source = resolve_declared(case_dir, item["path"], "source appendix path")
        except ValueError as exc:
            add_error(report, section, str(exc))
            output.append(finish_section(section))
            continue
        if not source.is_file():
            add_error(report, section, f"source appendix file does not exist: {item['path']}")
        else:
            text = source.read_text(encoding="utf-8", errors="replace")
            section["sha256"] = sha256_file(source)
            for token in item["required_tokens"]:
                if token not in text:
                    add_error(report, section, f"source file missing token: {token}")
        if not has_marker(paper_text, item["paper_marker"]):
            add_error(report, section, f"paper appendix missing source marker: {item['paper_marker']}")
        output.append(finish_section(section))
    return output


def check_formulas(plan: dict, case_dir: Path, paper_text: str, result_ids: set[str], report: dict) -> list[dict]:
    output = []
    for item in plan["formula_bindings"]:
        section = {"id": item["id"], "errors": []}
        for marker in item["paper_markers"]:
            if not has_marker(paper_text, marker):
                add_error(report, section, f"formula paper marker missing: {marker}")
        combined = []
        for source_path in item["source_files"]:
            try:
                source = resolve_declared(case_dir, source_path, "formula source file")
            except ValueError as exc:
                add_error(report, section, str(exc))
                continue
            if not source.is_file():
                add_error(report, section, f"formula source file does not exist: {source_path}")
                continue
            combined.append(source.read_text(encoding="utf-8", errors="replace"))
            section.setdefault("source_hashes", {})[source_path] = sha256_file(source)
        source_text = "\n".join(combined)
        for token in item["required_tokens"]:
            if token not in source_text:
                add_error(report, section, f"formula source token missing: {token}")
        for result_id in item["result_ids"]:
            if result_id not in result_ids:
                add_error(report, section, f"formula references unknown result id: {result_id}")
        output.append(finish_section(section))
    return output


def check_figures(
    plan: dict,
    case_dir: Path,
    paper_text: str,
    result_ids: set[str],
    report: dict,
    paper_dir: Path | None = None,
) -> list[dict]:
    output = []
    registered_paths: set[str] = set()
    for item in plan["figure_claims"]:
        section = {"id": item["id"], "figure": item["figure"], "errors": []}
        try:
            figure = resolve_declared(case_dir, item["figure"], "figure path")
            registered_paths.add(relative_case_path(case_dir, figure))
        except ValueError as exc:
            add_error(report, section, str(exc))
            output.append(finish_section(section))
            continue
        if not figure.is_file():
            add_error(report, section, f"figure does not exist: {item['figure']}")
        else:
            section["sha256"] = sha256_file(figure)
        for result_id in item["source_result_ids"]:
            if result_id not in result_ids:
                add_error(report, section, f"figure references unknown result id: {result_id}")
        for marker in item["body_markers"]:
            if not has_marker(paper_text, marker):
                add_error(report, section, f"figure body marker missing: {marker}")
        for marker in item["limitation_markers"]:
            if not has_marker(paper_text, marker):
                add_error(report, section, f"figure limitation marker missing: {marker}")
        output.append(finish_section(section))
    body_refs = extract_body_figure_references(case_dir, paper_dir or (case_dir / "paper"), paper_text)
    report["figure_body_references"] = {"references": body_refs, "unregistered": [], "errors": []}
    for body_ref in body_refs:
        if body_ref not in registered_paths:
            report["figure_body_references"]["unregistered"].append(body_ref)
            add_error(
                report,
                report["figure_body_references"],
                f"paper body figure is not registered in figure_claims: {body_ref}",
            )
    finish_section(report["figure_body_references"])
    return output


def check_result_references(paper_text: str, result_ids: set[str], report: dict) -> dict:
    section = {"references": [], "unknown": [], "errors": []}
    references = extract_result_id_references(paper_text)
    section["references"] = references
    for result_id in references:
        if result_id not in result_ids:
            section["unknown"].append(result_id)
            add_error(report, section, f"paper body references unknown result id: {result_id}")
    return finish_section(section)


def check_metadata(plan: dict, case_dir: Path, paper_text: str, docx: Path, pdf: Path, report: dict) -> dict:
    section = {"errors": []}
    docx_metadata = inspect_docx_metadata(docx)
    pdf_metadata = inspect_pdf_metadata(pdf)
    section["docx"] = docx_metadata
    section["pdf"] = pdf_metadata
    for error in docx_metadata["errors"] + pdf_metadata["errors"]:
        add_error(report, section, error)
    values = "\n".join(docx_metadata["values"].values()) + "\n" + "\n".join(pdf_metadata["values"].values())
    scan_text = paper_text + "\n" + values
    for marker in plan["metadata"].get("forbidden_terms", []):
        if has_marker(scan_text, marker):
            add_error(report, section, f"metadata/text forbidden term found: {marker}")
    for marker in plan["metadata"].get("forbidden_path_patterns", []):
        if re.search(marker, scan_text, flags=re.IGNORECASE):
            add_error(report, section, f"metadata/text forbidden path pattern found: {marker}")
    for marker in plan["metadata"].get("forbidden_command_markers", []):
        if has_marker(scan_text, marker):
            add_error(report, section, f"metadata/text forbidden command marker found: {marker}")
    allowed = {
        normalized(value)
        for value in plan["metadata"].get("allowed_anonymous_values", ["", "Anonymous", "匿名"])
    }
    identity_values = {}
    for source_name, metadata in (("docx", docx_metadata), ("pdf", pdf_metadata)):
        for label, value in metadata["values"].items():
            normalized_label = normalized(label).replace(" ", "")
            is_identity = normalized_label in {"creator", "lastmodifiedby", "author", "/author", "modifiedby", "xmp:dc_creator"}
            if is_identity:
                identity_values[f"{source_name}:{label}"] = value
                if normalized(value) not in allowed:
                    add_error(report, section, f"metadata identity field is not anonymous: {source_name}:{label}")
    section["identity_values"] = identity_values
    return finish_section(section)


def audit_quality_gates(case_dir: Path, plan_path: Path) -> dict:
    case_dir = case_dir.expanduser().resolve()
    plan_path = plan_path.expanduser().resolve()
    report = {
        "schema_version": 1,
        "passed": False,
        "case_dir": str(case_dir),
        "plan": str(plan_path),
        "plan_sha256": None,
        "errors": [],
        "warnings": [],
    }
    try:
        plan = load_plan(case_dir, plan_path)
        report["plan_sha256"] = sha256_file(plan_path)
        paper_path = resolve_declared(case_dir, plan["paper_source"], "paper source")
        docx_path = resolve_declared(case_dir, plan["docx"], "DOCX")
        pdf_path = resolve_declared(case_dir, plan["pdf"], "PDF")
        render_dir = resolve_declared(case_dir, plan["render_dir"], "render directory")
        register_path = resolve_declared(case_dir, plan["result_register"], "result register")
        paper_text = paper_path.read_text(encoding="utf-8")
        result_ids, register_errors = load_result_ids(register_path)
        if register_errors:
            report["errors"].extend(register_errors)
        pdf_pages = pdf_page_count(pdf_path)
        report["paper_source_sha256"] = sha256_file(paper_path)
        report["pdf_sha256"] = sha256_file(pdf_path)
        report["summary"] = check_summary(plan, paper_text, report)
        report["symbols_and_units"] = check_symbols_and_units(paper_text, report)
        report["figure_table_numbering"] = check_figure_table_numbering(paper_text, report)
        report["subproblems"] = check_subproblems(plan, paper_text, result_ids, report)
        report["result_references"] = check_result_references(paper_text, result_ids, report)
        report["page_regions"] = check_page_regions(plan, pdf_pages, report)
        report["rendered_pages"] = inspect_rendered_pages(render_dir, pdf_pages, report)
        report["source_appendix"] = check_sources(plan, case_dir, paper_text, report)
        report["formula_bindings"] = check_formulas(plan, case_dir, paper_text, result_ids, report)
        report["figure_claims"] = check_figures(plan, case_dir, paper_text, result_ids, report, paper_path.parent)
        report["metadata"] = check_metadata(plan, case_dir, paper_text, docx_path, pdf_path, report)
    except Exception as exc:
        report["errors"].append(str(exc))
    report["passed"] = not report["errors"]
    return report


def main() -> int:
    args = parse_args()
    try:
        report = audit_quality_gates(args.case_dir, args.plan)
    except Exception as exc:
        report = {"schema_version": 1, "passed": False, "errors": [str(exc)], "warnings": []}
    if args.report:
        args.report.expanduser().resolve().write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if args.json or not args.report:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())

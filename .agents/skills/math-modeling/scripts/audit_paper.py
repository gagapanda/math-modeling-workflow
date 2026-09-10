#!/usr/bin/env python
"""Run structural checks on mathematical-modeling DOCX and PDF papers."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
import zipfile
import zlib
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

from _workflow_common import extract_docx_xml_text


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
NS = {"w": W, "wp": WP}

PAGE_SIZES = {
    "a4": (595.28, 841.89),
    "letter": (612.0, 792.0),
}

UNREFRESHED_TOC_PATTERNS = (
    re.compile(r"目录\s*将在\s*Word\s*中\s*自动更新", re.IGNORECASE),
    re.compile(
        r"(?:table\s+of\s+contents|toc)\s+(?:will\s+be|is)\s+updated\s+in\s+Word",
        re.IGNORECASE,
    ),
)


TEMPLATE_PLACEHOLDER_MARKERS = (
    "Paper Title",
    "MMFINALIZE",
    "State the problem",
    "State every required output",
    "Explain the structure",
    "Justify material assumptions",
    "Document provenance",
    "Compare the baseline",
    "Answer every requested output",
    "Insert the exact statement",
    "Cite data, prior work",
    "List every submitted",
    "Include or assemble the complete final source code",
    # Visible instructions/examples shipped by the current Chinese LaTeX template.
    # A final paper must replace or remove these rather than merely compile them.
    "终稿前必须替换或删除本示例条目",
    "表中仅列可替换的导航示例",
    "最小可运行示例（终稿前替换或删除）",
)

UNRENDERED_LATEX_PATTERNS = (
    re.compile(r"\\\[|\\\]"),
    re.compile(
        r"\\(?:frac|sqrt|sum|int|prod|lim|rho|theta|omega|mathrm|"
        r"boldsymbol|mathsf|qquad|left|right|text)\b"
    ),
    # A plain-text generator may emit pseudo-LaTeX without the leading
    # backslash, for example ``sqrt{...}``. This is still a visible equation
    # rendering failure rather than acceptable mathematical typography.
    re.compile(r"(?<![A-Za-z0-9_])sqrt\s*\{"),
    # Literal dollar-delimited spans mean math source survived export. Inline
    # formulas are supported in ordinary paragraphs but not reliably in tables.
    re.compile(r"\$(?:[^$\n]{1,120})\$"),
)


def contains_template_placeholder(text: str, marker: str) -> bool:
    """Match visible template prose despite PDF/DOCX extraction line breaks."""
    if re.search(r"[\u3400-\u9fff]", marker):
        return re.sub(r"\s+", "", marker) in re.sub(r"\s+", "", text)
    return marker in text


def add_content_quality_checks(report: dict, label: str, text: str) -> None:
    placeholders = [
        marker
        for marker in TEMPLATE_PLACEHOLDER_MARKERS
        if contains_template_placeholder(text, marker)
    ]
    report[label]["template_placeholders"] = placeholders
    for marker in placeholders:
        report["errors"].append(f"{label}: template placeholder remains: {marker!r}")

    latex_markers = [pattern.pattern for pattern in UNRENDERED_LATEX_PATTERNS if pattern.search(text)]
    report[label]["unrendered_latex_markers"] = latex_markers
    for marker in latex_markers:
        report["errors"].append(f"{label}: visible unrendered LaTeX marker remains: {marker!r}")

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docx", type=Path, help="DOCX paper to inspect")
    parser.add_argument("--pdf", type=Path, help="PDF paper to inspect")
    parser.add_argument("--render-dir", type=Path, help="Directory containing page PNGs")
    parser.add_argument(
        "--page-size", choices=("any", "a4", "letter"), default="any"
    )
    parser.add_argument(
        "--orientation", choices=("any", "portrait", "landscape"), default="any"
    )
    parser.add_argument("--expect", action="append", default=[], help="Required text")
    parser.add_argument("--forbid", action="append", default=[], help="Forbidden text")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    return parser.parse_args()


def qn(namespace: str, local: str) -> str:
    return f"{{{namespace}}}{local}"


def page_matches(width: float, height: float, expected: str, tolerance: float = 7.0) -> bool:
    if expected == "any":
        return True
    target_width, target_height = PAGE_SIZES[expected]
    return (
        abs(width - target_width) <= tolerance
        and abs(height - target_height) <= tolerance
    ) or (
        abs(width - target_height) <= tolerance
        and abs(height - target_width) <= tolerance
    )


def orientation_matches(width: float, height: float, expected: str) -> bool:
    if expected == "any":
        return True
    actual = "portrait" if height >= width else "landscape"
    return actual == expected


def summarize_pages(pages: list[int]) -> str:
    ranges = []
    start = previous = pages[0]
    for page in pages[1:]:
        if page == previous + 1:
            previous = page
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = page
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(ranges)


def add_text_checks(report: dict, label: str, text: str, args: argparse.Namespace) -> None:
    expected = {value: value in text for value in args.expect}
    forbidden = {value: value in text for value in args.forbid}
    report[label]["expected_text"] = expected
    report[label]["forbidden_text"] = forbidden
    for value, found in expected.items():
        if not found:
            report["errors"].append(f"{label}: missing expected text {value!r}")
    for value, found in forbidden.items():
        if found:
            report["errors"].append(f"{label}: found forbidden text {value!r}")


def add_unresolved_toc_check(report: dict, label: str, text: str) -> None:
    markers = []
    for pattern in UNREFRESHED_TOC_PATTERNS:
        match = pattern.search(text)
        if match:
            markers.append(match.group(0))
    report[label]["unrefreshed_toc_markers"] = markers
    for marker in markers:
        report["errors"].append(
            f"{label}: unresolved table-of-contents placeholder found: {marker!r}"
        )


def inspect_docx(path: Path, report: dict, args: argparse.Namespace) -> None:
    label = "docx"
    report[label] = {"path": str(path.resolve())}
    if not path.is_file() or path.stat().st_size == 0:
        report["errors"].append(f"DOCX is missing or empty: {path}")
        return

    try:
        with zipfile.ZipFile(path) as package:
            root = ET.fromstring(package.read("word/document.xml"))
            try:
                styles_root = ET.fromstring(package.read("word/styles.xml"))
            except KeyError:
                styles_root = None
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
        report["errors"].append(f"DOCX cannot be parsed: {exc}")
        return

    text = extract_docx_xml_text(root)
    style_names = {}
    if styles_root is not None:
        for style_definition in styles_root.findall(".//w:style", NS):
            style_id = style_definition.get(qn(W, "styleId"), "")
            name = style_definition.find("./w:name", NS)
            if style_id and name is not None:
                style_names[style_id] = name.get(qn(W, "val"), style_id)
    headings = Counter()
    for paragraph in root.findall(".//w:p", NS):
        style = paragraph.find("./w:pPr/w:pStyle", NS)
        if style is None:
            continue
        value = style.get(qn(W, "val"), "")
        resolved_name = style_names.get(value, value)
        if resolved_name.casefold().startswith("heading"):
            headings[resolved_name] += 1

    inline_images = len(root.findall(".//wp:inline", NS))
    floating_images = len(root.findall(".//wp:anchor", NS))
    sections = []
    for section in root.findall(".//w:sectPr", NS):
        size = section.find("./w:pgSz", NS)
        margins = section.find("./w:pgMar", NS)
        if size is None:
            continue
        width = int(size.get(qn(W, "w"), "0")) / 20.0
        height = int(size.get(qn(W, "h"), "0")) / 20.0
        section_data = {"width_pt": width, "height_pt": height}
        if margins is not None:
            section_data["margins_pt"] = {
                name: int(margins.get(qn(W, name), "0")) / 20.0
                for name in ("top", "right", "bottom", "left")
            }
        sections.append(section_data)
        if not page_matches(width, height, args.page_size):
            report["errors"].append(
                f"docx: section page size {width:.1f}x{height:.1f} pt is not {args.page_size}"
            )
        if not orientation_matches(width, height, args.orientation):
            report["errors"].append(
                f"docx: section orientation is not {args.orientation}"
            )

    report[label].update(
        {
            "size_bytes": path.stat().st_size,
            "characters": len(text),
            "headings": dict(sorted(headings.items())),
            "inline_images": inline_images,
            "floating_images": floating_images,
            "sections": sections,
        }
    )
    if floating_images:
        report["errors"].append(f"docx: {floating_images} floating image(s) found")
    if not headings:
        report["warnings"].append("docx: no Heading styles found")
    if "qquad" in text or "\\le" in text or "\\in" in text:
        report["warnings"].append("docx: visible text may contain unrendered LaTeX")
    add_text_checks(report, label, text, args)
    add_unresolved_toc_check(report, label, text)
    add_content_quality_checks(report, label, text)


def resolve_object(value):
    return value.get_object() if hasattr(value, "get_object") else value


def inspect_pdf(path: Path, report: dict, args: argparse.Namespace) -> None:
    label = "pdf"
    report[label] = {"path": str(path.resolve())}
    if not path.is_file() or path.stat().st_size == 0:
        report["errors"].append(f"PDF is missing or empty: {path}")
        return
    try:
        from pypdf import PdfReader
    except ImportError:
        report["errors"].append("pdf: pypdf is required; use the Codex bundled runtime")
        return

    try:
        reader = PdfReader(path)
    except Exception as exc:  # pypdf exposes several parser-specific exceptions
        report["errors"].append(f"PDF cannot be parsed: {exc}")
        return

    if reader.is_encrypted:
        report["errors"].append("pdf: encrypted papers are not accepted by this audit")
        return

    text_parts = []
    page_sizes = []
    size_mismatches = []
    orientation_mismatches = []
    for index, page in enumerate(reader.pages, 1):
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        page_sizes.append({"page": index, "width_pt": width, "height_pt": height})
        if not page_matches(width, height, args.page_size):
            size_mismatches.append(index)
        if not orientation_matches(width, height, args.orientation):
            orientation_mismatches.append(index)
        text_parts.append(page.extract_text() or "")

    if size_mismatches:
        report["errors"].append(
            f"pdf: pages {summarize_pages(size_mismatches)} do not match {args.page_size}"
        )
    if orientation_mismatches:
        report["errors"].append(
            f"pdf: pages {summarize_pages(orientation_mismatches)} are not {args.orientation}"
        )

    root = resolve_object(reader.trailer["/Root"])
    names = resolve_object(root.get("/Names", {}))
    has_javascript = bool(names.get("/JavaScript")) or "/JavaScript" in str(
        root.get("/OpenAction", "")
    )
    has_forms = bool(root.get("/AcroForm"))
    tagged = bool(root.get("/MarkInfo"))
    report[label].update(
        {
            "size_bytes": path.stat().st_size,
            "pages": len(reader.pages),
            "page_sizes": page_sizes,
            "encrypted": False,
            "forms": has_forms,
            "javascript": has_javascript,
            "tagged": tagged,
        }
    )
    if has_forms:
        report["errors"].append("pdf: interactive form found")
    if has_javascript:
        report["errors"].append("pdf: JavaScript found")
    if not tagged:
        report["warnings"].append("pdf: document is not tagged")
    text = "\n".join(text_parts)
    add_text_checks(report, label, text, args)
    add_unresolved_toc_check(report, label, text)
    add_content_quality_checks(report, label, text)


def inspect_render_dir(path: Path, report: dict) -> None:
    label = "rendered_pages"
    report[label] = {"path": str(path.resolve())}
    if not path.is_dir():
        report["errors"].append(f"rendered pages directory does not exist: {path}")
        return
    files = sorted(path.glob("*.png"))
    empty = [item.name for item in files if item.stat().st_size == 0]
    images = []
    page_numbers = []
    for item in files:
        try:
            image = inspect_png(item)
        except ValueError as exc:
            image = {"name": item.name, "valid": False, "error": str(exc)}
            report["errors"].append(f"rendered pages: invalid PNG {item.name}: {exc}")
        images.append(image)
        match = re.search(r"(?:^|[-_])(\d+)\.png$", item.name, re.IGNORECASE)
        if match:
            page_numbers.append(int(match.group(1)))
        else:
            report["errors"].append(
                f"rendered pages: filename must end with a page number: {item.name}"
            )
    if page_numbers and sorted(page_numbers) != list(range(1, len(files) + 1)):
        report["errors"].append("rendered pages: page numbers must be unique and continuous from 1")
    report[label].update(
        {"png_count": len(files), "empty_files": empty, "images": images}
    )
    if empty:
        report["errors"].append(f"rendered pages: empty PNG files: {', '.join(empty)}")
    expected = report.get("pdf", {}).get("pages")
    if expected is None:
        report["errors"].append("rendered pages: --pdf is required for page-count comparison")
    elif len(files) != expected:
        report["errors"].append(
            f"rendered pages: found {len(files)} PNGs but PDF has {expected} pages"
        )


def inspect_png(path: Path) -> dict:
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("invalid PNG signature")
    offset = 8
    chunks = []
    compressed = bytearray()
    width = height = bit_depth = color_type = interlace = None
    while offset < len(data):
        if offset + 12 > len(data):
            raise ValueError("truncated PNG chunk")
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_end = offset + 12 + length
        if chunk_end > len(data):
            raise ValueError("PNG chunk exceeds file length")
        chunk_data = data[offset + 8 : offset + 8 + length]
        stored_crc = struct.unpack(">I", data[offset + 8 + length : chunk_end])[0]
        actual_crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
        if stored_crc != actual_crc:
            raise ValueError(f"CRC mismatch in {chunk_type.decode('ascii', 'replace')} chunk")
        chunks.append(chunk_type)
        if chunk_type == b"IHDR":
            if len(chunks) != 1 or length != 13:
                raise ValueError("invalid IHDR chunk")
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", chunk_data
            )
            if width == 0 or height == 0:
                raise ValueError("PNG dimensions must be positive")
            if compression != 0 or filtering != 0 or interlace not in (0, 1):
                raise ValueError("unsupported PNG encoding parameters")
        elif chunk_type == b"IDAT":
            compressed.extend(chunk_data)
        elif chunk_type == b"IEND":
            if length != 0:
                raise ValueError("invalid IEND chunk")
            offset = chunk_end
            break
        offset = chunk_end
    if not chunks or chunks[0] != b"IHDR" or b"IDAT" not in chunks or chunks[-1] != b"IEND":
        raise ValueError("PNG requires IHDR, IDAT, and terminal IEND chunks")
    if offset != len(data):
        raise ValueError("unexpected data after IEND chunk")
    try:
        pixels = zlib.decompress(bytes(compressed))
    except zlib.error as exc:
        raise ValueError(f"invalid compressed image data: {exc}") from exc
    if not pixels:
        raise ValueError("decompressed image data is empty")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
    if color_type not in channels:
        raise ValueError(f"unsupported PNG color type {color_type}")
    valid_depths = {
        0: {1, 2, 4, 8, 16},
        2: {8, 16},
        3: {1, 2, 4, 8},
        4: {8, 16},
        6: {8, 16},
    }
    if bit_depth not in valid_depths[color_type]:
        raise ValueError(
            f"invalid bit depth {bit_depth} for PNG color type {color_type}"
        )
    if color_type == 3 and b"PLTE" not in chunks:
        raise ValueError("indexed-color PNG is missing a PLTE chunk")
    if interlace == 0:
        row_bytes = (width * channels[color_type] * bit_depth + 7) // 8
        expected_bytes = height * (row_bytes + 1)
        if len(pixels) != expected_bytes:
            raise ValueError(
                f"decompressed data has {len(pixels)} bytes; expected {expected_bytes}"
            )
        for offset in range(0, len(pixels), row_bytes + 1):
            if pixels[offset] > 4:
                raise ValueError(f"invalid PNG row filter {pixels[offset]}")
    return {
        "name": path.name,
        "valid": True,
        "size_bytes": len(data),
        "width": width,
        "height": height,
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def print_human(report: dict) -> None:
    print(f"structural_ok={str(report['structural_ok']).lower()}")
    print(f"visual_review={report['visual_review']}")
    for label in ("docx", "pdf", "rendered_pages"):
        if label in report:
            data = report[label]
            summary = [f"path={data['path']}"]
            for key in (
                "size_bytes",
                "pages",
                "inline_images",
                "floating_images",
                "png_count",
            ):
                if key in data:
                    summary.append(f"{key}={data[key]}")
            print(f"{label}: " + " ".join(summary))
    for warning in report["warnings"]:
        print(f"warning: {warning}")
    for error in report["errors"]:
        print(f"error: {error}")


def main() -> int:
    args = parse_args()
    if args.docx is None and args.pdf is None:
        raise SystemExit("pass --docx, --pdf, or both")
    report = {
        "structural_ok": False,
        "visual_review": "not_performed",
        "errors": [],
        "warnings": [],
    }
    if args.docx is not None:
        inspect_docx(args.docx, report, args)
    if args.pdf is not None:
        inspect_pdf(args.pdf, report, args)
    if args.render_dir is not None:
        inspect_render_dir(args.render_dir, report)
    elif args.pdf is not None:
        report["warnings"].append(
            "rendered page directory not supplied; visual QA remains required"
        )
    report["structural_ok"] = not report["errors"]
    if args.json:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        print_human(report)
    return 0 if report["structural_ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())




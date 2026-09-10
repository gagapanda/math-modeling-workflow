#!/usr/bin/env python
"""Record hashes only after a human has inspected every final rendered page."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from _json_schema import load_and_validate
from _workflow_common import (
    atomic_write_json as atomic_write,
    resolve_path_inside as resolve_inside,
    sha256_file,
)


VISUAL_REVIEW_SCHEMA = (
    Path(__file__).resolve().parent.parent / "schemas" / "visual-review.schema.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--pdf", type=Path)
    parser.add_argument("--render-dir", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        help="Output record path relative to the case directory",
    )
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--notes", default="All final pages were inspected.")
    parser.add_argument("--confirm-all-pages-reviewed", action="store_true")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    return parser.parse_args()


def build_record(case_dir: Path, pdf: Path, render_dir: Path, reviewer: str, notes: str) -> dict:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError("pypdf is required to count final PDF pages") from exc
    if not pdf.is_file():
        raise ValueError(f"PDF does not exist: {pdf}")
    if not render_dir.is_dir():
        raise ValueError(f"render directory does not exist: {render_dir}")
    page_count = len(PdfReader(str(pdf)).pages)
    numbered_pages = []
    for page in render_dir.glob("*.png"):
        match = re.fullmatch(r"page-(\d+)\.png", page.name)
        if match:
            numbered_pages.append((int(match.group(1)), page))
    numbered_pages.sort()
    expected = list(range(1, page_count + 1))
    actual = [number for number, _ in numbered_pages]
    if actual != expected:
        raise ValueError(f"rendered pages must be exactly {expected}; found {actual}")
    for _, page in numbered_pages:
        if not page.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError(f"rendered page is not a PNG: {page.name}")
    return {
        "inspection_scope": "all_pages",
        "schema_version": 1,
        "status": "passed",
        "reviewed_at": datetime.now().astimezone().isoformat(),
        "reviewer": reviewer.strip(),
        "pdf_sha256": sha256_file(pdf),
        "page_count": page_count,
        "reviewed_pages": expected,
        "rendered_pages_sha256": {
            page.name: sha256_file(page) for _, page in numbered_pages
        },
        "notes": notes.strip(),
    }


def main() -> int:
    args = parse_args()
    report = {"recorded": False, "errors": []}
    try:
        case_dir = args.case_dir.expanduser().resolve()
        if not case_dir.is_dir():
            raise ValueError(f"case directory does not exist: {case_dir}")
        if not args.confirm_all_pages_reviewed:
            raise ValueError("--confirm-all-pages-reviewed is required after actual inspection")
        if not args.reviewer.strip():
            raise ValueError("reviewer must be non-empty")
        pdf = resolve_inside(case_dir, args.pdf or Path("paper/paper.pdf"), "PDF")
        render_dir = resolve_inside(
            case_dir, args.render_dir or Path("paper/rendered-pages"), "render directory"
        )
        output = resolve_inside(
            case_dir, args.output or Path("paper/visual-review.json"), "output record"
        )
        record = build_record(case_dir, pdf, render_dir, args.reviewer, args.notes)
        load_and_validate(record, VISUAL_REVIEW_SCHEMA, "visual review record")
        atomic_write(output, record)
        report.update({"recorded": True, "path": str(output), "record": record})
    except (OSError, ValueError) as exc:
        report["errors"].append(str(exc))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"recorded={str(report['recorded']).lower()}")
        if report.get("path"):
            print(f"path={report['path']}")
        for error in report["errors"]:
            print(f"error: {error}")
    return 0 if report["recorded"] else 2


if __name__ == "__main__":
    raise SystemExit(main())


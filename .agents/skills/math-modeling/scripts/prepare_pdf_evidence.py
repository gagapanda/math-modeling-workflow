#!/usr/bin/env python
"""Prepare a small, hash-bound set of PDF pages for OCR and human review."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import uuid
from pathlib import Path

from PIL import Image
from pypdf import PdfReader

from _json_schema import load_and_validate
from _workflow_common import atomic_write_json, sha256_file
from preflight import resolve_poppler_executable


SKILL_DIR = Path(__file__).resolve().parents[1]
PLAN_SCHEMA = SKILL_DIR / "schemas" / "pdf-evidence-plan.schema.json"
MANIFEST_SCHEMA = SKILL_DIR / "schemas" / "pdf-evidence-manifest.schema.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--json", action="store_true", help="Emit the complete result")
    return parser.parse_args()


def _load_plan(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read PDF evidence plan: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("PDF evidence plan must be a JSON object")
    load_and_validate(payload, PLAN_SCHEMA, "PDF evidence plan")
    return payload


def _resolve_source(plan_path: Path, value: str) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = plan_path.parent / candidate
    return candidate.resolve()


def _render_page(renderer: str, source: Path, page: int, dpi: int, target: Path) -> None:
    completed = subprocess.run(
        [renderer, "-f", str(page), "-l", str(page), "-singlefile", "-png", "-r", str(dpi), str(source), str(target.with_suffix(""))],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise ValueError(f"Poppler failed for page {page}: {detail or completed.returncode}")
    if not target.is_file() or not target.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError(f"renderer did not create a valid PNG for page {page}")


def _create_staging_directory(parent: Path, output_name: str) -> Path:
    """Create a private-name directory without tempfile's restrictive Windows ACL."""
    for _ in range(16):
        candidate = parent / f".{output_name}.{uuid.uuid4().hex}"
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return candidate
    raise OSError("cannot allocate a unique PDF evidence staging directory")


def prepare(plan_path: Path, output_dir: Path) -> dict:
    plan_path = plan_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists():
        raise ValueError(f"output directory already exists: {output_dir}")
    if not output_dir.parent.is_dir():
        raise ValueError(f"output parent does not exist: {output_dir.parent}")
    plan = _load_plan(plan_path)
    pages = plan["pages"]
    if pages != sorted(pages):
        raise ValueError("pages must be in strictly increasing order")
    source = _resolve_source(plan_path, plan["source_pdf"])
    if not source.is_file() or source.suffix.casefold() != ".pdf":
        raise ValueError(f"source PDF does not exist or is not a PDF: {source}")
    before = sha256_file(source)
    if before != plan["source_sha256"]:
        raise ValueError("source PDF SHA-256 does not match the plan")
    try:
        reader = PdfReader(str(source))
    except Exception as exc:
        raise ValueError(f"cannot parse source PDF: {exc}") from exc
    if reader.is_encrypted:
        raise ValueError("source PDF must not be encrypted")
    page_count = len(reader.pages)
    if not page_count:
        raise ValueError("source PDF has no pages")
    if pages[-1] > page_count:
        raise ValueError(f"selected page {pages[-1]} exceeds PDF page count {page_count}")
    renderer = resolve_poppler_executable("pdftoppm")
    if not renderer:
        raise ValueError("a working pdftoppm executable is required")

    staging = _create_staging_directory(output_dir.parent, output_dir.name)
    try:
        page_dir = staging / "pages"
        text_dir = staging / "native-text"
        page_dir.mkdir()
        text_dir.mkdir()
        records = []
        for page_number in pages:
            image = page_dir / f"page-{page_number}.png"
            _render_page(renderer, source, page_number, plan["dpi"], image)
            with Image.open(image) as opened:
                opened.verify()
            with Image.open(image) as opened:
                width, height = opened.size
            native_text = reader.pages[page_number - 1].extract_text() or ""
            text_path = text_dir / f"page-{page_number}.txt"
            text_path.write_text(native_text, encoding="utf-8", newline="\n")
            records.append(
                {
                    "page": page_number,
                    "image": image.relative_to(staging).as_posix(),
                    "image_sha256": sha256_file(image),
                    "width": width,
                    "height": height,
                    "native_text": text_path.relative_to(staging).as_posix(),
                    "native_text_sha256": sha256_file(text_path),
                    "native_text_characters": len(native_text),
                }
            )
        after = sha256_file(source)
        if after != before:
            raise ValueError("source PDF changed while selected pages were prepared")
        manifest = {
            "schema_version": 1,
            "status": "prepared",
            "plan_sha256": sha256_file(plan_path),
            "source": {
                "path": str(source),
                "sha256": before,
                "label": plan["source_label"],
                "provenance": plan["source_provenance"],
                "page_count": page_count,
            },
            "purpose": plan["purpose"],
            "dpi": plan["dpi"],
            "renderer": renderer,
            "pages": records,
            "source_unchanged": True,
            "limitations": [
                "native PDF text and OCR output are retrieval aids, not formula truth",
                "every selected page must be visually reviewed against its rendered PNG",
                "only formulas explicitly marked verified in a hash-bound human review may enter an evidence card",
            ],
        }
        load_and_validate(manifest, MANIFEST_SCHEMA, "PDF evidence manifest")
        atomic_write_json(staging / "manifest.json", manifest)
        staging.replace(output_dir)
        return manifest
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def main() -> int:
    args = parse_args()
    result = {"prepared": False, "errors": []}
    try:
        manifest = prepare(args.plan, args.output_dir)
        result.update({"prepared": True, "manifest": manifest, "path": str(args.output_dir.expanduser().resolve() / "manifest.json")})
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        result["errors"].append(str(exc))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"prepared={str(result['prepared']).lower()}")
        for error in result["errors"]:
            print(f"error: {error}")
    return 0 if result["prepared"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

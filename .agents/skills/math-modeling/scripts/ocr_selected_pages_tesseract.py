#!/usr/bin/env python
"""Run hash-bound Tesseract OCR on only the pages in a prepared evidence manifest."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import uuid
from datetime import datetime
from pathlib import Path

from _json_schema import load_and_validate
from _workflow_common import atomic_write_json, atomic_write_text, sha256_file


SKILL_DIR = Path(__file__).resolve().parents[1]
SOURCE_SCHEMA = SKILL_DIR / "schemas" / "pdf-evidence-manifest.schema.json"
RUN_SCHEMA = SKILL_DIR / "schemas" / "ocr-run-manifest.schema.json"
LANGUAGE_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tesseract", type=Path, required=True)
    parser.add_argument("--tessdata-dir", type=Path, required=True)
    parser.add_argument("--language", required=True)
    parser.add_argument("--oem", type=int, default=1, choices=range(4))
    parser.add_argument("--psm", type=int, default=3, choices=range(14))
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--completed-at", help="Explicit timezone-aware audit timestamp")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def _load_manifest(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read prepared manifest: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("prepared manifest must be a JSON object")
    load_and_validate(payload, SOURCE_SCHEMA, "prepared manifest")
    return payload


def _version(executable: Path, timeout: int) -> str:
    completed = subprocess.run(
        [str(executable), "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=timeout,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise ValueError(f"cannot query Tesseract version: {detail or completed.returncode}")
    first_line = completed.stdout.splitlines()[0].strip() if completed.stdout.splitlines() else ""
    if not first_line:
        raise ValueError("Tesseract version output is empty")
    return first_line


def _run_page(
    executable: Path,
    image: Path,
    tessdata_dir: Path,
    language: str,
    oem: int,
    psm: int,
    timeout: int,
) -> tuple[str, str]:
    completed = subprocess.run(
        [
            str(executable),
            str(image),
            "stdout",
            "--tessdata-dir",
            str(tessdata_dir),
            "-l",
            language,
            "--oem",
            str(oem),
            "--psm",
            str(psm),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=timeout,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise ValueError(f"Tesseract failed for {image.name}: {detail or completed.returncode}")
    return completed.stdout, completed.stderr.strip()


def run_selected_pages(
    manifest_path: Path,
    output_dir: Path,
    executable: Path,
    tessdata_dir: Path,
    language: str,
    oem: int,
    psm: int,
    timeout: int,
    completed_at: str | None = None,
) -> dict:
    manifest_path = manifest_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    executable = executable.expanduser().resolve()
    tessdata_dir = tessdata_dir.expanduser().resolve()
    if output_dir.exists():
        raise ValueError(f"output directory already exists: {output_dir}")
    if not output_dir.parent.is_dir():
        raise ValueError(f"output parent does not exist: {output_dir.parent}")
    if not executable.is_file():
        raise ValueError(f"Tesseract executable does not exist: {executable}")
    if not LANGUAGE_PATTERN.fullmatch(language):
        raise ValueError("language must be one explicit Tesseract model id")
    model = tessdata_dir / f"{language}.traineddata"
    if not model.is_file():
        raise ValueError(f"Tesseract language model does not exist: {model}")
    auxiliary_models = [
        {"path": str(path), "sha256": sha256_file(path)}
        for path in sorted(tessdata_dir.glob("*.traineddata"))
        if path != model
    ]
    if timeout < 1:
        raise ValueError("timeout must be positive")
    if completed_at is None:
        completed_at = datetime.now().astimezone().isoformat()
    else:
        try:
            parsed_time = datetime.fromisoformat(completed_at)
        except ValueError as exc:
            raise ValueError("completed_at must be an ISO 8601 timestamp") from exc
        if parsed_time.tzinfo is None:
            raise ValueError("completed_at must include a timezone offset")
        completed_at = parsed_time.isoformat()

    source = _load_manifest(manifest_path)
    version = _version(executable, timeout)
    staging = output_dir.parent / f".{output_dir.name}.{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        records = []
        for page in source["pages"]:
            image = (manifest_path.parent / page["image"]).resolve()
            if not image.is_file() or sha256_file(image) != page["image_sha256"]:
                raise ValueError(f"prepared page image is missing or changed: page {page['page']}")
            content, warning = _run_page(
                executable, image, tessdata_dir, language, oem, psm, timeout
            )
            text_path = staging / f"page-{page['page']}.txt"
            atomic_write_text(text_path, content)
            records.append(
                {
                    "page": page["page"],
                    "image": str(image),
                    "image_sha256": page["image_sha256"],
                    "text": text_path.name,
                    "text_sha256": sha256_file(text_path),
                    "text_characters": len(content),
                    "stderr": warning,
                }
            )
        result = {
            "schema_version": 1,
            "status": "completed",
            "completed_at": completed_at,
            "source_manifest": {
                "path": str(manifest_path),
                "sha256": sha256_file(manifest_path),
            },
            "engine": {
                "path": str(executable),
                "sha256": sha256_file(executable),
                "version": version,
            },
            "configuration": {
                "backend": "tesseract",
                "language": language,
                "model": str(model),
                "model_sha256": sha256_file(model),
                "auxiliary_models": auxiliary_models,
                "tessdata_dir": str(tessdata_dir),
                "oem": oem,
                "psm": psm,
            },
            "pages": records,
            "limitations": [
                "OCR output is a retrieval candidate and never formula truth",
                "the run covers only the pages declared by the prepared evidence manifest",
                "backend adoption requires scoring against named human-confirmed truth",
            ],
        }
        load_and_validate(result, RUN_SCHEMA, "OCR run manifest")
        atomic_write_json(staging / "manifest.json", result)
        staging.replace(output_dir)
        return result
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def main() -> int:
    args = parse_args()
    result = {"completed": False, "errors": []}
    try:
        manifest = run_selected_pages(
            args.manifest,
            args.output_dir,
            args.tesseract,
            args.tessdata_dir,
            args.language,
            args.oem,
            args.psm,
            args.timeout,
            args.completed_at,
        )
        result.update(
            {
                "completed": True,
                "path": str(args.output_dir.expanduser().resolve() / "manifest.json"),
                "manifest": manifest,
            }
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        result["errors"].append(str(exc))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"completed={str(result['completed']).lower()}")
        for error in result["errors"]:
            print(f"error: {error}")
    return 0 if result["completed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

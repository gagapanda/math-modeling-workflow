#!/usr/bin/env python
"""Validate the pinned Tesseract recovery manifest and every bound file."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from _json_schema import load_and_validate
from _workflow_common import sha256_file


SKILL_DIR = Path(__file__).resolve().parents[1]
SCHEMA = SKILL_DIR / "schemas" / "tesseract-recovery.schema.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def resolve_inside(base: Path, value: str, label: str) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(base.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} escapes its allowed root: {resolved}") from exc
    return resolved


def verify_file(path: Path, binding: dict, label: str) -> dict:
    if not path.is_file():
        raise ValueError(f"{label} does not exist: {path}")
    actual_bytes = path.stat().st_size
    if actual_bytes != binding["bytes"]:
        raise ValueError(
            f"{label} byte size mismatch: expected {binding['bytes']}, got {actual_bytes}"
        )
    actual_sha256 = sha256_file(path)
    if actual_sha256 != binding["sha256"]:
        raise ValueError(f"{label} SHA-256 mismatch")
    return {
        "label": label,
        "path": str(path),
        "bytes": actual_bytes,
        "sha256": actual_sha256,
        "verified": True,
    }


def verify_recovery_manifest(manifest_path: Path, project_root: Path) -> dict:
    manifest_path = manifest_path.expanduser().resolve()
    project_root = project_root.expanduser().resolve()
    if not project_root.is_dir():
        raise ValueError(f"project root does not exist: {project_root}")
    try:
        manifest_path.relative_to(project_root)
    except ValueError as exc:
        raise ValueError("recovery manifest must be inside the project root") from exc
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read recovery manifest: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError("recovery manifest must be a JSON object")
    load_and_validate(manifest, SCHEMA, "Tesseract recovery manifest")

    recovery_root = manifest_path.parent.resolve()
    verified_files = []
    installer = manifest["engine"]["installer"]
    verified_files.append(
        verify_file(
            resolve_inside(recovery_root, installer["path"], "engine installer"),
            installer,
            "engine installer",
        )
    )
    for index, model in enumerate(manifest["models"]["files"], start=1):
        verified_files.append(
            verify_file(
                resolve_inside(recovery_root, model["path"], f"model file {index}"),
                model,
                f"model file {index}",
            )
        )
    benchmark = manifest["benchmark_report"]
    verified_files.append(
        verify_file(
            resolve_inside(project_root, str(recovery_root / benchmark["path"]), "benchmark report"),
            benchmark,
            "benchmark report",
        )
    )

    installed = manifest["engine"]["installed_executable"]
    installed_path = Path(installed["path"]).expanduser().resolve()
    installed_status = {"path": str(installed_path), "present": installed_path.is_file()}
    if installed_path.is_file():
        try:
            installed_status.update(verify_file(installed_path, installed, "installed executable"))
        except ValueError as exc:
            installed_status["verified"] = False
            installed_status["error"] = str(exc)

    return {
        "schema_version": 1,
        "command": "verify_tesseract_recovery",
        "manifest": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "passed": True,
        "verified_files": verified_files,
        "installed_executable": installed_status,
        "errors": [],
    }


def main() -> int:
    args = parse_args()
    try:
        report = verify_recovery_manifest(args.manifest, args.project_root)
    except (OSError, ValueError) as exc:
        report = {
            "schema_version": 1,
            "command": "verify_tesseract_recovery",
            "manifest": str(args.manifest.expanduser().resolve()),
            "passed": False,
            "verified_files": [],
            "errors": [str(exc)],
        }
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

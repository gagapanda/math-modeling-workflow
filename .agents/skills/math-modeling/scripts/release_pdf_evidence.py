#!/usr/bin/env python
"""Release a PDF evidence card only after complete hash-bound human review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from _json_schema import load_and_validate
from _workflow_common import atomic_write_json, sha256_file


SKILL_DIR = Path(__file__).resolve().parents[1]
MANIFEST_SCHEMA = SKILL_DIR / "schemas" / "pdf-evidence-manifest.schema.json"
REVIEW_SCHEMA = SKILL_DIR / "schemas" / "pdf-evidence-review.schema.json"
CARD_SCHEMA = SKILL_DIR / "schemas" / "pdf-evidence-card.schema.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--json", action="store_true", help="Emit the complete result")
    return parser.parse_args()


def _load(path: Path, schema: Path, label: str) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    load_and_validate(payload, schema, label)
    return payload


def _require_unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} values must be unique")


def release(manifest_path: Path, review_path: Path, output: Path) -> dict:
    manifest_path = manifest_path.expanduser().resolve()
    review_path = review_path.expanduser().resolve()
    output = output.expanduser().resolve()
    if output.exists():
        raise ValueError(f"output already exists: {output}")
    if not output.parent.is_dir():
        raise ValueError(f"output parent does not exist: {output.parent}")
    manifest = _load(manifest_path, MANIFEST_SCHEMA, "PDF evidence manifest")
    review = _load(review_path, REVIEW_SCHEMA, "PDF evidence review")
    manifest_sha = sha256_file(manifest_path)
    if review["manifest_sha256"] != manifest_sha:
        raise ValueError("review is not bound to the current manifest")
    source = Path(manifest["source"]["path"])
    if not source.is_file() or sha256_file(source) != manifest["source"]["sha256"]:
        raise ValueError("source PDF is missing or changed after preparation")

    manifest_pages = {entry["page"]: entry for entry in manifest["pages"]}
    review_pages = {entry["page"]: entry for entry in review["pages"]}
    if len(review_pages) != len(review["pages"]):
        raise ValueError("review page numbers must be unique")
    if set(review_pages) != set(manifest_pages):
        raise ValueError("review must cover every selected page exactly once")
    for number, prepared in manifest_pages.items():
        image = manifest_path.parent / prepared["image"]
        native_text = manifest_path.parent / prepared["native_text"]
        if not image.is_file() or sha256_file(image) != prepared["image_sha256"]:
            raise ValueError(f"prepared image for page {number} is missing or changed")
        if not native_text.is_file() or sha256_file(native_text) != prepared["native_text_sha256"]:
            raise ValueError(f"native text for page {number} is missing or changed")
        if review_pages[number]["image_sha256"] != prepared["image_sha256"]:
            raise ValueError(f"review image hash does not match prepared page {number}")

    _require_unique([entry["id"] for entry in review["formulas"]], "formula id")
    _require_unique([entry["id"] for entry in review["insights"]], "insight id")
    selected = set(manifest_pages)
    if any(entry["page"] not in selected for entry in review["formulas"] + review["insights"]):
        raise ValueError("formula and insight pages must be selected pages")
    verified = [entry for entry in review["formulas"] if entry["status"] == "verified"]
    rejected = [entry for entry in review["formulas"] if entry["status"] == "rejected"]
    if any(not entry["verified_transcription"].strip() for entry in verified):
        raise ValueError("verified formulas must have a non-empty verified transcription")
    card = {
        "schema_version": 1,
        "ready": True,
        "manifest_sha256": manifest_sha,
        "review_sha256": sha256_file(review_path),
        "source": manifest["source"],
        "purpose": manifest["purpose"],
        "reviewer": review["reviewer"],
        "reviewed_at": review["reviewed_at"],
        "pages": [
            {
                "page": number,
                "image": manifest_pages[number]["image"],
                "image_sha256": manifest_pages[number]["image_sha256"],
                "ocr_backend": review_pages[number]["ocr_backend"],
                "review_notes": review_pages[number]["notes"],
            }
            for number in sorted(manifest_pages)
        ],
        "verified_formulas": verified,
        "rejected_formulas": rejected,
        "insights": review["insights"],
        "limitations": [
            "the evidence card covers only the selected pages, not the whole source",
            "verified transcription preserves what the page states; it does not establish mathematical correctness",
            "adoption decisions still require problem-specific model, data, validation, and rule review",
        ],
    }
    load_and_validate(card, CARD_SCHEMA, "PDF evidence card")
    atomic_write_json(output, card)
    return card


def main() -> int:
    args = parse_args()
    result = {"released": False, "errors": []}
    try:
        card = release(args.manifest, args.review, args.output)
        result.update({"released": True, "card": card, "path": str(args.output.expanduser().resolve())})
    except (OSError, ValueError) as exc:
        result["errors"].append(str(exc))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"released={str(result['released']).lower()}")
        for error in result["errors"]:
            print(f"error: {error}")
    return 0 if result["released"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

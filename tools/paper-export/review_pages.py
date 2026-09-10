#!/usr/bin/env python
"""Verify all rendered pages and optional AI observations against exact build hashes.

This is a supporting export check, never an M6/human acceptance substitute.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def checked_file(root, item):
    path = (root / item["file"]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("artifact missing or escapes bundle")
    if digest(path) != item["sha256"]:
        raise ValueError("artifact hash mismatch: " + item["file"])
    return path


def verify(manifest, review=None):
    from PIL import Image
    from pypdf import PdfReader
    manifest = Path(manifest).resolve()
    root = manifest.parent
    data = json.loads(manifest.read_text(encoding="utf-8-sig"))
    if data.get("schema_version") != 1 or data.get("submission_ready") is not False:
        raise ValueError("unsupported or falsely accepted export manifest")
    if data.get("status") != "pending_visual_review":
        raise ValueError("build manifest must not claim review acceptance")
    artifacts, pages = data["artifacts"], data["pages"]
    if not artifacts or len({i["file"] for i in artifacts}) != len(artifacts):
        raise ValueError("empty or duplicate artifacts")
    paths = [checked_file(root, item) for item in artifacts]
    pdfs = [p for p in paths if p.suffix.lower() == ".pdf"]
    docxs = [p for p in paths if p.suffix.lower() == ".docx"]
    if len(pdfs) != 1 or len(docxs) != 1 or not pages:
        raise ValueError("full DOCX/PDF/page bundle required; DOCX-only is not page-ready")
    count = len(PdfReader(pdfs[0]).pages)
    if data["page_count"] != count or [p["page"] for p in pages] != list(range(1, count + 1)):
        raise ValueError("page coverage mismatch")
    if len({p["file"] for p in pages}) != count:
        raise ValueError("duplicate page images")
    for page in pages:
        path = checked_file(root, page)
        with Image.open(path) as image:
            image.verify()
    result = {"bundle_integrity": "passed", "page_count": count,
              "manifest_sha256": digest(manifest), "visual_review": "pending",
              "submission_ready": False, "human_acceptance": "not_recorded"}
    if review is not None:
        review_path = Path(review)
        review = json.loads(review_path.read_text(encoding="utf-8-sig"))
        if review.get("manifest_sha256") != digest(manifest) or review.get("reviewer_kind") != "ai":
            raise ValueError("AI review must bind this exact manifest; human signoff uses the main workflow")
        observations = review.get("pages", [])
        if [p["page"] for p in observations] != list(range(1, count + 1)):
            raise ValueError("review must cover every page exactly once in order")
        for image, observation in zip(pages, observations):
            if observation.get("sha256") != image["sha256"]:
                raise ValueError("review image hash mismatch")
            notes = observation.get("notes")
            if observation.get("status") not in {"pass", "fail"} or not isinstance(notes, str) or not notes.strip():
                raise ValueError("each page needs an explicit judgement and observations")
        result["visual_review"] = "ai_pass" if all(x["status"] == "pass" for x in observations) else "ai_fail"
        result["review_sha256"] = digest(review_path)
        # Shape/hash validation cannot prove a reviewer actually looked at an image.
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--review", type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.manifest, args.review)
    except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        parser.exit(2, f"page evidence rejected: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result["visual_review"] == "ai_fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())


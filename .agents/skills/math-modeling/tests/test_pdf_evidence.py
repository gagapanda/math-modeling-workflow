from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfWriter


SKILL_DIR = Path(__file__).resolve().parents[1]
PREPARE = SKILL_DIR / "scripts" / "prepare_pdf_evidence.py"
RELEASE = SKILL_DIR / "scripts" / "release_pdf_evidence.py"


class PdfEvidenceTests(unittest.TestCase):
    def make_source(self, root: Path) -> Path:
        source = root / "source.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        writer.add_blank_page(width=595, height=842)
        with source.open("wb") as stream:
            writer.write(stream)
        return source

    def write_plan(self, root: Path, source: Path, **updates) -> Path:
        plan = {
            "schema_version": 1,
            "source_pdf": str(source),
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "source_label": "controlled two-page PDF",
            "source_provenance": {
                "status": "other",
                "note": "generated fixture for mechanical workflow tests",
            },
            "purpose": "verify selected-page evidence preparation",
            "pages": [1, 2],
            "dpi": 120,
        }
        plan.update(updates)
        path = root / "plan.json"
        path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        return path

    def run_prepare(self, plan: Path, output: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(PREPARE), "--plan", str(plan), "--output-dir", str(output), "--json"],
            capture_output=True,
            text=True,
            check=False,
        )

    def run_release(self, manifest: Path, review: Path, output: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(RELEASE), "--manifest", str(manifest), "--review", str(review), "--output", str(output), "--json"],
            capture_output=True,
            text=True,
            check=False,
        )

    def prepare_fixture(self, root: Path) -> tuple[Path, Path, dict]:
        source = self.make_source(root)
        plan = self.write_plan(root, source)
        output = root / "prepared"
        completed = self.run_prepare(plan, output)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        manifest_path = output / "manifest.json"
        return source, manifest_path, json.loads(manifest_path.read_text(encoding="utf-8"))

    def make_review(self, root: Path, manifest_path: Path, manifest: dict) -> Path:
        review = {
            "schema_version": 1,
            "status": "passed",
            "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "reviewer": "controlled-reviewer",
            "reviewed_at": "2026-08-17T12:00:00+08:00",
            "pages": [
                {
                    "page": page["page"],
                    "image_sha256": page["image_sha256"],
                    "visual_confirmed": True,
                    "ocr_backend": "manual_transcription",
                    "ocr_text": "candidate text",
                    "notes": "image inspected against the selected source page",
                }
                for page in manifest["pages"]
            ],
            "formulas": [
                {
                    "id": "formula.verified",
                    "page": 1,
                    "status": "verified",
                    "ocr_transcription": "x=I",
                    "verified_transcription": "x=1",
                    "visual_location": "page center",
                    "notes": "corrected OCR I to digit 1 after visual comparison",
                },
                {
                    "id": "formula.rejected",
                    "page": 2,
                    "status": "rejected",
                    "ocr_transcription": "unreadable",
                    "verified_transcription": "",
                    "visual_location": "page center",
                    "notes": "image does not support a reliable transcription",
                },
            ],
            "insights": [
                {
                    "id": "structure.1",
                    "page": 1,
                    "category": "structure",
                    "claim": "The page separates assumptions from derivation.",
                    "decision": "reference",
                    "rationale": "Useful organization, but not model evidence.",
                }
            ],
        }
        path = root / "review.json"
        path.write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
        return path

    def test_prepare_is_read_only_hash_bound_and_selective(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.make_source(root)
            before = source.read_bytes()
            plan = self.write_plan(root, source, pages=[2])
            output = root / "prepared"
            completed = self.run_prepare(plan, output)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(source.read_bytes(), before)
            self.assertTrue(manifest["source_unchanged"])
            self.assertEqual([page["page"] for page in manifest["pages"]], [2])
            self.assertTrue((output / "pages" / "page-2.png").is_file())
            self.assertFalse((output / "pages" / "page-1.png").exists())
            self.assertEqual(manifest["pages"][0]["native_text_characters"], 0)

    def test_prepare_rejects_hash_page_order_range_and_existing_output_without_partial_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.make_source(root)
            cases = [
                ("hash", {"source_sha256": "0" * 64}, "SHA-256"),
                ("order", {"pages": [2, 1]}, "strictly increasing"),
                ("range", {"pages": [3]}, "exceeds PDF page count"),
            ]
            for name, updates, message in cases:
                plan = self.write_plan(root, source, **updates)
                output = root / name
                completed = self.run_prepare(plan, output)
                self.assertEqual(completed.returncode, 2)
                self.assertIn(message, completed.stdout)
                self.assertFalse(output.exists())
            occupied = root / "occupied"
            occupied.mkdir()
            completed = self.run_prepare(self.write_plan(root, source), occupied)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("already exists", completed.stdout)

    def test_release_promotes_only_verified_formulas_and_binds_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, manifest_path, manifest = self.prepare_fixture(root)
            review = self.make_review(root, manifest_path, manifest)
            card_path = root / "evidence-card.json"
            completed = self.run_release(manifest_path, review, card_path)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            card = json.loads(card_path.read_text(encoding="utf-8"))
            self.assertTrue(card["ready"])
            self.assertEqual([item["id"] for item in card["verified_formulas"]], ["formula.verified"])
            self.assertEqual([item["id"] for item in card["rejected_formulas"]], ["formula.rejected"])

    def test_release_blocks_incomplete_stale_or_tampered_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, manifest_path, manifest = self.prepare_fixture(root)
            review_path = self.make_review(root, manifest_path, manifest)
            review = json.loads(review_path.read_text(encoding="utf-8"))
            review["pages"] = review["pages"][:1]
            review_path.write_text(json.dumps(review), encoding="utf-8")
            incomplete = self.run_release(manifest_path, review_path, root / "incomplete.json")
            self.assertEqual(incomplete.returncode, 2)
            self.assertIn("cover every selected page", incomplete.stdout)

            review_path = self.make_review(root, manifest_path, manifest)
            review = json.loads(review_path.read_text(encoding="utf-8"))
            review["manifest_sha256"] = "0" * 64
            review_path.write_text(json.dumps(review), encoding="utf-8")
            stale = self.run_release(manifest_path, review_path, root / "stale.json")
            self.assertEqual(stale.returncode, 2)
            self.assertIn("not bound", stale.stdout)

            review_path = self.make_review(root, manifest_path, manifest)
            image = manifest_path.parent / manifest["pages"][0]["image"]
            image.write_bytes(image.read_bytes() + b"tampered")
            tampered = self.run_release(manifest_path, review_path, root / "tampered.json")
            self.assertEqual(tampered.returncode, 2)
            self.assertIn("missing or changed", tampered.stdout)


if __name__ == "__main__":
    unittest.main()

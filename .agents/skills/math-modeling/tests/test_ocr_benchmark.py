from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCORER = SKILL_DIR / "scripts" / "score_ocr_benchmark.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class OcrBenchmarkTests(unittest.TestCase):
    def make_fixture(
        self,
        root: Path,
        *,
        benchmark_status: str,
        ocr_text: str,
        feature_status: str,
    ) -> tuple[Path, Path, Path]:
        prepared = root / "prepared"
        image = prepared / "pages" / "page-1.png"
        image.parent.mkdir(parents=True)
        image.write_bytes(b"controlled image bytes")
        manifest = prepared / "manifest.json"
        write_json(
            manifest,
            {
                "pages": [
                    {
                        "page": 1,
                        "image": "pages/page-1.png",
                        "image_sha256": sha256(image),
                    }
                ]
            },
        )
        evidence = root / "evidence-card.json"
        write_json(
            evidence,
            {
                "verified_formulas": [
                    {
                        "id": "formula.one",
                        "verified_transcription": "x=-1",
                    }
                ]
            },
        )
        benchmark = root / "benchmark.json"
        write_json(
            benchmark,
            {
                "schema_version": 1,
                "status": benchmark_status,
                "prepared_manifest": {"path": "prepared/manifest.json", "sha256": sha256(manifest)},
                "evidence_card": {"path": "evidence-card.json", "sha256": sha256(evidence)},
                "purpose": "controlled OCR scoring fixture",
                "body_text": {
                    "page": 1,
                    "image_sha256": sha256(image),
                    "location": "controlled paragraph",
                    "reference_text": "问题二",
                    "transcribed_by": "fixture",
                    "human_reviewer": "reviewer" if benchmark_status == "confirmed" else "",
                    "reviewed_at": "2026-08-18T12:00:00+08:00" if benchmark_status == "confirmed" else "",
                },
                "formulas": [
                    {
                        "id": "formula.one",
                        "page": 1,
                        "verified_transcription": "x=-1",
                        "features": [
                            {"id": "negative", "description": "negative sign", "risk": "high"}
                        ],
                    }
                ],
                "thresholds": {
                    "max_body_text_cer": 0.15,
                    "min_formula_detection_recall": 1.0,
                    "min_formula_feature_recall": 1.0,
                    "require_all_high_risk_features": True,
                },
                "limitations": ["controlled fixture only"],
            },
        )
        ocr_dir = root / "ocr"
        ocr_dir.mkdir()
        ocr_file = ocr_dir / "page-1.txt"
        ocr_file.write_text(ocr_text, encoding="utf-8")
        review = root / "review.json"
        write_json(
            review,
            {
                "schema_version": 1,
                "status": "completed",
                "benchmark_sha256": sha256(benchmark),
                "backend": "controlled",
                "model": "fixture",
                "layout_analysis": "page",
                "evaluated_by": "fixture",
                "evaluated_at": "2026-08-18T12:01:00+08:00",
                "ocr_files": [{"page": 1, "path": "page-1.txt", "sha256": sha256(ocr_file)}],
                "formula_results": [
                    {
                        "id": "formula.one",
                        "detected": True,
                        "usable_without_correction": feature_status == "correct",
                        "features": [
                            {"id": "negative", "status": feature_status, "notes": "controlled result"}
                        ],
                        "notes": "controlled formula review",
                    }
                ],
                "notes": ["controlled fixture only"],
            },
        )
        return benchmark, review, ocr_dir

    def run_score(self, benchmark: Path, review: Path, ocr_dir: Path, output: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCORER),
                "--benchmark",
                str(benchmark),
                "--review",
                str(review),
                "--ocr-dir",
                str(ocr_dir),
                "--output",
                str(output),
                "--json",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    def test_confirmed_exact_candidate_is_adopted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            benchmark, review, ocr_dir = self.make_fixture(
                root,
                benchmark_status="confirmed",
                ocr_text="页眉 问 题 二。页脚",
                feature_status="correct",
            )
            output = root / "report.json"
            completed = self.run_score(benchmark, review, ocr_dir, output)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "final")
            self.assertEqual(report["body_text"]["normalized_cer"], 0)
            self.assertEqual(report["decisions"]["production_default"], "adopt")
            self.assertEqual(report["decisions"]["body_text_retrieval"], "adopt")
            self.assertEqual(report["decisions"]["formula_retrieval"], "adopt")

    def test_draft_bad_candidate_is_provisional_and_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            benchmark, review, ocr_dir = self.make_fixture(
                root,
                benchmark_status="draft",
                ocr_text="WENTI ER",
                feature_status="incorrect",
            )
            output = root / "report.json"
            completed = self.run_score(benchmark, review, ocr_dir, output)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "provisional")
            self.assertEqual(report["body_text"]["normalized_cer"], 1)
            self.assertEqual(report["decisions"]["current_configuration"], "reject")
            self.assertEqual(report["decisions"]["body_text_retrieval"], "reject")
            self.assertEqual(report["decisions"]["formula_retrieval"], "reject")
            self.assertEqual(
                report["decisions"]["production_default"],
                "blocked_pending_named_human_confirmation",
            )

    def test_changed_ocr_output_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            benchmark, review, ocr_dir = self.make_fixture(
                root,
                benchmark_status="confirmed",
                ocr_text="问题二",
                feature_status="correct",
            )
            (ocr_dir / "page-1.txt").write_text("tampered", encoding="utf-8")
            completed = self.run_score(benchmark, review, ocr_dir, root / "report.json")
            self.assertEqual(completed.returncode, 2)
            self.assertIn("SHA-256", completed.stdout)


if __name__ == "__main__":
    unittest.main()

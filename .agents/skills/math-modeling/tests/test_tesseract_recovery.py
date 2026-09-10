from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_DIR / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import verify_tesseract_recovery as target  # noqa: E402


def binding(path: str, file_path: Path) -> dict:
    return {
        "path": path,
        "sha256": hashlib.sha256(file_path.read_bytes()).hexdigest(),
        "bytes": file_path.stat().st_size,
    }


class TesseractRecoveryTests(unittest.TestCase):
    def create_fixture(self, root: Path) -> Path:
        recovery = root / ".skill-audit" / "tool-cache" / "tesseract"
        engine = recovery / "engine"
        models = recovery / "models"
        benchmark_dir = root / ".skill-audit" / "pdf-evidence"
        engine.mkdir(parents=True)
        models.mkdir(parents=True)
        benchmark_dir.mkdir(parents=True)
        installer = engine / "installer.exe"
        model = models / "chi_sim.traineddata"
        benchmark = benchmark_dir / "report.json"
        installer.write_bytes(b"installer")
        model.write_bytes(b"model")
        benchmark.write_bytes(b"benchmark")
        manifest = {
            "schema_version": 1,
            "created_at": "2026-08-18T23:59:55+08:00",
            "engine": {
                "package_id": "UB-Mannheim.TesseractOCR",
                "version": "5.4.0",
                "installer": binding("engine/installer.exe", installer),
                "installed_executable": {
                    "path": str(root / "not-installed" / "tesseract.exe"),
                    "sha256": "0" * 64,
                    "bytes": 1,
                },
                "source_url": "https://example.invalid/tesseract.exe",
                "winget_hash_verified": True,
                "authenticode_status": "not independently verified",
                "signer": "test signer",
            },
            "models": {
                "repository": "tesseract-ocr/tessdata_best",
                "commit": "1" * 40,
                "files": [binding("models/chi_sim.traineddata", model)],
            },
            "benchmark_report": binding("../../pdf-evidence/report.json", benchmark),
            "restore_steps": ["verify files"],
            "limitations": ["test fixture"],
        }
        path = recovery / "recovery-manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def test_verifies_schema_hashes_and_sizes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.create_fixture(root)
            report = target.verify_recovery_manifest(manifest, root)
            self.assertTrue(report["passed"])
            self.assertEqual(len(report["verified_files"]), 3)
            self.assertFalse(report["installed_executable"]["present"])

    def test_rejects_tampered_cached_model(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.create_fixture(root)
            model = manifest.parent / "models" / "chi_sim.traineddata"
            model.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "model file 1 byte size mismatch"):
                target.verify_recovery_manifest(manifest, root)

    def test_rejects_cached_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.create_fixture(root)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["engine"]["installer"]["path"] = "../outside.exe"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "engine installer escapes"):
                target.verify_recovery_manifest(manifest, root)


if __name__ == "__main__":
    unittest.main()

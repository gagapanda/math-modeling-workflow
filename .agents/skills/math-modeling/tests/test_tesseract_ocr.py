from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS))

import ocr_selected_pages_tesseract as target  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TesseractOcrTests(unittest.TestCase):
    def make_fixture(self, root: Path) -> tuple[Path, Path, Path]:
        prepared = root / "prepared"
        pages = prepared / "pages"
        native = prepared / "native-text"
        pages.mkdir(parents=True)
        native.mkdir()
        image = pages / "page-3.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\ncontrolled")
        native_text = native / "page-3.txt"
        native_text.write_text("", encoding="utf-8")
        manifest = {
            "schema_version": 1,
            "status": "prepared",
            "plan_sha256": "0" * 64,
            "source": {
                "path": str(root / "source.pdf"),
                "sha256": "1" * 64,
                "label": "controlled source",
                "provenance": {"status": "other"},
                "page_count": 3,
            },
            "purpose": "controlled selected-page OCR",
            "dpi": 300,
            "renderer": "controlled",
            "pages": [
                {
                    "page": 3,
                    "image": "pages/page-3.png",
                    "image_sha256": sha256(image),
                    "width": 1,
                    "height": 1,
                    "native_text": "native-text/page-3.txt",
                    "native_text_sha256": sha256(native_text),
                    "native_text_characters": 0,
                }
            ],
            "source_unchanged": True,
            "limitations": ["controlled fixture"],
        }
        manifest_path = prepared / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        executable = root / "tesseract.exe"
        executable.write_bytes(b"controlled executable")
        tessdata = root / "tessdata"
        tessdata.mkdir()
        (tessdata / "chi_sim.traineddata").write_bytes(b"controlled model")
        return manifest_path, executable, tessdata

    @staticmethod
    def fake_run(args, **kwargs):
        if "--version" in args:
            return subprocess.CompletedProcess(args, 0, "tesseract v5.4.0\n", "")
        return subprocess.CompletedProcess(args, 0, "问题二\n", "resolution estimated")

    def test_run_is_hash_bound_and_records_explicit_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, executable, tessdata = self.make_fixture(root)
            output = root / "ocr"
            with patch.object(target.subprocess, "run", side_effect=self.fake_run):
                result = target.run_selected_pages(
                    manifest,
                    output,
                    executable,
                    tessdata,
                    "chi_sim",
                    1,
                    3,
                    30,
                    "2026-08-18T23:58:00+08:00",
                )
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["completed_at"], "2026-08-18T23:58:00+08:00")
            self.assertEqual(result["configuration"]["language"], "chi_sim")
            self.assertEqual(result["configuration"]["auxiliary_models"], [])
            self.assertEqual(result["configuration"]["oem"], 1)
            self.assertEqual(result["configuration"]["psm"], 3)
            self.assertEqual((output / "page-3.txt").read_text(encoding="utf-8"), "问题二\n")
            self.assertEqual(result["pages"][0]["text_sha256"], sha256(output / "page-3.txt"))

    def test_changed_image_and_existing_output_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, executable, tessdata = self.make_fixture(root)
            output = root / "ocr"
            output.mkdir()
            with self.assertRaisesRegex(ValueError, "already exists"):
                target.run_selected_pages(
                    manifest, output, executable, tessdata, "chi_sim", 1, 3, 30
                )
            output.rmdir()
            (manifest.parent / "pages" / "page-3.png").write_bytes(b"changed")
            with patch.object(target.subprocess, "run", side_effect=self.fake_run):
                with self.assertRaisesRegex(ValueError, "missing or changed"):
                    target.run_selected_pages(
                        manifest, output, executable, tessdata, "chi_sim", 1, 3, 30
                    )
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import importlib.util
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_DIR / "scripts"
PIPELINE_SCRIPT = SCRIPTS / "run_pipeline.py"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def load_pipeline_module():
    spec = importlib.util.spec_from_file_location(
        "math_modeling_pipeline_backend_faults", PIPELINE_SCRIPT
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load run_pipeline.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_pdf(path: Path) -> None:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=595.28, height=841.89)
    with path.open("wb") as stream:
        writer.write(stream)


def write_png(path: Path, red: int = 0) -> None:
    def chunk(name: bytes, payload: bytes) -> bytes:
        checksum = zlib.crc32(name + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + name + payload + struct.pack(">I", checksum)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    pixels = bytes((0, red, 0, 0, 255))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


def backend_config(kind: str, name: str = "fake") -> dict:
    return {
        "backends": {
            kind: {
                "primary": {"name": name, "path": "fake-backend", "usable": True},
                "fallbacks": [],
            }
        }
    }


@unittest.skipUnless(importlib.util.find_spec("pypdf"), "pypdf is unavailable")
class BackendFaultTests(unittest.TestCase):
    def test_export_rejects_empty_and_corrupt_pdf_without_overwriting_previous(self) -> None:
        pipeline = load_pipeline_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            docx = root / "paper.docx"
            pdf = root / "paper.pdf"
            docx.write_bytes(b"docx fixture")
            write_pdf(pdf)
            original = pdf.read_bytes()
            preflight = backend_config("docx_to_pdf", "Microsoft Word")

            for payload, expected in (
                (b"", "nonempty PDF"),
                (b"not-a-pdf", "unreadable PDF"),
            ):
                def fake_export(_docx, target, _cwd, data=payload):
                    target.write_bytes(data)
                    return {"ok": True, "exit_code": 0, "stdout": "", "stderr": ""}

                with patch.object(
                    pipeline, "export_with_word", side_effect=fake_export
                ):
                    report = pipeline.export_docx(docx, pdf, preflight, root)

                self.assertFalse(report["ok"])
                self.assertIn(expected, report["stderr"])
                self.assertEqual(pdf.read_bytes(), original)

    def test_export_replaces_previous_pdf_only_after_validation(self) -> None:
        pipeline = load_pipeline_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            docx = root / "paper.docx"
            pdf = root / "paper.pdf"
            generated = root / "generated.pdf"
            docx.write_bytes(b"docx fixture")
            pdf.write_bytes(b"stale PDF")
            write_pdf(generated)
            preflight = backend_config("docx_to_pdf", "Microsoft Word")

            def fake_export(_docx, target, _cwd):
                target.write_bytes(generated.read_bytes())
                return {"ok": True, "exit_code": 0, "stdout": "", "stderr": ""}

            with patch.object(pipeline, "export_with_word", side_effect=fake_export):
                report = pipeline.export_docx(docx, pdf, preflight, root)

            self.assertTrue(report["ok"])
            self.assertEqual(pdf.read_bytes(), generated.read_bytes())

    def test_renderer_preserves_previous_pages_on_zero_or_invalid_output(self) -> None:
        pipeline = load_pipeline_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf = root / "paper.pdf"
            render_dir = root / "rendered-pages"
            render_dir.mkdir()
            write_pdf(pdf)
            old_page = render_dir / "page-1.png"
            write_png(old_page, red=10)
            original = old_page.read_bytes()
            preflight = backend_config("pdf_to_images", "fake-renderer")

            def no_pages(_command, _cwd, timeout=180):
                return {"ok": True, "exit_code": 0, "stdout": "", "stderr": ""}

            with patch.object(pipeline, "run_command", side_effect=no_pages):
                empty = pipeline.render_pdf(pdf, render_dir, preflight, 150, root)
            self.assertFalse(empty["ok"])
            self.assertIn("created no pages", empty["stderr"])
            self.assertEqual(old_page.read_bytes(), original)

            def invalid_page(command, _cwd, timeout=180):
                Path(f"{command[-1]}-1.png").write_bytes(b"invalid")
                return {"ok": True, "exit_code": 0, "stdout": "", "stderr": ""}

            with patch.object(pipeline, "run_command", side_effect=invalid_page):
                invalid = pipeline.render_pdf(pdf, render_dir, preflight, 150, root)
            self.assertFalse(invalid["ok"])
            self.assertIn("invalid PNG", invalid["stderr"])
            self.assertEqual(old_page.read_bytes(), original)

    def test_renderer_atomically_replaces_stale_page_set(self) -> None:
        pipeline = load_pipeline_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf = root / "paper.pdf"
            render_dir = root / "rendered-pages"
            render_dir.mkdir()
            write_pdf(pdf)
            write_png(render_dir / "page-1.png", red=10)
            write_png(render_dir / "page-2.png", red=20)
            (render_dir / "stale.txt").write_text("stale", encoding="utf-8")
            preflight = backend_config("pdf_to_images", "fake-renderer")

            def one_page(command, _cwd, timeout=180):
                write_png(Path(f"{command[-1]}-1.png"), red=99)
                return {"ok": True, "exit_code": 0, "stdout": "", "stderr": ""}

            with patch.object(pipeline, "run_command", side_effect=one_page):
                report = pipeline.render_pdf(pdf, render_dir, preflight, 150, root)

            self.assertTrue(report["ok"])
            self.assertEqual(report["page_count"], 1)
            self.assertEqual([path.name for path in render_dir.iterdir()], ["page-1.png"])

    def test_renderer_tries_fallback_after_primary_startup_failure(self) -> None:
        pipeline = load_pipeline_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf = root / "paper.pdf"
            render_dir = root / "rendered-pages"
            write_pdf(pdf)
            preflight = {
                "backends": {
                    "pdf_to_images": {
                        "primary": {"name": "broken-pdftoppm", "path": "broken", "usable": True},
                        "fallbacks": [{"name": "working-pdftocairo", "path": "working", "usable": True}],
                    }
                }
            }

            def run(command, _cwd, timeout=180):
                if command[0] == "broken":
                    return {"ok": False, "exit_code": 3, "stdout": "", "stderr": "startup failed"}
                write_png(Path(f"{command[-1]}-1.png"), red=77)
                return {"ok": True, "exit_code": 0, "stdout": "", "stderr": ""}

            with patch.object(pipeline, "run_command", side_effect=run):
                report = pipeline.render_pdf(pdf, render_dir, preflight, 150, root)

            self.assertTrue(report["ok"])
            self.assertEqual(report["backend"], "working-pdftocairo")
            self.assertEqual([attempt["backend"] for attempt in report["attempts"]], ["broken-pdftoppm", "working-pdftocairo"])
            self.assertEqual(report["attempts"][0]["stderr"], "startup failed")
            self.assertTrue((render_dir / "page-1.png").is_file())

    def test_renderer_rejects_noncontinuous_page_names(self) -> None:
        pipeline = load_pipeline_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf = root / "paper.pdf"
            render_dir = root / "rendered-pages"
            render_dir.mkdir()
            write_pdf(pdf)
            write_png(render_dir / "page-1.png", red=10)
            original = (render_dir / "page-1.png").read_bytes()
            preflight = backend_config("pdf_to_images", "fake-renderer")

            def discontinuous(command, _cwd, timeout=180):
                write_png(Path(f"{command[-1]}-1.png"), red=30)
                write_png(Path(f"{command[-1]}-3.png"), red=40)
                return {"ok": True, "exit_code": 0, "stdout": "", "stderr": ""}

            with patch.object(pipeline, "run_command", side_effect=discontinuous):
                report = pipeline.render_pdf(pdf, render_dir, preflight, 150, root)

            self.assertFalse(report["ok"])
            self.assertIn("continuous", report["stderr"])
            self.assertEqual((render_dir / "page-1.png").read_bytes(), original)

    def test_renderer_restores_previous_pages_when_directory_commit_fails(self) -> None:
        pipeline = load_pipeline_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf = root / "paper.pdf"
            render_dir = root / "rendered-pages"
            render_dir.mkdir()
            write_pdf(pdf)
            old_page = render_dir / "page-1.png"
            write_png(old_page, red=10)
            original = old_page.read_bytes()
            preflight = backend_config("pdf_to_images", "fake-renderer")

            def one_page(command, _cwd, timeout=180):
                write_png(Path(f"{command[-1]}-1.png"), red=99)
                return {"ok": True, "exit_code": 0, "stdout": "", "stderr": ""}

            original_replace = Path.replace

            def fail_staging_commit(path: Path, target: Path):
                if (
                    path.name.startswith(".render-")
                    and not path.name.startswith(".render-backup-")
                    and Path(target) == render_dir
                ):
                    raise OSError("injected directory commit failure")
                return original_replace(path, target)

            with (
                patch.object(pipeline, "run_command", side_effect=one_page),
                patch.object(Path, "replace", new=fail_staging_commit),
            ):
                report = pipeline.render_pdf(pdf, render_dir, preflight, 150, root)

            self.assertFalse(report["ok"])
            self.assertIn("atomically replace", report["stderr"])
            self.assertEqual(old_page.read_bytes(), original)
            self.assertEqual([path.name for path in render_dir.iterdir()], ["page-1.png"])

    def test_cli_reports_atomic_report_write_failure_as_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary) / "report-failure"
            case_dir.mkdir()
            (case_dir / "step.py").write_text("print('ok')\n", encoding="utf-8")
            (case_dir / "workflow.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "profile": "explore",
                        "steps": [{"name": "analyze", "script": "step.py"}],
                    }
                ),
                encoding="utf-8",
            )
            report_path = case_dir / ".workflow" / "pipeline-report.json"
            report_path.mkdir(parents=True)
            environment = os.environ.copy()
            environment["PYTHONDONTWRITEBYTECODE"] = "1"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(PIPELINE_SCRIPT),
                    "--case-dir",
                    str(case_dir),
                    "--phase",
                    "build",
                    "--json",
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=environment,
                timeout=30,
            )
            report = json.loads(completed.stdout)

            self.assertEqual(completed.returncode, 2)
            self.assertEqual(report["failure"]["failed_stage"], "report_write")
            self.assertEqual(report["failure"]["cause_code"], "atomic_write_failed")
            self.assertTrue(report["failure"]["retryable"])
            self.assertIn("cannot write pipeline report atomically", "\n".join(report["errors"]))
            self.assertEqual(completed.stderr, "")
            self.assertTrue(report_path.is_dir())


if __name__ == "__main__":
    unittest.main()

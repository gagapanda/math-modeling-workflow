from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
import zlib
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from xml.sax.saxutils import escape


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_DIR / "scripts"
PIPELINE = SCRIPTS / "run_pipeline.py"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def load_finalize_module():
    spec = importlib.util.spec_from_file_location(
        "math_modeling_finalize_blackbox", SCRIPTS / "finalize_case.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load finalize_case.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_docx(path: Path, text: str) -> None:
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'
        f"{escape(text)}"
        "</w:t></w:r></w:p></w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("word/document.xml", document_xml)


def write_text_pdf(path: Path, text: str) -> None:
    from pypdf import PdfWriter
    from pypdf.generic import (
        DecodedStreamObject,
        DictionaryObject,
        NameObject,
    )

    writer = PdfWriter()
    page = writer.add_blank_page(width=595.28, height=841.89)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    with path.open("wb") as output:
        writer.write(output)


def write_png(path: Path) -> None:
    def chunk(name: bytes, payload: bytes) -> bytes:
        checksum = zlib.crc32(name + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + name + payload + struct.pack(">I", checksum)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    pixels = b"\x00\x00\x00\x00\xff"
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_profile_case(case_dir: Path, profile: str, ai_status: str | None = None) -> dict:
    for directory in ("src", "results", "problem", "paper", "paper/rendered-pages"):
        (case_dir / directory).mkdir(parents=True, exist_ok=True)
    (case_dir / "src" / "analyze.py").write_text("print('fixture')\n", encoding="utf-8")
    statement = f"AI disclosure status {ai_status}" if ai_status else ""
    paper_text = "Verified result 42" + (f". {statement}" if statement else "")
    docx = case_dir / "paper" / "paper.docx"
    pdf = case_dir / "paper" / "paper.pdf"
    page = case_dir / "paper" / "rendered-pages" / "page-1.png"
    write_docx(docx, paper_text)
    write_text_pdf(pdf, paper_text)
    write_png(page)

    (case_dir / "results" / "answer.json").write_text(
        json.dumps({"answer": 42}), encoding="utf-8"
    )
    (case_dir / "results" / "result-register.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "results": [
                    {
                        "id": "fixture.answer",
                        "value": 42,
                        "source_file": "results/answer.json",
                        "source_key": "answer",
                        "paper_required": True,
                        "paper_text": "Verified result 42",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (case_dir / "problem" / "model-definition-register.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "assessment_status": "completed",
                "assessment_evidence": "Reviewed the objective, constraints, units, time origin, aggregation, and boundary conventions.",
                "no_material_ambiguity_rationale": "The fixture defines every convention explicitly, and alternate readings cannot change its single scalar result.",
                "ambiguities": [],
            }
        ),
        encoding="utf-8",
    )
    review = {
        "schema_version": 1,
        "status": "passed",
        "reviewed_at": "2026-08-14T00:00:00+00:00",
        "reviewer": "profile-blackbox",
        "pdf_sha256": sha256(pdf),
        "page_count": 1,
        "reviewed_pages": [1],
        "rendered_pages_sha256": {"page-1.png": sha256(page)},
        "notes": "All final pages inspected.",
    }
    (case_dir / "paper" / "visual-review.json").write_text(
        json.dumps(review), encoding="utf-8"
    )

    manifest = {
        "schema_version": 2,
        "profile": profile,
        "steps": [{"name": "analyze", "script": "src/analyze.py"}],
        "artifacts": {
            "docx": "paper/paper.docx",
            "pdf": "paper/paper.pdf",
            "render_dir": "paper/rendered-pages",
            "visual_review": "paper/visual-review.json",
        },
        "audit": {
            "page_size": "a4",
            "orientation": "portrait",
            "forbid": ["TODO"],
        },
    }
    compliance_path = None
    if profile == "submission":
        if ai_status not in {"used", "not-used"}:
            raise ValueError("submission fixture requires an AI status")
        (case_dir / "ai").mkdir()
        (case_dir / "compliance").mkdir()
        (case_dir / "ai" / "ai-usage.md").write_text(
            "# AI Use Register\n\n"
            f"Status: {ai_status}\n\n"
            "The team reviewed the complete history and verified this disclosure against the retained case evidence.\n",
            encoding="utf-8",
        )
        ai = {
            "status": ai_status,
            "usage_log": "ai/ai-usage.md",
            "paper_statement": statement,
        }
        if ai_status == "used":
            detail_pdf = case_dir / "paper" / "AI-use-detail.pdf"
            write_text_pdf(detail_pdf, "Reviewed AI usage detail")
            ai["detail_pdf"] = "paper/AI-use-detail.pdf"
        compliance = {
            "schema_version": 1,
            "competition": "CUMCM profile acceptance",
            "year": date.today().year,
            "rules": {
                "verified_at": date.today().isoformat(),
                "max_age_days": 30,
                "sources": ["https://www.mcm.edu.cn/rules"],
            },
            "ai": ai,
        }
        compliance_path = case_dir / "compliance" / "submission.json"
        compliance_path.write_text(json.dumps(compliance), encoding="utf-8")
        manifest["compliance"] = "compliance/submission.json"
    (case_dir / "workflow.json").write_text(json.dumps(manifest), encoding="utf-8")
    return {
        "docx": docx,
        "pdf": pdf,
        "page": page,
        "review": case_dir / "paper" / "visual-review.json",
        "compliance": compliance_path,
    }


def run_script(script: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, str(script), *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        timeout=30,
    )


def finalize(case_dir: Path) -> tuple[subprocess.CompletedProcess[str], dict]:
    completed = run_script(
        PIPELINE,
        "--case-dir",
        str(case_dir),
        "--phase",
        "finalize",
        "--json",
    )
    return completed, json.loads(completed.stdout)


@unittest.skipUnless(importlib.util.find_spec("pypdf"), "pypdf is unavailable")
class ProfileBlackBoxTests(unittest.TestCase):
    def test_practice_profile_finalizes_through_real_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary) / "practice case"
            create_profile_case(case_dir, "practice")

            completed, report = finalize(case_dir)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(report["ready_for_submission"])
            self.assertEqual(report["profile"], "practice")
            self.assertTrue(report["reconciliation"]["reconciled"])
            self.assertTrue(report["model_definition_audit"]["passed"])
            self.assertTrue(report["paper_audit"]["structural_ok"])
            self.assertEqual(report["visual_review"]["status"], "passed")
            self.assertFalse(report["submission_compliance"]["required"])
            self.assertTrue((case_dir / "paper" / "finalization-report.json").is_file())
            self.assertTrue((case_dir / "paper" / "qa-register.md").is_file())

    def test_submission_profiles_finalize_for_used_and_not_used(self) -> None:
        for status in ("used", "not-used"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temporary:
                case_dir = Path(temporary) / f"submission-{status}"
                create_profile_case(case_dir, "submission", status)

                completed, report = finalize(case_dir)

                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertTrue(report["ready_for_submission"])
                compliance = report["submission_compliance"]
                self.assertTrue(compliance["required"])
                self.assertTrue(compliance["passed"])
                expected = {"compliance", "docx", "pdf", "ai_usage_log"}
                if status == "used":
                    expected.add("ai_detail_pdf")
                self.assertEqual(set(compliance["evidence_sha256"]), expected)

    def test_finalization_rejects_pdf_changed_after_visual_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary) / "stale-review"
            paths = create_profile_case(case_dir, "practice")
            write_text_pdf(paths["pdf"], "Verified result 42 changed after review")

            completed, report = finalize(case_dir)

            self.assertEqual(completed.returncode, 2)
            self.assertFalse(report["ready_for_submission"])
            self.assertEqual(report["visual_review"]["status"], "invalid")
            self.assertIn(
                "visual review PDF hash does not match",
                "\n".join(report["visual_review"]["errors"]),
            )

    def test_submission_audit_rejects_empty_pdf_and_usage_log_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case_dir = root / "submission-faults"
            paths = create_profile_case(case_dir, "submission", "not-used")
            paths["pdf"].write_bytes(b"")
            compliance = json.loads(paths["compliance"].read_text(encoding="utf-8"))
            compliance["ai"]["usage_log"] = "../outside.md"
            paths["compliance"].write_text(json.dumps(compliance), encoding="utf-8")

            completed = run_script(
                SCRIPTS / "audit_submission_compliance.py",
                "--case-dir",
                str(case_dir),
                "--compliance",
                "compliance/submission.json",
                "--docx",
                "paper/paper.docx",
                "--pdf",
                "paper/paper.pdf",
                "--json",
            )
            report = json.loads(completed.stdout)

            self.assertEqual(completed.returncode, 2)
            errors = "\n".join(report["errors"])
            self.assertIn("AI usage log escapes the case directory", errors)
            self.assertIn("cannot parse PDF", errors)

    def test_submission_audit_rejects_hardlink_detail_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary) / "hardlink-alias"
            paths = create_profile_case(case_dir, "submission", "used")
            detail = case_dir / "paper" / "AI-use-detail.pdf"
            detail.unlink()
            try:
                os.link(paths["pdf"], detail)
            except OSError as exc:
                self.skipTest(f"hard links are unavailable: {exc}")

            completed = run_script(
                SCRIPTS / "audit_submission_compliance.py",
                "--case-dir",
                str(case_dir),
                "--compliance",
                "compliance/submission.json",
                "--docx",
                "paper/paper.docx",
                "--pdf",
                "paper/paper.pdf",
                "--json",
            )
            report = json.loads(completed.stdout)

            self.assertEqual(completed.returncode, 2)
            self.assertFalse(report["checks"]["ai.detail_pdf"]["passed"])
            self.assertIn("distinct", "\n".join(report["errors"]))

    def test_finalization_detects_evidence_mutation_after_compliance_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary) / "evidence-race"
            paths = create_profile_case(case_dir, "submission", "used")
            usage_log = case_dir / "ai" / "ai-usage.md"
            finalize_module = load_finalize_module()
            arguments = SimpleNamespace(
                case_dir=case_dir,
                docx=paths["docx"],
                pdf=paths["pdf"],
                render_dir=case_dir / "paper" / "rendered-pages",
                register=None,
                visual_review_record=paths["review"],
                submission_compliance=paths["compliance"],
                qa_register=None,
                report=None,
                page_size="a4",
                orientation="portrait",
                forbid=["TODO"],
            )
            original_run_json = finalize_module.run_json

            def mutate_after_audit(script: Path, child_arguments: list[str]):
                payload, command = original_run_json(script, child_arguments)
                if script.name == "audit_submission_compliance.py" and payload.get(
                    "passed"
                ):
                    usage_log.write_text(
                        usage_log.read_text(encoding="utf-8")
                        + "Changed immediately after the compliance audit.\n",
                        encoding="utf-8",
                    )
                return payload, command

            with patch.object(
                finalize_module, "run_json", side_effect=mutate_after_audit
            ):
                report, report_path, _ = finalize_module.run_finalization(arguments)

            self.assertFalse(report["ready_for_submission"])
            self.assertIn(
                "changed after compliance audit", "\n".join(report["errors"])
            )
            persisted = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertFalse(persisted["ready_for_submission"])
            self.assertIn(
                "changed after compliance audit", "\n".join(persisted["errors"])
            )


if __name__ == "__main__":
    unittest.main()

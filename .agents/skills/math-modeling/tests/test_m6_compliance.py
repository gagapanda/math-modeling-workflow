from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
import zipfile
from argparse import Namespace
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


m6 = load_module("math_modeling_m6_compliance_test", SCRIPTS / "audit_m6_compliance.py")

import audit_submission_compliance as legacy_compliance


@contextmanager
def fixture_clock(today: date):
    """Freeze only the two audit modules' clocks, never production freshness logic.

    The synthetic fixture is dated 2026-08-27. prepare() deliberately checks
    today's rules, not its caller-supplied generated_at; both clocks must agree.
    Context exit restores them so unrelated tests still use their own clocks.
    """
    class FixtureDate(date):
        @classmethod
        def today(cls):
            return today

    with patch.object(m6, "date", FixtureDate), patch.object(legacy_compliance, "date", FixtureDate):
        yield


def write_docx(path: Path, text: str, creator: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>'
    )
    core = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f'<dc:creator>{creator}</dc:creator><cp:lastModifiedBy>{creator}</cp:lastModifiedBy>'
        '</cp:coreProperties>'
    )
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("word/document.xml", document)
        package.writestr("docProps/core.xml", core)


def write_text_pdf(path: Path, text: str, author: str = "") -> None:
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    page = writer.add_blank_page(width=595.28, height=841.89)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 10 Tf 36 760 Td ({escaped}) Tj ET".encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    if author:
        writer.add_metadata({"/Author": author})
    with path.open("wb") as output:
        writer.write(output)


def add_xmp_creators(path: Path, creators: list[str]) -> None:
    from pypdf import PdfReader, PdfWriter

    items = "".join(f"<rdf:li>{creator}</rdf:li>" for creator in creators)
    xmp = f'''<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:creator><rdf:Seq>{items}</rdf:Seq></dc:creator>
</rdf:Description></rdf:RDF></x:xmpmeta>
<?xpacket end="w"?>'''.encode("utf-8")
    reader = PdfReader(path)
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)
    if reader.metadata:
        writer.add_metadata({str(key): str(value) for key, value in reader.metadata.items()})
    writer.xmp_metadata = xmp
    with path.open("wb") as output:
        writer.write(output)


class M6ComplianceTests(unittest.TestCase):
    def make_case(self, root: Path) -> tuple[Path, Path, Path, Path]:
        case = root / "case"
        for directory in ("paper", "ai", "compliance", "src"):
            (case / directory).mkdir(parents=True, exist_ok=True)
        statement = "AI use statement reviewed"
        docx = case / "paper/paper.docx"
        pdf = case / "paper/paper.pdf"
        detail = case / "ai/AI-detail.pdf"
        write_docx(docx, statement)
        write_text_pdf(pdf, statement)
        detail_markers = "Tool/Version Purpose/Stage Prompt Process Adopted Result Human Modification Verification"
        write_text_pdf(detail, detail_markers)
        usage = (
            "# AI Use Register\n\nStatus: used\n\n"
            "Time: 2026-08-27T10:00:00+08:00\n"
            "Tool/Model: Codex Desktop test model\n"
            "Phase/Purpose: paper and code audit\n"
            "Task Summary: inspect evidence and draft code\n"
            "Adopted Output: reviewed implementation\n"
            "Human Changes: responsible human selected and edited outputs\n"
            "Verification Evidence: tests and hashes\n"
            "File Scope: case-local files\n"
            "Unresolved Limitations: none recorded after review\n"
        )
        (case / "ai/ai-usage.md").write_text(usage, encoding="utf-8")
        legacy = {
            "schema_version": 1,
            "competition": "2026 CUMCM",
            "year": 2026,
            "rules": {
                "verified_at": "2026-08-27",
                "max_age_days": 30,
                "sources": ["https://example.edu/official-rules"],
            },
            "ai": {
                "status": "used",
                "usage_log": "ai/ai-usage.md",
                "paper_statement": statement,
                "detail_pdf": "ai/AI-detail.pdf",
            },
        }
        (case / "compliance/submission.json").write_text(json.dumps(legacy), encoding="utf-8")
        snapshot = case / "compliance/official-rules-snapshot.md"
        snapshot.write_text("Official 2026 rules preserved and reviewed.\n", encoding="utf-8")
        source_register = {
            "schema_version": 1,
            "status": "complete",
            "reviewed_at": "2026-08-27T11:00:00+08:00",
            "not_applicable_reason": "",
            "entries": [{
                "id": "software-pypdf",
                "category": "software",
                "source": "pypdf official documentation",
                "citation_or_paper_locator": "paper references: pypdf",
                "license_status": "permitted",
                "local_evidence": "",
                "purpose": "PDF validation",
                "used_in": ["M6 audit"],
                "limitations": "Text extraction cannot inspect image-only pages.",
                "support_required": False,
                "support_path": "",
            }],
        }
        (case / "compliance/source-register.json").write_text(json.dumps(source_register), encoding="utf-8")
        (case / "src/analyze.py").write_text("print('ok')\n", encoding="utf-8")
        package = {
            "schema_version": 1,
            "finalization_report": "paper/finalization-report.json",
            "paper": {"source": "paper/paper.pdf", "output_name": "paper.pdf", "max_bytes": 20971520},
            "support": {
                "output_name": "support.zip",
                "max_bytes": 20971520,
                "files": [
                    {"source": "src/analyze.py", "archive_path": "src/analyze.py"},
                    {"source": "ai/AI-detail.pdf", "archive_path": "AI-detail.pdf"},
                ],
            },
            "anonymity": {"forbidden_terms": ["Real Name", "University of Example"]},
        }
        (case / "submission-package-plan.json").write_text(json.dumps(package), encoding="utf-8")
        plan = {
            "schema_version": 1,
            "legacy_submission_compliance": "compliance/submission.json",
            "official_rules": {
                "snapshot": "compliance/official-rules-snapshot.md",
                "snapshot_sha256": m6.sha256_file(snapshot),
                "verified_at": "2026-08-27",
                "max_age_days": 7,
                "sources": ["https://example.edu/official-rules"],
                "impact_steps": ["paper", "anonymity", "AI disclosure", "support package", "upload"],
            },
            "anonymity": {
                "submission_package_plan": "submission-package-plan.json",
                "allowed_anonymous_values": ["", "Anonymous", "匿名"],
                "forbidden_path_patterns": [r"(?i)(?:Users|\\Users)[/\\][^/\\]+"],
            },
            "sources": {"register": "compliance/source-register.json"},
            "ai": {
                "usage_log_required_markers": ["Time", "Tool/Model", "Phase/Purpose", "Task Summary", "Adopted Output", "Human Changes", "Verification Evidence", "File Scope", "Unresolved Limitations"],
                "detail_pdf_required_markers": ["Tool/Version", "Purpose/Stage", "Prompt Process", "Adopted Result", "Human Modification", "Verification"],
            },
            "human_gate": {"manifest": "compliance/M6-accepted.json"},
        }
        plan_path = case / "compliance/m6-plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        return case, plan_path, docx, pdf

    def test_technical_pass_does_not_claim_full_m6(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case, plan, docx, pdf = self.make_case(Path(temporary))
            report = m6.technical_audit(case, plan, docx, pdf, as_of=m6.date(2026, 8, 27))
            self.assertTrue(report["technical_passed"], report["errors"])
            self.assertFalse(report["passed"])
            self.assertFalse(report["full_m6_proven"])
            full = m6.audit(case, plan, docx, pdf, as_of=m6.date(2026, 8, 27))
            self.assertFalse(full["passed"])
            self.assertIn("human M6 gate", " ".join(full["errors"]))

    def test_prepare_finalize_verify_and_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case, plan, docx, pdf = self.make_case(Path(temporary))
            candidate = case / "compliance/M6-candidate.json"
            accepted = case / "compliance/M6-accepted.json"
            with fixture_clock(date(2026, 8, 27)):
                payload = m6.prepare(case, plan, docx, pdf, candidate, "2026-08-27T12:00:00+08:00", "M6-2026-test")
            self.assertEqual(payload["status"], "M6_PENDING_HUMAN")
            args = Namespace(
                confirm_human_reviewed=True, decision="accepted", reviewer="Responsible Operator",
                review_start="2026-08-27T12:05:00+08:00", review_end="2026-08-27T12:15:00+08:00",
                signed_at="2026-08-27T12:16:00+08:00", generated_at="2026-08-27T12:17:00+08:00",
                objections="NONE", resolution="NONE",
            )
            final = m6.finalize(case, candidate, accepted, args)
            self.assertTrue(final["full_m6_approved"])
            verified = m6.verify_manifest(case, "compliance/M6-accepted.json")
            self.assertTrue(verified["passed"], verified["errors"])
            report = m6.audit(case, plan, docx, pdf, as_of=m6.date(2026, 8, 27))
            self.assertTrue(report["passed"], report["errors"])
            self.assertTrue(report["full_m6_proven"])

    def test_codex_cannot_be_recorded_as_human_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case, plan, docx, pdf = self.make_case(Path(temporary))
            candidate = case / "compliance/M6-candidate.json"
            with fixture_clock(date(2026, 8, 27)):
                m6.prepare(case, plan, docx, pdf, candidate, "2026-08-27T12:00:00+08:00", "M6-2026-test")
            args = Namespace(
                confirm_human_reviewed=True, decision="accepted", reviewer="Codex",
                review_start="2026-08-27T12:05:00+08:00", review_end="2026-08-27T12:15:00+08:00",
                signed_at="2026-08-27T12:16:00+08:00", generated_at="2026-08-27T12:17:00+08:00",
                objections="NONE", resolution="NONE",
            )
            with self.assertRaisesRegex(ValueError, "responsible human"):
                m6.finalize(case, candidate, case / "compliance/M6-accepted.json", args)

    def test_freshness_boundaries_with_fixed_clock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case, plan, docx, pdf = self.make_case(Path(temporary))
            original_m6_date, original_legacy_date = m6.date, legacy_compliance.date
            for today, expected in (
                (date(2026, 8, 26), False),  # verified_at is in the future
                (date(2026, 8, 27), True),
                (date(2026, 9, 3), True),   # exactly seven days old
                (date(2026, 9, 4), False),  # eight days old
                (date(2026, 9, 9), False),
            ):
                with self.subTest(today=today), fixture_clock(today):
                    report = m6.technical_audit(case, plan, docx, pdf)
                    self.assertEqual(report["technical_passed"], expected, report["errors"])
                    if not expected:
                        self.assertIn("official rules snapshot is stale", " ".join(report["errors"]))
            self.assertIs(m6.date, original_m6_date)
            self.assertIs(legacy_compliance.date, original_legacy_date)

    def test_prepare_rejects_stale_rules_despite_backdated_generated_at(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case, plan, docx, pdf = self.make_case(Path(temporary))
            candidate = case / "compliance/M6-candidate.json"
            # A historical generated_at must NOT bypass today's freshness check.
            with fixture_clock(date(2026, 9, 9)):
                with self.assertRaisesRegex(ValueError, "official rules snapshot is stale"):
                    m6.prepare(case, plan, docx, pdf, candidate,
                               "2026-08-27T12:00:00+08:00", "M6-stale-test")
            self.assertFalse(candidate.exists())

    def test_anonymity_and_evidence_drift_block_m6(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case, plan, docx, pdf = self.make_case(Path(temporary))
            write_docx(docx, "AI use statement reviewed", creator="Real Name")
            report = m6.technical_audit(case, plan, docx, pdf, as_of=m6.date(2026, 8, 27))
            self.assertFalse(report["technical_passed"])
            self.assertIn("metadata identity", " ".join(report["errors"]))

    def test_m6_scans_support_docx_identity_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case, plan, docx, pdf = self.make_case(Path(temporary))
            support_docx = case / "support-identity.docx"
            write_docx(support_docx, "safe support text", creator="Real Name")
            package_path = case / "submission-package-plan.json"
            package = json.loads(package_path.read_text(encoding="utf-8"))
            package["support"]["files"].append(
                {"source": "support-identity.docx", "archive_path": "support-identity.docx"}
            )
            package_path.write_text(json.dumps(package), encoding="utf-8")
            report = m6.technical_audit(case, plan, docx, pdf, as_of=m6.date(2026, 8, 27))
            self.assertFalse(report["technical_passed"])
            self.assertIn("forbidden anonymity term", " ".join(report["errors"]))

    def test_m6_accepts_single_anonymous_xmp_creator_but_rejects_identity_sequences(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case, plan, docx, pdf = self.make_case(Path(temporary))
            add_xmp_creators(pdf, ["Anonymous"])
            report = m6.technical_audit(case, plan, docx, pdf, as_of=m6.date(2026, 8, 27))
            self.assertTrue(report["technical_passed"], report["errors"])
            self.assertEqual(
                report["anonymity"]["metadata"]["pdf"]["values"]["xmp:dc_creator"],
                "Anonymous",
            )

            for creators in (["Real Name"], ["Anonymous", "Real Name"]):
                with self.subTest(creators=creators):
                    add_xmp_creators(pdf, creators)
                    report = m6.technical_audit(case, plan, docx, pdf, as_of=m6.date(2026, 8, 27))
                    self.assertFalse(report["technical_passed"])
                    self.assertIn("metadata identity", " ".join(report["errors"]))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_DIR / "scripts"
SCHEMAS = SKILL_DIR / "schemas"


def load_module(name: str, path: Path):
    import sys
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


quality = load_module(
    "math_modeling_paper_quality_gates",
    SCRIPTS / "audit_paper_quality_gates.py",
)


def write_minimal_png(path: Path) -> None:
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = b"\x00\xff\x00\x00\xff"
    payload = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(payload)


def write_minimal_docx(path: Path, author: str = "") -> None:
    core = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties">
  <dc:creator xmlns:dc="http://purl.org/dc/elements/1.1/">{author}</dc:creator>
  <cp:lastModifiedBy></cp:lastModifiedBy>
</cp:coreProperties>'''
    document = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Paper</w:t></w:r></w:p></w:body></w:document>'''
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("docProps/core.xml", core)
        package.writestr("word/document.xml", document)


def write_pdf_with_xmp_creators(path: Path, creators: list[str], author: str = "") -> None:
    from pypdf import PdfWriter

    items = "".join(f"<rdf:li>{creator}</rdf:li>" for creator in creators)
    xmp = f'''<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:creator><rdf:Seq>{items}</rdf:Seq></dc:creator>
</rdf:Description></rdf:RDF></x:xmpmeta>
<?xpacket end="w"?>'''.encode("utf-8")
    writer = PdfWriter()
    writer.add_blank_page(width=595.28, height=841.89)
    writer.add_blank_page(width=595.28, height=841.89)
    if author:
        writer.add_metadata({"/Author": author})
    writer.xmp_metadata = xmp
    with path.open("wb") as stream:
        writer.write(stream)


class PaperQualityGateTests(unittest.TestCase):
    def make_case(self, root: Path) -> tuple[Path, Path]:
        from pypdf import PdfWriter

        case = root / "case"
        (case / "paper" / "rendered-pages").mkdir(parents=True)
        (case / "results").mkdir()
        (case / "src").mkdir()
        pdf = case / "paper" / "paper.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=595.28, height=841.89)
        writer.add_blank_page(width=595.28, height=841.89)
        with pdf.open("wb") as stream:
            writer.write(stream)
        write_minimal_docx(case / "paper" / "paper.docx")
        for index in (1, 2):
            write_minimal_png(case / "paper" / "rendered-pages" / f"page-{index}.png")
        source = case / "src" / "solve.py"
        source.write_text("THRESHOLD = 5\nprint('result')\n", encoding="utf-8")
        register = {
            "schema_version": 1,
            "results": [
                {
                    "id": "q1.result",
                    "value": 1,
                    "source_file": "results/result.json",
                    "source_key": "value",
                    "paper_required": True,
                    "paper_text": "1",
                }
            ],
        }
        (case / "results" / "result-register.json").write_text(
            json.dumps(register), encoding="utf-8"
        )
        (case / "results" / "result.json").write_text('{"value": 1}\n', encoding="utf-8")
        paper = case / "paper" / "full-paper.md"
        paper.write_text(
            """# Abstract\n\nQ1 method result boundary: result 1.\nQ2 method result boundary: result 1.\nQ3 method result boundary: result 1.\nQ4 method result boundary: result 1.\n\n## Q1 Method Result Validation Boundary\n\n## Q2 Method Result Validation Boundary\n\n## Q3 Method Result Validation Boundary\n\n## Q4 Method Result Validation Boundary\n\n## Appendix B Complete Runnable Source Code\n\n### src/solve.py\n\n```python\nTHRESHOLD = 5\nprint('result')\n```\n\nFigure 1 supports q1 with result 1 and limitation: descriptive only.\n""",
            encoding="utf-8",
        )
        plan = {
            "schema_version": 1,
            "paper_source": "paper/full-paper.md",
            "docx": "paper/paper.docx",
            "pdf": "paper/paper.pdf",
            "render_dir": "paper/rendered-pages",
            "result_register": "results/result-register.json",
            "summary": {
                "required_subproblem_ids": ["Q1", "Q2", "Q3", "Q4"],
                "max_pages": 1,
                "markers": ["Q1", "Q2", "Q3", "Q4"],
            },
            "subproblems": [
                {
                    "id": f"Q{i}",
                    "heading": f"## Q{i}",
                    "required_markers": ["Method", "Result", "Validation", "Boundary"],
                    "headline_result_ids": ["q1.result"],
                }
                for i in range(1, 5)
            ],
            "page_regions": [
                {"name": "abstract", "start": 1, "end": 1},
                {"name": "main_text", "start": 2, "end": 2},
            ],
            "source_appendix": [
                {
                    "path": "src/solve.py",
                    "paper_marker": "src/solve.py",
                    "required_tokens": ["THRESHOLD = 5", "print('result')"],
                }
            ],
            "formula_bindings": [
                {
                    "id": "formula.threshold",
                    "paper_markers": ["THRESHOLD = 5"],
                    "source_files": ["src/solve.py"],
                    "required_tokens": ["THRESHOLD = 5"],
                    "result_ids": ["q1.result"],
                }
            ],
            "figure_claims": [
                {
                    "id": "fig.q1",
                    "figure": "paper/rendered-pages/page-1.png",
                    "subproblem_id": "Q1",
                    "source_result_ids": ["q1.result"],
                    "body_markers": ["Figure 1 supports q1"],
                    "limitation_markers": ["descriptive only"],
                }
            ],
            "metadata": {"forbidden_terms": ["John Doe"]},
        }
        plan_path = case / "paper" / "quality-gate-plan.json"
        plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        return case, plan_path

    def test_quality_gate_plan_schema_exists_and_validates(self) -> None:
        from _json_schema import load_and_validate
        plan = {
            "schema_version": 1,
            "paper_source": "paper/full-paper.md",
            "docx": "paper/paper.docx",
            "pdf": "paper/paper.pdf",
            "render_dir": "paper/rendered-pages",
            "result_register": "results/result-register.json",
            "summary": {"required_subproblem_ids": ["Q1"], "max_pages": 1, "markers": ["Q1"]},
            "subproblems": [],
            "page_regions": [],
            "source_appendix": [],
            "formula_bindings": [],
            "figure_claims": [],
            "metadata": {"forbidden_terms": []},
        }
        load_and_validate(plan, SCHEMAS / "paper-quality-gate-plan.schema.json", "paper quality plan")

    def test_quality_gate_passes_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case, plan = self.make_case(Path(temporary))
            report = quality.audit_quality_gates(case, plan)
            self.assertTrue(report["passed"], report["errors"])
            self.assertEqual(report["summary"]["status"], "passed")
            self.assertEqual(report["rendered_pages"]["png_count"], 2)
            self.assertEqual(report["source_appendix"][0]["status"], "passed")

    def test_quality_gate_reports_missing_symbols_as_legacy_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case, plan = self.make_case(Path(temporary))
            report = quality.audit_quality_gates(case, plan)
            self.assertTrue(report["passed"], report["errors"])
            self.assertEqual(report["symbols_and_units"]["status"], "warning")
            self.assertTrue(
                any("Symbols and Units" in warning for warning in report["warnings"])
            )

    def test_quality_gate_accepts_populated_symbols_table(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case, plan = self.make_case(Path(temporary))
            paper = case / "paper" / "full-paper.md"
            text = paper.read_text(encoding="utf-8")
            text = text.replace(
                "## Q1 Method Result Validation Boundary",
                "## Symbols And Units\n\n"
                "| Symbol | Meaning | Unit / Domain |\n"
                "| --- | --- | --- |\n"
                "| `x(i,t)` | decision variable | nonnegative integer |\n\n"
                "## Q1 Method Result Validation Boundary",
                1,
            )
            paper.write_text(text, encoding="utf-8")
            report = quality.audit_quality_gates(case, plan)
            self.assertTrue(report["passed"], report["errors"])
            self.assertEqual(report["symbols_and_units"]["status"], "passed")
            self.assertTrue(report["symbols_and_units"]["table"]["found"])

    def test_quality_gate_warns_when_nearby_caption_number_disagrees(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case, plan = self.make_case(Path(temporary))
            paper = case / "paper" / "full-paper.md"
            text = paper.read_text(encoding="utf-8").replace(
                "## Appendix B Complete Runnable Source Code",
                "The comparison is shown in Table 2.\n\n"
                "**Table 1 Baseline comparison**\n\n"
                "| A |\n| --- |\n| 1 |\n\n"
                "**Table 2 Secondary result**\n\n"
                "| A |\n| --- |\n| 2 |\n\n"
                "## Appendix B Complete Runnable Source Code",
                1,
            )
            paper.write_text(text, encoding="utf-8")
            report = quality.audit_quality_gates(case, plan)
            self.assertTrue(report["passed"], report["errors"])
            self.assertEqual(report["figure_table_numbering"]["status"], "warning")
            self.assertTrue(
                any("immediately before a caption" in warning for warning in report["warnings"])
            )

    def test_quality_gate_does_not_misread_reference_to_previous_caption(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case, plan = self.make_case(Path(temporary))
            paper = case / "paper" / "full-paper.md"
            text = paper.read_text(encoding="utf-8").replace(
                "## Appendix B Complete Runnable Source Code",
                "**Table 1 Baseline comparison**\n\n"
                "| A |\n| --- |\n| 1 |\n\n"
                "Table 1 shows the baseline result.\n\n"
                "**Table 2 Secondary result**\n\n"
                "| A |\n| --- |\n| 2 |\n\n"
                "## Appendix B Complete Runnable Source Code",
                1,
            )
            paper.write_text(text, encoding="utf-8")
            report = quality.audit_quality_gates(case, plan)
            self.assertTrue(report["passed"], report["errors"])
            self.assertEqual(
                report["figure_table_numbering"]["near_caption_mismatches"], []
            )

    def test_quality_gate_rejects_duplicate_explicit_table_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case, plan = self.make_case(Path(temporary))
            paper = case / "paper" / "full-paper.md"
            text = paper.read_text(encoding="utf-8").replace(
                "## Appendix B Complete Runnable Source Code",
                "**Table 1 Baseline**\n\n| A |\n| --- |\n| 1 |\n\n"
                "**Table 1 Main model**\n\n| A |\n| --- |\n| 2 |\n\n"
                "## Appendix B Complete Runnable Source Code",
                1,
            )
            paper.write_text(text, encoding="utf-8")
            report = quality.audit_quality_gates(case, plan)
            self.assertFalse(report["passed"])
            self.assertTrue(
                any("duplicate explicit table number: 1" in error for error in report["errors"])
            )

    def test_quality_gate_rejects_extra_rendered_png(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case, plan = self.make_case(Path(temporary))
            (case / "paper" / "rendered-pages" / "contact-sheet.png").write_bytes(
                (case / "paper" / "rendered-pages" / "page-1.png").read_bytes()
            )
            report = quality.audit_quality_gates(case, plan)
            self.assertFalse(report["passed"])
            self.assertTrue(any("filename" in error or "page numbers" in error for error in report["errors"]))

    def test_quality_gate_rejects_docx_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case, plan = self.make_case(Path(temporary))
            write_minimal_docx(case / "paper" / "paper.docx", author="John Doe")
            report = quality.audit_quality_gates(case, plan)
            self.assertFalse(report["passed"])
            self.assertTrue(any("metadata" in error for error in report["errors"]))

    def test_quality_gate_scopes_summary_to_abstract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case, plan = self.make_case(Path(temporary))
            paper = case / "paper" / "full-paper.md"
            text = paper.read_text(encoding="utf-8")
            text = text.replace("Q4 method result boundary", "QX method result boundary", 1)
            paper.write_text(text, encoding="utf-8")
            report = quality.audit_quality_gates(case, plan)
            self.assertFalse(report["passed"])
            self.assertTrue(any("summary missing marker inside abstract: Q4" in error for error in report["errors"]))

    def test_quality_gate_scopes_subproblem_markers_to_section(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case, plan = self.make_case(Path(temporary))
            paper = case / "paper" / "full-paper.md"
            text = paper.read_text(encoding="utf-8")
            text = text.replace("## Q2 Method Result Validation Boundary", "## Q2 Method", 1)
            paper.write_text(text, encoding="utf-8")
            report = quality.audit_quality_gates(case, plan)
            self.assertFalse(report["passed"])
            self.assertTrue(any("Q2 missing required structure marker in its section: Result" in error for error in report["errors"]))

    def test_quality_gate_result_id_references_pass_and_reject_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case, plan = self.make_case(Path(temporary))
            paper = case / "paper" / "full-paper.md"
            text = paper.read_text(encoding="utf-8")
            text = text.replace("## Q1 Method Result Validation Boundary", "结果 ID: q1.result\n\n## Q1 Method Result Validation Boundary", 1)
            paper.write_text(text, encoding="utf-8")
            report = quality.audit_quality_gates(case, plan)
            self.assertTrue(report["passed"], report["errors"])
            paper.write_text(text.replace("q1.result", "q1.unknown", 1), encoding="utf-8")
            report = quality.audit_quality_gates(case, plan)
            self.assertFalse(report["passed"])
            self.assertTrue(any("unknown result id: q1.unknown" in error for error in report["errors"]))

    def _configure_hyphenated_result_id(
        self, case: Path, plan_path: Path, result_id: str
    ) -> None:
        old_id = "q1.result"
        register_path = case / "results" / "result-register.json"
        register = json.loads(register_path.read_text(encoding="utf-8"))
        register["results"][0]["id"] = result_id
        register_path.write_text(json.dumps(register), encoding="utf-8")

        plan = json.loads(plan_path.read_text(encoding="utf-8"))

        def replace_ids(value):
            if isinstance(value, dict):
                return {key: replace_ids(item) for key, item in value.items()}
            if isinstance(value, list):
                return [replace_ids(item) for item in value]
            if value == old_id:
                return result_id
            return value

        plan_path.write_text(
            json.dumps(replace_ids(plan), indent=2), encoding="utf-8"
        )
        paper = case / "paper" / "full-paper.md"
        text = paper.read_text(encoding="utf-8")
        text = text.replace(
            "## Q1 Method Result Validation Boundary",
            f"结果 ID: `{result_id}`\n\n## Q1 Method Result Validation Boundary",
            1,
        )
        paper.write_text(text, encoding="utf-8")

    def test_quality_gate_result_id_references_accept_hyphenated_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case, plan = self.make_case(Path(temporary))
            result_id = "q1-maximum-coverage-width-m"
            self._configure_hyphenated_result_id(case, plan, result_id)
            report = quality.audit_quality_gates(case, plan)
            self.assertTrue(report["passed"], report["errors"])
            self.assertEqual(
                report["result_references"]["references"], [result_id]
            )
            self.assertEqual(report["result_references"]["unknown"], [])

    def test_quality_gate_rejects_unknown_hyphenated_result_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case, plan = self.make_case(Path(temporary))
            valid_id = "q1-maximum-coverage-width-m"
            unknown_id = "q1-unknown-width-m"
            self._configure_hyphenated_result_id(case, plan, valid_id)
            paper = case / "paper" / "full-paper.md"
            text = paper.read_text(encoding="utf-8")
            paper.write_text(text.replace(valid_id, unknown_id, 1), encoding="utf-8")
            report = quality.audit_quality_gates(case, plan)
            self.assertFalse(report["passed"])
            self.assertIn(unknown_id, report["result_references"]["unknown"])
            self.assertTrue(
                any(
                    f"unknown result id: {unknown_id}" in error
                    for error in report["errors"]
                )
            )

    def test_quality_gate_rejects_unregistered_body_figure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case, plan = self.make_case(Path(temporary))
            paper = case / "paper" / "full-paper.md"
            text = paper.read_text(encoding="utf-8")
            text = text.replace("## Q1 Method Result Validation Boundary", "![Figure 1](rendered-pages/page-1.png)\n\n## Q1 Method Result Validation Boundary", 1)
            paper.write_text(text, encoding="utf-8")
            report = quality.audit_quality_gates(case, plan)
            self.assertTrue(report["passed"], report["errors"])
            data = json.loads(plan.read_text(encoding="utf-8"))
            data["figure_claims"] = []
            plan.write_text(json.dumps(data), encoding="utf-8")
            report = quality.audit_quality_gates(case, plan)
            self.assertFalse(report["passed"])
            self.assertTrue(any("paper body figure is not registered" in error for error in report["errors"]))

    def test_quality_gate_rejects_unknown_nonempty_identity_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case, plan = self.make_case(Path(temporary))
            write_minimal_docx(case / "paper" / "paper.docx", author="Regression Author")
            report = quality.audit_quality_gates(case, plan)
            self.assertFalse(report["passed"])
            self.assertTrue(any("metadata identity field is not anonymous" in error for error in report["errors"]))

    def test_quality_gate_normalizes_single_xmp_creator_and_rejects_complex_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case, plan = self.make_case(Path(temporary))
            pdf = case / "paper" / "paper.pdf"
            write_pdf_with_xmp_creators(pdf, ["Anonymous"], author="Anonymous")
            report = quality.audit_quality_gates(case, plan)
            self.assertTrue(report["passed"], report["errors"])
            self.assertEqual(
                report["metadata"]["identity_values"]["pdf:xmp:dc_creator"],
                "Anonymous",
            )

            for creators in (["Real Name"], ["Anonymous", "Real Name"]):
                with self.subTest(creators=creators):
                    write_pdf_with_xmp_creators(pdf, creators, author="Anonymous")
                    report = quality.audit_quality_gates(case, plan)
                    self.assertFalse(report["passed"])
                    self.assertTrue(
                        any("metadata identity field is not anonymous" in error for error in report["errors"])
                    )


if __name__ == "__main__":
    unittest.main()



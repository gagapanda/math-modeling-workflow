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


def load_module():
    import sys

    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        "math_modeling_submission_packaging", SCRIPTS / "package_submission.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load package_submission.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


packaging = load_module()


class SubmissionPackagingTests(unittest.TestCase):
    def make_case(self, root: Path) -> tuple[Path, Path]:
        from pypdf import PdfWriter

        case_dir = root / "case"
        (case_dir / "paper").mkdir(parents=True)
        (case_dir / "src").mkdir()
        (case_dir / "results").mkdir()
        paper = case_dir / "paper" / "paper.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=595.32, height=841.92)
        with paper.open("wb") as stream:
            writer.write(stream)
        (case_dir / "src" / "solve.py").write_text(
            "print('verified result')\n", encoding="utf-8"
        )
        (case_dir / "results" / "result.json").write_text(
            '{"value": 42}\n', encoding="utf-8"
        )
        digest = packaging.sha256_file(paper)
        finalization = {
            "schema_version": 1,
            "generated_at": "2026-08-17T00:00:00+08:00",
            "ready_for_submission": True,
            "case_dir": str(case_dir.resolve()),
            "artifacts": {"pdf": str(paper.resolve())},
            "artifact_hashes": {"after": {"pdf": digest}},
            "commands": {},
            "preflight": {},
            "reconciliation": {},
            "model_definition_audit": {},
            "paper_audit": {},
            "visual_review": {},
            "submission_compliance": {"required": False, "passed": True, "errors": []},
            "errors": [],
            "diagnostics_schema_version": 1,
            "diagnostics": [],
            "diagnostic_summary": {"error": 0, "warning": 0, "info": 0},
        }
        (case_dir / "paper" / "finalization-report.json").write_text(
            json.dumps(finalization, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        plan = {
            "schema_version": 1,
            "finalization_report": "paper/finalization-report.json",
            "paper": {
                "source": "paper/paper.pdf",
                "output_name": "paper.pdf",
                "max_bytes": 20 * 1024 * 1024,
            },
            "support": {
                "output_name": "support-materials.zip",
                "max_bytes": 20 * 1024 * 1024,
                "files": [
                    {"source": "src/solve.py", "archive_path": "src/solve.py"},
                    {"source": "results/result.json", "archive_path": "results/result.json"},
                ],
            },
            "anonymity": {"forbidden_terms": []},
        }
        plan_path = case_dir / "submission-package-plan.json"
        plan_path.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return case_dir, plan_path

    def read_plan(self, plan_path: Path) -> dict:
        return json.loads(plan_path.read_text(encoding="utf-8"))

    def write_plan(self, plan_path: Path, plan: dict) -> None:
        plan_path.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def test_successful_package_is_hash_bound_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir, plan_path = self.make_case(Path(temporary))
            report = packaging.package_submission(
                case_dir, plan_path, Path("submission-package")
            )
            self.assertTrue(report["packaged"])
            self.assertEqual(report["generated_at"], "2026-08-17T00:00:00+08:00")
            self.assertEqual(report["validation"]["pdf_pages"], 1)
            output_dir = case_dir / "submission-package"
            zip_path = output_dir / "support-materials.zip"
            first_zip_hash = packaging.sha256_file(zip_path)
            with zipfile.ZipFile(zip_path) as package:
                self.assertEqual(
                    package.namelist(),
                    ["results/result.json", "src/solve.py", "submission-manifest.json"],
                )
                manifest = json.loads(package.read("submission-manifest.json"))
                self.assertEqual(
                    [entry["archive_path"] for entry in manifest["files"]],
                    ["results/result.json", "src/solve.py"],
                )
                self.assertIsNone(package.testzip())
            second = packaging.package_submission(
                case_dir, plan_path, Path("submission-package"), replace=True
            )
            self.assertEqual(first_zip_hash, packaging.sha256_file(zip_path))
            packaging.load_and_validate(
                second,
                SCHEMAS / "submission-package-report.schema.json",
                "submission package report",
            )

    def test_full_m6_scope_requires_proven_human_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir, plan_path = self.make_case(Path(temporary))
            finalization_path = case_dir / "paper" / "finalization-report.json"
            finalization = json.loads(finalization_path.read_text(encoding="utf-8"))
            finalization["submission_compliance"] = {
                "required": True,
                "scope": "full_m6",
                "technical_passed": True,
                "passed": True,
                "full_m6_proven": False,
                "evidence_sha256": {},
                "errors": [],
            }
            finalization["gate_scopes"] = {"submission_compliance": "full_m6"}
            finalization_path.write_text(
                json.dumps(finalization, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "accepted human M6 decision"):
                packaging.package_submission(case_dir, plan_path, Path("out"))
            self.assertFalse((case_dir / "out").exists())

    def test_legacy_rules_and_ai_scope_remains_package_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir, plan_path = self.make_case(Path(temporary))
            finalization_path = case_dir / "paper" / "finalization-report.json"
            finalization = json.loads(finalization_path.read_text(encoding="utf-8"))
            finalization["submission_compliance"] = {
                "required": True,
                "scope": "rules_and_ai_technical_only",
                "passed": True,
                "full_m6_proven": False,
                "evidence_sha256": {
                    "analysis": {
                        "path": str((case_dir / "src" / "solve.py").resolve()),
                        "sha256": packaging.sha256_file(case_dir / "src" / "solve.py"),
                    }
                },
                "errors": [],
            }
            finalization["gate_scopes"] = {
                "submission_compliance": "rules_and_ai_technical_only"
            }
            finalization_path.write_text(
                json.dumps(finalization, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            report = packaging.package_submission(case_dir, plan_path, Path("out"))
            self.assertTrue(report["packaged"])

    def test_explicit_generated_at_requires_timezone_and_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir, plan_path = self.make_case(Path(temporary))
            report = packaging.package_submission(
                case_dir,
                plan_path,
                Path("controlled-time"),
                generated_at="2026-08-18T23:59:59+08:00",
            )
            self.assertEqual(report["generated_at"], "2026-08-18T23:59:59+08:00")
            with self.assertRaisesRegex(ValueError, "timezone offset"):
                packaging.package_submission(
                    case_dir,
                    plan_path,
                    Path("naive-time"),
                    generated_at="2026-08-18T23:59:59",
                )
            self.assertFalse((case_dir / "naive-time").exists())

    def test_stale_finalization_hash_is_rejected_without_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir, plan_path = self.make_case(Path(temporary))
            with (case_dir / "paper" / "paper.pdf").open("ab") as stream:
                stream.write(b"changed")
            with self.assertRaisesRegex(ValueError, "finalization report PDF binding"):
                packaging.package_submission(case_dir, plan_path, Path("out"))
            self.assertFalse((case_dir / "out").exists())

    def test_archive_traversal_and_case_collisions_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir, plan_path = self.make_case(Path(temporary))
            plan = self.read_plan(plan_path)
            plan["support"]["files"][0]["archive_path"] = "../escape.py"
            self.write_plan(plan_path, plan)
            with self.assertRaisesRegex(ValueError, "traversal"):
                packaging.package_submission(case_dir, plan_path, Path("out"))

            plan["support"]["files"][0]["archive_path"] = "SRC/file.txt"
            plan["support"]["files"][1]["archive_path"] = "src/FILE.txt"
            self.write_plan(plan_path, plan)
            with self.assertRaisesRegex(ValueError, "case-colliding"):
                packaging.package_submission(case_dir, plan_path, Path("out"))

    def test_anonymity_scan_checks_names_and_extractable_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir, plan_path = self.make_case(Path(temporary))
            (case_dir / "src" / "solve.py").write_text(
                "# University of Example\n", encoding="utf-8"
            )
            plan = self.read_plan(plan_path)
            plan["anonymity"]["forbidden_terms"] = ["University of Example"]
            self.write_plan(plan_path, plan)
            with self.assertRaisesRegex(ValueError, "forbidden anonymity terms"):
                packaging.package_submission(case_dir, plan_path, Path("out"))
            self.assertFalse((case_dir / "out").exists())

    def test_anonymity_scan_checks_support_docx_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir, plan_path = self.make_case(Path(temporary))
            support_docx = case_dir / "results" / "notes.docx"
            core = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<cp:coreProperties '
                'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                'xmlns:dc="http://purl.org/dc/elements/1.1/">'
                '<dc:creator>University of Example</dc:creator>'
                '</cp:coreProperties>'
            )
            with zipfile.ZipFile(support_docx, "w") as package:
                package.writestr("word/document.xml", "<document>safe text</document>")
                package.writestr("docProps/core.xml", core)
            plan = self.read_plan(plan_path)
            plan["support"]["files"].append(
                {"source": "results/notes.docx", "archive_path": "notes.docx"}
            )
            plan["anonymity"]["forbidden_terms"] = ["University of Example"]
            self.write_plan(plan_path, plan)
            with self.assertRaisesRegex(ValueError, "forbidden anonymity terms"):
                packaging.package_submission(case_dir, plan_path, Path("out"))

    def test_local_absolute_path_detector_distinguishes_latex_and_paths(self) -> None:
        cases = (
            (r"r_i=\frac{d_i}{h_i/100},", False),
            (r"C_j=\frac{\sum_{\ell\le j}v_\ell-v_j/2}{\sum_\ell v_\ell}.", False),
            (r"\mathcal B=\{f:f<\min(80, \lfloor f_{\max}/3\rfloor)\},\qquad", False),
            ("E:\\Competition\\file.csv", True),
            ("C:/Users/name/file.csv", True),
            ("file:///C:/Users/name/file.csv", True),
            ("/home/user/file.csv", True),
            ("/tmp/result.json", True),
            ("file:///tmp/result.json", True),
            ("\\\\server\\share\\file.csv", True),
            ("\\server/share/file.csv", False),
        )
        for value, expected in cases:
            with self.subTest(value=value):
                matches = packaging.find_local_absolute_path_matches([("sample", value)])
                self.assertEqual(bool(matches), expected)

    def test_latex_formulae_in_support_content_do_not_block_packaging(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir, plan_path = self.make_case(Path(temporary))
            (case_dir / "results" / "result.json").write_text(
                "\n".join(
                    (
                        r"$r_i=\frac{d_i}{h_i/100}$",
                        r"$C_j=\frac{\sum_{\ell\le j}v_\ell-v_j/2}{\sum_\ell v_\ell}$",
                        r"$\lfloor f_{\max}/3\rfloor$",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            report = packaging.package_submission(case_dir, plan_path, Path("out"))
            self.assertTrue(report["packaged"])

    def test_anonymity_scan_rejects_local_absolute_path_in_support_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir, plan_path = self.make_case(Path(temporary))
            (case_dir / "results" / "result.json").write_text(
                '{"source": "E:/Competition/MathModel/private.csv"}\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "local absolute paths"):
                packaging.package_submission(case_dir, plan_path, Path("out"))

    def test_failed_replace_preserves_verified_existing_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir, plan_path = self.make_case(Path(temporary))
            packaging.package_submission(case_dir, plan_path, Path("out"))
            output_dir = case_dir / "out"
            paths = [
                output_dir / "paper.pdf",
                output_dir / "support-materials.zip",
                output_dir / packaging.REPORT_NAME,
            ]
            before = {path.name: packaging.sha256_file(path) for path in paths}
            plan = self.read_plan(plan_path)
            plan["support"]["max_bytes"] = 1
            self.write_plan(plan_path, plan)
            with self.assertRaisesRegex(ValueError, "support ZIP exceeds"):
                packaging.package_submission(
                    case_dir, plan_path, Path("out"), replace=True
                )
            after = {path.name: packaging.sha256_file(path) for path in paths}
            self.assertEqual(before, after)
            self.assertEqual(
                {path.name for path in output_dir.iterdir()},
                {"paper.pdf", "support-materials.zip", packaging.REPORT_NAME},
            )


if __name__ == "__main__":
    unittest.main()

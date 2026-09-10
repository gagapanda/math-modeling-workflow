from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_DIR / "scripts"
SCHEMAS = SKILL_DIR / "schemas"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _json_schema import load_and_validate


def run_script(name: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
    )


def write_manifest(case_dir: Path, *, profile: str = "explore") -> Path:
    manifest = {
        "schema_version": 2,
        "profile": profile,
        "steps": [{"name": "analyze", "script": "src/analyze.py"}],
    }
    if profile != "explore":
        manifest["artifacts"] = {
            "docx": "paper/paper.docx",
            "pdf": "paper/paper.pdf",
            "render_dir": "paper/rendered-pages",
            "visual_review": "paper/visual-review.json",
        }
    path = case_dir / "workflow.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def snapshot(root: Path) -> dict[str, bytes | None]:
    return {
        str(path.relative_to(root)): path.read_bytes() if path.is_file() else None
        for path in sorted(root.rglob("*"))
    }


class DiagnosticTests(unittest.TestCase):
    def assert_diagnostic_schema(self, report: dict) -> None:
        load_and_validate(
            report, SCHEMAS / "diagnostics.schema.json", "diagnostic report"
        )

    def test_doctor_is_passive_and_healthy_for_complete_explore_case(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary)
            (case_dir / "src").mkdir()
            (case_dir / "src" / "analyze.py").write_text(
                "print('ok')\n", encoding="utf-8"
            )
            write_manifest(case_dir)
            before = snapshot(case_dir)

            completed = run_script(
                "doctor.py", "--case-dir", str(case_dir), "--json"
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(completed.stdout)
            self.assertTrue(report["healthy"])
            self.assertEqual(report["mode"], "passive_read_only")
            self.assertFalse(report["environment"]["active_probes_performed"])
            self.assertEqual(report["diagnostic_summary"]["error"], 0)
            self.assertEqual(snapshot(case_dir), before)
            self.assert_diagnostic_schema(report)

    def test_doctor_active_probe_is_explicit_and_nested(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary)
            (case_dir / "src").mkdir()
            (case_dir / "src" / "analyze.py").write_text(
                "print('ok')\n", encoding="utf-8"
            )
            write_manifest(case_dir)
            completed = run_script(
                "doctor.py",
                "--case-dir",
                str(case_dir),
                "--active-probe",
                "--json",
            )
            report = json.loads(completed.stdout)
            self.assertIn(completed.returncode, (0, 2))
            self.assertTrue(report["environment"]["active_probes_performed"])
            self.assertIn("active_probe_report", report["environment"])
            self.assert_diagnostic_schema(report)

    def test_doctor_reports_pointer_and_missing_step_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary)
            (case_dir / "src").mkdir()
            manifest_path = write_manifest(case_dir)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["steps"][0]["cache"] = True
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            invalid = run_script(
                "doctor.py", "--case-dir", str(case_dir), "--json"
            )
            self.assertEqual(invalid.returncode, 2)
            invalid_report = json.loads(invalid.stdout)
            self.assertEqual(invalid_report["diagnostics"][0]["code"], "manifest_invalid")
            self.assertEqual(
                invalid_report["diagnostics"][0]["json_pointer"],
                "/steps/0/outputs",
            )
            self.assert_diagnostic_schema(invalid_report)

            manifest["steps"][0].pop("cache")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            missing = run_script(
                "doctor.py", "--case-dir", str(case_dir), "--json"
            )
            missing_report = json.loads(missing.stdout)
            self.assertEqual(missing.returncode, 2)
            self.assertIn(
                "step_script_missing",
                {entry["code"] for entry in missing_report["diagnostics"]},
            )
            self.assert_diagnostic_schema(missing_report)

    def test_doctor_finalize_reports_missing_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary)
            (case_dir / "src").mkdir()
            (case_dir / "src" / "analyze.py").write_text(
                "print('ok')\n", encoding="utf-8"
            )
            write_manifest(case_dir, profile="practice")

            completed = run_script(
                "doctor.py",
                "--case-dir",
                str(case_dir),
                "--phase",
                "finalize",
                "--json",
            )
            report = json.loads(completed.stdout)
            self.assertEqual(completed.returncode, 2)
            missing = [
                entry
                for entry in report["diagnostics"]
                if entry["code"] == "finalization_input_missing"
            ]
            self.assertEqual(len(missing), 4)
            self.assertIn(
                "model_definition_register_missing",
                {entry["code"] for entry in report["diagnostics"]},
            )
            self.assert_diagnostic_schema(report)

    def test_doctor_validates_submission_evidence_paths_during_build(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary)
            (case_dir / "src").mkdir()
            (case_dir / "src" / "analyze.py").write_text(
                "print('ok')\n", encoding="utf-8"
            )
            (case_dir / "problem").mkdir()
            (case_dir / "problem" / "model-definition-register.json").write_text(
                "{}\n", encoding="utf-8"
            )
            (case_dir / "compliance").mkdir()
            manifest_path = write_manifest(case_dir, profile="submission")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["compliance"] = "compliance/submission.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            (case_dir / "compliance" / "submission.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "competition": "CUMCM 2026",
                        "year": 2026,
                        "rules": {
                            "verified_at": "2026-08-14",
                            "max_age_days": 30,
                            "sources": ["https://www.mcm.edu.cn/rules"],
                        },
                        "ai": {
                            "status": "used",
                            "usage_log": "ai/usage.md",
                            "paper_statement": "Reviewed statement",
                            "detail_pdf": "paper/AI-detail.pdf",
                        },
                    }
                ),
                encoding="utf-8",
            )

            completed = run_script(
                "doctor.py", "--case-dir", str(case_dir), "--json"
            )
            report = json.loads(completed.stdout)
            missing_pointers = {
                entry.get("json_pointer")
                for entry in report["diagnostics"]
                if entry["code"] == "compliance_evidence_missing"
            }
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(missing_pointers, {"/ai/usage_log", "/ai/detail_pdf"})
            self.assert_diagnostic_schema(report)

    def test_pipeline_and_preflight_emit_compatible_diagnostic_envelopes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary)
            (case_dir / "src").mkdir()
            (case_dir / "src" / "analyze.py").write_text(
                "print('ok')\n", encoding="utf-8"
            )
            write_manifest(case_dir)
            pipeline = run_script(
                "run_pipeline.py",
                "--case-dir",
                str(case_dir),
                "--validate-only",
                "--json",
            )
            self.assertEqual(pipeline.returncode, 0, pipeline.stderr)
            self.assert_diagnostic_schema(json.loads(pipeline.stdout))

            preflight = run_script(
                "preflight.py",
                "--project-root",
                str(case_dir),
                "--module",
                "json",
                "--json",
            )
            self.assertEqual(preflight.returncode, 0, preflight.stderr)
            self.assert_diagnostic_schema(json.loads(preflight.stdout))

    def test_compliance_and_finalizer_failures_emit_diagnostic_envelopes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary)
            compliance = run_script(
                "audit_submission_compliance.py",
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
            self.assertEqual(compliance.returncode, 2)
            compliance_report = json.loads(compliance.stdout)
            self.assertEqual(
                compliance_report["diagnostics"][0]["code"],
                "rules_or_ai_compliance_failed",
            )
            self.assert_diagnostic_schema(compliance_report)

            finalizer = run_script(
                "finalize_case.py",
                "--case-dir",
                str(case_dir),
                "--docx",
                str(case_dir / "paper" / "paper.docx"),
                "--pdf",
                str(case_dir / "paper" / "paper.pdf"),
                "--render-dir",
                str(case_dir / "paper" / "rendered-pages"),
                "--report",
                str(case_dir / "invalid-report.json"),
                "--json",
            )
            self.assertEqual(finalizer.returncode, 2)
            finalizer_report = json.loads(finalizer.stdout)
            self.assertEqual(
                finalizer_report["diagnostics"][0]["code"],
                "finalization_setup_invalid",
            )
            self.assert_diagnostic_schema(finalizer_report)


if __name__ == "__main__":
    unittest.main()

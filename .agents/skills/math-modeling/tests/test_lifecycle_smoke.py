from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_DIR / "scripts"
SCHEMAS = SKILL_DIR / "schemas"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _json_schema import load_and_validate
from test_profile_blackbox import create_profile_case, finalize, run_script


def load_pipeline_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "math_modeling_pipeline_lifecycle", SCRIPTS / "run_pipeline.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load run_pipeline.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LifecycleSmokeTests(unittest.TestCase):
    def test_practice_build_runs_result_precheck_before_export(self) -> None:
        pipeline = load_pipeline_module()
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary) / "practice-build"
            create_profile_case(case_dir, "practice")
            case_dir = case_dir.resolve()
            manifest = pipeline.load_manifest(case_dir, case_dir / "workflow.json")
            call_order: list[str] = []

            def fake_json(script, arguments, cwd):
                name = Path(script).name
                if name == "preflight.py":
                    return (
                        {
                            "ready": True,
                            "backends": {
                                "docx_to_pdf": {
                                    "primary": {
                                        "name": "fixture-export",
                                        "path": "fixture-export",
                                        "usable": True,
                                    },
                                    "fallbacks": [],
                                },
                                "pdf_to_images": {
                                    "primary": {
                                        "name": "fixture-renderer",
                                        "path": "fixture-renderer",
                                        "usable": True,
                                    },
                                    "fallbacks": [],
                                },
                            },
                            "tools": {},
                            "matlab_batch": {},
                        },
                        {},
                    )
                if name == "audit_model_definitions.py":
                    call_order.append("definitions")
                    return ({"passed": True, "errors": []}, {})
                if name == "reconcile_results.py":
                    call_order.append("reconcile")
                    return ({"reconciled": True, "errors": []}, {})
                if name == "audit_paper.py":
                    call_order.append("paper-audit")
                    return ({"structural_ok": True, "errors": []}, {})
                raise AssertionError(f"unexpected helper: {name}")

            def fake_step(step, case_root, state, fingerprint):
                call_order.append("step")
                return {"name": step["name"], "ok": True, "status": "executed"}

            def fake_export(docx, pdf, preflight, cwd):
                call_order.append("export")
                pdf.write_bytes(b"%PDF-1.4 fixture")
                return {"ok": True, "backend": "fixture-export", "attempts": []}

            def fake_render(pdf, render_dir, preflight, dpi, cwd):
                call_order.append("render")
                render_dir.mkdir(parents=True, exist_ok=True)
                (render_dir / "page-1.png").write_bytes(
                    b"\x89PNG\r\n\x1a\nfixture"
                )
                return {"ok": True, "backend": "fixture-renderer", "page_count": 1}

            with (
                patch.object(pipeline, "run_json_script", side_effect=fake_json),
                patch.object(pipeline, "cached_python_step", side_effect=fake_step),
                patch.object(pipeline, "export_docx", side_effect=fake_export),
                patch.object(pipeline, "render_pdf", side_effect=fake_render),
            ):
                report = pipeline.build_phase(case_dir, manifest, case_dir)

            self.assertTrue(report["steps_completed"])
            self.assertTrue(report["ready_for_visual_review"])
            self.assertEqual(
                call_order,
                ["definitions", "step", "reconcile", "export", "render", "paper-audit", "reconcile", "definitions"],
            )

    def test_explore_scaffold_doctor_and_build_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scaffolded = run_script(
                SCRIPTS / "scaffold_case.py",
                "explore-smoke",
                "--root",
                str(root),
                "--profile",
                "explore",
            )
            self.assertEqual(scaffolded.returncode, 0, scaffolded.stderr)
            case_dir = root / "explore-smoke"
            (case_dir / "src" / "analyze.py").write_text(
                "print('explore smoke passed')\n", encoding="utf-8"
            )

            doctor = run_script(
                SCRIPTS / "doctor.py", "--case-dir", str(case_dir), "--json"
            )
            self.assertEqual(doctor.returncode, 0, doctor.stderr)
            self.assertTrue(json.loads(doctor.stdout)["healthy"])

            build = run_script(
                SCRIPTS / "run_pipeline.py",
                "--case-dir",
                str(case_dir),
                "--phase",
                "build",
                "--json",
            )
            self.assertEqual(build.returncode, 0, build.stderr)
            report = json.loads(build.stdout)
            self.assertTrue(report["steps_completed"])
            self.assertTrue(report["postprocessing_skipped"])
            load_and_validate(
                report, SCHEMAS / "pipeline-report.schema.json", "pipeline report"
            )

    def test_practice_finalize_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary) / "practice-smoke"
            create_profile_case(case_dir, "practice")
            completed, report = finalize(case_dir)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(report["ready_for_submission"])
            load_and_validate(
                report,
                SCHEMAS / "finalization-report.schema.json",
                "finalization report",
            )

    def test_submission_finalize_lifecycle_for_both_ai_statuses(self) -> None:
        for status in ("used", "not-used"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temporary:
                case_dir = Path(temporary) / f"submission-{status}-smoke"
                create_profile_case(case_dir, "submission", status)
                completed, report = finalize(case_dir)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertTrue(report["ready_for_submission"])
                load_and_validate(
                    report,
                    SCHEMAS / "finalization-report.schema.json",
                    "finalization report",
                )

    def test_invalid_finalization_report_is_not_written(self) -> None:
        import finalize_case

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "finalization-report.json"
            with self.assertRaisesRegex(ValueError, "finalization report does not match"):
                finalize_case.write_finalization_report(output, {})
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()

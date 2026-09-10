from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
import zipfile
from argparse import Namespace
from pathlib import Path

from pypdf import PdfWriter

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


m7 = load_module("math_modeling_m7_f2_test", SCRIPTS / "audit_m7_f2.py")
packaging = load_module("math_modeling_packaging_for_m7", SCRIPTS / "package_submission.py")


class M7F2Tests(unittest.TestCase):
    def make_case(self, root: Path) -> tuple[Path, Path]:
        case = root / "case"
        for directory in ("paper", "src", "results", "submission-package", "submission"):
            (case / directory).mkdir(parents=True, exist_ok=True)
        paper = case / "paper/paper.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=595.32, height=841.92)
        with paper.open("wb") as stream:
            writer.write(stream)
        (case / "src/solve.py").write_text("print(\'ok\')\n", encoding="utf-8")
        (case / "results/out.json").write_text('{"ok": true}\n', encoding="utf-8")
        paper_hash = m7.sha256_file(paper)
        finalization = {
            "schema_version": 1,
            "generated_at": "2026-08-27T08:00:00+08:00",
            "ready_for_submission": True,
            "case_dir": str(case.resolve()),
            "artifacts": {"pdf": str(paper.resolve())},
            "artifact_hashes": {"after": {"pdf": paper_hash}},
            "commands": {}, "preflight": {}, "reconciliation": {},
            "model_definition_audit": {}, "paper_audit": {}, "visual_review": {},
            "submission_compliance": {"required": False, "passed": True, "errors": []},
            "errors": [], "diagnostics_schema_version": 1, "diagnostics": [],
            "diagnostic_summary": {"error": 0, "warning": 0, "info": 0},
        }
        finalization_path = case / "paper/finalization-report.json"
        finalization_path.write_text(json.dumps(finalization), encoding="utf-8")
        package_plan = {
            "schema_version": 1,
            "finalization_report": "paper/finalization-report.json",
            "paper": {"source": "paper/paper.pdf", "output_name": "paper.pdf", "max_bytes": 2000000},
            "support": {"output_name": "support-materials.zip", "max_bytes": 2000000, "files": [
                {"source": "src/solve.py", "archive_path": "src/solve.py"},
                {"source": "results/out.json", "archive_path": "results/out.json"},
            ]},
            "anonymity": {"forbidden_terms": []},
        }
        package_plan_path = case / "submission-package-plan.json"
        package_plan_path.write_text(json.dumps(package_plan), encoding="utf-8")
        packaging.package_submission(case, package_plan_path, Path("submission-package"))
        support = case / "submission-package/support-materials.zip"
        smoke_plan = case / "submission-package/support-smoke-plan.json"
        smoke_plan.write_text(json.dumps({"schema_version": 1, "package": "support-materials.zip", "tests": [{"name": "solve", "command": ["python", "src/solve.py"], "cwd": ".", "expected_outputs": [], "timeout_seconds": 10}]}), encoding="utf-8")
        smoke = {
            "schema_version": 1, "generated_at": "2026-08-27T08:10:00+08:00",
            "package": str(support.resolve()), "plan": str(smoke_plan.resolve()),
            "package_sha256": m7.sha256_file(support), "package_bytes": support.stat().st_size,
            "archive_members": ["results/out.json", "src/solve.py", "submission-manifest.json"],
            "tests": [{"name": "solve", "command": ["python", "src/solve.py"], "cwd": ".", "expected_outputs": [], "timeout_seconds": 10, "exit_code": 0, "timed_out": False, "stdout_bytes": 3, "stderr_bytes": 0, "stdout_sha256": "0" * 64, "stderr_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "missing_outputs": [], "elapsed_seconds": 0.1, "errors": []}],
            "errors": [], "passed": True,
        }
        smoke_report = case / "submission-package/support-smoke-report.json"
        smoke_report.write_text(json.dumps(smoke), encoding="utf-8")
        plan = {
            "schema_version": 1,
            "package_report": "submission-package/submission-package-report.json",
            "support_smoke_report": "submission-package/support-smoke-report.json",
            "required_smoke_tests": ["solve"],
            "official_upload": {"competition": "2026 CUMCM", "platform": "Official CUMCM Portal", "receipt": "submission/official-upload-receipt.pdf", "allowed_receipt_suffixes": [".pdf", ".png", ".jpg", ".jpeg"]},
            "human_gate": {"m7_manifest": "submission/M7-accepted.json", "f2_manifest": "submission/F2-submission.json"},
        }
        plan_path = case / "m7-f2-plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        return case, plan_path

    def finalize_m7(self, case: Path, plan: Path, reviewer: str = "Responsible Human") -> Path:
        candidate = case / "submission/M7-candidate.json"
        m7.prepare_m7(case, plan, candidate, "2026-08-27T08:20:00+08:00", "m7-review-1")
        output = case / "submission/M7-accepted.json"
        args = Namespace(confirm_human_reviewed=True, reviewer=reviewer, decision="accepted", review_start="2026-08-27T08:21:00+08:00", review_end="2026-08-27T08:25:00+08:00", signed_at="2026-08-27T08:26:00+08:00", generated_at="2026-08-27T08:27:00+08:00", objections="NONE", resolution="NONE")
        m7.finalize_m7(case, candidate, output, args)
        return output

    def f2_args(self, **updates) -> Namespace:
        values = dict(confirm_official_upload=True, submission_id="local-f2-1", portal_submission_identifier="portal-123", operator="Responsible Human", upload_start="2026-08-27T08:30:00+08:00", upload_end="2026-08-27T08:35:00+08:00", receipt_recorded_at="2026-08-27T08:36:00+08:00", generated_at="2026-08-27T08:37:00+08:00")
        values.update(updates)
        return Namespace(**values)

    def test_precheck_and_m7_acceptance_are_not_formal_f2(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case, plan = self.make_case(Path(temporary))
            report = m7.precheck(case, plan)
            self.assertTrue(report["m7_precheck_passed"], report["errors"])
            self.assertEqual(report["official_submission_status"], "NOT_FORMAL_F2")
            manifest = self.finalize_m7(case, plan)
            verified = m7.verify_m7(case, manifest)
            self.assertTrue(verified["passed"], verified["errors"])
            self.assertTrue(verified["m7_approved"])
            self.assertEqual(verified["official_submission_status"], "NOT_FORMAL_F2")

    def test_prepare_is_pending_and_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case, plan = self.make_case(Path(temporary))
            candidate = case / "submission/M7-candidate.json"
            payload = m7.prepare_m7(case, plan, candidate, "2026-08-27T08:20:00+08:00", "review-1")
            self.assertEqual(payload["status"], "M7_PENDING_HUMAN")
            with self.assertRaisesRegex(ValueError, "immutable"):
                m7.prepare_m7(case, plan, candidate, "2026-08-27T08:20:00+08:00", "review-2")

    def test_finalize_requires_confirmation_and_human_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case, plan = self.make_case(Path(temporary))
            candidate = case / "submission/M7-candidate.json"
            m7.prepare_m7(case, plan, candidate, "2026-08-27T08:20:00+08:00", "review-1")
            common = dict(reviewer="Human", decision="accepted", review_start="2026-08-27T08:21:00+08:00", review_end="2026-08-27T08:25:00+08:00", signed_at="2026-08-27T08:26:00+08:00", generated_at="2026-08-27T08:27:00+08:00", objections="NONE", resolution="NONE")
            with self.assertRaisesRegex(ValueError, "confirm-human-reviewed"):
                m7.finalize_m7(case, candidate, case / "submission/M7-accepted.json", Namespace(confirm_human_reviewed=False, **common))
            common["reviewer"] = "Codex"
            with self.assertRaisesRegex(ValueError, "not Codex/AI"):
                m7.finalize_m7(case, candidate, case / "submission/M7-accepted.json", Namespace(confirm_human_reviewed=True, **common))

    def test_additional_ai_names_are_rejected_for_m7_and_f2(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case, plan = self.make_case(Path(temporary))
            candidate = case / "submission/M7-candidate.json"
            m7.prepare_m7(case, plan, candidate, "2026-08-27T08:20:00+08:00", "review-ai-name")
            common = dict(confirm_human_reviewed=True, decision="accepted", review_start="2026-08-27T08:21:00+08:00", review_end="2026-08-27T08:25:00+08:00", signed_at="2026-08-27T08:26:00+08:00", generated_at="2026-08-27T08:27:00+08:00", objections="NONE", resolution="NONE")
            accepted = case / "submission/M7-accepted.json"
            with self.assertRaisesRegex(ValueError, "not Codex/AI"):
                m7.finalize_m7(case, candidate, accepted, Namespace(reviewer="OpenAI", **common))
            m7.finalize_m7(case, candidate, accepted, Namespace(reviewer="Responsible Human", **common))
            (case / "submission/official-upload-receipt.pdf").write_bytes(b"receipt")
            with self.assertRaisesRegex(ValueError, "not Codex/AI"):
                m7.record_f2(case, plan, case / "submission/F2-submission.json", self.f2_args(operator="Claude"))

    def test_verify_m7_rejects_status_decision_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case, plan = self.make_case(Path(temporary))
            manifest = self.finalize_m7(case, plan)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["status"] = "M7_REJECTED"
            payload["m7_approved"] = False
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            report = m7.verify_m7(case, manifest)
            self.assertFalse(report["passed"])
            self.assertTrue(any("status does not match" in error for error in report["errors"]))

    def test_missing_or_empty_receipt_and_ai_operator_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case, plan = self.make_case(Path(temporary))
            self.finalize_m7(case, plan)
            with self.assertRaisesRegex(ValueError, "regular non-symlink"):
                m7.record_f2(case, plan, case / "submission/F2-submission.json", self.f2_args())
            receipt = case / "submission/official-upload-receipt.pdf"
            receipt.touch()
            with self.assertRaisesRegex(ValueError, "non-empty"):
                m7.record_f2(case, plan, case / "submission/F2-submission.json", self.f2_args())
            receipt.write_bytes(b"receipt")
            with self.assertRaisesRegex(ValueError, "not Codex/AI"):
                m7.record_f2(case, plan, case / "submission/F2-submission.json", self.f2_args(operator="ChatGPT"))

    def test_required_smoke_test_and_selected_zip_binding_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case, plan = self.make_case(Path(temporary))
            smoke_path = case / "submission-package/support-smoke-report.json"
            smoke = json.loads(smoke_path.read_text(encoding="utf-8"))
            smoke["tests"] = []
            smoke_path.write_text(json.dumps(smoke), encoding="utf-8")
            report = m7.precheck(case, plan)
            self.assertFalse(report["m7_precheck_passed"])
            self.assertTrue(any("required support smoke test" in error for error in report["errors"]))
            smoke["tests"] = [{"name": "solve", "command": [], "cwd": ".", "expected_outputs": [], "timeout_seconds": 10, "exit_code": 0, "timed_out": False, "stdout_bytes": 0, "stderr_bytes": 0, "stdout_sha256": None, "stderr_sha256": None, "missing_outputs": [], "elapsed_seconds": 0.1, "errors": []}]
            smoke["package_sha256"] = "0" * 64
            smoke_path.write_text(json.dumps(smoke), encoding="utf-8")
            report = m7.precheck(case, plan)
            self.assertFalse(report["m7_precheck_passed"])
            self.assertTrue(any("SHA-256 differs" in error for error in report["errors"]))

    def test_package_change_after_m7_blocks_f2(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case, plan = self.make_case(Path(temporary))
            self.finalize_m7(case, plan)
            (case / "submission/official-upload-receipt.pdf").write_bytes(b"receipt")
            with (case / "submission-package/support-materials.zip").open("ab") as stream:
                stream.write(b"changed")
            with self.assertRaisesRegex(ValueError, "selected package changed|verified accepted M7"):
                m7.record_f2(case, plan, case / "submission/F2-submission.json", self.f2_args())

    def test_human_upload_receipt_can_create_and_verify_f2(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case, plan = self.make_case(Path(temporary))
            self.finalize_m7(case, plan)
            receipt = case / "submission/official-upload-receipt.pdf"
            receipt.write_bytes(b"official receipt evidence")
            output = case / "submission/F2-submission.json"
            payload = m7.record_f2(case, plan, output, self.f2_args())
            self.assertEqual(payload["status"], "F2_COMPLETE")
            verified = m7.verify_f2(case, output)
            self.assertTrue(verified["passed"], verified["errors"])
            with self.assertRaisesRegex(ValueError, "immutable"):
                m7.record_f2(case, plan, output, self.f2_args())
            receipt.write_bytes(b"changed receipt")
            self.assertFalse(m7.verify_f2(case, output)["passed"])

    def test_f2_time_cannot_precede_m7_signature(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case, plan = self.make_case(Path(temporary))
            self.finalize_m7(case, plan)
            (case / "submission/official-upload-receipt.pdf").write_bytes(b"receipt")
            args = self.f2_args(upload_start="2026-08-27T08:00:00+08:00")
            with self.assertRaisesRegex(ValueError, "M7 signed_at"):
                m7.record_f2(case, plan, case / "submission/F2-submission.json", args)


if __name__ == "__main__":
    unittest.main()

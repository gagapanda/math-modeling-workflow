from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


authority = load_module("math_modeling_paper_authority", SCRIPTS / "audit_paper_authority.py")
pipeline = load_module("math_modeling_pipeline_authority", SCRIPTS / "run_pipeline.py")
scaffold = load_module("math_modeling_scaffold_authority", SCRIPTS / "scaffold_case.py")
freeze = load_module("math_modeling_freeze_authority", SCRIPTS / "freeze_results.py")


class PaperAuthorityTests(unittest.TestCase):
    def write_base_case(self, root: Path, mode: str = "draft") -> Path:
        case = root / "case"
        for directory in ("paper", "results", "replay"):
            (case / directory).mkdir(parents=True, exist_ok=True)
        marker = "NON_AUTHORITATIVE REVIEW DRAFT"
        source = f"# Paper\n\n**{marker}**\n" if mode == "draft" else "# Paper\n\nFinal text\n"
        (case / "paper" / "full-paper.md").write_text(source, encoding="utf-8")
        (case / "results" / "result-register.json").write_text(
            json.dumps({"schema_version": 1, "results": [{"id": "Q1", "value": 42}]}) + "\n",
            encoding="utf-8",
        )
        (case / "results" / "result.json").write_text('{"value": 42}\n', encoding="utf-8")
        for index in (1, 2):
            (case / "replay" / f"run-{index}.json").write_text(
                json.dumps({"run": index, "value": 42}) + "\n", encoding="utf-8"
            )
        (case / "CURRENT-STATE.md").write_text(
            "# Current State\n\n## Authority\n\n"
            "| Field | Current value |\n| --- | --- |\n"
            "| Pointer status | `INITIALIZING` |\n"
            "| Canonical result register | `results/result-register.json` |\n"
            "| F1 status | `NOT_FROZEN` |\n"
            "| F1 accepted manifest | `NOT_CREATED` |\n"
            "| F1 verification | `NOT_RUN` |\n"
            "| Paper authoritative | `false` |\n"
            "| Authoritative paper source | `paper/full-paper.md` |\n"
            "| Human approval | `NOT_SIGNED` |\n",
            encoding="utf-8",
        )
        plan = {
            "schema_version": 1,
            "mode": mode,
            "current_state": "CURRENT-STATE.md",
            "result_register": "results/result-register.json",
            "freeze_manifest": "",
            "paper_source": "paper/full-paper.md",
            "draft_marker": marker,
        }
        (case / "paper" / "paper-authority-plan.json").write_text(
            json.dumps(plan, indent=2) + "\n", encoding="utf-8"
        )
        return case

    def accept_f1(self, case: Path) -> None:
        plan = {
            "schema_version": 1,
            "freeze_id": "F1-test-001",
            "result_register": "results/result-register.json",
            "files": [
                {"path": "results/result-register.json", "kind": "result-register"},
                {"path": "results/result.json", "kind": "result"},
                {"path": "replay/run-1.json", "kind": "replay"},
                {"path": "replay/run-2.json", "kind": "replay"},
            ],
            "replay_evidence": ["replay/run-1.json", "replay/run-2.json"],
            "limitations": [],
            "unresolved": [],
        }
        (case / "results" / "f1-freeze-plan.json").write_text(
            json.dumps(plan, indent=2) + "\n", encoding="utf-8"
        )
        candidate = freeze.prepare(
            case,
            "results/f1-freeze-plan.json",
            "results/f1-candidate.json",
            "2026-08-27T10:00:00+08:00",
        )
        freeze.finalize(
            case,
            "results/f1-candidate.json",
            "results/f1-manifest.json",
            SimpleNamespace(
                confirm_human_reviewed=True,
                reviewer="Responsible Operator",
                review_start="2026-08-27T10:01:00+08:00",
                review_end="2026-08-27T10:02:00+08:00",
                signed_at="2026-08-27T10:03:00+08:00",
                generated_at="2026-08-27T10:04:00+08:00",
                decision="accepted",
                objections="NONE",
                resolution="NONE",
            ),
        )
        authority_plan = json.loads((case / "paper" / "paper-authority-plan.json").read_text())
        authority_plan.update(mode="authoritative", freeze_manifest="results/f1-manifest.json")
        (case / "paper" / "paper-authority-plan.json").write_text(
            json.dumps(authority_plan, indent=2) + "\n", encoding="utf-8"
        )
        (case / "paper" / "full-paper.md").write_text("# Paper\n\nFinal text\n", encoding="utf-8")
        (case / "CURRENT-STATE.md").write_text(
            "# Current State\n\n## Authority\n\n"
            "| Field | Current value |\n| --- | --- |\n"
            "| Pointer status | `ACTIVE` |\n"
            "| Canonical result register | `results/result-register.json` |\n"
            "| F1 status | `F1_ACCEPTED` |\n"
            "| F1 accepted manifest | `results/f1-manifest.json` |\n"
            "| F1 verification | `PASSED` |\n"
            "| Paper authoritative | `true` |\n"
            "| Authoritative paper source | `paper/full-paper.md` |\n"
            "| Human approval | `SIGNED` |\n",
            encoding="utf-8",
        )

    def test_draft_is_visible_but_never_authoritative(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.write_base_case(Path(temporary))
            report = authority.run_audit(case, "paper/paper-authority-plan.json")
            self.assertFalse(report["passed"])
            self.assertFalse(report["paper_authoritative"])
            self.assertTrue(report["marker_checks"]["paper_source_contains_draft_marker"])

    def test_draft_requires_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.write_base_case(Path(temporary))
            (case / "paper" / "full-paper.md").write_text("# Paper\n", encoding="utf-8")
            report = authority.run_audit(case, "paper/paper-authority-plan.json")
            self.assertTrue(any("must contain" in item for item in report["errors"]))

    def test_authoritative_chain_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.write_base_case(Path(temporary))
            self.accept_f1(case)
            report = authority.run_audit(case, "paper/paper-authority-plan.json")
            self.assertTrue(report["passed"], report["errors"])
            self.assertTrue(report["paper_authoritative"])

    def test_current_state_mismatch_and_frozen_drift_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.write_base_case(Path(temporary))
            self.accept_f1(case)
            state = case / "CURRENT-STATE.md"
            state.write_text(state.read_text().replace("F1_ACCEPTED`", "F1_REJECTED`"), encoding="utf-8")
            report = authority.run_audit(case, "paper/paper-authority-plan.json")
            self.assertFalse(report["passed"])
            self.assertTrue(any("F1 status" in item for item in report["errors"]))

    def test_frozen_file_drift_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.write_base_case(Path(temporary))
            self.accept_f1(case)
            (case / "results" / "result.json").write_text('{"value": 99}\n', encoding="utf-8")
            report = authority.run_audit(case, "paper/paper-authority-plan.json")
            self.assertFalse(report["passed"])
            self.assertTrue(any("F1 verification" in item for item in report["errors"]))

    def test_authoritative_source_must_not_retain_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.write_base_case(Path(temporary))
            self.accept_f1(case)
            (case / "paper" / "full-paper.md").write_text(
                "# Paper\nNON_AUTHORITATIVE REVIEW DRAFT\n", encoding="utf-8"
            )
            report = authority.run_audit(case, "paper/paper-authority-plan.json")
            self.assertFalse(report["passed"])
            self.assertTrue(any("still contains" in item for item in report["errors"]))

    def test_path_escape_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case = self.write_base_case(root)
            outside = root / "outside.json"
            outside.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "escapes"):
                authority.run_audit(case, str(outside.resolve()))

    def test_scaffold_defaults_and_second_run_preserves_operator_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = subprocess.run(
                [sys.executable, str(SCRIPTS / "scaffold_case.py"), "case-a", "--root", str(root)],
                capture_output=True, text=True, encoding="utf-8", check=False,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            case = root / "case-a"
            workflow = json.loads((case / "workflow.json").read_text())
            self.assertEqual(workflow["paper_authority_plan"], "paper/paper-authority-plan.json")
            self.assertIn("NON_AUTHORITATIVE REVIEW DRAFT", (case / "paper/full-paper.md").read_text())
            (case / "paper/paper-authority-plan.json").write_text("operator plan\n", encoding="utf-8")
            (case / "paper/full-paper.md").write_text("operator paper\n", encoding="utf-8")
            second = subprocess.run(
                [sys.executable, str(SCRIPTS / "scaffold_case.py"), "case-a", "--root", str(root)],
                capture_output=True, text=True, encoding="utf-8", check=False,
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual((case / "paper/paper-authority-plan.json").read_text(), "operator plan\n")
            self.assertEqual((case / "paper/full-paper.md").read_text(), "operator paper\n")

    def test_workflow_loader_serializer_and_legacy_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = Path(temporary)
            (case / "src").mkdir()
            (case / "paper").mkdir()
            (case / "src/analyze.py").write_text("print(1)\n", encoding="utf-8")
            (case / "paper/paper-authority-plan.json").write_text("{}\n", encoding="utf-8")
            manifest = {
                "schema_version": 2,
                "profile": "explore",
                "paper_authority_plan": "paper/paper-authority-plan.json",
                "steps": [{"name": "a", "script": "src/analyze.py", "inputs": [], "outputs": []}],
            }
            path = case / "workflow.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            normalized = pipeline.load_manifest(case, path)
            self.assertEqual(normalized["paper_authority_plan"], (case / "paper/paper-authority-plan.json").resolve())
            self.assertIn("paper_authority_plan", pipeline.serialize_manifest(normalized))
            legacy = {
                "schema_version": 1,
                "steps": [{"name": "a", "script": "src/analyze.py"}],
                "artifacts": {
                    "docx": "paper/paper.docx",
                    "pdf": "paper/paper.pdf",
                    "render_dir": "paper/rendered-pages",
                    "visual_review": "paper/visual-review.json",
                },
            }
            path.write_text(json.dumps(legacy), encoding="utf-8")
            self.assertIsNone(pipeline.load_manifest(case, path)["paper_authority_plan"])
            legacy["paper_authority_plan"] = "paper/paper-authority-plan.json"
            path.write_text(json.dumps(legacy), encoding="utf-8")
            with self.assertRaises(ValueError):
                pipeline.load_manifest(case, path)

    def test_scaffold_explore_omits_authority_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "scaffold_case.py"),
                    "case-explore",
                    "--root",
                    str(root),
                    "--profile",
                    "explore",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            case = root / "case-explore"
            workflow = json.loads((case / "workflow.json").read_text())
            self.assertNotIn("paper_authority_plan", workflow)
            self.assertFalse((case / "paper/paper-authority-plan.json").exists())

    def test_finalize_phase_routes_authority_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = Path(temporary)
            plan = case / "paper" / "paper-authority-plan.json"
            artifacts = {
                "docx": case / "paper" / "paper.docx",
                "pdf": case / "paper" / "paper.pdf",
                "render_dir": case / "paper" / "rendered-pages",
                "visual_review": case / "paper" / "visual-review.json",
            }
            manifest = {
                "profile": "practice",
                "paper_authority_plan": plan,
                "quality_gate_plan": None,
                "artifacts": artifacts,
                "audit": {"page_size": "a4", "orientation": "portrait", "forbid": []},
            }
            from unittest.mock import patch
            with patch.object(pipeline, "run_json_script", return_value=({"ready_for_submission": False}, {})) as call:
                pipeline.finalize_phase(case, manifest, SCRIPTS)
            arguments = call.call_args.args[1]
            index = arguments.index("--paper-authority-plan")
            self.assertEqual(arguments[index + 1], str(plan))

    def test_finalization_authority_gate_blocks_draft_and_allows_accepted_chain(self) -> None:
        profile_tests = load_module(
            "math_modeling_profile_authority_fixture", Path(__file__).with_name("test_profile_blackbox.py")
        )
        finalize_module = load_module(
            "math_modeling_finalize_authority", SCRIPTS / "finalize_case.py"
        )
        with tempfile.TemporaryDirectory() as temporary:
            case = Path(temporary) / "draft-case"
            fixture = profile_tests.create_profile_case(case, "practice")
            (case / "paper/full-paper.md").write_text(
                "# Paper\n\nNON_AUTHORITATIVE REVIEW DRAFT\n", encoding="utf-8"
            )
            (case / "CURRENT-STATE.md").write_text(
                "| Field | Current value |\n| --- | --- |\n"
                "| Pointer status | `INITIALIZING` |\n"
                "| Canonical result register | `results/result-register.json` |\n"
                "| F1 status | `NOT_FROZEN` |\n"
                "| F1 accepted manifest | `NOT_CREATED` |\n"
                "| F1 verification | `NOT_RUN` |\n"
                "| Paper authoritative | `false` |\n"
                "| Authoritative paper source | `paper/full-paper.md` |\n"
                "| Human approval | `NOT_SIGNED` |\n",
                encoding="utf-8",
            )
            authority_plan = {
                "schema_version": 1,
                "mode": "draft",
                "current_state": "CURRENT-STATE.md",
                "result_register": "results/result-register.json",
                "freeze_manifest": "",
                "paper_source": "paper/full-paper.md",
                "draft_marker": "NON_AUTHORITATIVE REVIEW DRAFT",
            }
            plan_path = case / "paper/paper-authority-plan.json"
            plan_path.write_text(json.dumps(authority_plan, indent=2) + "\n", encoding="utf-8")
            args = SimpleNamespace(
                case_dir=case,
                docx=fixture["docx"],
                pdf=fixture["pdf"],
                render_dir=case / "paper/rendered-pages",
                register=None,
                visual_review_record=fixture["review"],
                submission_compliance=None,
                paper_authority_plan=plan_path,
                quality_gate_plan=None,
                qa_register=None,
                report=None,
                page_size="a4",
                orientation="portrait",
                forbid=["TODO"],
                json=True,
            )
            report, _, _ = finalize_module.run_finalization(args)
            self.assertFalse(report["ready_for_submission"])
            self.assertTrue(report["paper_authority"]["required"])
            self.assertFalse(report["paper_authority"]["passed"])

        with tempfile.TemporaryDirectory() as temporary:
            case = Path(temporary) / "accepted-case"
            fixture = profile_tests.create_profile_case(case, "practice")
            (case / "paper/full-paper.md").write_text("# Paper\n\nFinal text\n", encoding="utf-8")
            for directory in ("replay",):
                (case / directory).mkdir(exist_ok=True)
            for index in (1, 2):
                (case / "replay" / f"run-{index}.json").write_text(
                    json.dumps({"run": index, "value": 42}) + "\n", encoding="utf-8"
                )
            freeze_plan = {
                "schema_version": 1,
                "freeze_id": "F1-finalization-001",
                "result_register": "results/result-register.json",
                "files": [
                    {"path": "results/result-register.json", "kind": "result-register"},
                    {"path": "results/answer.json", "kind": "result"},
                    {"path": "replay/run-1.json", "kind": "replay"},
                    {"path": "replay/run-2.json", "kind": "replay"},
                ],
                "replay_evidence": ["replay/run-1.json", "replay/run-2.json"],
                "limitations": [],
                "unresolved": [],
            }
            (case / "results/f1-freeze-plan.json").write_text(
                json.dumps(freeze_plan, indent=2) + "\n", encoding="utf-8"
            )
            freeze.prepare(case, "results/f1-freeze-plan.json", "results/f1-candidate.json", "2026-08-27T10:00:00+08:00")
            freeze.finalize(
                case, "results/f1-candidate.json", "results/f1-manifest.json",
                SimpleNamespace(
                    confirm_human_reviewed=True, reviewer="Responsible Operator",
                    review_start="2026-08-27T10:01:00+08:00", review_end="2026-08-27T10:02:00+08:00",
                    signed_at="2026-08-27T10:03:00+08:00", generated_at="2026-08-27T10:04:00+08:00",
                    decision="accepted", objections="NONE", resolution="NONE",
                ),
            )
            (case / "CURRENT-STATE.md").write_text(
                "| Field | Current value |\n| --- | --- |\n"
                "| Pointer status | `ACTIVE` |\n"
                "| Canonical result register | `results/result-register.json` |\n"
                "| F1 status | `F1_ACCEPTED` |\n"
                "| F1 accepted manifest | `results/f1-manifest.json` |\n"
                "| F1 verification | `PASSED` |\n"
                "| Paper authoritative | `true` |\n"
                "| Authoritative paper source | `paper/full-paper.md` |\n"
                "| Human approval | `SIGNED` |\n",
                encoding="utf-8",
            )
            plan_path = case / "paper/paper-authority-plan.json"
            plan_path.write_text(
                json.dumps({
                    "schema_version": 1, "mode": "authoritative", "current_state": "CURRENT-STATE.md",
                    "result_register": "results/result-register.json", "freeze_manifest": "results/f1-manifest.json",
                    "paper_source": "paper/full-paper.md", "draft_marker": "NON_AUTHORITATIVE REVIEW DRAFT",
                }, indent=2) + "\n", encoding="utf-8"
            )
            args = SimpleNamespace(
                case_dir=case, docx=fixture["docx"], pdf=fixture["pdf"],
                render_dir=case / "paper/rendered-pages", register=None,
                visual_review_record=fixture["review"], submission_compliance=None,
                paper_authority_plan=plan_path, quality_gate_plan=None,
                qa_register=None, report=None, page_size="a4", orientation="portrait",
                forbid=["TODO"], json=True,
            )
            report, _, _ = finalize_module.run_finalization(args)
            self.assertTrue(report["paper_authority"]["passed"], report["paper_authority"]["errors"])
            self.assertTrue(report["ready_for_submission"], report["errors"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


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


manager = load_module("math_modeling_candidate_manager", SCRIPTS / "manage_candidates.py")
heartbeat = load_module("math_modeling_candidate_heartbeat", SCRIPTS / "audit_authority_heartbeat.py")
MM = SCRIPTS / "mm.py"


def arguments(action: str, case: Path, **values):
    defaults = {
        "candidate_action": action,
        "case_dir": case,
        "registry": "authority/candidate-registry.json",
        "json": True,
        "at": "2026-09-14T12:00:00+08:00",
        "kind": "paper",
        "path": "paper/candidates/paper-01/paper.pdf",
        "source": "test fixture",
        "supersede_current": False,
        "reason": "",
        "by": "",
        "skip_content_verification": False,
        "plan": "authority/candidate-classification-plan.json",
    }
    defaults.update(values)
    return type("Arguments", (), defaults)()


class CandidateManagerTests(unittest.TestCase):
    def write_case(self, root: Path) -> Path:
        case = root / "case"
        (case / "paper/candidates/paper-01").mkdir(parents=True)
        (case / "paper/candidates/paper-01/paper.pdf").write_bytes(b"paper one")
        (case / "paper/candidates/paper-02").mkdir()
        (case / "paper/candidates/paper-02/paper.pdf").write_bytes(b"paper two")
        (case / "results").mkdir()
        (case / "results/result-register.json").write_text(
            '{"schema_version": 1, "results": []}\n', encoding="utf-8"
        )
        (case / "paper/full-paper.md").write_text("# Draft\n", encoding="utf-8")
        template = (SKILL_ROOT / "templates/CURRENT-STATE.md").read_text(encoding="utf-8")
        (case / "CURRENT-STATE.md").write_text(template, encoding="utf-8")
        return case

    def test_register_binds_content_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.write_case(Path(temporary))
            first = manager.execute(arguments("register", case))
            second = manager.execute(arguments("register", case))
            self.assertTrue(first["changed"])
            self.assertFalse(second["changed"])
            self.assertEqual(first["candidate"]["sha256"], second["candidate"]["sha256"])
            self.assertEqual(second["summary"]["revision"], 1)

    def test_select_requires_explicit_superseding_and_reason(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.write_case(Path(temporary))
            manager.execute(arguments("register", case))
            manager.execute(arguments("select", case))
            manager.execute(
                arguments(
                    "register",
                    case,
                    path="paper/candidates/paper-02/paper.pdf",
                    at="2026-09-14T12:01:00+08:00",
                )
            )
            with self.assertRaisesRegex(ValueError, "current candidate already exists"):
                manager.execute(
                    arguments(
                        "select",
                        case,
                        path="paper/candidates/paper-02/paper.pdf",
                        at="2026-09-14T12:02:00+08:00",
                    )
                )
            selected = manager.execute(
                arguments(
                    "select",
                    case,
                    path="paper/candidates/paper-02/paper.pdf",
                    supersede_current=True,
                    reason="reader-reviewed replacement",
                    at="2026-09-14T12:03:00+08:00",
                )
            )
            self.assertTrue(selected["pointer_update_required"])
            entries = selected["summary"]["candidates"]
            statuses = {entry["path"]: entry["status"] for entry in entries}
            self.assertEqual(statuses["paper/candidates/paper-01/paper.pdf"], "superseded")
            self.assertEqual(statuses["paper/candidates/paper-02/paper.pdf"], "current")
            self.assertTrue((case / "paper/candidates/paper-01/paper.pdf").is_file())

    def test_explicit_supersede_records_lineage_without_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.write_case(Path(temporary))
            manager.execute(arguments("register", case))
            manager.execute(
                arguments(
                    "register",
                    case,
                    path="paper/candidates/paper-02/paper.pdf",
                    at="2026-09-14T12:01:00+08:00",
                )
            )
            report = manager.execute(
                arguments(
                    "supersede",
                    case,
                    path="paper/candidates/paper-01/paper.pdf",
                    by="paper/candidates/paper-02/paper.pdf",
                    reason="replaced after review",
                    at="2026-09-14T12:02:00+08:00",
                )
            )
            self.assertTrue(report["changed"])
            self.assertTrue((case / "paper/candidates/paper-01/paper.pdf").is_file())
            self.assertTrue((case / "paper/candidates/paper-02/paper.pdf").is_file())
            entry = next(
                item
                for item in report["summary"]["candidates"]
                if item["path"] == "paper/candidates/paper-01/paper.pdf"
            )
            self.assertEqual(entry["status"], "superseded")
            self.assertEqual(entry["reason"], "replaced after review")

    def test_semantics_reject_timezone_free_transition_time(self) -> None:
        payload = manager.empty_registry()
        payload.update(revision=1, updated_at="2026-09-14T12:00:00")
        self.assertTrue(
            any("timezone offset" in error for error in manager.validate_semantics(payload))
        )

    def test_list_detects_content_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.write_case(Path(temporary))
            manager.execute(arguments("register", case))
            (case / "paper/candidates/paper-01/paper.pdf").write_bytes(b"changed")
            listed = manager.execute(arguments("list", case))
            self.assertFalse(listed["passed"])
            self.assertTrue(listed["summary"]["verification_errors"])

    def test_directory_candidate_has_deterministic_tree_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.write_case(Path(temporary))
            support = case / "paper/candidates/support-01"
            support.mkdir()
            (support / "b.txt").write_text("b", encoding="utf-8")
            (support / "a.txt").write_text("a", encoding="utf-8")
            first = manager.snapshot(
                case.resolve(), case / "authority/candidate-registry.json", "paper/candidates/support-01"
            )
            second = manager.snapshot(
                case.resolve(), case / "authority/candidate-registry.json", "paper/candidates/support-01"
            )
            self.assertEqual(first, second)
            self.assertEqual(first["file_count"], 2)

    def test_retain_preserves_non_current_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.write_case(Path(temporary))
            manager.execute(arguments("register", case))
            report = manager.execute(
                arguments(
                    "retain",
                    case,
                    reason="component evidence, not a standalone paper",
                )
            )
            self.assertEqual(report["candidate"]["status"], "retained")
            self.assertTrue((case / "paper/candidates/paper-01/paper.pdf").is_file())

    def test_import_plan_initializes_registry_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.write_case(Path(temporary))
            plan_path = case / "authority/candidate-classification-plan.json"
            plan_path.parent.mkdir(exist_ok=True)
            plan_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "recorded_at": "2026-09-14T12:00:00+08:00",
                        "source": "post-contest inventory",
                        "entries": [
                            {
                                "kind": "paper",
                                "path": "paper/candidates/paper-01/paper.pdf",
                                "status": "superseded",
                                "reason": "replaced by reviewed paper",
                                "superseded_by": "paper/candidates/paper-02/paper.pdf",
                            },
                            {
                                "kind": "paper",
                                "path": "paper/candidates/paper-02/paper.pdf",
                                "status": "current",
                                "reason": None,
                                "superseded_by": None,
                            },
                            {
                                "kind": "paper",
                                "path": "paper/candidates/paper-02",
                                "status": "retained",
                                "reason": "container evidence retained for audit",
                                "superseded_by": None,
                            },
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            report = manager.execute(arguments("import-plan", case))
            self.assertTrue(report["passed"])
            self.assertEqual(report["summary"]["revision"], 1)
            self.assertEqual(report["summary"]["counts"]["retained"], 1)
            with self.assertRaisesRegex(ValueError, "absent, empty"):
                manager.execute(arguments("import-plan", case))

    def test_import_plan_failure_does_not_create_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.write_case(Path(temporary))
            plan_path = case / "authority/candidate-classification-plan.json"
            plan_path.parent.mkdir(exist_ok=True)
            plan_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "recorded_at": "2026-09-14T12:00:00+08:00",
                        "source": "bad fixture",
                        "entries": [
                            {
                                "kind": "paper",
                                "path": "paper/candidates/missing.pdf",
                                "status": "current",
                                "reason": None,
                                "superseded_by": None,
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "does not exist"):
                manager.execute(arguments("import-plan", case))
            self.assertFalse((case / "authority/candidate-registry.json").exists())

    def test_heartbeat_requires_registry_current_to_match_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.write_case(Path(temporary))
            manager.execute(arguments("register", case))
            manager.execute(arguments("select", case))
            report = heartbeat.audit(case)
            self.assertFalse(report["healthy"])
            self.assertIn(
                "candidate_registry_pointer_mismatch",
                {item["code"] for item in report["diagnostics"]},
            )
            state = case / "CURRENT-STATE.md"
            state.write_text(
                state.read_text(encoding="utf-8").replace(
                    "| Current generated paper | `NOT_BUILT` |",
                    "| Current generated paper | `paper/candidates/paper-01/paper.pdf` |",
                ),
                encoding="utf-8",
            )
            repaired = heartbeat.audit(case)
            self.assertNotIn(
                "candidate_registry_pointer_mismatch",
                {item["code"] for item in repaired["diagnostics"]},
            )

    def test_mm_candidate_delegates_without_changing_gate_meaning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.write_case(Path(temporary))
            completed = subprocess.run(
                [
                    sys.executable,
                    str(MM),
                    "candidate",
                    "register",
                    str(case),
                    "--kind",
                    "paper",
                    "--path",
                    "paper/candidates/paper-01/paper.pdf",
                    "--at",
                    "2026-09-14T12:00:00+08:00",
                    "--json",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(completed.stdout)
            self.assertTrue(report["passed"])
            self.assertIn("does not select authority", report["claim_scope"])

    def test_absolute_candidate_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.write_case(Path(temporary))
            with self.assertRaisesRegex(ValueError, "case-relative"):
                manager.execute(
                    arguments(
                        "register",
                        case,
                        path=str((case / "paper/candidates/paper-01/paper.pdf").resolve()),
                    )
                )


if __name__ == "__main__":
    unittest.main()

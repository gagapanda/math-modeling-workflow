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


heartbeat = load_module(
    "math_modeling_authority_heartbeat", SCRIPTS / "audit_authority_heartbeat.py"
)


class AuthorityHeartbeatTests(unittest.TestCase):
    def write_case(self, root: Path) -> Path:
        case = root / "case"
        (case / "paper").mkdir(parents=True)
        (case / "results").mkdir()
        (case / "authority").mkdir()
        (case / "authority/candidate-registry.json").write_text(
            json.dumps(
                {"schema_version": 1, "revision": 0, "updated_at": None, "candidates": []}
            )
            + "\n",
            encoding="utf-8",
        )
        (case / "results/result-register.json").write_text(
            json.dumps({"schema_version": 1, "results": []}) + "\n", encoding="utf-8"
        )
        (case / "paper/full-paper.md").write_text("# Draft\n", encoding="utf-8")
        template = (SKILL_ROOT / "templates/CURRENT-STATE.md").read_text(encoding="utf-8")
        (case / "CURRENT-STATE.md").write_text(template, encoding="utf-8")
        return case

    def test_clean_initial_pointer_is_healthy_with_metadata_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.write_case(Path(temporary))
            report = heartbeat.audit(case)
            self.assertTrue(report["healthy"], report["diagnostics"])
            self.assertEqual(report["diagnostic_summary"]["error"], 0)
            self.assertEqual(report["diagnostic_summary"]["warning"], 2)
            self.assertEqual(report["candidate_lineage"]["found"], [])

    def test_missing_selected_path_is_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.write_case(Path(temporary))
            state = case / "CURRENT-STATE.md"
            state.write_text(
                state.read_text(encoding="utf-8").replace(
                    "| Current generated paper | `NOT_BUILT` |",
                    "| Current generated paper | `paper/missing.pdf` |",
                ),
                encoding="utf-8",
            )
            report = heartbeat.audit(case)
            self.assertFalse(report["healthy"])
            self.assertIn(
                "selected_authority_path_missing",
                {item["code"] for item in report["diagnostics"]},
            )

    def test_authoritative_claim_requires_f1_and_human_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.write_case(Path(temporary))
            state = case / "CURRENT-STATE.md"
            state.write_text(
                state.read_text(encoding="utf-8").replace(
                    "| Paper authoritative | `false` |",
                    "| Paper authoritative | `true` |",
                ),
                encoding="utf-8",
            )
            report = heartbeat.audit(case)
            self.assertFalse(report["healthy"])
            codes = {item["code"] for item in report["diagnostics"]}
            self.assertIn("paper_authority_state_mismatch", codes)
            self.assertIn("paper_authority_manifest_missing", codes)

    def test_multiple_unclassified_candidates_require_unresolved_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.write_case(Path(temporary))
            candidates = case / "paper/candidates"
            (candidates / "paper-01").mkdir(parents=True)
            (candidates / "paper-02").mkdir()
            report = heartbeat.audit(case)
            self.assertFalse(report["healthy"])
            self.assertEqual(len(report["candidate_lineage"]["unresolved"]), 2)
            codes = {item["code"] for item in report["diagnostics"]}
            self.assertIn("candidate_lineage_unresolved", codes)
            self.assertIn("pointer_status_not_unresolved", codes)

    def test_selected_and_superseded_candidates_close_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.write_case(Path(temporary))
            candidates = case / "paper/candidates"
            old = candidates / "paper-01"
            current = candidates / "paper-02"
            old.mkdir(parents=True)
            current.mkdir()
            (current / "paper.pdf").write_bytes(b"pdf")
            state = case / "CURRENT-STATE.md"
            text = state.read_text(encoding="utf-8")
            text = text.replace(
                "| Current generated paper | `NOT_BUILT` |",
                "| Current generated paper | `paper/candidates/paper-02/paper.pdf` |",
            ).replace(
                "## Superseded Candidates\n\n`NONE_RECORDED`",
                "## Superseded Candidates\n\n"
                "`paper/candidates/paper-01` superseded by `paper/candidates/paper-02`",
            )
            state.write_text(text, encoding="utf-8")
            report = heartbeat.audit(case)
            self.assertTrue(report["healthy"], report["diagnostics"])
            self.assertEqual(report["candidate_lineage"]["selected"], ["paper/candidates/paper-02"])
            self.assertEqual(report["candidate_lineage"]["superseded"], ["paper/candidates/paper-01"])

    def test_paper_and_support_may_select_distinct_candidate_containers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.write_case(Path(temporary))
            candidates = case / "paper/candidates"
            paper = candidates / "paper-02"
            support = candidates / "support-02"
            paper.mkdir(parents=True)
            support.mkdir()
            (paper / "paper.pdf").write_bytes(b"pdf")
            (support / "support.zip").write_bytes(b"zip")
            state = case / "CURRENT-STATE.md"
            text = state.read_text(encoding="utf-8").replace(
                "| Current generated paper | `NOT_BUILT` |",
                "| Current generated paper | `paper/candidates/paper-02/paper.pdf` |",
            ).replace(
                "| Selected support ZIP | `NOT_SELECTED` |",
                "| Selected support ZIP | `paper/candidates/support-02/support.zip` |",
            )
            state.write_text(text, encoding="utf-8")
            report = heartbeat.audit(case)
            self.assertTrue(report["healthy"], report["diagnostics"])
            self.assertEqual(
                report["candidate_lineage"]["selected"],
                ["paper/candidates/paper-02", "paper/candidates/support-02"],
            )

    def test_superseded_matching_does_not_use_directory_name_prefixes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.write_case(Path(temporary))
            candidates = case / "paper/candidates"
            (candidates / "paper-01").mkdir(parents=True)
            (candidates / "paper-010").mkdir()
            state = case / "CURRENT-STATE.md"
            state.write_text(
                state.read_text(encoding="utf-8").replace(
                    "## Superseded Candidates\n\n`NONE_RECORDED`",
                    "## Superseded Candidates\n\n`paper/candidates/paper-010`",
                ),
                encoding="utf-8",
            )
            report = heartbeat.audit(case)
            self.assertEqual(
                report["candidate_lineage"]["superseded"],
                ["paper/candidates/paper-010"],
            )
            self.assertEqual(
                report["candidate_lineage"]["unresolved"],
                ["paper/candidates/paper-01"],
            )

    def test_retained_registry_entry_closes_component_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.write_case(Path(temporary))
            component = case / "paper/candidates/model-schematic-01"
            component.mkdir(parents=True)
            (component / "figure.png").write_bytes(b"png")
            recorded = __import__("manage_candidates").snapshot(
                case.resolve(),
                case / "authority/candidate-registry.json",
                "paper/candidates/model-schematic-01",
            )
            entry = {
                "id": __import__("manage_candidates").candidate_id("paper", recorded["path"]),
                "kind": "paper",
                **recorded,
                "status": "retained",
                "registered_at": "2026-09-14T12:00:00+08:00",
                "source": "test fixture",
                "selected_at": None,
                "superseded_at": None,
                "superseded_by": None,
                "reason": "component evidence, not a standalone paper",
            }
            (case / "authority/candidate-registry.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "revision": 1,
                        "updated_at": "2026-09-14T12:00:00+08:00",
                        "candidates": [entry],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            report = heartbeat.audit(case)
            self.assertTrue(report["healthy"], report["diagnostics"])
            self.assertEqual(
                report["candidate_lineage"]["retained"],
                ["paper/candidates/model-schematic-01"],
            )
            self.assertEqual(report["candidate_lineage"]["unresolved"], [])

    def test_control_markers_are_warnings_not_invented_gate_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.write_case(Path(temporary))
            (case / "PLAN.md").write_text("# Plan\n\n- TODO verify data\n", encoding="utf-8")
            report = heartbeat.audit(case)
            self.assertTrue(report["healthy"])
            self.assertIn(
                "stale_control_file_marker",
                {item["code"] for item in report["diagnostics"]},
            )

    def test_absolute_or_escaping_paths_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.write_case(Path(temporary))
            state = case / "CURRENT-STATE.md"
            state.write_text(
                state.read_text(encoding="utf-8").replace(
                    "| Current generated paper | `NOT_BUILT` |",
                    f"| Current generated paper | `{(Path(temporary) / 'outside.pdf').resolve()}` |",
                ),
                encoding="utf-8",
            )
            report = heartbeat.audit(case)
            self.assertFalse(report["healthy"])
            self.assertIn(
                "authority_path_invalid",
                {item["code"] for item in report["diagnostics"]},
            )

    def test_cli_exit_codes_follow_blocking_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.write_case(Path(temporary))
            passed = subprocess.run(
                [sys.executable, str(SCRIPTS / "audit_authority_heartbeat.py"), "--case-dir", str(case), "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(passed.returncode, 0, passed.stderr)
            payload = json.loads(passed.stdout)
            self.assertTrue(payload["healthy"])
            (case / "CURRENT-STATE.md").write_text("# Legacy state\n", encoding="utf-8")
            failed = subprocess.run(
                [sys.executable, str(SCRIPTS / "audit_authority_heartbeat.py"), "--case-dir", str(case), "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(failed.returncode, 2, failed.stderr)
            self.assertFalse(json.loads(failed.stdout)["healthy"])


if __name__ == "__main__":
    unittest.main()

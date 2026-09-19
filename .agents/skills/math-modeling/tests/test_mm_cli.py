from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
MM = SKILL_ROOT / "scripts/mm.py"


def run_mm(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MM), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


class UnifiedModelingCliTests(unittest.TestCase):
    def test_start_and_status_use_existing_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            started = run_mm(
                "start", "case-a", "--root", str(root), "--profile", "explore", "--json"
            )
            self.assertEqual(started.returncode, 0, started.stderr)
            start_report = json.loads(started.stdout)
            self.assertTrue(start_report["passed"])
            self.assertTrue(
                os.path.samefile(start_report["case"]["case_dir"], root / "case-a")
            )
            status = run_mm("status", str(root / "case-a"), "--json")
            self.assertEqual(status.returncode, 0, status.stderr)
            status_report = json.loads(status.stdout)
            self.assertTrue(status_report["healthy"])
            self.assertEqual(status_report["command"], "authority-heartbeat")

    def test_check_aggregates_three_read_only_components(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            started = run_mm(
                "start", "case-check", "--root", str(root), "--profile", "explore", "--json"
            )
            self.assertEqual(started.returncode, 0, started.stderr)
            checked = run_mm("check", str(root / "case-check"), "--json")
            self.assertEqual(checked.returncode, 0, checked.stderr)
            report = json.loads(checked.stdout)
            self.assertTrue(report["passed"], report)
            self.assertEqual(report["mode"], "passive_read_only")
            self.assertEqual(
                [component["name"] for component in report["components"]],
                ["authority_heartbeat", "doctor", "manifest_validation"],
            )
            self.assertIn("does not execute modeling steps", report["claim_scope"])

    def test_check_fails_when_heartbeat_finds_pointer_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            started = run_mm(
                "start", "case-drift", "--root", str(root), "--profile", "explore", "--json"
            )
            self.assertEqual(started.returncode, 0, started.stderr)
            (root / "case-drift/CURRENT-STATE.md").write_text("# Legacy\n", encoding="utf-8")
            checked = run_mm("check", str(root / "case-drift"), "--json")
            self.assertEqual(checked.returncode, 2, checked.stderr)
            report = json.loads(checked.stdout)
            self.assertFalse(report["passed"])
            failed = {item["name"] for item in report["components"] if not item["passed"]}
            self.assertEqual(failed, {"authority_heartbeat"})

    def test_freeze_verify_preserves_underlying_failure_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = Path(temporary) / "case"
            case.mkdir()
            failed = run_mm("freeze", "verify", str(case), "--manifest", "missing.json")
            self.assertEqual(failed.returncode, 2, failed.stderr)
            report = json.loads(failed.stdout)
            self.assertFalse(report["passed"])

    def test_help_exposes_only_thin_workflow_commands(self) -> None:
        completed = run_mm("--help")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        for command in ("start", "status", "check", "freeze", "package", "candidate"):
            self.assertIn(command, completed.stdout)
        source = MM.read_text(encoding="utf-8")
        self.assertIn("does not reimplement", source)
        self.assertIn("does not execute modeling steps", source)

    def test_candidate_help_is_delegated(self) -> None:
        completed = run_mm("candidate", "--help")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        for action in ("list", "register", "select", "supersede"):
            self.assertIn(action, completed.stdout)


if __name__ == "__main__":
    unittest.main()

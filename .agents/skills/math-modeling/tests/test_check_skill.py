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


def run_gate(workspace_root: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "check_skill.py"),
            "--workspace-root",
            str(workspace_root),
            "--skip-tests",
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        timeout=60,
    )


class CheckSkillTests(unittest.TestCase):
    def test_gate_passes_and_preserves_complete_historical_case(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case_dir = root / "historical-case"
            (case_dir / "src").mkdir(parents=True)
            (case_dir / "src" / "analyze.py").write_text(
                "print('ok')\n", encoding="utf-8"
            )
            (case_dir / "workflow.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "profile": "explore",
                        "steps": [
                            {"name": "analyze", "script": "src/analyze.py"}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            before = {
                str(path.relative_to(case_dir)): path.read_bytes()
                for path in case_dir.rglob("*")
                if path.is_file()
            }

            completed = run_gate(root)
            report = json.loads(completed.stdout)
            checks = {item["name"]: item for item in report["checks"]}

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(report["passed"])
            self.assertEqual(report["historical_cases"][0]["case"], "historical-case")
            self.assertTrue(report["historical_cases"][0]["healthy"])
            self.assertTrue(report["historical_cases"][0]["execution_plan_valid"])
            self.assertTrue(report["historical_cases"][0]["migration_analysis_valid"])
            self.assertTrue(report["historical_cases"][0]["migration_rehearsal_valid"])
            self.assertTrue(
                report["historical_cases"][0]["migration_review_preview_valid"]
            )
            self.assertTrue(
                report["historical_cases"][0][
                    "migration_acceptance_preview_valid"
                ]
            )
            self.assertEqual(
                report["historical_cases"][0]["migration_rehearsal_status"],
                "not_applicable",
            )
            self.assertFalse(report["historical_cases"][0]["migration_applicable"])
            self.assertEqual(
                report["historical_cases"][0]["migration_review_status"],
                "not_applicable",
            )
            self.assertEqual(
                report["historical_cases"][0]["migration_acceptance_status"],
                "not_applicable",
            )
            self.assertEqual(
                checks["historical_read_only"]["review_preview_failures"], 0
            )
            self.assertEqual(
                checks["historical_read_only"]["acceptance_preview_failures"], 0
            )
            self.assertEqual(checks["migration_readiness"]["status"], "passed")
            self.assertIsNone(checks["migration_readiness"]["recommended_case"])
            self.assertEqual(
                report["migration_readiness"]["status"], "no_applicable_cases"
            )
            self.assertEqual(
                checks["migration_review_package"]["status"], "not_applicable"
            )
            self.assertIsNone(report["migration_review_package"])
            self.assertEqual(
                checks["migration_review_markdown"]["status"], "not_applicable"
            )
            self.assertIsNone(report["migration_review_markdown"])
            self.assertTrue(report["historical_cases"][0]["read_only_unchanged"])
            self.assertEqual(
                report["historical_cases"][0]["plan_reason_codes"],
                ["cache_disabled"],
            )
            after = {
                str(path.relative_to(case_dir)): path.read_bytes()
                for path in case_dir.rglob("*")
                if path.is_file()
            }
            self.assertEqual(after, before)
            load_and_validate(
                report, SCHEMAS / "diagnostics.schema.json", "quality gate report"
            )

    def test_gate_fails_for_invalid_historical_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case_dir = root / "invalid-case"
            case_dir.mkdir()
            (case_dir / "workflow.json").write_text(
                '{"schema_version": 2, "profile": "explore", "steps": []}',
                encoding="utf-8",
            )

            completed = run_gate(root)
            report = json.loads(completed.stdout)

            self.assertEqual(completed.returncode, 2)
            self.assertFalse(report["passed"])
            self.assertIn(
                "historical_manifest_invalid",
                {entry["code"] for entry in report["diagnostics"]},
            )


if __name__ == "__main__":
    unittest.main()

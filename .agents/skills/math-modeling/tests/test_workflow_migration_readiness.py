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
READINESS = SCRIPTS / "summarize_workflow_migration_readiness.py"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _json_schema import load_and_validate


def run_readiness(root: Path) -> tuple[subprocess.CompletedProcess[str], dict]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [
            sys.executable,
            str(READINESS),
            "--workspace-root",
            str(root),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        timeout=30,
    )
    return completed, json.loads(completed.stdout)


def snapshot(root: Path) -> dict[str, tuple[int, int]]:
    return {
        str(path.relative_to(root)): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


def make_case(
    root: Path,
    name: str,
    *,
    scripts: list[str],
    schema_version: int = 1,
) -> Path:
    case_dir = root / name
    (case_dir / "src").mkdir(parents=True)
    steps = []
    for index, source in enumerate(scripts, start=1):
        script = f"src/step-{index}.py"
        (case_dir / script).write_text(source, encoding="utf-8")
        steps.append({"name": f"step-{index}", "script": script})
    manifest = {"schema_version": schema_version, "steps": steps}
    if schema_version == 2:
        manifest["profile"] = "explore"
    else:
        manifest["artifacts"] = {
            "docx": "paper/paper.docx",
            "pdf": "paper/paper.pdf",
            "render_dir": "paper/rendered-pages",
            "visual_review": "paper/visual-review.json",
        }
    (case_dir / "workflow.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return case_dir


def mark_doctor_healthy(case_dir: Path) -> None:
    register = case_dir / "problem" / "model-definition-register.json"
    register.parent.mkdir(parents=True, exist_ok=True)
    register.write_text("{}\n", encoding="utf-8")


class WorkflowMigrationReadinessTests(unittest.TestCase):
    def test_ranks_applicable_cases_and_preserves_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_case(
                root,
                "one-reviewed-step",
                scripts=[
                    "from pathlib import Path\n"
                    "root = Path(__file__).resolve().parents[1]\n"
                    "source = root / 'data' / 'input.csv'\n"
                    "print(source.read_text())\n"
                ],
            )
            make_case(
                root,
                "two-reviewed-steps",
                scripts=["print('one')\n", "print('two')\n"],
            )
            make_case(
                root,
                "already-v2",
                scripts=["print('v2')\n"],
                schema_version=2,
            )
            before = snapshot(root)

            completed, report = run_readiness(root)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(report["status"], "ready")
            self.assertEqual(report["recommended_case"], "one-reviewed-step")
            self.assertFalse(report["files_written"])
            self.assertFalse(report["case_steps_executed"])
            self.assertFalse(report["external_tools_started"])
            by_name = {item["case"]: item for item in report["cases"]}
            self.assertEqual(by_name["one-reviewed-step"]["rank"], 1)
            self.assertEqual(by_name["two-reviewed-steps"]["rank"], 2)
            self.assertEqual(
                by_name["already-v2"]["status"], "not_applicable"
            )
            self.assertIsNone(by_name["already-v2"]["rank"])
            self.assertRegex(
                by_name["one-reviewed-step"]["expected_candidate_sha256"],
                r"^[0-9a-f]{64}$",
            )
            self.assertTrue(
                all(item["source_unchanged"] for item in report["cases"])
            )
            self.assertEqual(snapshot(root), before)
            load_and_validate(
                report,
                SCHEMAS / "workflow-migration-readiness.schema.json",
                "readiness report",
            )

    def test_unavailable_source_analysis_sorts_after_available_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_case(root, "unavailable", scripts=["def broken(:\n"])
            make_case(
                root,
                "available",
                scripts=["print('one')\n", "print('two')\n"],
            )

            completed, report = run_readiness(root)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(report["recommended_case"], "available")
            by_name = {item["case"]: item for item in report["cases"]}
            self.assertEqual(
                by_name["unavailable"]["metrics"][
                    "source_analysis_unavailable_steps"
                ],
                1,
            )
            self.assertGreater(
                by_name["unavailable"]["rank"], by_name["available"]["rank"]
            )

    def test_existing_diagnostic_errors_sort_after_healthy_cases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            smaller_but_unhealthy = make_case(
                root, "smaller-unhealthy", scripts=["print('one')\n"]
            )
            healthy = make_case(
                root,
                "larger-healthy",
                scripts=["print('one')\n", "print('two')\n"],
            )
            mark_doctor_healthy(healthy)

            completed, report = run_readiness(root)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(report["recommended_case"], "larger-healthy")
            by_name = {item["case"]: item for item in report["cases"]}
            self.assertEqual(by_name["larger-healthy"]["metrics"]["diagnostic_errors"], 0)
            self.assertGreater(
                by_name["smaller-unhealthy"]["metrics"]["diagnostic_errors"], 0
            )
            self.assertIn(
                "model_definition_register_missing",
                by_name["smaller-unhealthy"]["diagnostic_codes"],
            )

    def test_blocked_case_is_isolated_and_fails_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_case(root, "valid-case", scripts=["print('ok')\n"])
            blocked = root / "invalid-case"
            blocked.mkdir()
            (blocked / "workflow.json").write_text(
                '{"schema_version": 1, "steps": []}', encoding="utf-8"
            )
            before = snapshot(root)

            completed, report = run_readiness(root)

            self.assertEqual(completed.returncode, 2)
            self.assertEqual(report["status"], "failed")
            by_name = {item["case"]: item for item in report["cases"]}
            self.assertEqual(
                by_name["valid-case"]["status"], "ready_for_human_review"
            )
            self.assertEqual(by_name["invalid-case"]["status"], "blocked")
            self.assertEqual(report["summary"]["blocked"], 1)
            self.assertIn(
                "migration_readiness_case_blocked",
                {item["code"] for item in report["diagnostics"]},
            )
            self.assertEqual(snapshot(root), before)
            load_and_validate(
                report,
                SCHEMAS / "workflow-migration-readiness.schema.json",
                "blocked readiness report",
            )

    def test_reports_no_applicable_cases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_case(
                root,
                "already-v2",
                scripts=["print('v2')\n"],
                schema_version=2,
            )

            completed, report = run_readiness(root)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(report["status"], "no_applicable_cases")
            self.assertIsNone(report["recommended_case"])
            self.assertEqual(report["summary"]["not_applicable"], 1)


if __name__ == "__main__":
    unittest.main()

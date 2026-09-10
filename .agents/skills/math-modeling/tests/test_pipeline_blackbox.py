from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
PIPELINE = SKILL_DIR / "scripts" / "run_pipeline.py"


def write_explore_case(
    case_dir: Path,
    script_source: str,
    *,
    inputs: list[str] | None = None,
    outputs: list[str] | None = None,
    timeout_seconds: int = 30,
    cache: bool = False,
) -> None:
    src_dir = case_dir / "src"
    src_dir.mkdir(parents=True)
    (src_dir / "step.py").write_text(script_source, encoding="utf-8")
    manifest = {
        "schema_version": 2,
        "profile": "explore",
        "steps": [
            {
                "name": "analyze",
                "type": "python",
                "script": "src/step.py",
                "inputs": inputs or [],
                "outputs": outputs or [],
                "timeout_seconds": timeout_seconds,
                "cache": cache,
            }
        ],
    }
    (case_dir / "workflow.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )


def run_pipeline(case_dir: Path) -> tuple[subprocess.CompletedProcess[str], dict, dict]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [
            sys.executable,
            str(PIPELINE),
            "--case-dir",
            str(case_dir),
            "--phase",
            "build",
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        timeout=15,
    )
    stdout_report = json.loads(completed.stdout)
    report_path = case_dir / ".workflow" / "pipeline-report.json"
    disk_report = json.loads(report_path.read_text(encoding="utf-8"))
    return completed, stdout_report, disk_report


def run_validate(case_dir: Path) -> tuple[subprocess.CompletedProcess[str], dict]:
    completed = subprocess.run(
        [
            sys.executable,
            str(PIPELINE),
            "--case-dir",
            str(case_dir),
            "--validate-only",
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    return completed, json.loads(completed.stdout)


def run_plan(case_dir: Path, *arguments: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [
            sys.executable,
            str(PIPELINE),
            "--case-dir",
            str(case_dir),
            "--plan",
            *arguments,
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        timeout=15,
    )
    return completed, json.loads(completed.stdout)


class PipelineBlackBoxTests(unittest.TestCase):
    def test_plan_explains_cache_lifecycle_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary) / "plan-cache"
            data_dir = case_dir / "data"
            data_dir.mkdir(parents=True)
            input_path = data_dir / "input.txt"
            input_path.write_text("first\n", encoding="utf-8")
            write_explore_case(
                case_dir,
                "from pathlib import Path\n"
                "root = Path(__file__).resolve().parents[1]\n"
                "output = root / 'results' / 'output.txt'\n"
                "output.parent.mkdir(exist_ok=True)\n"
                "output.write_text((root / 'data' / 'input.txt').read_text())\n",
                inputs=["data/input.txt"],
                outputs=["results/output.txt"],
                cache=True,
            )
            before = {
                str(path.relative_to(case_dir)): (path.stat().st_size, path.stat().st_mtime_ns)
                for path in case_dir.rglob("*")
                if path.is_file()
            }

            initial, initial_plan = run_plan(case_dir)

            self.assertEqual(initial.returncode, 0, initial.stderr)
            self.assertEqual(initial_plan["mode"], "passive_read_only")
            self.assertEqual(initial_plan["steps"][0]["reason_code"], "cache_state_missing")
            self.assertFalse((case_dir / ".workflow").exists())
            after = {
                str(path.relative_to(case_dir)): (path.stat().st_size, path.stat().st_mtime_ns)
                for path in case_dir.rglob("*")
                if path.is_file()
            }
            self.assertEqual(after, before)

            built, _, _ = run_pipeline(case_dir)
            self.assertEqual(built.returncode, 0, built.stderr)
            hit, hit_plan = run_plan(case_dir)
            self.assertEqual(hit.returncode, 0, hit.stderr)
            self.assertEqual(hit_plan["steps"][0]["action"], "cache-hit")
            self.assertEqual(hit_plan["steps"][0]["reason_code"], "cache_hit")

            output_path = case_dir / "results" / "output.txt"
            output_path.write_text("tampered\n", encoding="utf-8")
            _, output_plan = run_plan(case_dir)
            self.assertEqual(output_plan["steps"][0]["reason_code"], "output_hash_changed")

            output_path.write_text("first\n", encoding="utf-8")
            input_path.write_text("second\n", encoding="utf-8")
            _, input_plan = run_plan(case_dir)
            self.assertEqual(input_plan["steps"][0]["reason_code"], "fingerprint_changed")

            _, forced_plan = run_plan(case_dir, "--force", "analyze")
            self.assertEqual(forced_plan["steps"][0]["reason_code"], "forced")

    def test_plan_honors_resume_selection_from_failed_step(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary) / "resume-plan"
            (case_dir / "src").mkdir(parents=True)
            (case_dir / "src" / "first.py").write_text(
                "print('first')\n", encoding="utf-8"
            )
            (case_dir / "src" / "second.py").write_text(
                "raise SystemExit(3)\n", encoding="utf-8"
            )
            manifest = {
                "schema_version": 2,
                "profile": "explore",
                "steps": [
                    {
                        "name": "first",
                        "script": "src/first.py",
                        "inputs": [],
                        "outputs": [],
                        "cache": False,
                    },
                    {
                        "name": "second",
                        "script": "src/second.py",
                        "inputs": [],
                        "outputs": [],
                        "cache": False,
                    },
                ],
            }
            (case_dir / "workflow.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )

            failed, report, _ = run_pipeline(case_dir)
            self.assertEqual(failed.returncode, 2, failed.stderr)
            self.assertIn("--from second", report["failure"]["resume_command"])

            planned, plan = run_plan(case_dir, "--from", "second")
            self.assertEqual(planned.returncode, 0, planned.stderr)
            self.assertEqual([step["name"] for step in plan["steps"]], ["second"])
            self.assertEqual(plan["selection"]["from"], "second")
            self.assertEqual(plan["steps"][0]["reason_code"], "cache_disabled")

    def assert_step_failure(
        self,
        completed: subprocess.CompletedProcess[str],
        report: dict,
        disk_report: dict,
        cause_code: str,
    ) -> None:
        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertEqual(report, disk_report)
        self.assertEqual(report["failure"]["failed_stage"], "pipeline_step")
        self.assertEqual(report["failure"]["step"], "analyze")
        self.assertEqual(report["failure"]["cause_code"], cause_code)
        self.assertTrue(report["failure"]["retryable"])
        self.assertTrue(report["failure"]["remediation"])
        self.assertIn("--from analyze", report["failure"]["resume_command"])
        self.assertFalse(report["steps"][0]["ok"])

    def test_cli_reports_timeout_with_recovery_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary) / "timeout case"
            write_explore_case(
                case_dir,
                "import time\nprint('started', flush=True)\ntime.sleep(5)\n",
                timeout_seconds=1,
            )

            completed, report, disk_report = run_pipeline(case_dir)

            self.assert_step_failure(
                completed, report, disk_report, cause_code="timeout"
            )
            self.assertEqual(report["steps"][0]["timeout_seconds"], 1)
            self.assertIn(
                "timeout_seconds", " ".join(report["failure"]["remediation"])
            )
            resume_command = report["failure"]["resume_command"]
            self.assertIn('--case-dir "', resume_command)
            self.assertIn('timeout case" --phase build', resume_command)

    def test_cli_reports_nonzero_exit_as_execution_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary) / "nonzero"
            write_explore_case(
                case_dir,
                "import sys\nprint('before failure')\n"
                "print('bad input', file=sys.stderr)\nraise SystemExit(7)\n",
            )

            completed, report, disk_report = run_pipeline(case_dir)

            self.assert_step_failure(
                completed, report, disk_report, cause_code="execution"
            )
            step = report["steps"][0]
            self.assertEqual(step["exit_code"], 7)
            self.assertIn("before failure", step["stdout"])
            self.assertIn("bad input", step["stderr"])

    def test_cli_reports_missing_declared_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary) / "missing-output"
            write_explore_case(
                case_dir,
                "print('completed without writing output')\n",
                outputs=["results/expected.json"],
            )

            completed, report, disk_report = run_pipeline(case_dir)

            self.assert_step_failure(
                completed, report, disk_report, cause_code="outputs"
            )
            self.assertEqual(
                report["steps"][0]["missing_outputs"],
                ["results/expected.json"],
            )
            self.assertIn(
                "results/expected.json",
                " ".join(report["failure"]["remediation"]),
            )

    def test_cli_recovers_from_corrupt_cache_and_invalidates_changed_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary) / "cache"
            data_dir = case_dir / "data"
            data_dir.mkdir(parents=True)
            input_path = data_dir / "input.txt"
            input_path.write_text("first\n", encoding="utf-8")
            write_explore_case(
                case_dir,
                "from pathlib import Path\n"
                "root = Path(__file__).resolve().parents[1]\n"
                "counter = root / 'counter.txt'\n"
                "count = int(counter.read_text()) + 1 if counter.exists() else 1\n"
                "counter.write_text(str(count))\n"
                "output = root / 'results' / 'output.txt'\n"
                "output.parent.mkdir(exist_ok=True)\n"
                "output.write_text((root / 'data' / 'input.txt').read_text())\n",
                inputs=["data/input.txt"],
                outputs=["results/output.txt"],
                cache=True,
            )

            first, first_report, _ = run_pipeline(case_dir)
            second, second_report, _ = run_pipeline(case_dir)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(first_report["steps"][0]["status"], "executed")
            self.assertEqual(second_report["steps"][0]["status"], "cache-hit")
            self.assertEqual((case_dir / "counter.txt").read_text(), "1")

            state_path = case_dir / ".workflow" / "state.json"
            state_path.write_text("{not-json", encoding="utf-8")
            corrupt, corrupt_report, _ = run_pipeline(case_dir)
            self.assertEqual(corrupt.returncode, 0, corrupt.stderr)
            self.assertEqual(corrupt_report["steps"][0]["status"], "executed")
            self.assertEqual((case_dir / "counter.txt").read_text(), "2")
            self.assertEqual(json.loads(state_path.read_text())["schema_version"], 1)

            output_path = case_dir / "results" / "output.txt"
            output_path.write_text("tampered\n", encoding="utf-8")
            output_changed, output_report, _ = run_pipeline(case_dir)
            self.assertEqual(output_changed.returncode, 0, output_changed.stderr)
            self.assertEqual(output_report["steps"][0]["status"], "executed")
            self.assertEqual((case_dir / "counter.txt").read_text(), "3")

            input_path.write_text("second\n", encoding="utf-8")
            input_changed, input_report, _ = run_pipeline(case_dir)
            self.assertEqual(input_changed.returncode, 0, input_changed.stderr)
            self.assertEqual(input_report["steps"][0]["status"], "executed")
            self.assertEqual((case_dir / "counter.txt").read_text(), "4")
            self.assertEqual(output_path.read_text(encoding="utf-8"), "second\n")


    def test_data_preparation_runs_cleaning_then_reuses_hash_bound_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary) / "data-preparation"
            raw_dir = case_dir / "data" / "raw"
            raw_dir.mkdir(parents=True)
            source = raw_dir / "observations.csv"
            source.write_text(
                "id,name,value\n"
                "a, Alice ,10\n"
                "b,Bob,20\n",
                encoding="utf-8",
            )
            before = source.read_bytes()
            plan_dir = case_dir / "data" / "cleaning"
            plan_dir.mkdir()
            plan = plan_dir / "plan.json"
            plan.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "input_sha256": hashlib.sha256(before).hexdigest(),
                        "row_id_columns": ["id"],
                        "rules": [
                            {
                                "id": "trim_name",
                                "operation": "trim_whitespace",
                                "columns": ["name"],
                                "reason": "remove source export padding",
                                "expected_changes": 1,
                            }
                        ],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            write_explore_case(
                case_dir,
                "from pathlib import Path\n"
                "root = Path(__file__).resolve().parents[1]\n"
                "source = root / 'data' / 'processed' / 'observations-cleaning' / 'processed.csv'\n"
                "output = root / 'results' / 'names.txt'\n"
                "output.parent.mkdir(exist_ok=True)\n"
                "output.write_text(source.read_text(encoding='utf-8'))\n",
                inputs=["data/processed/observations-cleaning/processed.csv"],
                outputs=["results/names.txt"],
                cache=True,
            )
            manifest_path = case_dir / "workflow.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["data_preparation"] = {
                "input": "data/raw/observations.csv",
                "raw_audit_output": "evidence/data-preparation/raw-audit",
                "id_columns": ["id"],
                "cleaning_plan": "data/cleaning/plan.json",
                "cleaning_output": "data/processed/observations-cleaning",
                "processed_audit_output": "evidence/data-preparation/processed-audit",
            }
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

            before_plan = {
                str(path.relative_to(case_dir)): (path.stat().st_size, path.stat().st_mtime_ns)
                for path in case_dir.rglob("*")
                if path.is_file()
            }
            planned, plan_report = run_plan(case_dir)
            self.assertEqual(planned.returncode, 0, planned.stderr)
            self.assertEqual(plan_report["data_preparation"]["action"], "execute")
            after_plan = {
                str(path.relative_to(case_dir)): (path.stat().st_size, path.stat().st_mtime_ns)
                for path in case_dir.rglob("*")
                if path.is_file()
            }
            self.assertEqual(after_plan, before_plan)

            first, first_report, _ = run_pipeline(case_dir)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(first_report["data_preparation"]["status"], "executed")
            self.assertTrue(first_report["data_preparation"]["ok"])
            self.assertEqual(first_report["steps"][0]["status"], "executed")
            self.assertEqual(source.read_bytes(), before)
            processed = case_dir / "data" / "processed" / "observations-cleaning" / "processed.csv"
            self.assertIn("a,Alice,10", processed.read_text(encoding="utf-8"))
            processed_audit = json.loads(
                (case_dir / "evidence" / "data-preparation" / "processed-audit" / "run.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertTrue(processed_audit["ready_for_modeling"])

            second, second_report, _ = run_pipeline(case_dir)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(second_report["data_preparation"]["status"], "cache-hit")
            self.assertEqual(second_report["steps"][0]["status"], "cache-hit")

    def test_plural_data_preparations_are_independently_cached(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary) / "plural-data-preparation"
            raw_dir = case_dir / "data" / "raw"
            raw_dir.mkdir(parents=True)
            first_source = raw_dir / "first.csv"
            second_source = raw_dir / "second.csv"
            first_source.write_text("id,value\na,1\nb,2\n", encoding="utf-8")
            second_source.write_text("id,value\nc,3\nd,4\n", encoding="utf-8")
            source_bytes = {
                "first": first_source.read_bytes(),
                "second": second_source.read_bytes(),
            }
            source_hashes = {
                name: hashlib.sha256(content).hexdigest()
                for name, content in source_bytes.items()
            }
            write_explore_case(
                case_dir,
                "from pathlib import Path\n"
                "root = Path(__file__).resolve().parents[1]\n"
                "result = root / 'results' / 'summary.txt'\n"
                "result.parent.mkdir(exist_ok=True)\n"
                "result.write_text((root / 'data' / 'raw' / 'first.csv').read_text() + (root / 'data' / 'raw' / 'second.csv').read_text())\n",
                inputs=["data/raw/first.csv", "data/raw/second.csv"],
                outputs=["results/summary.txt"],
                cache=True,
            )
            manifest_path = case_dir / "workflow.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["data_preparations"] = [
                {
                    "name": "first",
                    "input": "data/raw/first.csv",
                    "raw_audit_output": "evidence/data-preparation/first-audit",
                    "id_columns": ["id"],
                },
                {
                    "name": "second",
                    "input": "data/raw/second.csv",
                    "raw_audit_output": "evidence/data-preparation/second-audit",
                    "id_columns": ["id"],
                },
            ]
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

            before_plan = {
                str(path.relative_to(case_dir)): (path.stat().st_size, path.stat().st_mtime_ns)
                for path in case_dir.rglob("*")
                if path.is_file()
            }
            planned, plan_report = run_plan(case_dir)
            self.assertEqual(planned.returncode, 0, planned.stderr)
            self.assertEqual(plan_report["data_preparation"]["action"], "execute")
            self.assertEqual(
                [item["name"] for item in plan_report["data_preparation"]["datasets"]],
                ["first", "second"],
            )
            self.assertEqual(
                {item["action"] for item in plan_report["data_preparation"]["datasets"]},
                {"execute"},
            )
            after_plan = {
                str(path.relative_to(case_dir)): (path.stat().st_size, path.stat().st_mtime_ns)
                for path in case_dir.rglob("*")
                if path.is_file()
            }
            self.assertEqual(after_plan, before_plan)

            first, first_report, _ = run_pipeline(case_dir)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(first_report["data_preparation"]["status"], "executed")
            self.assertTrue(first_report["data_preparation"]["ok"])
            self.assertEqual(
                [item["name"] for item in first_report["data_preparation"]["datasets"]],
                ["first", "second"],
            )
            self.assertEqual(first_source.read_bytes(), source_bytes["first"])
            self.assertEqual(second_source.read_bytes(), source_bytes["second"])
            state = json.loads((case_dir / ".workflow" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(set(state["data_preparation"]["entries"]), {"first", "second"})
            self.assertEqual(
                hashlib.sha256(first_source.read_bytes()).hexdigest(), source_hashes["first"]
            )
            self.assertEqual(
                hashlib.sha256(second_source.read_bytes()).hexdigest(), source_hashes["second"]
            )

            second, second_report, _ = run_pipeline(case_dir)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(second_report["data_preparation"]["status"], "cache-hit")
            self.assertEqual(
                {item["status"] for item in second_report["data_preparation"]["datasets"]},
                {"cache-hit"},
            )
            self.assertEqual(second_report["steps"][0]["status"], "cache-hit")

    def test_plural_data_preparations_reject_ambiguous_names_and_overlapping_outputs(self) -> None:
        variants = [
            (
                "ambiguous",
                {
                    "data_preparation": {
                        "input": "data/raw/one.csv",
                        "raw_audit_output": "evidence/data-preparation/legacy",
                    },
                    "data_preparations": [
                        {
                            "name": "one",
                            "input": "data/raw/one.csv",
                            "raw_audit_output": "evidence/data-preparation/one",
                        }
                    ],
                },
                "forbidden shape",
            ),
            (
                "duplicate",
                {
                    "data_preparations": [
                        {
                            "name": "same",
                            "input": "data/raw/one.csv",
                            "raw_audit_output": "evidence/data-preparation/one",
                        },
                        {
                            "name": "same",
                            "input": "data/raw/two.csv",
                            "raw_audit_output": "evidence/data-preparation/two",
                        },
                    ]
                },
                "duplicate data_preparations name",
            ),
            (
                "overlap",
                {
                    "data_preparations": [
                        {
                            "name": "one",
                            "input": "data/raw/one.csv",
                            "raw_audit_output": "evidence/data-preparation/shared",
                        },
                        {
                            "name": "two",
                            "input": "data/raw/two.csv",
                            "raw_audit_output": "evidence/data-preparation/shared",
                        },
                    ]
                },
                "data_preparations output directories",
            ),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, additions, expected in variants:
                case_dir = root / name
                raw_dir = case_dir / "data" / "raw"
                raw_dir.mkdir(parents=True)
                (raw_dir / "one.csv").write_text("id,value\na,1\n", encoding="utf-8")
                (raw_dir / "two.csv").write_text("id,value\nb,2\n", encoding="utf-8")
                write_explore_case(case_dir, "print('unused')\n")
                manifest_path = case_dir / "workflow.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest.update(additions)
                manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
                completed, report = run_validate(case_dir)
                self.assertEqual(completed.returncode, 2, completed.stderr)
                self.assertIsNot(report.get("valid"), True)
                self.assertIn(expected, json.dumps(report, ensure_ascii=False))

    def test_data_preparation_blocks_modeling_when_raw_audit_has_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary) / "data-preparation-blocked"
            raw_dir = case_dir / "data" / "raw"
            raw_dir.mkdir(parents=True)
            (raw_dir / "observations.csv").write_text(
                "id,value\n"
                "repeat,1\n"
                "repeat,2\n",
                encoding="utf-8",
            )
            write_explore_case(
                case_dir,
                "from pathlib import Path\n"
                "root = Path(__file__).resolve().parents[1]\n"
                "(root / 'model-ran.txt').write_text('unexpected')\n",
            )
            manifest_path = case_dir / "workflow.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["data_preparation"] = {
                "input": "data/raw/observations.csv",
                "raw_audit_output": "evidence/data-preparation/raw-audit",
                "id_columns": ["id"],
            }
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

            completed, report, disk_report = run_pipeline(case_dir)
            self.assertEqual(completed.returncode, 2, completed.stderr)
            self.assertEqual(report, disk_report)
            self.assertEqual(report["failure"]["failed_stage"], "data_preparation")
            self.assertEqual(report["failure"]["cause_code"], "raw_audit")
            self.assertFalse((case_dir / "model-ran.txt").exists())
            raw_audit = json.loads(
                (case_dir / "evidence" / "data-preparation" / "raw-audit" / "run.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertFalse(raw_audit["ready_for_modeling"])

if __name__ == "__main__":
    unittest.main()

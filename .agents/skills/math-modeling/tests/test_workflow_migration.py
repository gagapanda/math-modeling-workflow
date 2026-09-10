from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
ANALYZER = SKILL_DIR / "scripts" / "analyze_workflow_migration.py"
REHEARSAL = SKILL_DIR / "scripts" / "rehearse_workflow_migration.py"
REVIEWER = SKILL_DIR / "scripts" / "review_workflow_migration.py"
ACCEPTANCE_AUDITOR = (
    SKILL_DIR / "scripts" / "audit_workflow_migration_candidate.py"
)


def run_analyzer(case_dir: Path) -> tuple[subprocess.CompletedProcess[str], dict]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, str(ANALYZER), "--case-dir", str(case_dir), "--json"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        timeout=15,
    )
    return completed, json.loads(completed.stdout)


def run_rehearsal(case_dir: Path) -> tuple[subprocess.CompletedProcess[str], dict]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, str(REHEARSAL), "--case-dir", str(case_dir), "--json"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        timeout=15,
    )
    return completed, json.loads(completed.stdout)


def run_reviewer(
    case_dir: Path, *arguments: str
) -> tuple[subprocess.CompletedProcess[str], dict]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [
            sys.executable,
            str(REVIEWER),
            "--case-dir",
            str(case_dir),
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


def run_acceptance_auditor(
    case_dir: Path, *arguments: str
) -> tuple[subprocess.CompletedProcess[str], dict]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [
            sys.executable,
            str(ACCEPTANCE_AUDITOR),
            "--case-dir",
            str(case_dir),
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


def snapshot(case_dir: Path) -> dict[str, tuple[int, int]]:
    return {
        str(path.relative_to(case_dir)): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in case_dir.rglob("*")
        if path.is_file()
    }


def make_legacy_python_case(root: Path, step_count: int = 1) -> Path:
    case_dir = root / "legacy-review"
    (case_dir / "src").mkdir(parents=True)
    steps = []
    for index in range(step_count):
        name = f"analyze-{index + 1}"
        script = f"src/{name}.py"
        (case_dir / script).write_text("print('not executed')\n", encoding="utf-8")
        steps.append({"name": name, "script": script})
    (case_dir / "workflow.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "steps": steps,
                "artifacts": {
                    "docx": "paper/paper.docx",
                    "pdf": "paper/paper.pdf",
                    "render_dir": "paper/rendered-pages",
                    "visual_review": "paper/visual-review.json",
                },
            }
        ),
        encoding="utf-8",
    )
    return case_dir


def completed_review(template: dict) -> dict:
    review = json.loads(json.dumps(template))
    review["reviewer"] = "Migration reviewer"
    review["reviewed_at"] = "2026-08-14T10:00:00+08:00"
    for step in review["steps"]:
        step.update(
            {
                "deterministic": True,
                "confirm_declared_inputs": True,
                "confirm_declared_outputs": True,
                "confirm_timeout": True,
                "confirm_determinism": True,
                "decide_cache_enablement": True,
                "decision_notes": "Dependencies, timeout, determinism, and cache policy were checked.",
            }
        )
    return review


class WorkflowMigrationTests(unittest.TestCase):
    def test_v1_analysis_emits_safe_candidate_and_hints_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary) / "legacy-case"
            (case_dir / "src").mkdir(parents=True)
            (case_dir / "src" / "analyze.py").write_text(
                "from pathlib import Path\n"
                "root = Path(__file__).resolve().parents[1]\n"
                "source = root / 'data' / 'input.csv'\n"
                "target = root / 'results' / 'output.json'\n"
                "text = source.read_text(encoding='utf-8')\n"
                "target.write_text(text, encoding='utf-8')\n",
                encoding="utf-8",
            )
            (case_dir / "workflow.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "steps": [{"name": "analyze", "script": "src/analyze.py"}],
                        "artifacts": {
                            "docx": "paper/paper.docx",
                            "pdf": "paper/paper.pdf",
                            "render_dir": "paper/rendered-pages",
                            "visual_review": "paper/visual-review.json",
                        },
                    }
                ),
                encoding="utf-8",
            )
            before = snapshot(case_dir)

            completed, report = run_analyzer(case_dir)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(report["mode"], "passive_read_only")
            self.assertFalse(report["files_written"])
            self.assertFalse(report["case_steps_executed"])
            self.assertTrue(report["applicable"])
            self.assertTrue(report["candidate_valid"])
            candidate = report["candidate_manifest"]
            self.assertEqual(candidate["schema_version"], 2)
            self.assertEqual(candidate["profile"], "practice")
            self.assertEqual(
                candidate["steps"][0],
                {
                    "name": "analyze",
                    "script": "src/analyze.py",
                    "inputs": [],
                    "outputs": [],
                    "timeout_seconds": 300,
                    "cache": False,
                },
            )
            hints = {
                (item["path"], item["access"])
                for item in report["steps"][0]["static_path_hints"]
            }
            self.assertEqual(
                hints,
                {("data/input.csv", "input"), ("results/output.json", "output")},
            )
            self.assertEqual(report["summary"]["cache_enable_recommended"], 0)
            self.assertEqual(snapshot(case_dir), before)
            self.assertFalse((case_dir / ".workflow").exists())

    def test_v2_analysis_is_not_applicable_and_does_not_emit_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary) / "current-case"
            (case_dir / "src").mkdir(parents=True)
            (case_dir / "src" / "analyze.py").write_text(
                "print('ok')\n", encoding="utf-8"
            )
            (case_dir / "workflow.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "profile": "explore",
                        "steps": [{"name": "analyze", "script": "src/analyze.py"}],
                    }
                ),
                encoding="utf-8",
            )

            completed, report = run_analyzer(case_dir)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse(report["applicable"])
            self.assertFalse(report["candidate_valid"])
            self.assertIsNone(report["candidate_manifest"])
            self.assertEqual(report["review_required"], [])

    def test_rehearsal_validates_candidate_plan_and_cleans_temporary_case(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary) / "legacy-rehearsal"
            (case_dir / "src").mkdir(parents=True)
            (case_dir / "src" / "analyze.py").write_text(
                "print('not executed')\n", encoding="utf-8"
            )
            (case_dir / "workflow.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "steps": [{"name": "analyze", "script": "src/analyze.py"}],
                        "artifacts": {
                            "docx": "paper/paper.docx",
                            "pdf": "paper/paper.pdf",
                            "render_dir": "paper/rendered-pages",
                            "visual_review": "paper/visual-review.json",
                        },
                    }
                ),
                encoding="utf-8",
            )
            before = snapshot(case_dir)

            completed, report = run_rehearsal(case_dir)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(report["status"], "passed")
            self.assertTrue(report["rehearsal_passed"])
            self.assertTrue(report["source_unchanged"])
            self.assertFalse(report["source_files_written"])
            self.assertFalse(report["case_steps_executed"])
            self.assertFalse(report["external_tools_started"])
            self.assertTrue(report["candidate_valid_in_isolation"])
            self.assertTrue(report["temporary_workspace_created"])
            self.assertTrue(report["temporary_workspace_removed"])
            self.assertEqual(report["isolated_plan"]["reason_codes"], ["cache_disabled"])
            self.assertEqual(report["isolated_plan"]["blocked_steps"], [])
            self.assertEqual(
                report["review_checklist"][0]["status"], "pending_human_review"
            )
            self.assertEqual(len(report["review_checklist"][0]["checks"]), 5)
            self.assertEqual(snapshot(case_dir), before)

    def test_rehearsal_failure_removes_temporary_case_and_preserves_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary) / "incomplete-matlab"
            (case_dir / "src").mkdir(parents=True)
            (case_dir / "src" / "check.m").write_text(
                "disp('not executed')\n", encoding="utf-8"
            )
            (case_dir / "workflow.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "steps": [
                            {
                                "name": "matlab-check",
                                "type": "matlab",
                                "runner": "mcp-evidence",
                                "script": "src/check.m",
                                "outputs": ["results/missing.json"],
                            }
                        ],
                        "artifacts": {
                            "docx": "paper/paper.docx",
                            "pdf": "paper/paper.pdf",
                            "render_dir": "paper/rendered-pages",
                            "visual_review": "paper/visual-review.json",
                        },
                    }
                ),
                encoding="utf-8",
            )
            before = snapshot(case_dir)

            completed, report = run_rehearsal(case_dir)

            self.assertEqual(completed.returncode, 2)
            self.assertEqual(report["status"], "failed")
            self.assertTrue(report["temporary_workspace_created"])
            self.assertTrue(report["temporary_workspace_removed"])
            self.assertTrue(report["source_unchanged"])
            self.assertIn("required rehearsal file is missing", report["errors"][0])
            self.assertEqual(snapshot(case_dir), before)

    def test_rehearsal_reports_v2_as_not_applicable_without_temporary_case(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary) / "current-rehearsal"
            (case_dir / "src").mkdir(parents=True)
            (case_dir / "src" / "analyze.py").write_text(
                "print('ok')\n", encoding="utf-8"
            )
            (case_dir / "workflow.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "profile": "explore",
                        "steps": [{"name": "analyze", "script": "src/analyze.py"}],
                    }
                ),
                encoding="utf-8",
            )

            completed, report = run_rehearsal(case_dir)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(report["status"], "not_applicable")
            self.assertTrue(report["rehearsal_passed"])
            self.assertTrue(report["source_unchanged"])
            self.assertFalse(report["temporary_workspace_created"])
            self.assertFalse(report["temporary_workspace_removed"])

    def test_review_preview_is_read_only_and_hash_binds_python_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = make_legacy_python_case(Path(temporary), step_count=2)
            before = snapshot(case_dir)

            completed, report = run_reviewer(case_dir)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(report["status"], "preview_ready")
            self.assertTrue(report["rehearsal_passed"])
            self.assertTrue(report["source_manifest_unchanged"])
            self.assertFalse(report["review_complete"])
            self.assertEqual(report["files_written"], [])
            self.assertEqual(len(report["review_template"]["source_scripts"]), 2)
            self.assertEqual(len(report["review_template"]["steps"]), 2)
            self.assertEqual(snapshot(case_dir), before)

    def test_completed_review_exports_new_candidate_without_changing_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = make_legacy_python_case(Path(temporary))
            preview_completed, preview = run_reviewer(case_dir)
            self.assertEqual(preview_completed.returncode, 0, preview_completed.stderr)
            review = completed_review(preview["review_template"])
            step = review["steps"][0]
            step["inputs"] = ["data/input.csv"]
            step["outputs"] = ["results/output.json"]
            step["timeout_seconds"] = 900
            step["cache"] = True
            review_path = case_dir / "migration-review.json"
            review_path.write_text(json.dumps(review), encoding="utf-8")
            source_before = (case_dir / "workflow.json").read_bytes()

            completed, report = run_reviewer(
                case_dir,
                "--review",
                "migration-review.json",
                "--output",
                "workflow.v2.candidate.json",
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(report["status"], "candidate_written")
            self.assertTrue(report["review_complete"])
            self.assertTrue(report["source_manifest_unchanged"])
            self.assertFalse(report["case_steps_executed"])
            self.assertFalse(report["external_tools_started"])
            candidate_path = case_dir / "workflow.v2.candidate.json"
            self.assertEqual(
                [Path(path).resolve() for path in report["files_written"]],
                [candidate_path.resolve()],
            )
            candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            self.assertEqual(candidate["schema_version"], 2)
            self.assertEqual(candidate["profile"], "practice")
            self.assertEqual(candidate["steps"][0]["inputs"], ["data/input.csv"])
            self.assertEqual(candidate["steps"][0]["outputs"], ["results/output.json"])
            self.assertEqual(candidate["steps"][0]["timeout_seconds"], 900)
            self.assertTrue(candidate["steps"][0]["cache"])
            self.assertEqual((case_dir / "workflow.json").read_bytes(), source_before)

    def test_incomplete_review_fails_before_candidate_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = make_legacy_python_case(Path(temporary))
            _, preview = run_reviewer(case_dir)
            review = completed_review(preview["review_template"])
            review["steps"][0]["confirm_declared_inputs"] = False
            (case_dir / "migration-review.json").write_text(
                json.dumps(review), encoding="utf-8"
            )

            completed, report = run_reviewer(
                case_dir,
                "--review",
                "migration-review.json",
                "--output",
                "workflow.v2.candidate.json",
            )

            self.assertEqual(completed.returncode, 2)
            self.assertEqual(report["status"], "failed")
            self.assertIn("unconfirmed decisions", report["errors"][0])
            self.assertFalse((case_dir / "workflow.v2.candidate.json").exists())

    def test_stale_manifest_or_script_hash_rejects_review(self) -> None:
        for changed_file in ("workflow.json", "src/analyze-1.py"):
            with self.subTest(changed_file=changed_file), tempfile.TemporaryDirectory() as temporary:
                case_dir = make_legacy_python_case(Path(temporary))
                _, preview = run_reviewer(case_dir)
                review = completed_review(preview["review_template"])
                (case_dir / "migration-review.json").write_text(
                    json.dumps(review), encoding="utf-8"
                )
                target = case_dir / changed_file
                target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")

                completed, report = run_reviewer(
                    case_dir,
                    "--review",
                    "migration-review.json",
                    "--output",
                    "workflow.v2.candidate.json",
                )

                self.assertEqual(completed.returncode, 2)
                self.assertEqual(report["status"], "failed")
                self.assertIn("stale", report["errors"][0])
                self.assertFalse((case_dir / "workflow.v2.candidate.json").exists())

    def test_tampered_candidate_hash_rejects_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = make_legacy_python_case(Path(temporary))
            _, preview = run_reviewer(case_dir)
            review = completed_review(preview["review_template"])
            review["base_candidate_sha256"] = "0" * 64
            (case_dir / "migration-review.json").write_text(
                json.dumps(review), encoding="utf-8"
            )

            completed, report = run_reviewer(
                case_dir,
                "--review",
                "migration-review.json",
                "--output",
                "workflow.v2.candidate.json",
            )

            self.assertEqual(completed.returncode, 2)
            self.assertIn("base candidate hash is stale", report["errors"][0])
            self.assertFalse((case_dir / "workflow.v2.candidate.json").exists())

    def test_review_rejects_unsafe_cache_and_output_conflicts(self) -> None:
        scenarios = (
            ({"cache": True, "deterministic": False, "outputs": ["results/a.json"]}, "without determinism"),
            ({"cache": True, "deterministic": True, "outputs": []}, "without outputs"),
            ({"outputs": [".workflow/state.json"]}, "reserved by the workflow"),
            ({"outputs": ["workflow.json"]}, "overwrite migration evidence or source code"),
        )
        for changes, message in scenarios:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temporary:
                case_dir = make_legacy_python_case(Path(temporary))
                _, preview = run_reviewer(case_dir)
                review = completed_review(preview["review_template"])
                review["steps"][0].update(changes)
                (case_dir / "migration-review.json").write_text(
                    json.dumps(review), encoding="utf-8"
                )

                completed, report = run_reviewer(
                    case_dir,
                    "--review",
                    "migration-review.json",
                    "--output",
                    "workflow.v2.candidate.json",
                )

                self.assertEqual(completed.returncode, 2)
                self.assertIn(message, report["errors"][0])
                self.assertFalse((case_dir / "workflow.v2.candidate.json").exists())

    def test_review_rejects_escaped_and_existing_output_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = make_legacy_python_case(Path(temporary))
            source_before = (case_dir / "workflow.json").read_bytes()

            escaped, escaped_report = run_reviewer(
                case_dir, "--write-review-template", "../review.json"
            )
            self.assertEqual(escaped.returncode, 2)
            self.assertIn("escapes the case directory", escaped_report["errors"][0])

            existing, existing_report = run_reviewer(
                case_dir, "--write-review-template", "workflow.json"
            )
            self.assertEqual(existing.returncode, 2)
            self.assertIn("already exists", existing_report["errors"][0])
            self.assertEqual((case_dir / "workflow.json").read_bytes(), source_before)

            _, preview = run_reviewer(case_dir)
            review = completed_review(preview["review_template"])
            (case_dir / "migration-review.json").write_text(
                json.dumps(review), encoding="utf-8"
            )
            overwrite, overwrite_report = run_reviewer(
                case_dir,
                "--review",
                "migration-review.json",
                "--output",
                "workflow.json",
            )
            self.assertEqual(overwrite.returncode, 2)
            self.assertIn("already exists", overwrite_report["errors"][0])
            self.assertEqual((case_dir / "workflow.json").read_bytes(), source_before)

    def test_review_reports_v2_as_not_applicable_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary) / "current-review"
            (case_dir / "src").mkdir(parents=True)
            (case_dir / "src" / "analyze.py").write_text("print('ok')\n", encoding="utf-8")
            (case_dir / "workflow.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "profile": "explore",
                        "steps": [{"name": "analyze", "script": "src/analyze.py"}],
                    }
                ),
                encoding="utf-8",
            )
            before = snapshot(case_dir)

            completed, report = run_reviewer(case_dir)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(report["status"], "not_applicable")
            self.assertTrue(report["source_manifest_unchanged"])
            self.assertEqual(report["files_written"], [])
            self.assertEqual(snapshot(case_dir), before)

    def test_acceptance_preview_requires_evidence_and_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = make_legacy_python_case(Path(temporary))
            before = snapshot(case_dir)

            completed, report = run_acceptance_auditor(case_dir)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(report["status"], "evidence_required")
            self.assertFalse(report["accepted"])
            self.assertTrue(report["rehearsal_passed"])
            self.assertTrue(report["source_unchanged"])
            self.assertFalse(report["case_files_written"])
            self.assertFalse(report["case_steps_executed"])
            self.assertFalse(report["external_tools_started"])
            self.assertEqual(snapshot(case_dir), before)

    def test_acceptance_audit_accepts_exact_reviewed_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = make_legacy_python_case(Path(temporary))
            _, preview = run_reviewer(case_dir)
            review = completed_review(preview["review_template"])
            review_path = case_dir / "migration-review.json"
            review_path.write_text(json.dumps(review), encoding="utf-8")
            exported, export_report = run_reviewer(
                case_dir,
                "--review",
                "migration-review.json",
                "--output",
                "workflow.v2.candidate.json",
            )
            self.assertEqual(exported.returncode, 0, exported.stderr)
            before = snapshot(case_dir)

            completed, report = run_acceptance_auditor(
                case_dir,
                "--review",
                "migration-review.json",
                "--candidate",
                "workflow.v2.candidate.json",
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(report["status"], "accepted")
            self.assertTrue(report["accepted"])
            self.assertTrue(report["review_valid"])
            self.assertTrue(report["candidate_valid"])
            self.assertTrue(report["source_unchanged"])
            self.assertEqual(report["unauthorized_changes"], [])
            self.assertEqual(report["summary"]["authorized_changes"], 6)
            self.assertEqual(report["summary"]["invariants_failed"], 0)
            self.assertTrue(report["plan_comparison"]["structure_equivalent"])
            self.assertEqual(
                report["plan_comparison"]["action_changes"],
                [
                    {
                        "step": "analyze-1",
                        "source_action": "execute",
                        "source_reason_code": "manifest_v1_cache_unsupported",
                        "candidate_action": "execute",
                        "candidate_reason_code": "cache_disabled",
                    }
                ],
            )
            self.assertEqual(
                report["bindings"]["expected_candidate_sha256"],
                report["bindings"]["actual_candidate_sha256"],
            )
            self.assertEqual(snapshot(case_dir), before)

    def test_acceptance_audit_reports_unauthorized_candidate_changes(self) -> None:
        scenarios = (
            (lambda candidate: candidate.update({"profile": "submission"}), "/profile"),
            (
                lambda candidate: candidate["steps"][0].update({"script": "src/replaced.py"}),
                "/steps/0/script",
            ),
            (
                lambda candidate: candidate["steps"].append(
                    {"name": "extra", "script": "src/analyze-1.py"}
                ),
                "/steps/1",
            ),
        )
        for mutate, expected_pointer in scenarios:
            with self.subTest(expected_pointer=expected_pointer), tempfile.TemporaryDirectory() as temporary:
                case_dir = make_legacy_python_case(Path(temporary))
                _, preview = run_reviewer(case_dir)
                review = completed_review(preview["review_template"])
                (case_dir / "migration-review.json").write_text(
                    json.dumps(review), encoding="utf-8"
                )
                candidate = json.loads(
                    json.dumps(preview["candidate_manifest"])
                ) if preview.get("candidate_manifest") else None
                exported, export_report = run_reviewer(
                    case_dir,
                    "--review",
                    "migration-review.json",
                    "--output",
                    "workflow.v2.candidate.json",
                )
                self.assertEqual(exported.returncode, 0, exported.stderr)
                candidate_path = case_dir / "workflow.v2.candidate.json"
                candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
                mutate(candidate)
                if expected_pointer == "/steps/0/script":
                    (case_dir / "src" / "replaced.py").write_text(
                        "print('replacement')\n", encoding="utf-8"
                    )
                if candidate.get("profile") == "submission":
                    candidate["compliance"] = "compliance/submission.json"
                candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
                before = snapshot(case_dir)

                completed, report = run_acceptance_auditor(
                    case_dir,
                    "--review",
                    "migration-review.json",
                    "--candidate",
                    "workflow.v2.candidate.json",
                )

                self.assertEqual(completed.returncode, 2)
                self.assertEqual(report["status"], "failed")
                self.assertFalse(report["accepted"])
                pointers = {
                    item["json_pointer"] for item in report["unauthorized_changes"]
                }
                self.assertIn(expected_pointer, pointers)
                self.assertEqual(snapshot(case_dir), before)

    def test_acceptance_audit_rejects_stale_review_or_candidate_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = make_legacy_python_case(Path(temporary))
            _, preview = run_reviewer(case_dir)
            review = completed_review(preview["review_template"])
            review_path = case_dir / "migration-review.json"
            review_path.write_text(json.dumps(review), encoding="utf-8")
            exported, _ = run_reviewer(
                case_dir,
                "--review",
                "migration-review.json",
                "--output",
                "workflow.v2.candidate.json",
            )
            self.assertEqual(exported.returncode, 0)
            review["base_candidate_sha256"] = "0" * 64
            review_path.write_text(json.dumps(review), encoding="utf-8")

            completed, report = run_acceptance_auditor(
                case_dir,
                "--review",
                "migration-review.json",
                "--candidate",
                "workflow.v2.candidate.json",
            )

            self.assertEqual(completed.returncode, 2)
            self.assertFalse(report["accepted"])
            self.assertIn("base candidate hash is stale", report["errors"][0])

    def test_acceptance_audit_reports_v2_as_not_applicable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary) / "current-acceptance"
            (case_dir / "src").mkdir(parents=True)
            (case_dir / "src" / "analyze.py").write_text(
                "print('ok')\n", encoding="utf-8"
            )
            (case_dir / "workflow.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "profile": "explore",
                        "steps": [{"name": "analyze", "script": "src/analyze.py"}],
                    }
                ),
                encoding="utf-8",
            )
            before = snapshot(case_dir)

            completed, report = run_acceptance_auditor(case_dir)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(report["status"], "not_applicable")
            self.assertFalse(report["accepted"])
            self.assertTrue(report["source_unchanged"])
            self.assertEqual(snapshot(case_dir), before)


if __name__ == "__main__":
    unittest.main()

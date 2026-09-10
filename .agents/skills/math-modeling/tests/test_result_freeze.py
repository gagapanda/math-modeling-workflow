from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]
FREEZE_SCRIPT = SKILL_ROOT / "scripts" / "freeze_results.py"
SCAFFOLD_SCRIPT = SKILL_ROOT / "scripts" / "scaffold_case.py"


class ResultFreezeTests(unittest.TestCase):
    def run_cli(self, script: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), *map(str, args)],
            text=True,
            capture_output=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )

    def make_case(
        self,
        root: Path,
        *,
        limitations: list[str] | None = None,
        unresolved: list[str] | None = None,
        replay_count: int = 2,
        register_kind: str = "result-register",
        file_path: str = "results/result.json",
    ) -> Path:
        case = root / "case"
        (case / "results").mkdir(parents=True)
        (case / "replay").mkdir(parents=True)
        (case / "results" / "result-register.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "results": [{"id": "Q1.value", "value": 42}],
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        (case / "results" / "result.json").write_text('{"value": 42}\n', encoding="utf-8")
        replay_paths = []
        for index in range(replay_count):
            relative = f"replay/run-{index + 1}.json"
            (case / relative).write_text(
                json.dumps({"run": index + 1, "value": 42}) + "\n",
                encoding="utf-8",
            )
            replay_paths.append(relative)
        files = [
            {"path": "results/result-register.json", "kind": register_kind},
            {"path": file_path, "kind": "result"},
            *({"path": replay, "kind": "replay"} for replay in replay_paths),
        ]
        plan = {
            "schema_version": 1,
            "freeze_id": "F1-20260827-001",
            "result_register": "results/result-register.json",
            "files": files,
            "replay_evidence": replay_paths,
            "limitations": limitations or [],
            "unresolved": unresolved or [],
        }
        (case / "results" / "f1-freeze-plan.json").write_text(
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return case

    def prepare(self, case: Path, output: str = "results/f1-candidate.json") -> subprocess.CompletedProcess[str]:
        return self.run_cli(
            FREEZE_SCRIPT,
            "prepare",
            "--case-dir",
            case,
            "--plan",
            "results/f1-freeze-plan.json",
            "--output",
            output,
            "--generated-at",
            "2026-08-27T10:00:00+08:00",
        )

    def finalize(
        self,
        case: Path,
        *,
        decision: str = "accepted",
        reviewer: str = "Responsible Operator",
        output: str = "results/f1-manifest.json",
        confirm: bool = True,
        review_start: str = "2026-08-27T10:01:00+08:00",
        review_end: str = "2026-08-27T10:02:00+08:00",
        signed_at: str = "2026-08-27T10:03:00+08:00",
        generated_at: str = "2026-08-27T10:04:00+08:00",
    ) -> subprocess.CompletedProcess[str]:
        args = [
            "finalize",
            "--case-dir",
            str(case),
            "--candidate",
            "results/f1-candidate.json",
            "--output",
            output,
            "--decision",
            decision,
            "--reviewer",
            reviewer,
            "--review-start",
            review_start,
            "--review-end",
            review_end,
            "--signed-at",
            signed_at,
            "--generated-at",
            generated_at,
        ]
        if confirm:
            args.append("--confirm-human-reviewed")
        return self.run_cli(FREEZE_SCRIPT, *args)

    def test_prepare_creates_pending_non_authoritative_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.make_case(Path(temporary))
            completed = self.prepare(case)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            report = json.loads(completed.stdout)
            candidate = json.loads((case / "results" / "f1-candidate.json").read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "F1_PENDING_HUMAN")
            self.assertFalse(report["paper_authoritative"])
            self.assertEqual(candidate["human_decision"]["decision"], "not_reviewed")

    def test_prepare_rejects_fewer_than_two_replays(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.make_case(Path(temporary), replay_count=1)
            completed = self.prepare(case)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("at least two", completed.stdout)
            self.assertFalse((case / "results" / "f1-candidate.json").exists())

    def test_prepare_rejects_wrong_result_register_kind(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.make_case(Path(temporary), register_kind="result")
            completed = self.prepare(case)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("kind=result-register", completed.stdout)

    def test_prepare_rejects_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.make_case(Path(temporary), file_path="../outside.json")
            completed = self.prepare(case)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("without '..'", completed.stdout)

    def test_prepare_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.make_case(Path(temporary))
            link = case / "results" / "linked-result.json"
            try:
                link.symlink_to(case / "results" / "result.json")
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            plan_path = case / "results" / "f1-freeze-plan.json"
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["files"][1]["path"] = "results/linked-result.json"
            plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
            completed = self.prepare(case)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("must not be a symlink", completed.stdout)

    def test_finalize_requires_explicit_human_confirmation_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.make_case(Path(temporary))
            self.assertEqual(self.prepare(case).returncode, 0)
            completed = self.finalize(case, confirm=False)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("confirm-human-reviewed", completed.stdout)
            self.assertFalse((case / "results" / "f1-manifest.json").exists())

    def test_finalize_rejects_ai_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.make_case(Path(temporary))
            self.assertEqual(self.prepare(case).returncode, 0)
            for reviewer in ("Codex", "AI", "assistant"):
                completed = self.finalize(case, reviewer=reviewer, output=f"results/{reviewer}.json")
                with self.subTest(reviewer=reviewer):
                    self.assertEqual(completed.returncode, 2)
                    self.assertFalse((case / "results" / f"{reviewer}.json").exists())

    def test_accepted_finalize_and_verify_are_authoritative(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.make_case(Path(temporary))
            self.assertEqual(self.prepare(case).returncode, 0)
            finalized = self.finalize(case)
            self.assertEqual(finalized.returncode, 0, finalized.stdout + finalized.stderr)
            final = json.loads((case / "results" / "f1-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(final["status"], "F1_ACCEPTED")
            self.assertTrue(final["paper_authoritative"])
            verified = self.run_cli(
                FREEZE_SCRIPT,
                "verify",
                "--case-dir",
                case,
                "--manifest",
                "results/f1-manifest.json",
            )
            self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
            self.assertTrue(json.loads(verified.stdout)["paper_authoritative"])

    def test_verify_fails_after_frozen_file_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.make_case(Path(temporary))
            self.assertEqual(self.prepare(case).returncode, 0)
            self.assertEqual(self.finalize(case).returncode, 0)
            (case / "results" / "result.json").write_text('{"value": 43}\n', encoding="utf-8")
            verified = self.run_cli(
                FREEZE_SCRIPT,
                "verify",
                "--case-dir",
                case,
                "--manifest",
                "results/f1-manifest.json",
            )
            self.assertEqual(verified.returncode, 2)
            self.assertIn("mismatch", verified.stdout)

    def test_accepted_rejects_unresolved_items(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.make_case(Path(temporary), unresolved=["Q4 not reconciled"])
            self.assertEqual(self.prepare(case).returncode, 0)
            completed = self.finalize(case)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("unresolved=[]", completed.stdout)

    def test_accepted_with_limitations_requires_limitation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.make_case(Path(temporary))
            self.assertEqual(self.prepare(case).returncode, 0)
            completed = self.finalize(case, decision="accepted_with_limitations")
            self.assertEqual(completed.returncode, 2)
            self.assertIn("requires at least one limitation", completed.stdout)

    def test_rejected_manifest_remains_non_authoritative(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.make_case(Path(temporary), unresolved=["Result is not accepted"])
            self.assertEqual(self.prepare(case).returncode, 0)
            completed = self.finalize(case, decision="rejected")
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            report = json.loads(completed.stdout)
            self.assertEqual(report["status"], "F1_REJECTED")
            self.assertFalse(report["paper_authoritative"])

    def test_existing_outputs_are_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.make_case(Path(temporary))
            first = self.prepare(case)
            self.assertEqual(first.returncode, 0)
            candidate = case / "results" / "f1-candidate.json"
            before = candidate.read_bytes()
            second = self.prepare(case)
            self.assertEqual(second.returncode, 2)
            self.assertEqual(candidate.read_bytes(), before)

    def test_finalize_rejects_invalid_timestamp_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.make_case(Path(temporary))
            self.assertEqual(self.prepare(case).returncode, 0)
            completed = self.finalize(
                case,
                review_start="2026-08-27T10:03:00+08:00",
                review_end="2026-08-27T10:02:00+08:00",
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("review_start <= review_end", completed.stdout)

    def test_verify_rejects_tampered_human_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.make_case(Path(temporary))
            self.assertEqual(self.prepare(case).returncode, 0)
            self.assertEqual(self.finalize(case).returncode, 0)
            manifest_path = case / "results" / "f1-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["human_decision"]["reviewer"] = "Codex"
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            verified = self.run_cli(
                FREEZE_SCRIPT,
                "verify",
                "--case-dir",
                case,
                "--manifest",
                "results/f1-manifest.json",
            )
            self.assertEqual(verified.returncode, 2)
            self.assertIn("actual human operator", verified.stdout)

    def test_scaffold_second_run_preserves_f1_plan_and_human_card(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = self.run_cli(SCAFFOLD_SCRIPT, "case-a", "--root", root)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            case = root / "case-a"
            plan = case / "results" / "f1-freeze-plan.json"
            card = case / "results" / "F1-review-card.md"
            self.assertTrue(plan.is_file())
            self.assertTrue(card.is_file())
            self.assertIn("REPLACE_BEFORE_PREPARE", plan.read_text(encoding="utf-8"))
            self.assertIn("cannot sign", card.read_text(encoding="utf-8"))
            plan.write_text("operator plan\n", encoding="utf-8")
            card.write_text("operator review\n", encoding="utf-8")
            second = self.run_cli(SCAFFOLD_SCRIPT, "case-a", "--root", root)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertEqual(plan.read_text(encoding="utf-8"), "operator plan\n")
            self.assertEqual(card.read_text(encoding="utf-8"), "operator review\n")


if __name__ == "__main__":
    unittest.main()

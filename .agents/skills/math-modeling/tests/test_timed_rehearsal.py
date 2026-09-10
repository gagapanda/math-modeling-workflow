from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_DIR / "scripts"
SCHEMAS = SKILL_DIR / "schemas"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def load_module():
    spec = importlib.util.spec_from_file_location(
        "math_modeling_timed_rehearsal", SCRIPTS / "manage_timed_rehearsal.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load manage_timed_rehearsal.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rehearsal = load_module()


class TimedRehearsalTests(unittest.TestCase):
    def test_cli_json_switch_is_accepted_before_or_after_subcommand(self) -> None:
        common = ["--case-dir", ".", "--plan", "plan.json", "--log", "log.json"]
        for argv in (
            ["manage_timed_rehearsal.py", "--json", "init", *common],
            ["manage_timed_rehearsal.py", "init", *common, "--json"],
        ):
            with self.subTest(argv=argv), patch.object(sys, "argv", argv):
                self.assertTrue(rehearsal.parse_args().json)
    def make_case(self, root: Path) -> tuple[Path, Path, Path]:
        case_dir = root / "case"
        (case_dir / "evidence").mkdir(parents=True)
        (case_dir / "evidence" / "record.txt").write_text(
            "verified rehearsal action\n", encoding="utf-8"
        )
        plan = {
            "schema_version": 1,
            "rehearsal_id": "2026-test-001",
            "mode": "full-simulation",
            "competition": "CUMCM 2026",
            "problem": "controlled workflow rehearsal",
            "started_at": "2026-08-17T08:00:00+08:00",
            "deadline_at": "2026-08-17T20:00:00+08:00",
            "team": [{"member_id": "member-a", "role": "workflow operator"}],
            "phases": [
                {"id": phase_id, "planned_minutes": 60}
                for phase_id in rehearsal.PHASE_IDS
            ],
            "fault_injections": [
                {
                    "id": "network-offline",
                    "planned_at": "2026-08-17T09:00:00+08:00",
                    "expected_response": "use local evidence and record the outage",
                },
                {
                    "id": "input-path-change",
                    "planned_at": "2026-08-17T14:00:00+08:00",
                    "expected_response": "fail closed and update the declared path",
                },
            ],
        }
        plan_path = case_dir / "rehearsal-plan.json"
        plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        log_path = case_dir / "rehearsal-log.json"
        rehearsal.initialize_log(case_dir, plan_path, log_path)
        return case_dir, plan_path, log_path

    def append(
        self,
        case_dir: Path,
        plan_path: Path,
        log_path: Path,
        minute: int,
        phase: str,
        event_type: str = "milestone",
        **kwargs,
    ) -> dict:
        hour, minute_value = divmod(minute, 60)
        return rehearsal.append_event(
            case_dir,
            plan_path,
            log_path,
            occurred_at=f"2026-08-17T{8 + hour:02d}:{minute_value:02d}:00+08:00",
            phase=phase,
            event_type=event_type,
            summary=kwargs.pop("summary", f"{phase} {event_type}"),
            evidence_paths=["evidence/record.txt"],
            **kwargs,
        )

    def populate_complete_log(self, case_dir: Path, plan_path: Path, log_path: Path) -> None:
        self.append(case_dir, plan_path, log_path, 0, "problem-selection")
        self.append(case_dir, plan_path, log_path, 30, "baseline")
        self.append(
            case_dir, plan_path, log_path, 60, "baseline", "fault-injection",
            fault_id="network-offline",
        )
        self.append(
            case_dir, plan_path, log_path, 70, "baseline", "recovery",
            fault_id="network-offline", related_event=3,
        )
        self.append(case_dir, plan_path, log_path, 120, "primary-model")
        self.append(
            case_dir, plan_path, log_path, 150, "primary-model", "failure",
            category="result-mismatch",
        )
        self.append(
            case_dir, plan_path, log_path, 170, "primary-model", "rework",
            category="data-contract", related_event=6,
        )
        self.append(case_dir, plan_path, log_path, 240, "synchronized-writing")
        self.append(
            case_dir, plan_path, log_path, 360, "independent-review", "fault-injection",
            fault_id="input-path-change",
        )
        self.append(
            case_dir, plan_path, log_path, 375, "independent-review", "recovery",
            fault_id="input-path-change", related_event=9,
        )
        self.append(case_dir, plan_path, log_path, 420, "independent-review")
        self.append(case_dir, plan_path, log_path, 480, "packaging")

    def review_input(self) -> dict:
        return {
            "closed_at": "2026-08-17T16:30:00+08:00",
            "actual_minutes": {phase_id: 60 for phase_id in rehearsal.PHASE_IDS},
            "result_assessment": "complete-unverified",
            "scorecard": [
                {
                    "id": scorecard_id,
                    "status": "pass",
                    "event_sequences": [12],
                    "notes": "reviewed against the recorded packaging evidence",
                }
                for scorecard_id in rehearsal.SCORECARD_IDS
            ],
            "improvements": [
                {
                    "id": "improve-result-contract",
                    "source_event_sequences": [6, 7],
                    "statement": "validate the result contract before paper synchronization",
                    "owner": "member-a",
                    "priority": "P0",
                    "acceptance_criterion": "a regression test rejects the reproduced mismatch",
                    "destination": "test",
                    "decision": "adopt",
                    "rationale": "the failure caused measurable rework",
                    "due_date": "2026-08-18",
                    "status": "open",
                }
            ],
            "no_durable_change": [],
            "unresolved_blockers": [],
            "closure_notes": "The record is complete; result quality remains separately assessed.",
        }

    def write_review(self, case_dir: Path, payload: dict) -> Path:
        path = case_dir / "review-input.json"
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return path

    def test_successful_lifecycle_is_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir, plan_path, log_path = self.make_case(Path(temporary))
            self.populate_complete_log(case_dir, plan_path, log_path)
            review_path = self.write_review(case_dir, self.review_input())
            output_path = case_dir / "rehearsal-review.json"
            result = rehearsal.close_rehearsal(
                case_dir, plan_path, log_path, review_path, output_path
            )
            self.assertTrue(result["record_complete"])
            self.assertEqual(result["record_scope"], rehearsal.RECORD_SCOPE)
            self.assertEqual(result["event_counts"]["failure"], 1)
            self.assertEqual(result["event_counts"]["rework"], 1)
            self.assertEqual(
                [entry["recovery_minutes"] for entry in result["fault_summary"]],
                [10, 15],
            )
            rehearsal.load_and_validate(
                result, SCHEMAS / "timed-rehearsal-review.schema.json", "review"
            )

    def test_stale_plan_and_tampered_chain_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir, plan_path, log_path = self.make_case(Path(temporary))
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["problem"] = "changed after initialization"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "plan changed"):
                self.append(case_dir, plan_path, log_path, 1, "baseline")

            case_dir, plan_path, log_path = self.make_case(Path(temporary) / "second")
            self.append(case_dir, plan_path, log_path, 1, "problem-selection")
            log = json.loads(log_path.read_text(encoding="utf-8"))
            log["events"][0]["summary"] = "silent rewrite"
            log_path.write_text(json.dumps(log), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash does not match"):
                self.append(case_dir, plan_path, log_path, 2, "baseline")

    def test_invalid_append_preserves_existing_log(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir, plan_path, log_path = self.make_case(Path(temporary))
            self.append(case_dir, plan_path, log_path, 20, "problem-selection")
            before = rehearsal.sha256_file(log_path)
            with self.assertRaisesRegex(ValueError, "timestamp precedes"):
                self.append(case_dir, plan_path, log_path, 10, "baseline")
            self.assertEqual(rehearsal.sha256_file(log_path), before)
            with self.assertRaisesRegex(ValueError, "escapes the case directory"):
                rehearsal.append_event(
                    case_dir, plan_path, log_path, occurred_at="2026-08-17T08:30:00+08:00",
                    phase="baseline", event_type="milestone", summary="escaped evidence",
                    evidence_paths=["../outside.txt"],
                )
            self.assertEqual(rehearsal.sha256_file(log_path), before)

    def test_rework_and_recovery_require_valid_triggers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir, plan_path, log_path = self.make_case(Path(temporary))
            with self.assertRaisesRegex(ValueError, "rework event 1"):
                self.append(
                    case_dir, plan_path, log_path, 1, "baseline", "rework",
                    category="late-change",
                )
            with self.assertRaisesRegex(ValueError, "recovery event 1"):
                self.append(case_dir, plan_path, log_path, 2, "baseline", "recovery")
            self.assertEqual(
                json.loads(log_path.read_text(encoding="utf-8"))["events"], []
            )

    def test_review_gates_and_failed_replace_preserve_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir, plan_path, log_path = self.make_case(Path(temporary))
            self.populate_complete_log(case_dir, plan_path, log_path)
            review = self.review_input()
            review_path = self.write_review(case_dir, review)
            output_path = case_dir / "rehearsal-review.json"
            rehearsal.close_rehearsal(case_dir, plan_path, log_path, review_path, output_path)
            before = rehearsal.sha256_file(output_path)

            review["scorecard"].pop()
            self.write_review(case_dir, review)
            with self.assertRaisesRegex(ValueError, "scorecard must contain"):
                rehearsal.close_rehearsal(
                    case_dir, plan_path, log_path, review_path, output_path, replace=True
                )
            self.assertEqual(rehearsal.sha256_file(output_path), before)

            review = self.review_input()
            review["improvements"][0]["owner"] = ""
            self.write_review(case_dir, review)
            with self.assertRaisesRegex(ValueError, "requires owner"):
                rehearsal.close_rehearsal(
                    case_dir, plan_path, log_path, review_path, output_path, replace=True
                )
            self.assertEqual(rehearsal.sha256_file(output_path), before)


if __name__ == "__main__":
    unittest.main()

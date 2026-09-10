from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "data_clean.py"


class DataCleanTests(unittest.TestCase):
    def run_clean(
        self, input_path: Path, plan_path: Path, output: Path
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable, str(SCRIPT), "--input", str(input_path),
                "--plan", str(plan_path), "--output", str(output),
            ],
            capture_output=True, text=True, check=False,
        )

    def write_plan(
        self, path: Path, input_path: Path, rules: list[dict],
        row_ids: list[str] | None = None,
    ) -> None:
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
                    "row_id_columns": row_ids or [],
                    "rules": rules,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def test_cleaning_is_hash_bound_deterministic_and_fully_logged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.csv"
            source.write_text(
                "id,name,score,status\n"
                "a, Alice ,10,ok\n"
                "b,Bob,bad,missing\n"
                "b,Bob,bad,missing\n"
                "c, Cara ,30,ok\n",
                encoding="utf-8",
            )
            before = source.read_bytes()
            plan = root / "plan.json"
            self.write_plan(
                plan, source,
                [
                    {
                        "id": "trim_names", "operation": "trim_whitespace",
                        "columns": ["name"], "reason": "remove export padding",
                        "expected_changes": 2,
                    },
                    {
                        "id": "mark_missing", "operation": "replace_values",
                        "columns": ["status"],
                        "replacements": [{"from": "missing", "to": None}],
                        "reason": "documented source sentinel", "expected_changes": 2,
                    },
                    {
                        "id": "numeric_score", "operation": "convert_numeric",
                        "columns": ["score"], "errors": "coerce",
                        "reason": "score is defined as numeric", "expected_changes": 4,
                    },
                    {
                        "id": "fill_score", "operation": "fill_missing",
                        "columns": ["score"], "value": 20,
                        "reason": "reviewed constant for this fixture",
                        "expected_changes": 2,
                    },
                    {
                        "id": "deduplicate", "operation": "drop_duplicate_rows",
                        "subset": ["id", "name", "score", "status"],
                        "keep": "first", "reason": "exact repeated export row",
                        "expected_changes": 1,
                    },
                    {
                        "id": "rename_score", "operation": "rename_columns",
                        "mapping": {"score": "score_clean"},
                        "reason": "distinguish processed field", "expected_changes": 1,
                    },
                ],
                ["id"],
            )

            outputs = [root / "out-a", root / "out-b"]
            for output in outputs:
                completed = self.run_clean(source, plan, output)
                self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(source.read_bytes(), before)
            result = pd.read_csv(outputs[0] / "processed.csv")
            self.assertEqual(result.columns.tolist(), ["id", "name", "score_clean", "status"])
            self.assertEqual(result["name"].tolist(), ["Alice", "Bob", "Cara"])
            self.assertEqual(result["score_clean"].tolist(), [10, 20, 30])
            changes = pd.read_csv(outputs[0] / "changes.csv")
            self.assertEqual(len(changes), 10)
            self.assertEqual(set(changes["source_row"]), {2, 3, 4, 5})
            self.assertEqual(len(pd.read_csv(outputs[0] / "dropped_rows.csv")), 1)
            self.assertEqual(len(pd.read_csv(outputs[0] / "schema_changes.csv")), 1)
            evidence = json.loads((outputs[0] / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(evidence["input_rows"], 4)
            self.assertEqual(evidence["output_rows"], 3)
            self.assertEqual(evidence["rules_applied"], 6)
            self.assertTrue(evidence["input_unchanged"])
            for name, digest in evidence["output_sha256"].items():
                self.assertEqual(
                    digest, hashlib.sha256((outputs[0] / name).read_bytes()).hexdigest()
                )
            for filename in (
                "processed.csv", "changes.csv", "dropped_rows.csv",
                "schema_changes.csv", "rule_summary.csv", "plan.json",
                "run.json", "summary.md",
            ):
                self.assertEqual(
                    (outputs[0] / filename).read_bytes(),
                    (outputs[1] / filename).read_bytes(),
                    filename,
                )

    def test_hash_and_expected_change_mismatches_leave_no_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.csv"
            source.write_text("id,value\na, 1 \n", encoding="utf-8")
            bad_hash = root / "bad-hash.json"
            self.write_plan(
                bad_hash, source,
                [{
                    "id": "trim", "operation": "trim_whitespace",
                    "columns": ["value"], "reason": "fixture",
                    "expected_changes": 1,
                }],
            )
            payload = json.loads(bad_hash.read_text(encoding="utf-8"))
            payload["input_sha256"] = "0" * 64
            bad_hash.write_text(json.dumps(payload), encoding="utf-8")
            output_hash = root / "out-hash"
            completed = self.run_clean(source, bad_hash, output_hash)
            self.assertEqual(completed.returncode, 1)
            self.assertIn("does not match", completed.stderr)
            self.assertFalse(output_hash.exists())

            bad_count = root / "bad-count.json"
            self.write_plan(
                bad_count, source,
                [{
                    "id": "trim", "operation": "trim_whitespace",
                    "columns": ["value"], "reason": "fixture",
                    "expected_changes": 2,
                }],
            )
            output_count = root / "out-count"
            completed = self.run_clean(source, bad_count, output_count)
            self.assertEqual(completed.returncode, 1)
            self.assertIn("expected 2 changes but observed 1", completed.stderr)
            self.assertFalse(output_count.exists())

    def test_clip_transform_and_missing_row_drop_are_ordered_and_logged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.csv"
            source.write_text(
                "id,temp_c,required\na,-20,yes\nb,10,\nc,80,yes\n",
                encoding="utf-8",
            )
            plan = root / "plan.json"
            self.write_plan(
                plan, source,
                [
                    {
                        "id": "missing_marker", "operation": "replace_values",
                        "columns": ["required"],
                        "replacements": [{"from": "", "to": None}],
                        "reason": "blank means missing in source dictionary",
                        "expected_changes": 1,
                    },
                    {
                        "id": "numeric_temp", "operation": "convert_numeric",
                        "columns": ["temp_c"], "errors": "fail",
                        "reason": "declared temperature field", "expected_changes": 3,
                    },
                    {
                        "id": "physical_range", "operation": "clip_numeric",
                        "columns": ["temp_c"], "minimum": -10, "maximum": 50,
                        "reason": "reviewed sensor operating range",
                        "expected_changes": 2,
                    },
                    {
                        "id": "to_fahrenheit", "operation": "unit_transform",
                        "columns": ["temp_c"], "factor": 1.8, "offset": 32,
                        "reason": "required output unit", "expected_changes": 3,
                    },
                    {
                        "id": "required_complete", "operation": "drop_missing_rows",
                        "columns": ["required"], "how": "any",
                        "reason": "required response absent", "expected_changes": 1,
                    },
                ],
                ["id"],
            )
            output = root / "output"
            completed = self.run_clean(source, plan, output)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = pd.read_csv(output / "processed.csv")
            self.assertEqual(result["id"].tolist(), ["a", "c"])
            self.assertEqual(result["temp_c"].tolist(), [14.0, 122.0])
            changes = pd.read_csv(output / "changes.csv")
            self.assertEqual(len(changes), 9)
            dropped = pd.read_csv(output / "dropped_rows.csv")
            self.assertEqual(dropped["source_row"].tolist(), [3])
            self.assertEqual(dropped["rule_id"].tolist(), ["required_complete"])

    def test_row_keyed_column_swap_is_exact_hash_bound_and_logged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "members.csv"
            source.write_text(
                "member_id,latitude,longitude\n"
                "A100,23.1,113.1\n"
                "B1175,113.131483,23.031824\n",
                encoding="utf-8",
            )
            before = source.read_bytes()
            plan = root / "plan.json"
            rule = {
                "id": "swap_b1175_coordinates",
                "operation": "swap_columns_by_row_key",
                "columns": ["latitude", "longitude"],
                "row_keys": [{"member_id": "B1175"}],
                "reason": "reviewed row-specific coordinate-order correction",
                "expected_changes": 2,
            }
            self.write_plan(plan, source, [rule], ["member_id"])
            output = root / "output"
            completed = self.run_clean(source, plan, output)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(source.read_bytes(), before)
            result = pd.read_csv(output / "processed.csv")
            b1175 = result.set_index("member_id").loc["B1175"]
            self.assertEqual(b1175["latitude"], 23.031824)
            self.assertEqual(b1175["longitude"], 113.131483)
            changes = pd.read_csv(output / "changes.csv")
            self.assertEqual(changes["column"].tolist(), ["latitude", "longitude"])
            self.assertEqual(changes["source_row"].tolist(), [3, 3])
            self.assertEqual(changes["row_key_json"].tolist(), ['{"member_id":"B1175"}'] * 2)

            missing = root / "missing.json"
            bad_rule = {**rule, "row_keys": [{"member_id": "missing"}]}
            self.write_plan(missing, source, [bad_rule], ["member_id"])
            failed = self.run_clean(source, missing, root / "missing-output")
            self.assertEqual(failed.returncode, 1)
            self.assertIn('matched 0 rows', failed.stderr)

    def test_rejects_unsafe_rules_and_failed_numeric_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.csv"
            source.write_text("id,value\na,nope\n", encoding="utf-8")
            cases = [
                (
                    [{
                        "id": "eval", "operation": "python_expression",
                        "reason": "unsafe", "expected_changes": 0,
                    }],
                    "unsupported operation",
                ),
                (
                    [{
                        "id": "numeric", "operation": "convert_numeric",
                        "columns": ["value"], "errors": "fail",
                        "reason": "declared numeric", "expected_changes": 1,
                    }],
                    "cannot convert value at source row 2",
                ),
                (
                    [{
                        "id": "rename", "operation": "rename_columns",
                        "mapping": {"value": "id"}, "reason": "collision",
                        "expected_changes": 1,
                    }],
                    "would not be unique",
                ),
            ]
            for index, (rules, expected) in enumerate(cases):
                plan = root / f"plan-{index}.json"
                self.write_plan(plan, source, rules)
                output = root / f"out-{index}"
                completed = self.run_clean(source, plan, output)
                self.assertEqual(completed.returncode, 1)
                self.assertIn(expected, completed.stderr)
                self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()

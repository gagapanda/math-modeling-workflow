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
SCRIPT = SKILL_DIR / "scripts" / "data_audit.py"


class DataAuditTests(unittest.TestCase):
    def run_audit(
        self, input_path: Path, output: Path, *arguments: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--input",
                str(input_path),
                "--output",
                str(output),
                *arguments,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_audit_writes_hash_bound_deterministic_structured_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "mixed.csv"
            rows = []
            for index in range(24):
                rows.append(
                    {
                        "id": f"s-{index:02d}",
                        "group": "a" if index < 12 else "b",
                        "time": f"2026-01-{index % 12 + 1:02d}",
                        "x": 1000 if index == 23 else index,
                        "x_scaled": 2 * (1000 if index == 23 else index),
                        "category": "low" if index < 18 else "high",
                        "target": index % 2,
                    }
                )
            rows[8]["category"] = None
            rows[10]["time"] = "2026-01-01"
            rows.append(dict(rows[3]))
            pd.DataFrame(rows).to_csv(input_path, index=False)
            before = input_path.read_bytes()
            outputs = [root / "run-a", root / "run-b"]
            for output in outputs:
                completed = self.run_audit(
                    input_path,
                    output,
                    "--id-columns",
                    "id",
                    "--target-columns",
                    "target",
                    "--time-columns",
                    "time",
                    "--group-columns",
                    "group",
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
            evidence = json.loads(
                (outputs[0] / "run.json").read_text(encoding="utf-8")
            )
            self.assertEqual(evidence["rows"], 25)
            self.assertEqual(evidence["columns"], 7)
            self.assertEqual(
                evidence["input_sha256"], hashlib.sha256(before).hexdigest()
            )
            self.assertFalse(evidence["ready_for_modeling"])
            self.assertEqual(input_path.read_bytes(), before)
            issues = pd.read_csv(outputs[0] / "issues.csv")
            codes = set(issues["code"])
            self.assertTrue(
                {
                    "duplicate_rows",
                    "id_not_unique",
                    "missing_values",
                    "iqr_outlier_candidates",
                    "high_numeric_correlation",
                    "time_order_violation",
                }.issubset(codes)
            )
            self.assertEqual(
                len(pd.read_csv(outputs[0] / "duplicate_rows.csv")), 2
            )
            columns = pd.read_csv(outputs[0] / "columns.csv").set_index("column")
            self.assertEqual(columns.loc["id", "role"], "id")
            self.assertEqual(columns.loc["target", "role"], "target")
            for filename in (
                "columns.csv",
                "numeric_summary.csv",
                "categorical_summary.csv",
                "outliers.csv",
                "correlations.csv",
                "time_summary.csv",
                "duplicate_rows.csv",
                "issues.csv",
                "run.json",
                "summary.md",
            ):
                self.assertEqual(
                    (outputs[0] / filename).read_bytes(),
                    (outputs[1] / filename).read_bytes(),
                    filename,
                )

    def test_audit_flags_target_copy_and_near_perfect_correlation_as_candidates(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "leakage.csv"
            rows = [
                {
                    "id": f"r-{index}",
                    "target": float(index),
                    "target_copy": index,
                    "near_target": index + (0.0001 if index % 2 else -0.0001),
                    "feature": (index * 7) % 13,
                }
                for index in range(40)
            ]
            pd.DataFrame(rows).to_csv(input_path, index=False)
            output = root / "output"
            completed = self.run_audit(
                input_path,
                output,
                "--id-columns",
                "id",
                "--target-columns",
                "target",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            issues = pd.read_csv(output / "issues.csv")
            exact = issues[issues["code"] == "target_exact_copy_candidate"]
            near = issues[
                issues["code"] == "target_near_perfect_correlation_candidate"
            ]
            self.assertEqual(exact["column"].tolist(), ["target_copy"])
            self.assertEqual(near["column"].tolist(), ["near_target"])
            self.assertIn(
                "correlation alone does not prove leakage", near.iloc[0]["action"]
            )

    def test_audit_treats_multiple_id_columns_as_a_composite_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "panel.csv"
            rows = [
                {
                    "entity": entity,
                    "period": period,
                    "value": entity * 10 + period,
                }
                for entity in range(4)
                for period in range(3)
            ]
            pd.DataFrame(rows).to_csv(input_path, index=False)
            output = root / "output"
            completed = self.run_audit(
                input_path,
                output,
                "--id-columns",
                "entity,period",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            issues = pd.read_csv(output / "issues.csv")
            self.assertNotIn("id_not_unique", set(issues["code"]))
            evidence = json.loads((output / "run.json").read_text(encoding="utf-8"))
            self.assertTrue(evidence["ready_for_modeling"])

    def test_audit_preserves_numeric_time_units_and_checks_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "numeric-time.csv"
            pd.DataFrame(
                {
                    "time_min": [0, 20, 70, 50, 120],
                    "value": [1.0, 1.2, 1.5, 1.4, 1.8],
                }
            ).to_csv(input_path, index=False)
            output = root / "output"
            completed = self.run_audit(
                input_path,
                output,
                "--time-columns",
                "time_min",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            time_summary = pd.read_csv(output / "time_summary.csv")
            self.assertEqual(time_summary.loc[0, "time_kind"], "numeric")
            self.assertEqual(time_summary.loc[0, "minimum"], 0.0)
            self.assertEqual(time_summary.loc[0, "maximum"], 120.0)
            self.assertEqual(time_summary.loc[0, "order_violation_count"], 1)
            issues = pd.read_csv(output / "issues.csv")
            self.assertIn("time_order_violation", set(issues["code"]))

    def test_audit_rejects_bad_headers_roles_and_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases = [
                ("a,a\n1,2\n", [], "column names must be unique"),
                ("a, b \n1,2\n", [], "leading or trailing whitespace"),
                (
                    "a,b\n1,2\n",
                    ["--target-columns", "missing"],
                    "role columns are missing",
                ),
                (
                    "a,b\n1,2\n",
                    ["--id-columns", "a", "--target-columns", "a"],
                    "multiple declared roles",
                ),
                (
                    "a,b\n1,2\n",
                    ["--high-correlation-threshold", "1.1"],
                    "must be finite and in",
                ),
            ]
            for index, (content, arguments, expected) in enumerate(cases):
                input_path = root / f"bad-{index}.csv"
                input_path.write_text(content, encoding="utf-8")
                completed = self.run_audit(
                    input_path, root / f"out-{index}", *arguments
                )
                self.assertEqual(completed.returncode, 1)
                self.assertIn(expected, completed.stderr)


if __name__ == "__main__":
    unittest.main()

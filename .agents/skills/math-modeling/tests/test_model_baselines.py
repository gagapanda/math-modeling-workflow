from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "model_baselines" / "topsis.py"
ENTROPY_SCRIPT = (
    SKILL_DIR / "scripts" / "model_baselines" / "entropy_weight.py"
)
GM11_SCRIPT = SKILL_DIR / "scripts" / "model_baselines" / "gm11.py"
REGRESSION_SCRIPT = SKILL_DIR / "scripts" / "model_baselines" / "regression.py"
AHP_SCRIPT = SKILL_DIR / "scripts" / "model_baselines" / "ahp.py"
GREY_SCRIPT = SKILL_DIR / "scripts" / "model_baselines" / "grey_relation.py"
TIME_SERIES_SCRIPT = (
    SKILL_DIR / "scripts" / "model_baselines" / "time_series.py"
)
LP_SCRIPT = SKILL_DIR / "scripts" / "model_baselines" / "linear_programming.py"
MILP_SCRIPT = (
    SKILL_DIR / "scripts" / "model_baselines" / "integer_programming.py"
)
MONTE_CARLO_SCRIPT = (
    SKILL_DIR / "scripts" / "model_baselines" / "monte_carlo.py"
)
QUEUE_SCRIPT = (
    SKILL_DIR / "scripts" / "model_baselines" / "queue_simulation.py"
)
NONLINEAR_SCRIPT = (
    SKILL_DIR / "scripts" / "model_baselines" / "nonlinear_optimization.py"
)
CLASSIFICATION_SCRIPT = (
    SKILL_DIR / "scripts" / "model_baselines" / "classification.py"
)
CLUSTERING_SCRIPT = (
    SKILL_DIR / "scripts" / "model_baselines" / "clustering.py"
)
PCA_SCRIPT = SKILL_DIR / "scripts" / "model_baselines" / "pca.py"


class ModelBaselineTests(unittest.TestCase):
    def make_input(self, root: Path) -> Path:
        path = root / "指标数据.csv"
        path.write_text(
            "方案,x1,x2\nA,10,2\nB,8,1\nC,6,3\n", encoding="utf-8"
        )
        return path

    def test_topsis_writes_hash_bound_evidence_and_rank(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = self.make_input(root)
            output = root / "输出目录"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output),
                    "--columns",
                    "x1,x2",
                    "--weights",
                    "0.6,0.4",
                    "--directions",
                    "positive,negative",
                    "--id-column",
                    "方案",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                sorted(path.name for path in output.iterdir()),
                [
                    "ideal_solutions.csv",
                    "normalized_matrix.csv",
                    "run.json",
                    "topsis_result.csv",
                ],
            )
            evidence = json.loads((output / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(evidence["rows"], 3)
            self.assertEqual(sum(evidence["weights"]), 1.0)
            with (output / "topsis_result.csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["方案"], "B")
            self.assertEqual({int(row["rank"]) for row in rows}, {1, 2, 3})

    def test_topsis_rejects_weight_length_and_bad_direction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = self.make_input(root)
            common = [
                sys.executable,
                str(SCRIPT),
                "--input",
                str(input_path),
                "--output",
                str(root / "out"),
                "--columns",
                "x1,x2",
            ]
            for weights, directions in [("1", "positive,negative"), ("0.5,0.5", "positive,bad")]:
                completed = subprocess.run(
                    common + ["--weights", weights, "--directions", directions],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("ERROR:", completed.stderr)

    def test_entropy_weight_marks_constant_columns_and_writes_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "评价数据.csv"
            input_path.write_text(
                "方案,x1,x2,constant\nA,10,2,5\nB,8,1,5\nC,6,3,5\n",
                encoding="utf-8",
            )
            output = root / "熵权输出"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ENTROPY_SCRIPT),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output),
                    "--columns",
                    "x1,x2,constant",
                    "--directions",
                    "positive,negative,positive",
                    "--id-column",
                    "方案",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            evidence = json.loads((output / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(evidence["constant_columns"], ["constant"])
            self.assertAlmostEqual(sum(evidence["weights"]), 1.0)
            self.assertEqual(evidence["weights"][2], 0.0)
            with (output / "scores.csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            leaders = [row for row in rows if int(row["rank"]) == 1]
            self.assertEqual({row["方案"] for row in leaders}, {"A", "B"})
            self.assertAlmostEqual(float(leaders[0]["score"]), float(leaders[1]["score"]))

    def test_entropy_weight_rejects_all_constant_indicators(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "constant.csv"
            input_path.write_text("x1,x2\n1,2\n1,2\n", encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ENTROPY_SCRIPT),
                    "--input",
                    str(input_path),
                    "--output",
                    str(root / "out"),
                    "--columns",
                    "x1,x2",
                    "--directions",
                    "positive,negative",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("zero information diversity", completed.stderr)

    def test_gm11_writes_rolling_baseline_and_hash_bound_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "年度序列.csv"
            input_path.write_text(
                "year,value\n2019,10\n2020,12\n2021,14.4\n2022,17.28\n2023,20.736\n2024,24.8832\n",
                encoding="utf-8",
            )
            output = root / "灰色预测输出"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(GM11_SCRIPT),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output),
                    "--column",
                    "value",
                    "--periods",
                    "2",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                sorted(path.name for path in output.iterdir()),
                ["gm11_forecast.csv", "rolling_validation.csv", "run.json"],
            )
            evidence = json.loads((output / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(evidence["observations"], 6)
            self.assertEqual(evidence["rolling_validation_points"], 2)
            self.assertLess(evidence["rolling_gm11_mape_percent"], 1.0)
            self.assertLess(
                evidence["rolling_gm11_mape_percent"],
                evidence["rolling_naive_mape_percent"],
            )
            with (output / "gm11_forecast.csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 8)
            self.assertEqual(rows[-1]["type"], "forecast")

    def test_gm11_rejects_nonpositive_values_and_bad_training_window(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "bad.csv"
            input_path.write_text("value\n1\n2\n0\n4\n5\n", encoding="utf-8")
            for extra_args, expected in [([], "strictly positive"), (["--minimum-train", "3"], "at least 4")]:
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(GM11_SCRIPT),
                        "--input",
                        str(input_path),
                        "--output",
                        str(root / "out"),
                        "--column",
                        "value",
                    ]
                    + extra_args,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn(expected, completed.stderr)

    def test_regression_group_split_records_no_leakage_and_beats_mean(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "分组回归.csv"
            rows = ["group,x1,x2,y"]
            for group, offset in [("A", 0), ("B", 10), ("C", 20), ("D", 30)]:
                for step in range(4):
                    x1 = step + offset / 10
                    x2 = step * 2 + 1
                    rows.append(f"{group},{x1},{x2},{3 * x1 - 0.5 * x2 + 2}")
            input_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
            output = root / "回归输出"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(REGRESSION_SCRIPT),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output),
                    "--target",
                    "y",
                    "--features",
                    "x1,x2",
                    "--split",
                    "group",
                    "--group-column",
                    "group",
                    "--test-size",
                    "0.25",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            evidence = json.loads((output / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(evidence["split"], "group")
            self.assertTrue(set(evidence["split_evidence"]["train_groups"]).isdisjoint(evidence["split_evidence"]["test_groups"]))
            self.assertTrue(evidence["beats_mean_baseline_rmse"])
            self.assertEqual(evidence["coefficient_scale"], "standardized_features")
            with (output / "predictions.csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), evidence["test_rows"])

    def test_regression_time_split_rejects_missing_group_and_bad_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "tiny.csv"
            input_path.write_text("x,y\n1,2\n2,4\n3,6\n4,8\n5,10\n6,12\n", encoding="utf-8")
            base = [
                sys.executable,
                str(REGRESSION_SCRIPT),
                "--input",
                str(input_path),
                "--output",
                str(root / "out"),
                "--target",
                "y",
                "--features",
                "x",
            ]
            cases = [
                (["--split", "group"], "requires --group-column"),
                (["--split", "time", "--test-size", "1.0"], "between 0 and 1"),
            ]
            for extra, expected in cases:
                completed = subprocess.run(
                    base + extra, capture_output=True, text=True, check=False
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn(expected, completed.stderr)

    def test_ahp_writes_consistency_and_pairwise_sensitivity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "判断矩阵.csv"
            input_path.write_text(
                "1,2,4\n0.5,1,2\n0.25,0.5,1\n", encoding="utf-8"
            )
            output = root / "AHP输出"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(AHP_SCRIPT),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output),
                    "--perturbation",
                    "0.2",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            evidence = json.loads((output / "run.json").read_text(encoding="utf-8"))
            self.assertTrue(evidence["consistency_passed"])
            self.assertAlmostEqual(evidence["cr"], 0.0, places=10)
            self.assertAlmostEqual(sum(evidence["weights"]), 1.0)
            self.assertEqual(evidence["sensitivity_cases"], 6)
            with (output / "ahp_weights.csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertAlmostEqual(float(rows[0]["weight"]), 4 / 7, places=6)

    def test_ahp_rejects_nonreciprocal_and_bad_diagonal_matrices(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, content, expected in [
                ("nonreciprocal.csv", "1,3\n0.5,1\n", "must be reciprocal"),
                ("diagonal.csv", "2,2\n0.5,1\n", "diagonal must be 1"),
            ]:
                input_path = root / name
                input_path.write_text(content, encoding="utf-8")
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(AHP_SCRIPT),
                        "--input",
                        str(input_path),
                        "--output",
                        str(root / "out"),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn(expected, completed.stderr)

    def test_grey_relation_writes_coefficients_correlations_and_sensitivity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "关联数据.csv"
            input_path.write_text(
                "reference,similar,opposite,noise\n1,2,8,4\n2,4,7,1\n3,6,6,5\n4,8,5,2\n5,10,4,6\n",
                encoding="utf-8",
            )
            output = root / "灰色关联输出"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(GREY_SCRIPT),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output),
                    "--reference-column",
                    "reference",
                    "--columns",
                    "similar,opposite,noise",
                    "--sensitivity-rhos",
                    "0.2,0.5",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            evidence = json.loads((output / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(evidence["ranking"][0], "similar")
            self.assertEqual(evidence["sensitivity_cases"], 6)
            self.assertFalse(evidence["ranking_stable_across_sensitivity"])
            self.assertTrue(evidence["top_rank_stable_across_sensitivity"])
            with (output / "grey_coefficients.csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            for row in rows:
                for key in ("similar", "opposite", "noise"):
                    self.assertGreaterEqual(float(row[key]), 0.0)
                    self.assertLessEqual(float(row[key]), 1.0)
            with (output / "correlation_baselines.csv").open(encoding="utf-8", newline="") as stream:
                correlation_rows = list(csv.DictReader(stream))
            similar = next(row for row in correlation_rows if row["column"] == "similar")
            self.assertGreater(float(similar["spearman_rho"]), 0.99)

    def test_grey_relation_rejects_constant_columns_and_bad_rho(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "bad_grey.csv"
            input_path.write_text("reference,constant,other\n1,2,3\n2,2,2\n3,2,1\n4,2,4\n", encoding="utf-8")
            common = [
                sys.executable,
                str(GREY_SCRIPT),
                "--input",
                str(input_path),
                "--output",
                str(root / "out"),
                "--reference-column",
                "reference",
                "--columns",
                "constant,other",
            ]
            for extra, expected in [([], "is constant"), (["--rho", "0"], "in (0, 1]")]:
                completed = subprocess.run(
                    common + extra, capture_output=True, text=True, check=False
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn(expected, completed.stderr)

    def test_time_series_writes_rolling_baselines_and_future_forecasts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "时间序列.csv"
            input_path.write_text(
                "time,value\n1,1\n2,2\n3,3\n4,4\n5,5\n6,6\n7,7\n8,8\n",
                encoding="utf-8",
            )
            output = root / "时间序列输出"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(TIME_SERIES_SCRIPT),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output),
                    "--time-column",
                    "time",
                    "--value-column",
                    "value",
                    "--window",
                    "2",
                    "--alpha",
                    "0.8",
                    "--minimum-train",
                    "4",
                    "--periods",
                    "2",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                sorted(path.name for path in output.iterdir()),
                ["future_forecast.csv", "metrics.csv", "rolling_predictions.csv", "run.json"],
            )
            evidence = json.loads((output / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(evidence["rolling_validation_points"], 4)
            self.assertTrue(evidence["regular_time_intervals"])
            self.assertEqual(evidence["best_rolling_rmse_model"], "persistence")
            with (output / "future_forecast.csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 2)
            self.assertEqual(float(rows[-1]["time"]), 10.0)
            self.assertEqual(rows[0]["selected_model"], "persistence")

    def test_time_series_records_zero_mape_exclusions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "zeros.csv"
            input_path.write_text(
                "date,value\n2025-01-01,1\n2025-01-02,2\n2025-01-03,3\n2025-01-04,0\n2025-01-05,4\n2025-01-06,0\n",
                encoding="utf-8",
            )
            output = root / "out"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(TIME_SERIES_SCRIPT),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output),
                    "--time-column",
                    "date",
                    "--value-column",
                    "value",
                    "--minimum-train",
                    "3",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            evidence = json.loads((output / "run.json").read_text(encoding="utf-8"))
            persistence = evidence["metrics"]["persistence"]
            self.assertEqual(persistence["zero_actuals_excluded_from_mape"], 2)
            self.assertEqual(persistence["mape_used_count"], 1)
            self.assertTrue(any("MAPE excludes 2" in warning for warning in evidence["warnings"]))

    def test_time_series_rejects_bad_time_order_and_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "bad_time.csv"
            input_path.write_text(
                "time,value\n1,1\n2,2\n2,3\n4,4\n5,5\n6,6\n", encoding="utf-8"
            )
            base = [
                sys.executable,
                str(TIME_SERIES_SCRIPT),
                "--input",
                str(input_path),
                "--output",
                str(root / "out"),
                "--time-column",
                "time",
                "--value-column",
                "value",
            ]
            for extra, expected in [
                ([], "unique values"),
                (["--window", "6", "--minimum-train", "5"], "cannot exceed"),
                (["--alpha", "0"], "in (0, 1]"),
                (["--minimum-train", "2"], "at least 3"),
            ]:
                completed = subprocess.run(
                    base + extra, capture_output=True, text=True, check=False
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn(expected, completed.stderr)
            input_path.write_text(
                "time,value\n1,1\n3,2\n2,3\n4,4\n5,5\n6,6\n", encoding="utf-8"
            )
            completed = subprocess.run(
                base, capture_output=True, text=True, check=False
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("strictly increasing", completed.stderr)

    def test_linear_programming_writes_solution_constraint_recheck_and_sensitivity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "lp.json"
            input_path.write_text(
                json.dumps(
                    {
                        "sense": "maximize",
                        "variables": [
                            {"name": "x", "unit": "kg", "lower": 0},
                            {"name": "y", "unit": "kg", "lower": 0},
                        ],
                        "objective": {"coefficients": [3, 2], "unit": "yuan"},
                        "baseline_solution": [0, 0],
                        "constraints": [
                            {"name": "resource", "coefficients": [2, 1], "sense": "<=", "rhs": 100, "unit": "kg"},
                            {"name": "demand", "coefficients": [1, 1], "sense": "<=", "rhs": 80, "unit": "kg"},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            output = root / "lp-output"
            completed = subprocess.run(
                [sys.executable, str(LP_SCRIPT), "--input", str(input_path), "--output", str(output)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            evidence = json.loads((output / "run.json").read_text(encoding="utf-8"))
            self.assertTrue(evidence["success"])
            self.assertTrue(evidence["feasibility_passed"])
            self.assertAlmostEqual(evidence["objective_value"], 180.0, places=6)
            self.assertTrue(evidence["baseline_feasible"])
            self.assertAlmostEqual(evidence["objective_improvement_over_baseline"], 180.0)
            self.assertEqual(evidence["maximum_bound_violation"], 0.0)
            self.assertEqual(evidence["sensitivity_cases"], 4)
            with (output / "constraint_check.csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertTrue(all(float(row["violation"]) <= 1e-7 for row in rows))

    def test_linear_programming_handles_infeasible_and_unbounded_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = {
                "sense": "maximize",
                "variables": [{"name": "x", "lower": 0, "unit": "unit"}],
                "objective": {"coefficients": [1], "unit": "value"},
            }
            cases = [
                ("infeasible", {**base, "constraints": [{"name": "upper", "coefficients": [1], "sense": "<=", "rhs": 1}, {"name": "lower", "coefficients": [1], "sense": ">=", "rhs": 2}]}, 2, "infeasible"),
                ("unbounded", {**base, "constraints": []}, 3, "unbounded"),
            ]
            for name, problem, status, expected in cases:
                input_path = root / f"{name}.json"
                input_path.write_text(json.dumps(problem), encoding="utf-8")
                output = root / name
                completed = subprocess.run(
                    [sys.executable, str(LP_SCRIPT), "--input", str(input_path), "--output", str(output)],
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(completed.returncode, 2, completed.stderr)
                evidence = json.loads((output / "run.json").read_text(encoding="utf-8"))
                self.assertEqual(evidence["status"], status)
                self.assertIn(expected, evidence["message"].lower())

    def test_linear_programming_rejects_ambiguous_or_bad_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = {
                "variables": [{"name": "x"}, {"name": "y"}],
                "objective": {"coefficients": [1, 2]},
            }
            cases = [
                (
                    {
                        **base,
                        "constraints": [
                            {"name": "capacity", "coefficients": [1, 0], "sense": "<=", "rhs": 2},
                            {"name": "capacity", "coefficients": [0, 1], "sense": "<=", "rhs": 3},
                        ],
                    },
                    "duplicate constraint name",
                ),
                (
                    {
                        **base,
                        "constraints": [
                            {"name": "bad", "coefficients": [1], "sense": "<=", "rhs": 2}
                        ],
                    },
                    "must have length 2",
                ),
            ]
            for index, (problem, expected) in enumerate(cases):
                input_path = root / f"bad-{index}.json"
                input_path.write_text(json.dumps(problem), encoding="utf-8")
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(LP_SCRIPT),
                        "--input",
                        str(input_path),
                        "--output",
                        str(root / "out"),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 1)
                self.assertIn(expected, completed.stderr)

    def test_integer_programming_writes_integer_checks_and_lp_relaxation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "milp.json"
            input_path.write_text(
                json.dumps(
                    {
                        "sense": "maximize",
                        "variables": [
                            {"name": "x", "type": "integer", "lower": 0, "unit": "item"},
                            {"name": "y", "type": "integer", "lower": 0, "unit": "item"},
                        ],
                        "objective": {"coefficients": [0, 1], "unit": "score"},
                        "baseline_solution": [0, 0],
                        "constraints": [
                            {"name": "difference", "coefficients": [-1, 1], "sense": "<=", "rhs": 1, "unit": "item"},
                            {"name": "capacity_1", "coefficients": [3, 2], "sense": "<=", "rhs": 12, "unit": "resource"},
                            {"name": "capacity_2", "coefficients": [2, 3], "sense": "<=", "rhs": 12, "unit": "resource"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            output = root / "milp-output"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(MILP_SCRIPT),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            evidence = json.loads((output / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(evidence["solution_class"], "optimal")
            self.assertTrue(evidence["candidate_feasible"])
            self.assertTrue(evidence["lp_relaxation_feasible"])
            self.assertEqual(evidence["maximum_integrality_violation"], 0.0)
            self.assertAlmostEqual(evidence["objective_value"], 2.0)
            self.assertGreater(
                evidence["lp_relaxation_objective"], evidence["objective_value"]
            )
            self.assertAlmostEqual(
                evidence["objective_improvement_over_baseline"], 2.0
            )

    def test_integer_programming_supports_binary_and_continuous_variables(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "mixed.json"
            input_path.write_text(
                json.dumps(
                    {
                        "sense": "maximize",
                        "variables": [
                            {"name": "amount", "type": "continuous", "upper": 10, "unit": "kg"},
                            {"name": "open", "type": "binary", "unit": "flag"},
                        ],
                        "objective": {"coefficients": [4, -5], "unit": "yuan"},
                        "constraints": [
                            {"name": "link", "coefficients": [1, -10], "sense": "<=", "rhs": 0, "unit": "kg"}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            output = root / "mixed-output"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(MILP_SCRIPT),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            with (output / "solution.csv").open(
                encoding="utf-8", newline=""
            ) as stream:
                rows = {row["variable"]: row for row in csv.DictReader(stream)}
            self.assertAlmostEqual(float(rows["amount"]["value"]), 10.0)
            self.assertAlmostEqual(float(rows["open"]["value"]), 1.0)

    def test_integer_programming_records_infeasible_and_rejects_bad_types(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            infeasible = root / "infeasible.json"
            infeasible.write_text(
                json.dumps(
                    {
                        "variables": [{"name": "x", "type": "binary"}],
                        "objective": {"coefficients": [1]},
                        "constraints": [
                            {"name": "impossible", "coefficients": [1], "sense": ">=", "rhs": 2}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            output = root / "infeasible-output"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(MILP_SCRIPT),
                    "--input",
                    str(infeasible),
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 2)
            evidence = json.loads((output / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(evidence["solution_class"], "infeasible")

            bad_type = root / "bad-type.json"
            bad_type.write_text(
                json.dumps(
                    {
                        "variables": [{"name": "x", "type": "categorical"}],
                        "objective": {"coefficients": [1]},
                    }
                ),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(MILP_SCRIPT),
                    "--input",
                    str(bad_type),
                    "--output",
                    str(root / "bad"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 1)
            self.assertIn("continuous, integer, or binary", completed.stderr)

    def test_monte_carlo_is_reproducible_and_matches_uniform_analytics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "uniform.json"
            input_path.write_text(
                json.dumps(
                    {
                        "variables": [
                            {
                                "name": "x",
                                "distribution": "uniform",
                                "parameters": {"low": 0, "high": 1},
                                "unit": "ratio",
                                "source": "analytic verification fixture",
                            }
                        ],
                        "target": {
                            "name": "score",
                            "expression": "2 * x + 1",
                            "unit": "score",
                            "threshold": 2,
                            "threshold_operator": "<=",
                        },
                        "simulation": {
                            "iterations": 20000,
                            "seed": 123,
                            "replications": 4,
                            "confidence_level": 0.95,
                            "convergence_points": 8,
                            "sample_output_limit": 100,
                        },
                        "analytical": {
                            "expected_mean": 2,
                            "expected_threshold_probability": 0.5,
                        },
                    }
                ),
                encoding="utf-8",
            )
            outputs = [root / "run-a", root / "run-b"]
            for output in outputs:
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(MONTE_CARLO_SCRIPT),
                        "--input",
                        str(input_path),
                        "--output",
                        str(output),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
            evidence = json.loads(
                (outputs[0] / "run.json").read_text(encoding="utf-8")
            )
            self.assertTrue(
                evidence["analytical_checks"][
                    "expected_mean_in_confidence_interval"
                ]
            )
            self.assertTrue(
                evidence["analytical_checks"][
                    "expected_threshold_probability_in_confidence_interval"
                ]
            )
            self.assertLess(
                evidence["summary"]["mean_confidence_upper"]
                - evidence["summary"]["mean_confidence_lower"],
                evidence["summary"]["distribution_upper_quantile"]
                - evidence["summary"]["distribution_lower_quantile"],
            )
            self.assertEqual(
                (outputs[0] / "samples.csv").read_bytes(),
                (outputs[1] / "samples.csv").read_bytes(),
            )
            convergence = pd.read_csv(outputs[0] / "convergence.csv")
            self.assertLess(
                convergence.iloc[-1]["monte_carlo_standard_error"],
                convergence.iloc[0]["monte_carlo_standard_error"],
            )

    def test_monte_carlo_supports_declared_distributions_and_sample_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "distributions.json"
            variables = [
                ("c", "constant", {"value": 2}),
                ("n", "normal", {"mean": 1, "std": 0.2}),
                ("u", "uniform", {"low": 0, "high": 1}),
                (
                    "tri",
                    "triangular",
                    {"left": 0, "mode": 0.5, "right": 1},
                ),
                ("exp", "exponential", {"scale": 1}),
                (
                    "logn",
                    "lognormal",
                    {"mean_log": 0, "sigma_log": 0.2},
                ),
                ("b", "bernoulli", {"probability": 0.4}),
            ]
            input_path.write_text(
                json.dumps(
                    {
                        "variables": [
                            {
                                "name": name,
                                "distribution": distribution,
                                "parameters": parameters,
                                "unit": "test-unit",
                                "source": "distribution coverage fixture",
                            }
                            for name, distribution, parameters in variables
                        ],
                        "target": {
                            "name": "combined",
                            "expression": "c + n + u + tri + exp + logn + b",
                            "unit": "test-unit",
                        },
                        "simulation": {
                            "iterations": 500,
                            "seed": 7,
                            "replications": 2,
                            "sample_output_limit": 25,
                        },
                    }
                ),
                encoding="utf-8",
            )
            output = root / "output"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(MONTE_CARLO_SCRIPT),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            samples = pd.read_csv(output / "samples.csv")
            self.assertEqual(len(samples), 25)
            self.assertEqual(
                set(samples.columns),
                {"iteration", *(name for name, _, _ in variables), "combined"},
            )
            evidence = json.loads(
                (output / "run.json").read_text(encoding="utf-8")
            )
            self.assertIn("sampled independently", evidence["warnings"][0])
            self.assertTrue(
                any("truncated" in warning for warning in evidence["warnings"])
            )

    def test_monte_carlo_rejects_unsupported_or_unsafe_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = {
                "variables": [
                    {
                        "name": "x",
                        "distribution": "normal",
                        "parameters": {"mean": 0, "std": 1},
                        "unit": "score",
                        "source": "validation fixture",
                    }
                ],
                "target": {
                    "name": "result",
                    "expression": "x + 1",
                    "unit": "score",
                },
            }
            cases = [
                (
                    {
                        **base,
                        "variables": [
                            {
                                **base["variables"][0],
                                "source": "",
                            }
                        ],
                    },
                    "distribution source",
                ),
                (
                    {
                        **base,
                        "variables": [
                            {
                                **base["variables"][0],
                                "parameters": {"mean": 0, "std": 0},
                            }
                        ],
                    },
                    "std must be positive",
                ),
                (
                    {
                        **base,
                        "target": {
                            **base["target"],
                            "expression": "__import__('os').getcwd()",
                        },
                    },
                    "forbidden syntax",
                ),
                ({**base, "correlations": [[1.0]]}, "not supported"),
            ]
            for index, (problem, expected) in enumerate(cases):
                input_path = root / f"bad-{index}.json"
                input_path.write_text(json.dumps(problem), encoding="utf-8")
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(MONTE_CARLO_SCRIPT),
                        "--input",
                        str(input_path),
                        "--output",
                        str(root / f"out-{index}"),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 1)
                self.assertIn(expected, completed.stderr)

    def test_queue_simulation_matches_mm1_theory_and_is_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "mm1.json"
            input_path.write_text(
                json.dumps(
                    {
                        "model": "M/M/1",
                        "discipline": "FCFS",
                        "capacity": "infinite",
                        "arrival_rate": 0.8,
                        "service_rate": 1.0,
                        "arrival_rate_source": "analytic verification fixture",
                        "service_rate_source": "analytic verification fixture",
                        "time_unit": "hour",
                        "simulation": {
                            "customers": 30000,
                            "warmup_customers": 3000,
                            "replications": 10,
                            "seed": 31415,
                            "confidence_level": 0.95,
                            "convergence_points": 8,
                            "event_output_limit": 50,
                        },
                    }
                ),
                encoding="utf-8",
            )
            outputs = [root / "run-a", root / "run-b"]
            for output in outputs:
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(QUEUE_SCRIPT),
                        "--input",
                        str(input_path),
                        "--output",
                        str(output),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
            evidence = json.loads(
                (outputs[0] / "run.json").read_text(encoding="utf-8")
            )
            for metric in (
                "mean_waiting_time",
                "mean_system_time",
                "p95_waiting_time",
                "probability_of_wait",
                "time_average_queue_length",
                "time_average_system_size",
                "utilization",
                "effective_arrival_rate",
            ):
                self.assertTrue(
                    evidence["summary"][metric][
                        "theoretical_value_in_confidence_interval"
                    ],
                    metric,
                )
            self.assertLess(
                abs(
                    evidence["summary"]["little_lq_residual"][
                        "replication_mean"
                    ]
                ),
                0.01,
            )
            self.assertLess(
                abs(
                    evidence["summary"]["little_l_residual"][
                        "replication_mean"
                    ]
                ),
                0.01,
            )
            self.assertEqual(
                (outputs[0] / "replications.csv").read_bytes(),
                (outputs[1] / "replications.csv").read_bytes(),
            )
            self.assertEqual(
                len(pd.read_csv(outputs[0] / "queue_events.csv")), 50
            )
            self.assertTrue(
                any("truncated" in warning for warning in evidence["warnings"])
            )

    def test_queue_simulation_records_warmup_and_convergence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "warmup.json"
            input_path.write_text(
                json.dumps(
                    {
                        "model": "M/M/1",
                        "arrival_rate": 0.5,
                        "service_rate": 1.0,
                        "arrival_rate_source": "warmup test fixture",
                        "service_rate_source": "warmup test fixture",
                        "time_unit": "minute",
                        "simulation": {
                            "customers": 2000,
                            "warmup_customers": 0,
                            "replications": 3,
                            "seed": 8,
                            "convergence_points": 6,
                            "event_output_limit": 0,
                        },
                    }
                ),
                encoding="utf-8",
            )
            output = root / "output"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(QUEUE_SCRIPT),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            evidence = json.loads(
                (output / "run.json").read_text(encoding="utf-8")
            )
            self.assertTrue(
                any("warmup_customers is zero" in warning for warning in evidence["warnings"])
            )
            self.assertEqual(len(pd.read_csv(output / "queue_events.csv")), 0)
            warmup = pd.read_csv(output / "warmup_comparison.csv")
            self.assertEqual(warmup["warmup_customers"].tolist(), [0, 0])
            convergence = pd.read_csv(output / "convergence.csv")
            self.assertEqual(convergence.iloc[-1]["customers"], 2000)
            self.assertGreater(len(convergence), 2)

    def test_queue_simulation_rejects_unstable_or_unsupported_models(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = {
                "model": "M/M/1",
                "arrival_rate": 0.8,
                "service_rate": 1.0,
                "arrival_rate_source": "validation fixture",
                "service_rate_source": "validation fixture",
                "time_unit": "hour",
            }
            cases = [
                ({**base, "arrival_rate": 1.0}, "arrival_rate < service_rate"),
                ({**base, "model": "M/M/2"}, "exactly M/M/1"),
                ({**base, "discipline": "priority"}, "only FCFS"),
                ({**base, "capacity": 20}, "infinite system capacity"),
                ({**base, "arrival_rate_source": ""}, "non-empty string"),
                (
                    {
                        **base,
                        "simulation": {"replications": 2},
                    },
                    "replications",
                ),
            ]
            for index, (problem, expected) in enumerate(cases):
                input_path = root / f"bad-{index}.json"
                input_path.write_text(json.dumps(problem), encoding="utf-8")
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(QUEUE_SCRIPT),
                        "--input",
                        str(input_path),
                        "--output",
                        str(root / f"out-{index}"),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 1)
                self.assertIn(expected, completed.stderr)

    def test_nonlinear_optimization_matches_analytic_solution_and_repeats(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "quadratic.json"
            input_path.write_text(
                json.dumps(
                    {
                        "sense": "minimize",
                        "variables": [
                            {
                                "name": "x",
                                "lower": -5,
                                "upper": 5,
                                "unit": "m",
                                "source": "analytic benchmark domain",
                            },
                            {
                                "name": "y",
                                "lower": -5,
                                "upper": 5,
                                "unit": "m",
                                "source": "analytic benchmark domain",
                            },
                        ],
                        "objective": {
                            "expression": "(x - 1) ** 2 + (y - 2) ** 2",
                            "unit": "m^2",
                            "source": "convex quadratic benchmark",
                        },
                        "constraints": [
                            {
                                "name": "minimum_total",
                                "expression": "x + y",
                                "sense": ">=",
                                "rhs": 2.5,
                                "unit": "m",
                                "source": "analytic benchmark constraint",
                            }
                        ],
                        "initial_solution": [0, 2.5],
                        "baseline_solution": [0, 2.5],
                        "solver": {
                            "starts": 10,
                            "seed": 20260816,
                            "objective_tolerance": 1e-6,
                        },
                        "analytical_reference": {
                            "solution": [1, 2],
                            "objective": 0,
                            "tolerance": 1e-5,
                            "source": "complete-the-square derivation",
                        },
                    }
                ),
                encoding="utf-8",
            )
            outputs = [root / "run-a", root / "run-b"]
            for output in outputs:
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(NONLINEAR_SCRIPT),
                        "--input",
                        str(input_path),
                        "--output",
                        str(output),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
            evidence = json.loads(
                (outputs[0] / "run.json").read_text(encoding="utf-8")
            )
            self.assertTrue(evidence["success"])
            self.assertTrue(evidence["analytical_reference"]["passed"])
            self.assertGreater(evidence["successful_feasible_starts"], 1)
            self.assertEqual(
                evidence["successful_feasible_starts"],
                evidence["near_best_starts"],
            )
            self.assertGreater(evidence["baseline"]["objective_improvement"], 1.2)
            self.assertLess(evidence["maximum_constraint_violation"], 1e-7)
            self.assertEqual(
                (outputs[0] / "multistart.csv").read_bytes(),
                (outputs[1] / "multistart.csv").read_bytes(),
            )

    def test_nonlinear_optimization_records_no_feasible_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "infeasible.json"
            input_path.write_text(
                json.dumps(
                    {
                        "variables": [
                            {
                                "name": "x",
                                "lower": 0,
                                "upper": 1,
                                "unit": "unit",
                                "source": "infeasible fixture",
                            }
                        ],
                        "objective": {
                            "expression": "x ** 2",
                            "unit": "unit^2",
                            "source": "infeasible fixture",
                        },
                        "constraints": [
                            {
                                "name": "impossible",
                                "expression": "x",
                                "sense": ">=",
                                "rhs": 2,
                                "unit": "unit",
                                "source": "infeasible fixture",
                            }
                        ],
                        "solver": {"starts": 3, "seed": 4},
                    }
                ),
                encoding="utf-8",
            )
            output = root / "output"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(NONLINEAR_SCRIPT),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 2)
            evidence = json.loads((output / "run.json").read_text(encoding="utf-8"))
            self.assertFalse(evidence["success"])
            self.assertEqual(evidence["successful_feasible_starts"], 0)
            self.assertEqual(len(pd.read_csv(output / "solution.csv")), 0)

    def test_nonlinear_optimization_rejects_unsafe_or_unsupported_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = {
                "variables": [
                    {
                        "name": "x",
                        "lower": 0,
                        "upper": 2,
                        "unit": "unit",
                        "source": "validation fixture",
                    }
                ],
                "objective": {
                    "expression": "sqrt(x)",
                    "unit": "unit",
                    "source": "validation fixture",
                },
            }
            cases = [
                (
                    {
                        **base,
                        "objective": {
                            **base["objective"],
                            "expression": "__import__('os').getcwd()",
                        },
                    },
                    "forbidden function call",
                ),
                (
                    {
                        **base,
                        "variables": [{**base["variables"][0], "type": "integer"}],
                    },
                    "continuous variables only",
                ),
                ({**base, "objectives": []}, "multiple objectives"),
                (
                    {
                        **base,
                        "objective": {**base["objective"], "expression": "sin + x"},
                    },
                    "unknown name: sin",
                ),
                (
                    {
                        **base,
                        "variables": [{**base["variables"][0], "source": ""}],
                    },
                    "source must be a non-empty string",
                ),
            ]
            for index, (problem, expected) in enumerate(cases):
                input_path = root / f"bad-{index}.json"
                input_path.write_text(json.dumps(problem), encoding="utf-8")
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(NONLINEAR_SCRIPT),
                        "--input",
                        str(input_path),
                        "--output",
                        str(root / f"out-{index}"),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 1)
                self.assertIn(expected, completed.stderr)

    def test_pca_selects_low_rank_structure_and_is_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "rank-two.csv"
            rows = []
            for index in range(120):
                latent_a = (index - 59.5) / 12
                latent_b = ((index * 37) % 127 - 63) / 15
                rows.append(
                    {
                        "id": f"sample-{index:03d}",
                        "x1": latent_a,
                        "x2": 2 * latent_a + 0.3 * latent_b,
                        "x3": latent_b,
                        "x4": latent_a - latent_b,
                    }
                )
            pd.DataFrame(rows).to_csv(input_path, index=False)
            outputs = [root / "run-a", root / "run-b"]
            for output in outputs:
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(PCA_SCRIPT),
                        "--input",
                        str(input_path),
                        "--output",
                        str(output),
                        "--features",
                        "x1,x2,x3,x4",
                        "--id-column",
                        "id",
                        "--variance-threshold",
                        "0.95",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
            evidence = json.loads(
                (outputs[0] / "run.json").read_text(encoding="utf-8")
            )
            self.assertEqual(evidence["retained_component_count"], 2)
            self.assertTrue(evidence["threshold_achieved"])
            self.assertGreater(evidence["retained_explained_variance_ratio"], 0.999999)
            self.assertGreater(evidence["reconstruction_error_reduction"], 0.999999)
            explained = pd.read_csv(outputs[0] / "explained_variance.csv")
            self.assertAlmostEqual(explained["explained_variance_ratio"].sum(), 1.0)
            self.assertEqual(explained["retained"].tolist(), [True, True, False, False])
            loadings = pd.read_csv(outputs[0] / "loadings.csv")
            self.assertTrue(np.isfinite(loadings["correlation_loading"]).all())
            for _, component in loadings.groupby("component", sort=False):
                anchor = component.loc[
                    component["eigenvector_coefficient"].abs().idxmax()
                ]
                self.assertGreaterEqual(anchor["eigenvector_coefficient"], 0)
            reconstructed = pd.read_csv(outputs[0] / "reconstructed_data.csv")
            source = pd.read_csv(input_path)
            for feature in ("x1", "x2", "x3", "x4"):
                self.assertLess(
                    (source[feature] - reconstructed[f"{feature}_reconstructed"]).abs().max(),
                    1e-10,
                )
            self.assertEqual(
                (outputs[0] / "scores.csv").read_bytes(),
                (outputs[1] / "scores.csv").read_bytes(),
            )
            self.assertEqual(
                (outputs[0] / "loadings.csv").read_bytes(),
                (outputs[1] / "loadings.csv").read_bytes(),
            )

    def test_pca_records_scale_risk_and_unmet_component_cap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "scale-risk.csv"
            rows = []
            for left in range(10):
                for right in range(10):
                    rows.append(
                        {
                            "id": f"{left}-{right}",
                            "small": left / 10,
                            "large": right * 100000,
                        }
                    )
            pd.DataFrame(rows).to_csv(input_path, index=False)
            output = root / "output"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(PCA_SCRIPT),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output),
                    "--features",
                    "small,large",
                    "--id-column",
                    "id",
                    "--variance-threshold",
                    "0.9",
                    "--max-components",
                    "1",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            evidence = json.loads((output / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(evidence["threshold_component_count"], 2)
            self.assertEqual(evidence["retained_component_count"], 1)
            self.assertFalse(evidence["threshold_achieved"])
            self.assertIn(
                "max_components prevents the retained components from reaching the declared variance threshold",
                evidence["warnings"],
            )
            self.assertIn(
                "one feature contributes over 90% of raw-scale variance; standardized and unstandardized PCA would answer materially different questions",
                evidence["warnings"],
            )
            preprocessing = pd.read_csv(output / "preprocessing.csv")
            self.assertGreater(preprocessing["original_scale_variance_share"].max(), 0.999)
            self.assertEqual(
                preprocessing["standardized_scale_variance_share"].tolist(),
                [0.5, 0.5],
            )

    def test_pca_rejects_incomplete_constant_or_ambiguous_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            valid = [
                {"id": f"r-{index}", "x": index, "y": index % 4}
                for index in range(12)
            ]
            cases = [
                (
                    [{**row, "x": None if index == 0 else row["x"]} for index, row in enumerate(valid)],
                    ["--features", "x,y", "--id-column", "id"],
                    "complete numeric values",
                ),
                (
                    [{**row, "y": 1} for row in valid],
                    ["--features", "x,y", "--id-column", "id"],
                    "constant feature columns",
                ),
                (
                    [{**row, "id": "duplicate"} for row in valid],
                    ["--features", "x,y", "--id-column", "id"],
                    "unique values",
                ),
                (
                    valid,
                    ["--features", "x", "--id-column", "id"],
                    "at least two feature columns",
                ),
                (
                    valid,
                    ["--features", "x,y", "--id-column", "id", "--variance-threshold", "1.1"],
                    "variance_threshold must be finite",
                ),
                (
                    valid,
                    ["--features", "x,y", "--id-column", "id", "--max-components", "3"],
                    "max_components cannot exceed",
                ),
            ]
            for index, (rows, arguments, expected) in enumerate(cases):
                input_path = root / f"bad-{index}.csv"
                pd.DataFrame(rows).to_csv(input_path, index=False)
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(PCA_SCRIPT),
                        "--input",
                        str(input_path),
                        "--output",
                        str(root / f"out-{index}"),
                        *arguments,
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 1)
                self.assertIn(expected, completed.stderr)

    def test_clustering_selects_three_stable_clusters_and_is_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "three-clusters.csv"
            rows = ["sample,x1,x2"]
            centers = [(-5.0, -4.0), (0.0, 5.0), (6.0, -2.0)]
            for cluster, (center_x, center_y) in enumerate(centers):
                for index in range(30):
                    offset_x = ((index % 5) - 2) * 0.08
                    offset_y = ((index // 5) - 2.5) * 0.06
                    rows.append(
                        f"c{cluster}-{index},{center_x + offset_x:.4f},{center_y + offset_y:.4f}"
                    )
            input_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
            outputs = [root / "run-a", root / "run-b"]
            for output in outputs:
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(CLUSTERING_SCRIPT),
                        "--input",
                        str(input_path),
                        "--output",
                        str(output),
                        "--features",
                        "x1,x2",
                        "--id-column",
                        "sample",
                        "--k-min",
                        "2",
                        "--k-max",
                        "5",
                        "--repeats",
                        "6",
                        "--seed",
                        "20260816",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
            evidence = json.loads(
                (outputs[0] / "run.json").read_text(encoding="utf-8")
            )
            self.assertEqual(evidence["selected_k"], 3)
            self.assertEqual(evidence["cluster_sizes"], {"0": 30, "1": 30, "2": 30})
            self.assertGreater(evidence["selected_candidate"]["mean_silhouette"], 0.9)
            self.assertEqual(evidence["selected_candidate"]["mean_pairwise_ari"], 1.0)
            self.assertGreater(evidence["inertia_reduction_from_single_cluster"], 0.99)
            self.assertEqual(len(pd.read_csv(outputs[0] / "candidate_k.csv")), 4)
            self.assertEqual(len(pd.read_csv(outputs[0] / "stability_runs.csv")), 24)
            stability_pairs = pd.read_csv(outputs[0] / "stability_pairs.csv")
            self.assertEqual(len(stability_pairs), 60)
            self.assertTrue(
                (stability_pairs.loc[stability_pairs["k"] == 3, "adjusted_rand_index"] == 1).all()
            )
            centers_frame = pd.read_csv(outputs[0] / "cluster_centers.csv")
            self.assertEqual(centers_frame["cluster"].tolist(), [0, 1, 2])
            self.assertEqual(centers_frame["size"].tolist(), [30, 30, 30])
            self.assertTrue(centers_frame["x1_center"].is_monotonic_increasing)
            self.assertEqual(
                (outputs[0] / "cluster_assignments.csv").read_bytes(),
                (outputs[1] / "cluster_assignments.csv").read_bytes(),
            )
            self.assertEqual(
                (outputs[0] / "candidate_k.csv").read_bytes(),
                (outputs[1] / "candidate_k.csv").read_bytes(),
            )

    def test_clustering_records_boundary_warning_and_standardization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "two-clusters.csv"
            rows = [
                {
                    "id": f"a-{index}",
                    "small": index / 100,
                    "large": 100000 + index,
                }
                for index in range(15)
            ] + [
                {
                    "id": f"b-{index}",
                    "small": 10 + index / 100,
                    "large": 200000 + index,
                }
                for index in range(15)
            ]
            pd.DataFrame(rows).to_csv(input_path, index=False)
            output = root / "output"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(CLUSTERING_SCRIPT),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output),
                    "--features",
                    "small,large",
                    "--id-column",
                    "id",
                    "--k-min",
                    "2",
                    "--k-max",
                    "3",
                    "--repeats",
                    "4",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            evidence = json.loads((output / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(evidence["selected_k"], 2)
            self.assertIn(
                "the selected k is on the lower candidate-range boundary; compare a smaller k when possible and retain the one-cluster no-segmentation baseline",
                evidence["warnings"],
            )
            preprocessing = pd.read_csv(output / "preprocessing.csv")
            self.assertEqual(preprocessing["feature"].tolist(), ["small", "large"])
            self.assertTrue((preprocessing["scale_standard_deviation"] > 0).all())
            assignments = pd.read_csv(output / "cluster_assignments.csv")
            self.assertEqual(assignments["id"].nunique(), 30)
            self.assertEqual(set(assignments["cluster"]), {0, 1})

    def test_clustering_rejects_incomplete_constant_or_ambiguous_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            valid = [
                {"id": f"r-{index}", "x": index, "y": index % 4}
                for index in range(12)
            ]
            cases = [
                (
                    [{**row, "x": None if index == 0 else row["x"]} for index, row in enumerate(valid)],
                    ["--features", "x,y", "--id-column", "id", "--k-max", "3"],
                    "complete numeric values",
                ),
                (
                    [{**row, "y": 1} for row in valid],
                    ["--features", "x,y", "--id-column", "id", "--k-max", "3"],
                    "constant feature columns",
                ),
                (
                    [{**row, "id": "duplicate"} for row in valid],
                    ["--features", "x,y", "--id-column", "id", "--k-max", "3"],
                    "unique values",
                ),
                (
                    valid,
                    ["--features", "x,y", "--id-column", "id", "--k-min", "4", "--k-max", "3"],
                    "k_min cannot exceed k_max",
                ),
                (
                    valid,
                    ["--features", "x,y", "--id-column", "id", "--k-max", "3", "--repeats", "3", "--seed", str(2**32 - 2)],
                    "seed plus repeats exceeds",
                ),
                (
                    valid[:8],
                    ["--features", "x,y", "--id-column", "id", "--k-max", "3"],
                    "at least three rows per candidate cluster",
                ),
                (
                    valid,
                    ["--features", "x,y", "--id-column", "id", "--k-max", "51"],
                    "k_max cannot exceed 50",
                ),
            ]
            for index, (rows, arguments, expected) in enumerate(cases):
                input_path = root / f"bad-{index}.csv"
                pd.DataFrame(rows).to_csv(input_path, index=False)
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(CLUSTERING_SCRIPT),
                        "--input",
                        str(input_path),
                        "--output",
                        str(root / f"out-{index}"),
                        *arguments,
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 1)
                self.assertIn(expected, completed.stderr)

    def test_classification_is_reproducible_and_beats_prior_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "imbalanced.csv"
            rows = ["x1,x2,label"]
            for index in range(160):
                rows.append(
                    f"{(index % 17) / 20:.4f},{(index % 13) / 20:.4f},negative"
                )
            for index in range(40):
                rows.append(
                    f"{2 + (index % 11) / 20:.4f},{2 + (index % 7) / 20:.4f},positive"
                )
            input_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
            outputs = [root / "run-a", root / "run-b"]
            for output in outputs:
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(CLASSIFICATION_SCRIPT),
                        "--input",
                        str(input_path),
                        "--output",
                        str(output),
                        "--target",
                        "label",
                        "--features",
                        "x1,x2",
                        "--positive-label",
                        "positive",
                        "--class-weight",
                        "balanced",
                        "--threshold-strategy",
                        "f1",
                        "--seed",
                        "20260816",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
            evidence = json.loads(
                (outputs[0] / "run.json").read_text(encoding="utf-8")
            )
            self.assertEqual(evidence["full_class_counts"], {"0": 160, "1": 40})
            self.assertEqual(
                evidence["threshold_evidence"]["source"],
                "training_only_validation_partition",
            )
            self.assertEqual(evidence["calibration"], "sigmoid")
            self.assertEqual(
                evidence["probability_calibration_evidence"]["calibration_method"],
                "sigmoid_on_training_only_validation_partition",
            )
            self.assertTrue(evidence["beats_prior_baseline_balanced_accuracy"] )
            self.assertTrue(evidence["beats_prior_baseline_log_loss"] )
            self.assertGreater(evidence["model_metrics"]["roc_auc"], 0.99)
            self.assertGreater(evidence["model_metrics"]["average_precision"], 0.99)
            self.assertGreater(evidence["model_metrics"]["recall_sensitivity"], 0.9)
            self.assertEqual(len(pd.read_csv(outputs[0] / "threshold_selection.csv")), 181)
            self.assertEqual(
                (outputs[0] / "predictions.csv").read_bytes(),
                (outputs[1] / "predictions.csv").read_bytes(),
            )
            self.assertEqual(
                (outputs[0] / "threshold_selection.csv").read_bytes(),
                (outputs[1] / "threshold_selection.csv").read_bytes(),
            )

    def test_classification_group_split_prevents_outer_and_threshold_leakage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "groups.csv"
            rows = ["group,x1,x2,label"]
            for group in range(24):
                for repeat in range(2):
                    rows.append(
                        f"g{group},{group / 100 + repeat / 1000:.4f},0.{repeat + 1},no"
                    )
                    rows.append(
                        f"g{group},{2 + group / 100 + repeat / 1000:.4f},2.{repeat + 1},yes"
                    )
            input_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
            output = root / "output"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(CLASSIFICATION_SCRIPT),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output),
                    "--target",
                    "label",
                    "--features",
                    "x1,x2",
                    "--positive-label",
                    "yes",
                    "--split",
                    "group",
                    "--group-column",
                    "group",
                    "--threshold-strategy",
                    "balanced_accuracy",
                    "--seed",
                    "99",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            evidence = json.loads((output / "run.json").read_text(encoding="utf-8"))
            outer = evidence["outer_split_evidence"]
            inner = evidence["threshold_evidence"]["split_evidence"]
            self.assertEqual(outer["group_overlap"], [])
            self.assertEqual(inner["group_overlap"], [])
            self.assertFalse(set(outer["train_groups"]) & set(outer["test_groups"]))
            self.assertFalse(set(inner["train_groups"]) & set(inner["test_groups"]))
            predictions = pd.read_csv(output / "predictions.csv")
            source = pd.read_csv(input_path)
            test_groups = set(source.iloc[predictions["row"]]["group"] )
            self.assertEqual(test_groups, set(outer["test_groups"]))

    def test_classification_rejects_unsupported_or_leaky_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base_rows = [
                {"x": index, "label": "yes" if index >= 10 else "no"}
                for index in range(20)
            ]
            cases = [
                (
                    [
                        {"x": index, "label": ("a" if index < 8 else "b" if index < 16 else "c")}
                        for index in range(24)
                    ],
                    ["--target", "label", "--features", "x", "--positive-label", "c"],
                    "exactly two classes",
                ),
                (
                    base_rows,
                    ["--target", "label", "--features", "x,label", "--positive-label", "yes"],
                    "target cannot also be a feature",
                ),
                (
                    [{"x": index, "label": "yes" if index >= 12 else "no"} for index in range(16)],
                    ["--target", "label", "--features", "x", "--positive-label", "yes"],
                    "at least eight rows",
                ),
                (
                    base_rows,
                    ["--target", "label", "--features", "x", "--positive-label", "missing"],
                    "positive_label must match",
                ),
            ]
            for index, (rows, arguments, expected) in enumerate(cases):
                input_path = root / f"bad-{index}.csv"
                pd.DataFrame(rows).to_csv(input_path, index=False)
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(CLASSIFICATION_SCRIPT),
                        "--input",
                        str(input_path),
                        "--output",
                        str(root / f"out-{index}"),
                        *arguments,
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 1)
                self.assertIn(expected, completed.stderr)

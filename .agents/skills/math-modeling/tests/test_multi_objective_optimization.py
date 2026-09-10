from __future__ import annotations

import csv
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "model_baselines" / "multi_objective_optimization.py"


def load_module():
    baseline_dir = SCRIPT.parent
    sys.path.insert(0, str(baseline_dir))
    try:
        spec = importlib.util.spec_from_file_location("multi_objective_optimization", SCRIPT)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load {SCRIPT}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(baseline_dir))


MODULE = load_module()


def controlled_problem() -> dict:
    return {
        "variables": [
            {"name": "x", "type": "continuous", "lower": 0, "upper": 6, "unit": "allocation units", "source": "controlled validation design"},
            {"name": "y", "type": "continuous", "lower": 0, "upper": 4, "unit": "allocation units", "source": "controlled validation design"},
        ],
        "objectives": [
            {"name": "cost", "sense": "minimize", "expression": "100*x + 300*y", "unit": "CNY", "source": "controlled validation coefficients"},
            {"name": "service_loss", "sense": "minimize", "expression": "(6-x)**2 + 4*(4-y)**2", "unit": "loss points", "source": "controlled validation loss definition"},
        ],
        "constraints": [
            {"name": "minimum_service", "sense": ">=", "expression": "x + 2*y", "rhs": 2, "unit": "service units", "source": "controlled validation requirement"},
            {"name": "capacity", "sense": "<=", "expression": "x + y", "rhs": 7, "unit": "allocation units", "source": "controlled validation capacity"},
        ],
        "solver": {
            "algorithm": "NSGA-II",
            "population_size": 60,
            "generations": 80,
            "seeds": [11, 29],
            "feasibility_tolerance": 1e-7,
            "duplicate_tolerance": 1e-8,
            "stability_thresholds": {
                "max_normalized_igd": 0.08,
                "min_hypervolume_ratio": 0.88,
                "max_hypervolume_ratio_range": 0.08,
                "max_endpoint_gap": 0.15,
            },
        },
        "decision": {
            "weights": [0.5, 0.5],
            "sensitivity_weights": [[0.25, 0.75], [0.75, 0.25]],
            "material_change_threshold": 0.15,
        },
        "reference_front": {
            "method": "dense_grid",
            "points_per_variable": 61,
            "source": "independent deterministic grid over declared bounds",
        },
    }


class MultiObjectiveOptimizationTests(unittest.TestCase):
    def run_cli(self, problem: dict, root: Path, output_name: str = "out") -> subprocess.CompletedProcess[str]:
        input_path = root / f"{output_name}.json"
        input_path.write_text(json.dumps(problem, ensure_ascii=False), encoding="utf-8")
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--input", str(input_path), "--output", str(root / output_name)],
            capture_output=True,
            text=True,
            check=False,
            env=environment,
        )

    def test_constrained_example_is_reproducible_feasible_and_nondominated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = self.run_cli(controlled_problem(), root, "first")
            second = self.run_cli(controlled_problem(), root, "second")
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            first_dir, second_dir = root / "first", root / "second"
            expected = {
                "compromise_sensitivity.csv", "constraint_check.csv", "pareto_front.png",
                "pareto_solutions.csv", "reference_front.csv", "run.json",
                "seed_fronts.csv", "seed_stability.csv",
            }
            self.assertEqual({path.name for path in first_dir.iterdir()}, expected)
            for name in expected - {"run.json", "pareto_front.png"}:
                self.assertEqual((first_dir / name).read_bytes(), (second_dir / name).read_bytes())

            evidence = json.loads((first_dir / "run.json").read_text(encoding="utf-8"))
            self.assertTrue(evidence["success"])
            self.assertTrue(evidence["seed_stability"]["passed"])
            self.assertTrue(evidence["merged_front"]["independently_feasible"])
            self.assertTrue(evidence["merged_front"]["nondominance_recomputed"])
            self.assertEqual(evidence["reference_front"]["method"], "dense_grid")
            self.assertGreater(evidence["objectives"][0]["normalization_range"], 100)
            self.assertGreater(evidence["objectives"][1]["normalization_range"], 1)
            self.assertTrue(evidence["compromise"]["preference_conditioned"])

            with (first_dir / "pareto_solutions.csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            solutions = np.asarray([[float(row["x"]), float(row["y"])] for row in rows])
            objectives = np.asarray([[float(row["cost"]), float(row["service_loss"])] for row in rows])
            self.assertTrue(np.all(solutions >= -1e-7))
            self.assertTrue(np.all(solutions[:, 0] <= 6 + 1e-7))
            self.assertTrue(np.all(solutions[:, 1] <= 4 + 1e-7))
            self.assertTrue(np.all(solutions[:, 0] + 2 * solutions[:, 1] >= 2 - 1e-7))
            self.assertTrue(np.all(solutions[:, 0] + solutions[:, 1] <= 7 + 1e-7))
            np.testing.assert_allclose(objectives[:, 0], 100 * solutions[:, 0] + 300 * solutions[:, 1])
            np.testing.assert_allclose(objectives[:, 1], (6 - solutions[:, 0]) ** 2 + 4 * (4 - solutions[:, 1]) ** 2)
            for index, current in enumerate(objectives):
                others = np.delete(objectives, index, axis=0)
                dominated = np.any(np.all(others <= current + 1e-8, axis=1) & np.any(others < current - 1e-8, axis=1))
                self.assertFalse(dominated)

    def test_invalid_contracts_fail_before_creating_output(self) -> None:
        cases = []
        unsafe = controlled_problem()
        unsafe["objectives"][0]["expression"] = "__import__('os').getcwd()"
        cases.append((unsafe, "forbidden function call"))
        missing_unit = controlled_problem()
        missing_unit["variables"][0]["unit"] = ""
        cases.append((missing_unit, "unit must be a non-empty string"))
        bad_constraint = controlled_problem()
        bad_constraint["constraints"][0]["sense"] = "<"
        cases.append((bad_constraint, "sense must be <=, >=, or ="))
        duplicate_seed = controlled_problem()
        duplicate_seed["solver"]["seeds"] = [11, 11]
        cases.append((duplicate_seed, "must not contain duplicates"))
        bad_weights = controlled_problem()
        bad_weights["decision"]["weights"] = [0.2, 0.2]
        cases.append((bad_weights, "must sum to one"))
        missing_reference = controlled_problem()
        missing_reference["reference_front"] = {"method": "external_csv", "path": "missing.csv", "sha256": "a" * 64, "source": "test"}
        cases.append((missing_reference, "reference front CSV not found"))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, (problem, expected) in enumerate(cases):
                with self.subTest(expected=expected):
                    completed = self.run_cli(problem, root, f"bad-{index}")
                    self.assertEqual(completed.returncode, 1)
                    self.assertIn(expected, completed.stderr)
                    self.assertFalse((root / f"bad-{index}").exists())

    def test_zero_reference_range_and_stability_failure_are_honest(self) -> None:
        constant = controlled_problem()
        constant["objectives"][1]["expression"] = "5"
        strict = controlled_problem()
        strict["solver"]["stability_thresholds"]["max_normalized_igd"] = 1e-12
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            zero_range = self.run_cli(constant, root, "constant")
            self.assertEqual(zero_range.returncode, 1)
            self.assertIn("zero-range objective", zero_range.stderr)
            self.assertFalse((root / "constant").exists())

            failed_stability = self.run_cli(strict, root, "strict")
            self.assertEqual(failed_stability.returncode, 2)
            evidence = json.loads((root / "strict" / "run.json").read_text(encoding="utf-8"))
            self.assertFalse(evidence["success"])
            self.assertFalse(evidence["seed_stability"]["passed"])
            self.assertIn("declared Pareto stability thresholds were not met", failed_stability.stderr)


if __name__ == "__main__":
    unittest.main()

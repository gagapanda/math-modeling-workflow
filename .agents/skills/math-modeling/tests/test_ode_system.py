from __future__ import annotations

import csv
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "model_baselines" / "ode_system.py"


def exchange_problem() -> dict:
    return {
        "time": {"start": 0, "end": 12, "evaluation_points": 121, "unit": "hour"},
        "states": [
            {"name": "x", "initial": 80, "unit": "kg", "source": "controlled initial condition"},
            {"name": "y", "initial": 20, "unit": "kg", "source": "controlled initial condition"},
        ],
        "parameters": [{"name": "k", "value": 0.3, "unit": "1/hour", "source": "controlled exchange rate"}],
        "equations": [
            {"state": "x", "expression": "-k*x + k*y", "unit": "kg/hour", "source": "conservative exchange balance"},
            {"state": "y", "expression": "k*x - k*y", "unit": "kg/hour", "source": "conservative exchange balance"},
        ],
        "solver": {"method": "DOP853", "rtol": 1e-8, "atol": 1e-10, "max_step": 0.25},
        "invariants": [{"name": "total_mass", "expression": "x + y", "expected": "initial", "unit": "kg", "source": "sum of exchange balances", "absolute_tolerance": 1e-8}],
        "reference_solution": {
            "expressions": [
                {"state": "x", "expression": "(initial_x + initial_y)/2 + (initial_x - initial_y)/2*exp(-2*k*t)"},
                {"state": "y", "expression": "(initial_x + initial_y)/2 - (initial_x - initial_y)/2*exp(-2*k*t)"},
            ],
            "source": "closed-form diagonalization of the controlled system",
            "absolute_tolerance": 1e-7, "relative_tolerance": 1e-8,
        },
        "sensitivity": {"tolerance_factor": 0.1, "max_step_factor": 0.5, "endpoint_absolute_tolerance": 1e-8, "trajectory_absolute_tolerance": 1e-8},
    }


def decay_problem() -> dict:
    problem = exchange_problem()
    problem["time"] = {"start": 0, "end": 5, "evaluation_points": 51, "unit": "day"}
    problem["states"] = [{"name": "amount", "initial": 10, "unit": "mg", "source": "controlled initial condition"}]
    problem["parameters"] = [{"name": "rate", "value": 0.4, "unit": "1/day", "source": "controlled decay rate"}]
    problem["equations"] = [{"state": "amount", "expression": "-rate*amount", "unit": "mg/day", "source": "first-order decay law"}]
    problem["invariants"] = []
    problem["reference_solution"] = {"expressions": [{"state": "amount", "expression": "initial_amount*exp(-rate*t)"}], "source": "closed-form exponential decay", "absolute_tolerance": 1e-7, "relative_tolerance": 1e-8}
    return problem


class OdeSystemTests(unittest.TestCase):
    def run_cli(self, problem: dict, root: Path, name: str) -> subprocess.CompletedProcess[str]:
        input_path = root / f"{name}.json"
        input_path.write_text(json.dumps(problem), encoding="utf-8")
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run([sys.executable, str(SCRIPT), "--input", str(input_path), "--output", str(root / name)], capture_output=True, text=True, check=False, env=environment)

    def test_exchange_system_matches_reference_conserves_and_is_repeatable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = self.run_cli(exchange_problem(), root, "first")
            second = self.run_cli(exchange_problem(), root, "second")
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            expected = {"trajectory.csv", "invariant_check.csv", "solver_sensitivity.csv", "reference_check.csv", "trajectory.png", "run.json"}
            self.assertEqual({path.name for path in root.joinpath("first").iterdir()}, expected)
            for name in expected - {"trajectory.png", "run.json"}:
                self.assertEqual((root / "first" / name).read_bytes(), (root / "second" / name).read_bytes())
            evidence = json.loads((root / "first" / "run.json").read_text(encoding="utf-8"))
            self.assertTrue(evidence["success"])
            self.assertTrue(evidence["sensitivity"]["passed"])
            self.assertTrue(evidence["reference_solution"]["passed"])
            self.assertLess(evidence["invariants"][0]["maximum_absolute_residual"], 1e-8)
            with (root / "first" / "trajectory.csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(float(rows[0]["time"]), 0.0)
            self.assertEqual(float(rows[-1]["time"]), 12.0)
            for row in rows:
                time = float(row["time"]); x = float(row["x"]); y = float(row["y"])
                self.assertAlmostEqual(x + y, 100.0, places=8)
                self.assertGreater(x, 0); self.assertGreater(y, 0)
                self.assertAlmostEqual(x, 50 + 30 * math.exp(-0.6 * time), delta=1e-7)
            self.assertLess(float(rows[-1]["x"]), float(rows[0]["x"]))
            self.assertGreater(float(rows[-1]["y"]), float(rows[0]["y"]))

    def test_scalar_decay_matches_closed_form(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            completed = self.run_cli(decay_problem(), root, "decay")
            self.assertEqual(completed.returncode, 0, completed.stderr)
            evidence = json.loads((root / "decay" / "run.json").read_text(encoding="utf-8"))
            self.assertTrue(evidence["reference_solution"]["passed"])
            self.assertEqual(evidence["invariants"], [])
            with (root / "decay" / "trajectory.csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertAlmostEqual(float(rows[-1]["amount"]), 10 * math.exp(-2), delta=1e-7)

    def test_invalid_contracts_fail_without_output(self) -> None:
        cases: list[tuple[dict, str]] = []
        unsafe = exchange_problem(); unsafe["equations"][0]["expression"] = "__import__('os').getcwd()"
        cases.append((unsafe, "forbidden function call"))
        unknown = exchange_problem(); unknown["equations"][0]["expression"] = "-missing*x"
        cases.append((unknown, "references unknown name"))
        missing_equation = exchange_problem(); missing_equation["equations"] = missing_equation["equations"][:1]
        cases.append((missing_equation, "exactly one equation per state"))
        missing_unit = exchange_problem(); missing_unit["states"][0]["unit"] = ""
        cases.append((missing_unit, "unit must be a non-empty string"))
        duplicate = exchange_problem(); duplicate["states"][1]["name"] = "x"
        cases.append((duplicate, "duplicate or reserved state name"))
        bad_method = exchange_problem(); bad_method["solver"]["method"] = "Euler"
        cases.append((bad_method, "solver.method must be one of"))
        bad_time = exchange_problem(); bad_time["time"]["end"] = 0
        cases.append((bad_time, "time.start must be less than time.end"))
        bad_tolerance = exchange_problem(); bad_tolerance["solver"]["rtol"] = 0
        cases.append((bad_tolerance, "solver.rtol must be positive"))
        bad_step = exchange_problem(); bad_step["solver"]["max_step"] = -1
        cases.append((bad_step, "solver.max_step must be positive"))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, (problem, message) in enumerate(cases):
                with self.subTest(message=message):
                    completed = self.run_cli(problem, root, f"bad-{index}")
                    self.assertEqual(completed.returncode, 1)
                    self.assertIn(message, completed.stderr)
                    self.assertFalse((root / f"bad-{index}").exists())

    def test_failed_validation_retains_structured_evidence(self) -> None:
        strict_reference = exchange_problem(); strict_reference["reference_solution"]["absolute_tolerance"] = 1e-16; strict_reference["reference_solution"]["relative_tolerance"] = 1e-16
        wrong_invariant = exchange_problem(); wrong_invariant["invariants"][0]["expected"] = 101
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reference = self.run_cli(strict_reference, root, "strict-reference")
            self.assertEqual(reference.returncode, 2)
            evidence = json.loads((root / "strict-reference" / "run.json").read_text(encoding="utf-8"))
            self.assertFalse(evidence["success"]); self.assertFalse(evidence["reference_solution"]["passed"])
            invariant = self.run_cli(wrong_invariant, root, "wrong-invariant")
            self.assertEqual(invariant.returncode, 2)
            evidence = json.loads((root / "wrong-invariant" / "run.json").read_text(encoding="utf-8"))
            self.assertFalse(evidence["invariants"][0]["passed"])

    def test_existing_output_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); output = root / "existing"; output.mkdir()
            marker = output / "marker.txt"; marker.write_text("keep", encoding="utf-8")
            completed = self.run_cli(exchange_problem(), root, "existing")
            self.assertEqual(completed.returncode, 1)
            self.assertIn("output directory already exists", completed.stderr)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()

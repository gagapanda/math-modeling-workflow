from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "model_baselines" / "curve_analysis.py"


def quadratic_data(path: Path, rows: int = 41) -> None:
    x = np.linspace(0.0, 10.0, rows)
    noise = 0.18 * np.sin(np.arange(rows) * 1.7)
    y = 3.0 + 1.2 * x + 0.75 * x**2 + noise
    pd.DataFrame({"distance": x, "response": y}).to_csv(path, index=False)


class CurveAnalysisTests(unittest.TestCase):
    def run_cli(
        self, input_path: Path, output: Path, *extra: str
    ) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            str(SCRIPT),
            "--input",
            str(input_path),
            "--output",
            str(output),
            "--x-column",
            "distance",
            "--y-column",
            "response",
            "--x-unit",
            "m",
            "--y-unit",
            "kg",
            "--source-note",
            "controlled quadratic observations",
            "--seed",
            "20260817",
            "--bootstrap-iterations",
            "300",
            *extra,
        ]
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            command, capture_output=True, text=True, check=False, env=environment
        )

    def test_quadratic_selection_intervals_and_repeatability(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "quadratic.csv"
            quadratic_data(input_path)
            outputs = [root / "one", root / "two"]
            completions = [self.run_cli(input_path, output) for output in outputs]
            for completion in completions:
                self.assertEqual(completion.returncode, 0, completion.stderr)
            expected = {
                "candidate_metrics.csv",
                "cross_validation_residuals.csv",
                "curve.csv",
                "test_predictions.csv",
                "model_parameters.csv",
                "fit_diagnostics.png",
                "run.json",
            }
            self.assertEqual({path.name for path in outputs[0].iterdir()}, expected)
            for name in expected - {"fit_diagnostics.png"}:
                self.assertEqual(
                    (outputs[0] / name).read_bytes(), (outputs[1] / name).read_bytes(), name
                )
            evidence = json.loads((outputs[0] / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(evidence["selection"]["selected_candidate"], "quadratic")
            self.assertTrue(evidence["split"]["all_test_points_within_development_range"])
            self.assertTrue(evidence["beats_linear_baseline_test_rmse"])
            self.assertLess(evidence["held_out_test_metrics"]["rmse"], 0.4)
            self.assertGreaterEqual(
                evidence["uncertainty"]["test_prediction_interval_empirical_coverage"],
                0.75,
            )
            self.assertTrue(evidence["uncertainty"]["parameter_intervals_available"])

    def test_outputs_are_internally_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "quadratic.csv"
            quadratic_data(input_path)
            output = root / "output"
            completion = self.run_cli(input_path, output)
            self.assertEqual(completion.returncode, 0, completion.stderr)
            curve = pd.read_csv(output / "curve.csv")
            test = pd.read_csv(output / "test_predictions.csv")
            parameters = pd.read_csv(output / "model_parameters.csv")
            candidates = pd.read_csv(output / "candidate_metrics.csv")
            self.assertEqual(len(curve), 201)
            self.assertTrue((curve["mean_lower"] <= curve["fitted"]).all())
            self.assertTrue((curve["fitted"] <= curve["mean_upper"]).all())
            self.assertTrue((curve["prediction_lower"] <= curve["mean_lower"]).all())
            self.assertTrue((curve["mean_upper"] <= curve["prediction_upper"]).all())
            self.assertTrue((test["prediction_lower"] <= test["prediction_upper"]).all())
            self.assertEqual(len(parameters), 3)
            self.assertEqual(int(candidates["selected"].sum()), 1)
            coefficients = parameters.sort_values("power")["estimate"].to_numpy()
            self.assertTrue(np.allclose(coefficients, [3.0, 1.2, 0.75], atol=0.15))

    def test_pchip_candidate_runs_without_parameter_claims(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "wavy.csv"
            x = np.linspace(0, 8, 45)
            y = 2 + np.sin(1.4 * x) + 0.02 * np.cos(np.arange(len(x)) * 1.3)
            pd.DataFrame({"distance": x, "response": y}).to_csv(input_path, index=False)
            output = root / "output"
            completion = self.run_cli(
                input_path, output, "--candidates", "linear,pchip"
            )
            self.assertEqual(completion.returncode, 0, completion.stderr)
            evidence = json.loads((output / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(evidence["selection"]["selected_candidate"], "pchip")
            self.assertFalse(evidence["uncertainty"]["parameter_intervals_available"])
            with (output / "model_parameters.csv").open(encoding="utf-8", newline="") as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 0)

    def test_invalid_contracts_fail_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            good = root / "good.csv"
            quadratic_data(good)
            duplicate = root / "duplicate.csv"
            frame = pd.read_csv(good)
            frame.loc[1, "distance"] = frame.loc[0, "distance"]
            frame.to_csv(duplicate, index=False)
            cases = [
                (duplicate, ["--candidates", "linear,quadratic"], "x values must be unique"),
                (good, ["--candidates", "quadratic"], "must include the transparent linear baseline"),
                (good, ["--confidence-level", "1"], "confidence level must be"),
                (good, ["--bootstrap-iterations", "199"], "bootstrap iterations must be"),
                (good, ["--x-unit", ""], "x unit must be a non-empty string"),
            ]
            for index, (input_path, extra, message) in enumerate(cases):
                with self.subTest(message=message):
                    output = root / f"bad-{index}"
                    completion = self.run_cli(input_path, output, *extra)
                    self.assertEqual(completion.returncode, 1)
                    self.assertIn(message, completion.stderr)
                    self.assertFalse(output.exists())

    def test_existing_output_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "quadratic.csv"
            quadratic_data(input_path)
            output = root / "existing"
            output.mkdir()
            marker = output / "marker.txt"
            marker.write_text("keep", encoding="utf-8")
            completion = self.run_cli(input_path, output)
            self.assertEqual(completion.returncode, 1)
            self.assertIn("output directory already exists", completion.stderr)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()

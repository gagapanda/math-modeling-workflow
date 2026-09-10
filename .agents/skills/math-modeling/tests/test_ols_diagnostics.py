from __future__ import annotations

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
SCRIPT = SKILL_DIR / "scripts" / "model_baselines" / "ols_diagnostics.py"


def run_script(*arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        timeout=60,
    )


class OlsDiagnosticsTests(unittest.TestCase):
    def common_arguments(self, source: Path, output: Path) -> list[str]:
        return [
            "--input", str(source), "--output", str(output),
            "--target", "y", "--features", "x1,x2",
            "--target-unit", "kg", "--feature-units", "m,s",
            "--source-note", "controlled OLS diagnostic case",
        ]

    def write_heteroskedastic(self, path: Path, *, influential: bool = False) -> None:
        random = np.random.default_rng(20260817)
        x1 = np.linspace(0.2, 12.0, 160)
        x2 = random.normal(0.0, 1.0, len(x1))
        errors = random.normal(0.0, 0.12 + 0.12 * x1, len(x1))
        y = 2.5 + 1.4 * x1 - 0.8 * x2 + errors
        if influential:
            x1[-1] = 30.0
            x2[-1] = 8.0
            y[-1] = -25.0
        pd.DataFrame({"x1": x1, "x2": x2, "y": y}).to_csv(path, index=False)

    def test_hc3_outputs_and_heteroskedasticity_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "data.csv"
            output = root / "output"
            self.write_heteroskedastic(source)
            completed = run_script(*self.common_arguments(source, output), "--covariance", "hc3")
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(len(list(output.iterdir())), 8)
            evidence = json.loads((output / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(evidence["covariance"], "hc3")
            self.assertTrue(evidence["diagnostic_summary"]["breusch_pagan_flagged"])
            self.assertGreater(evidence["model_effects"]["r_squared"], 0.9)
            coefficients = pd.read_csv(output / "coefficients.csv").set_index("term")
            self.assertAlmostEqual(coefficients.loc["x1", "estimate"], 1.4, delta=0.12)
            self.assertAlmostEqual(coefficients.loc["x2", "estimate"], -0.8, delta=0.18)
            self.assertTrue((coefficients["confidence_lower"] < coefficients["estimate"]).all())
            self.assertTrue((coefficients["confidence_upper"] > coefficients["estimate"]).all())
            fitted = pd.read_csv(output / "fitted.csv")
            self.assertLess(abs(fitted["residual"].sum()), 1e-9)
            vifs = pd.read_csv(output / "vif.csv").set_index("feature")
            correlation = np.corrcoef(
                pd.read_csv(source)["x1"], pd.read_csv(source)["x2"]
            )[0, 1]
            expected_vif = 1.0 / (1.0 - correlation**2)
            self.assertAlmostEqual(vifs.loc["x1", "vif"], expected_vif, places=10)

    def test_cluster_covariance_requires_declared_groups(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "cluster.csv"
            random = np.random.default_rng(1908)
            groups = np.repeat(np.arange(24), 6)
            x1 = random.normal(size=len(groups))
            x2 = random.normal(size=len(groups))
            group_effect = random.normal(scale=1.2, size=24)[groups]
            y = 1.0 + 0.9 * x1 - 0.4 * x2 + group_effect + random.normal(scale=0.25, size=len(groups))
            pd.DataFrame({"group": groups, "x1": x1, "x2": x2, "y": y}).to_csv(source, index=False)
            output = root / "output"
            completed = run_script(
                *self.common_arguments(source, output), "--covariance", "cluster",
                "--group-column", "group",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            evidence = json.loads((output / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(evidence["group_count"], 24)
            self.assertEqual(evidence["covariance"], "cluster")
            self.assertIn("group", pd.read_csv(output / "fitted.csv").columns)

    def test_influence_flags_create_sensitivity_not_primary_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "influence.csv"
            output = root / "output"
            self.write_heteroskedastic(source, influential=True)
            completed = run_script(*self.common_arguments(source, output))
            self.assertEqual(completed.returncode, 0, completed.stderr)
            evidence = json.loads((output / "run.json").read_text(encoding="utf-8"))
            self.assertGreater(evidence["influence_review"]["flagged_rows"], 0)
            self.assertTrue(evidence["influence_review"]["sensitivity_available"])
            influence = pd.read_csv(output / "influence.csv")
            self.assertTrue(bool(influence.loc[influence["row"] == 159, "review_flag"].iloc[0]))
            sensitivity = pd.read_csv(output / "influence_sensitivity.csv")
            self.assertEqual(set(sensitivity["term"]), {"intercept", "x1", "x2"})
            self.assertEqual(evidence["rows"], 160)

    def test_repeatable_structured_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "data.csv"
            self.write_heteroskedastic(source)
            first = root / "first"
            second = root / "second"
            self.assertEqual(run_script(*self.common_arguments(source, first)).returncode, 0)
            self.assertEqual(run_script(*self.common_arguments(source, second)).returncode, 0)
            for name in ["coefficients.csv", "diagnostics.csv", "vif.csv", "influence.csv", "fitted.csv", "influence_sensitivity.csv"]:
                self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())
            left = json.loads((first / "run.json").read_text(encoding="utf-8"))
            right = json.loads((second / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(left, right)

    def test_invalid_contracts_fail_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "data.csv"
            self.write_heteroskedastic(source)
            cases = [
                ["--features", "x1,x1"],
                ["--feature-units", "m"],
                ["--covariance", "cluster"],
                ["--confidence-level", "1"],
            ]
            for index, replacement in enumerate(cases):
                output = root / f"bad-{index}"
                arguments = self.common_arguments(source, output)
                option = replacement[0]
                position = arguments.index(option) if option in arguments else None
                if position is None:
                    arguments.extend(replacement)
                else:
                    arguments[position : position + 2] = replacement
                completed = run_script(*arguments)
                self.assertNotEqual(completed.returncode, 0)
                self.assertFalse(output.exists())

            existing = root / "existing"
            existing.mkdir()
            completed = run_script(*self.common_arguments(source, existing))
            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual(list(existing.iterdir()), [])


if __name__ == "__main__":
    unittest.main()

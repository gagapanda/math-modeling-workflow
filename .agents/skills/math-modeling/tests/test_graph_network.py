from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "model_baselines" / "graph_network.py"


def shortest_problem(directed: bool = True) -> dict:
    return {
        "task": "shortest_path",
        "directed": directed,
        "nodes": ["A", "B", "C", "D", "E"],
        "source": "A",
        "target": "E",
        "cost_unit": "km",
        "source_note": "controlled validation edge costs",
        "edges": [
            {"from": "A", "to": "B", "cost": 4},
            {"from": "A", "to": "C", "cost": 2},
            {"from": "C", "to": "B", "cost": 1},
            {"from": "B", "to": "D", "cost": 5},
            {"from": "C", "to": "D", "cost": 8},
            {"from": "C", "to": "E", "cost": 10},
            {"from": "D", "to": "E", "cost": 2},
        ],
    }


def flow_problem() -> dict:
    return {
        "task": "maximum_flow",
        "directed": True,
        "nodes": ["S", "A", "B", "C", "D", "T"],
        "source": "S",
        "target": "T",
        "capacity_unit": "vehicles/hour",
        "source_note": "controlled validation capacities",
        "edges": [
            {"from": "S", "to": "A", "capacity": 10},
            {"from": "S", "to": "C", "capacity": 10},
            {"from": "A", "to": "B", "capacity": 4},
            {"from": "A", "to": "C", "capacity": 2},
            {"from": "A", "to": "D", "capacity": 8},
            {"from": "C", "to": "D", "capacity": 9},
            {"from": "D", "to": "B", "capacity": 6},
            {"from": "B", "to": "T", "capacity": 10},
            {"from": "D", "to": "T", "capacity": 10},
        ],
    }


class GraphNetworkTests(unittest.TestCase):
    def run_cli(self, problem: dict, root: Path, name: str) -> subprocess.CompletedProcess[str]:
        input_path = root / f"{name}.json"
        input_path.write_text(json.dumps(problem), encoding="utf-8")
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--input", str(input_path), "--output", str(root / name)],
            capture_output=True, text=True, check=False, env=environment,
        )

    def test_shortest_path_is_recomputed_and_repeatable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = self.run_cli(shortest_problem(), root, "first")
            second = self.run_cli(shortest_problem(), root, "second")
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual((root / "first" / "path_edges.csv").read_bytes(), (root / "second" / "path_edges.csv").read_bytes())
            evidence = json.loads((root / "first" / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(evidence["result"]["path_nodes"], ["A", "C", "B", "D", "E"])
            self.assertEqual(evidence["result"]["solver_distance"], 10.0)
            self.assertEqual(evidence["result"]["recomputed_total_cost"], 10.0)
            self.assertTrue(evidence["result"]["path_continuity_passed"])
            with (root / "first" / "path_edges.csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(sum(float(row["cost"]) for row in rows), 10.0)
            self.assertTrue(all(left["to"] == right["from"] for left, right in zip(rows, rows[1:])))

    def test_undirected_shortest_path_supports_reverse_traversal(self) -> None:
        problem = shortest_problem(directed=False)
        problem["source"], problem["target"] = "E", "A"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            completed = self.run_cli(problem, root, "undirected")
            self.assertEqual(completed.returncode, 0, completed.stderr)
            evidence = json.loads((root / "undirected" / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(evidence["result"]["path_nodes"], ["E", "D", "B", "C", "A"])
            self.assertEqual(evidence["result"]["recomputed_total_cost"], 10.0)

    def test_shortest_path_preserves_zero_cost_edges(self) -> None:
        problem = {
            "task": "shortest_path", "directed": True,
            "nodes": ["A", "B", "C"], "source": "A", "target": "C",
            "cost_unit": "cost units", "source_note": "controlled zero-cost edge check",
            "edges": [
                {"from": "A", "to": "B", "cost": 0},
                {"from": "B", "to": "C", "cost": 1},
                {"from": "A", "to": "C", "cost": 3},
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            completed = self.run_cli(problem, root, "zero")
            self.assertEqual(completed.returncode, 0, completed.stderr)
            evidence = json.loads((root / "zero" / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(evidence["result"]["path_nodes"], ["A", "B", "C"])
            self.assertEqual(evidence["result"]["recomputed_total_cost"], 1.0)

    def test_maximum_flow_recomputes_capacity_conservation_and_cut(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            completed = self.run_cli(flow_problem(), root, "flow")
            repeated = self.run_cli(flow_problem(), root, "flow-repeat")
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            for name in ("edge_flows.csv", "node_balance.csv", "minimum_cut.csv"):
                self.assertEqual((root / "flow" / name).read_bytes(), (root / "flow-repeat" / name).read_bytes())
            evidence = json.loads((root / "flow" / "run.json").read_text(encoding="utf-8"))
            result = evidence["result"]
            self.assertEqual(result["flow_value"], 19)
            self.assertEqual(result["minimum_cut_capacity"], 19)
            self.assertEqual(result["maximum_capacity_violation"], 0)
            self.assertEqual(result["maximum_conservation_violation"], 0)
            self.assertTrue(result["max_flow_min_cut_check_passed"])
            with (root / "flow" / "node_balance.csv").open(encoding="utf-8", newline="") as stream:
                balances = list(csv.DictReader(stream))
            for row in balances:
                self.assertEqual(int(row["net_inflow"]), int(row["expected_net_inflow"]))

    def test_invalid_contracts_and_unreachable_target_leave_no_output(self) -> None:
        cases: list[tuple[dict, str]] = []
        negative = shortest_problem()
        negative["edges"][0]["cost"] = -1
        cases.append((negative, "must be non-negative"))
        duplicate = shortest_problem()
        duplicate["edges"].append({"from": "A", "to": "B", "cost": 9})
        cases.append((duplicate, "duplicate edge"))
        noninteger = flow_problem()
        noninteger["edges"][0]["capacity"] = 1.5
        cases.append((noninteger, "capacities must be integers"))
        undirected_flow = flow_problem()
        undirected_flow["directed"] = False
        cases.append((undirected_flow, "requires directed=true"))
        missing_unit = shortest_problem()
        missing_unit["cost_unit"] = ""
        cases.append((missing_unit, "cost_unit must be a non-empty string"))
        unreachable = shortest_problem()
        unreachable["edges"] = [edge for edge in unreachable["edges"] if edge["to"] != "E"]
        cases.append((unreachable, "target is unreachable"))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, (problem, message) in enumerate(cases):
                with self.subTest(message=message):
                    completed = self.run_cli(problem, root, f"bad-{index}")
                    self.assertEqual(completed.returncode, 1)
                    self.assertIn(message, completed.stderr)
                    self.assertFalse((root / f"bad-{index}").exists())

    def test_existing_output_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            existing = root / "existing"
            existing.mkdir()
            marker = existing / "marker.txt"
            marker.write_text("keep", encoding="utf-8")
            completed = self.run_cli(shortest_problem(), root, "existing")
            self.assertEqual(completed.returncode, 1)
            self.assertIn("output directory already exists", completed.stderr)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()

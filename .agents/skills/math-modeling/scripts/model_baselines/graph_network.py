"""Solve auditable shortest-path or maximum-flow problems from a JSON edge list."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import scipy
from scipy.sparse import csr_array
from scipy.sparse.csgraph import dijkstra, maximum_flow


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    return float(value)


def _load_problem(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"input file not found: {path}")
    try:
        problem = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid problem JSON: {exc.msg}") from exc
    if not isinstance(problem, dict):
        raise ValueError("problem JSON must be an object")
    return problem


def _parse_problem(problem: dict[str, Any]) -> dict[str, Any]:
    task = problem.get("task")
    if task not in {"shortest_path", "maximum_flow"}:
        raise ValueError("task must be shortest_path or maximum_flow")
    directed = problem.get("directed")
    if not isinstance(directed, bool):
        raise ValueError("directed must be true or false")
    if task == "maximum_flow" and not directed:
        raise ValueError("maximum_flow requires directed=true; expand undirected capacity explicitly")
    nodes_value = problem.get("nodes")
    if not isinstance(nodes_value, list) or len(nodes_value) < 2:
        raise ValueError("nodes must contain at least two node names")
    nodes = [_text(value, "node name") for value in nodes_value]
    if len(set(nodes)) != len(nodes):
        raise ValueError("node names must be unique")
    source = _text(problem.get("source"), "source")
    target = _text(problem.get("target"), "target")
    if source not in nodes or target not in nodes:
        raise ValueError("source and target must appear in nodes")
    if source == target:
        raise ValueError("source and target must be different")
    unit_key = "cost_unit" if task == "shortest_path" else "capacity_unit"
    unit = _text(problem.get(unit_key), unit_key)
    source_note = _text(problem.get("source_note"), "source_note")
    edges_value = problem.get("edges")
    if not isinstance(edges_value, list) or not edges_value:
        raise ValueError("edges must be a non-empty list")
    value_key = "cost" if task == "shortest_path" else "capacity"
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(edges_value, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"edge {index} must be an object")
        origin = _text(item.get("from"), f"edge {index} from")
        destination = _text(item.get("to"), f"edge {index} to")
        if origin not in nodes or destination not in nodes:
            raise ValueError(f"edge {index} endpoint is not declared in nodes")
        if origin == destination:
            raise ValueError(f"edge {index} self-loops are not supported")
        key = (origin, destination)
        reverse = (destination, origin)
        if key in seen or (not directed and reverse in seen):
            raise ValueError(f"duplicate edge between {origin} and {destination}")
        seen.add(key)
        value = _number(item.get(value_key), f"edge {index} {value_key}")
        if value < 0:
            raise ValueError(f"edge {index} {value_key} must be non-negative")
        if task == "maximum_flow" and not value.is_integer():
            raise ValueError("maximum_flow capacities must be integers for scipy maximum_flow")
        edges.append({"edge_id": f"E{index:04d}", "from": origin, "to": destination, value_key: int(value) if task == "maximum_flow" else value})
    return {
        "task": task,
        "directed": directed,
        "nodes": nodes,
        "node_index": {name: index for index, name in enumerate(nodes)},
        "source": source,
        "target": target,
        "unit": unit,
        "source_note": source_note,
        "edges": edges,
    }


def _adjacency(parsed: dict[str, Any], value_key: str) -> csr_array:
    node_index = parsed["node_index"]
    rows: list[int] = []
    columns: list[int] = []
    values: list[float | int] = []
    for edge in parsed["edges"]:
        rows.append(node_index[edge["from"]])
        columns.append(node_index[edge["to"]])
        values.append(edge[value_key])
        if not parsed["directed"]:
            rows.append(node_index[edge["to"]])
            columns.append(node_index[edge["from"]])
            values.append(edge[value_key])
    dtype = np.int64 if value_key == "capacity" else float
    return csr_array((np.asarray(values, dtype=dtype), (rows, columns)), shape=(len(node_index), len(node_index)))


def _solve_shortest_path(parsed: dict[str, Any]) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    graph = _adjacency(parsed, "cost")
    source_index = parsed["node_index"][parsed["source"]]
    target_index = parsed["node_index"][parsed["target"]]
    distances, predecessors = dijkstra(
        graph, directed=parsed["directed"], indices=source_index, return_predecessors=True
    )
    if not np.isfinite(distances[target_index]):
        raise ValueError("target is unreachable from source")
    index_node = parsed["nodes"]
    path_indices = [target_index]
    while path_indices[-1] != source_index:
        predecessor = int(predecessors[path_indices[-1]])
        if predecessor < 0:
            raise ValueError("predecessor chain is incomplete")
        path_indices.append(predecessor)
    path_indices.reverse()
    path_nodes = [index_node[index] for index in path_indices]
    edge_lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for edge in parsed["edges"]:
        edge_lookup[(edge["from"], edge["to"])] = edge
        if not parsed["directed"]:
            edge_lookup[(edge["to"], edge["from"])] = edge
    rows: list[dict[str, Any]] = []
    cumulative = 0.0
    for step, (origin, destination) in enumerate(zip(path_nodes, path_nodes[1:]), start=1):
        edge = edge_lookup.get((origin, destination))
        if edge is None:
            raise RuntimeError("solver path contains an edge absent from the original edge list")
        cumulative += float(edge["cost"])
        rows.append({
            "step": step,
            "edge_id": edge["edge_id"],
            "from": origin,
            "to": destination,
            "cost": float(edge["cost"]),
            "cumulative_cost": cumulative,
            "unit": parsed["unit"],
        })
    solver_distance = float(distances[target_index])
    if not np.isclose(cumulative, solver_distance, rtol=1e-12, atol=1e-12):
        raise RuntimeError("independent path-cost recomputation disagrees with solver distance")
    evidence = {
        "solver": "scipy.sparse.csgraph.dijkstra",
        "reachable": True,
        "path_nodes": path_nodes,
        "edge_count": len(rows),
        "solver_distance": solver_distance,
        "recomputed_total_cost": cumulative,
        "path_continuity_passed": True,
        "cost_recomputation_passed": True,
    }
    return evidence, {"path_edges.csv": pd.DataFrame.from_records(rows)}


def _reachable_residual_nodes(capacity: np.ndarray, flow: np.ndarray, source_index: int) -> set[int]:
    residual = capacity - flow
    reached = {source_index}
    pending = [source_index]
    while pending:
        origin = pending.pop()
        for destination in np.flatnonzero(residual[origin] > 0):
            node = int(destination)
            if node not in reached:
                reached.add(node)
                pending.append(node)
    return reached


def _solve_maximum_flow(parsed: dict[str, Any]) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    graph = _adjacency(parsed, "capacity")
    source_index = parsed["node_index"][parsed["source"]]
    target_index = parsed["node_index"][parsed["target"]]
    result = maximum_flow(graph, source_index, target_index, method="dinic")
    flow_matrix = result.flow.toarray().astype(np.int64)
    capacity_matrix = graph.toarray().astype(np.int64)
    rows: list[dict[str, Any]] = []
    for edge in parsed["edges"]:
        origin = parsed["node_index"][edge["from"]]
        destination = parsed["node_index"][edge["to"]]
        flow_value = int(max(flow_matrix[origin, destination], 0))
        capacity = int(edge["capacity"])
        rows.append({
            "edge_id": edge["edge_id"],
            "from": edge["from"],
            "to": edge["to"],
            "capacity": capacity,
            "flow": flow_value,
            "residual_capacity": capacity - flow_value,
            "capacity_violation": max(0, flow_value - capacity),
            "unit": parsed["unit"],
        })
    edge_frame = pd.DataFrame.from_records(rows)
    balance_rows: list[dict[str, Any]] = []
    maximum_conservation_violation = 0
    source_net_outflow = 0
    target_net_inflow = 0
    for node, index in parsed["node_index"].items():
        inflow = int(sum(row["flow"] for row in rows if row["to"] == node))
        outflow = int(sum(row["flow"] for row in rows if row["from"] == node))
        balance = inflow - outflow
        expected = -int(result.flow_value) if node == parsed["source"] else int(result.flow_value) if node == parsed["target"] else 0
        violation = abs(balance - expected)
        maximum_conservation_violation = max(maximum_conservation_violation, violation)
        if node == parsed["source"]:
            source_net_outflow = outflow - inflow
        if node == parsed["target"]:
            target_net_inflow = inflow - outflow
        balance_rows.append({
            "node": node,
            "inflow": inflow,
            "outflow": outflow,
            "net_inflow": balance,
            "expected_net_inflow": expected,
            "conservation_violation": violation,
            "unit": parsed["unit"],
        })
    reachable = _reachable_residual_nodes(capacity_matrix, flow_matrix, source_index)
    cut_rows: list[dict[str, Any]] = []
    cut_capacity = 0
    for edge in parsed["edges"]:
        origin = parsed["node_index"][edge["from"]]
        destination = parsed["node_index"][edge["to"]]
        if origin in reachable and destination not in reachable:
            cut_capacity += int(edge["capacity"])
            cut_rows.append({
                "edge_id": edge["edge_id"],
                "from": edge["from"],
                "to": edge["to"],
                "capacity": int(edge["capacity"]),
                "unit": parsed["unit"],
            })
    maximum_capacity_violation = int(edge_frame["capacity_violation"].max())
    flow_value = int(result.flow_value)
    evidence = {
        "solver": "scipy.sparse.csgraph.maximum_flow(method=dinic)",
        "flow_value": flow_value,
        "source_net_outflow": source_net_outflow,
        "target_net_inflow": target_net_inflow,
        "maximum_capacity_violation": maximum_capacity_violation,
        "maximum_conservation_violation": maximum_conservation_violation,
        "residual_source_side_nodes": [parsed["nodes"][index] for index in sorted(reachable)],
        "minimum_cut_capacity": cut_capacity,
        "capacity_check_passed": maximum_capacity_violation == 0,
        "flow_conservation_passed": maximum_conservation_violation == 0,
        "source_sink_balance_passed": source_net_outflow == flow_value == target_net_inflow,
        "max_flow_min_cut_check_passed": cut_capacity == flow_value,
    }
    if not all(evidence[key] for key in ("capacity_check_passed", "flow_conservation_passed", "source_sink_balance_passed", "max_flow_min_cut_check_passed")):
        raise RuntimeError("independent maximum-flow verification failed")
    return evidence, {
        "edge_flows.csv": edge_frame,
        "node_balance.csv": pd.DataFrame.from_records(balance_rows),
        "minimum_cut.csv": pd.DataFrame.from_records(cut_rows, columns=["edge_id", "from", "to", "capacity", "unit"]),
    }


def run(input_path: Path, output_dir: Path) -> dict[str, Any]:
    input_path = input_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists():
        raise ValueError(f"output directory already exists: {output_dir}")
    problem = _load_problem(input_path)
    parsed = _parse_problem(problem)
    if parsed["task"] == "shortest_path":
        result, frames = _solve_shortest_path(parsed)
    else:
        result, frames = _solve_maximum_flow(parsed)
    evidence = {
        "input": str(input_path),
        "input_sha256": _sha256(input_path),
        "runtime": {"python": sys.version.split()[0], "numpy": np.__version__, "scipy": scipy.__version__},
        "task": parsed["task"],
        "directed": parsed["directed"],
        "source": parsed["source"],
        "target": parsed["target"],
        "nodes": len(parsed["nodes"]),
        "edges": len(parsed["edges"]),
        "unit": parsed["unit"],
        "source_note": parsed["source_note"],
        "claim_scope": "single-source single-target graph result under the declared edge semantics",
        "result": result,
        "success": True,
        "warnings": [
            "the result is valid only for the declared nodes, edges, directions, costs or capacities",
            "network topology and edge parameters require domain validation before recommendations",
        ],
        "outputs": sorted(frames),
    }
    parent = output_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}-", dir=parent))
    try:
        for name, frame in frames.items():
            frame.to_csv(temporary / name, index=False)
        (temporary / "run.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
        temporary.replace(output_dir)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        run(args.input, args.output)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

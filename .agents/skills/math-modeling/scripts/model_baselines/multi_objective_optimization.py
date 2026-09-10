"""Run an auditable constrained NSGA-II multi-objective baseline."""

from __future__ import annotations

import argparse
import csv
import importlib.metadata
import json
import math
import platform
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.core.problem import Problem
from pymoo.indicators.hv import HV
from pymoo.indicators.igd import IGD
from pymoo.optimize import minimize

from nonlinear_optimization import (
    _expression_value,
    _finite_number,
    _load_problem,
    _non_empty,
    _sha256,
    _validate_expression,
)


def _positive(value: object, label: str) -> float:
    number = _finite_number(value, label)
    if number <= 0:
        raise ValueError(f"{label} must be positive")
    return number


def _integer(value: object, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be an integer from {minimum} to {maximum}")
    return value


def _weights(value: object, count: int, label: str) -> np.ndarray:
    if not isinstance(value, list) or len(value) != count:
        raise ValueError(f"{label} must contain exactly {count} weights")
    weights = np.asarray([_positive(item, label) for item in value], dtype=float)
    if not math.isclose(float(weights.sum()), 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError(f"{label} must sum to one within 1e-9")
    return weights


def _parse_problem(problem: dict[str, Any]) -> dict[str, Any]:
    variables = problem.get("variables")
    if not isinstance(variables, list) or not variables:
        raise ValueError("variables must be a non-empty list")
    names: list[str] = []
    units: list[str] = []
    sources: list[str] = []
    lower: list[float] = []
    upper: list[float] = []
    for index, item in enumerate(variables):
        if not isinstance(item, dict):
            raise ValueError(f"variables[{index}] must be an object")
        name = item.get("name")
        if not isinstance(name, str) or not name.isidentifier():
            raise ValueError(f"variables[{index}].name must be a valid identifier")
        if name in names:
            raise ValueError(f"duplicate variable name: {name}")
        if item.get("type", "continuous") != "continuous":
            raise ValueError("multi-objective baseline supports continuous variables only")
        low = _finite_number(item.get("lower"), f"variable {name} lower")
        high = _finite_number(item.get("upper"), f"variable {name} upper")
        if low >= high:
            raise ValueError(f"variable {name} lower must be less than upper")
        names.append(name)
        units.append(_non_empty(item.get("unit"), f"variable {name} unit"))
        sources.append(_non_empty(item.get("source"), f"variable {name} source"))
        lower.append(low)
        upper.append(high)

    objectives = problem.get("objectives")
    if not isinstance(objectives, list) or len(objectives) not in {2, 3}:
        raise ValueError("objectives must contain exactly two or three objectives")
    objective_records: list[dict[str, Any]] = []
    objective_names: set[str] = set()
    for index, item in enumerate(objectives):
        if not isinstance(item, dict):
            raise ValueError(f"objectives[{index}] must be an object")
        name = _non_empty(item.get("name"), f"objective {index + 1} name")
        if not name.isidentifier() or name in objective_names:
            raise ValueError(f"objective name must be a unique identifier: {name}")
        sense = item.get("sense")
        if sense not in {"minimize", "maximize"}:
            raise ValueError(f"objective {name} sense must be minimize or maximize")
        objective_names.add(name)
        objective_records.append(
            {
                "name": name,
                "sense": sense,
                "expression": _non_empty(item.get("expression"), f"objective {name} expression"),
                "tree": _validate_expression(item.get("expression"), set(names), f"objective {name}"),
                "unit": _non_empty(item.get("unit"), f"objective {name} unit"),
                "source": _non_empty(item.get("source"), f"objective {name} source"),
                "factor": 1.0 if sense == "minimize" else -1.0,
            }
        )

    raw_constraints = problem.get("constraints")
    if not isinstance(raw_constraints, list) or not raw_constraints:
        raise ValueError("constraints must be a non-empty list")
    constraints: list[dict[str, Any]] = []
    constraint_names: set[str] = set()
    for index, item in enumerate(raw_constraints):
        if not isinstance(item, dict):
            raise ValueError(f"constraints[{index}] must be an object")
        name = _non_empty(item.get("name"), f"constraint {index + 1} name")
        if name in constraint_names:
            raise ValueError(f"duplicate constraint name: {name}")
        sense = item.get("sense")
        if sense not in {"<=", ">=", "="}:
            raise ValueError(f"constraint {name} sense must be <=, >=, or =")
        constraint_names.add(name)
        constraints.append(
            {
                "name": name,
                "sense": sense,
                "expression": _non_empty(item.get("expression"), f"constraint {name} expression"),
                "tree": _validate_expression(item.get("expression"), set(names), f"constraint {name}"),
                "rhs": _finite_number(item.get("rhs"), f"constraint {name} rhs"),
                "unit": _non_empty(item.get("unit"), f"constraint {name} unit"),
                "source": _non_empty(item.get("source"), f"constraint {name} source"),
            }
        )

    solver = problem.get("solver")
    if not isinstance(solver, dict) or solver.get("algorithm") != "NSGA-II":
        raise ValueError("solver.algorithm must be NSGA-II")
    population_size = _integer(solver.get("population_size"), "solver.population_size", 20, 2000)
    generations = _integer(solver.get("generations"), "solver.generations", 10, 100000)
    raw_seeds = solver.get("seeds")
    if not isinstance(raw_seeds, list) or not 2 <= len(raw_seeds) <= 20:
        raise ValueError("solver.seeds must contain from 2 to 20 fixed seeds")
    seeds = [_integer(seed, "solver seed", 0, 2**32 - 1) for seed in raw_seeds]
    if len(set(seeds)) != len(seeds):
        raise ValueError("solver.seeds must not contain duplicates")
    feasibility_tolerance = _positive(
        solver.get("feasibility_tolerance", 1e-7), "solver.feasibility_tolerance"
    )
    duplicate_tolerance = _positive(
        solver.get("duplicate_tolerance", 1e-8), "solver.duplicate_tolerance"
    )
    thresholds = solver.get("stability_thresholds")
    if not isinstance(thresholds, dict):
        raise ValueError("solver.stability_thresholds must be an object")
    stability_thresholds = {
        "max_normalized_igd": _positive(thresholds.get("max_normalized_igd"), "max_normalized_igd"),
        "min_hypervolume_ratio": _positive(thresholds.get("min_hypervolume_ratio"), "min_hypervolume_ratio"),
        "max_hypervolume_ratio_range": _positive(thresholds.get("max_hypervolume_ratio_range"), "max_hypervolume_ratio_range"),
        "max_endpoint_gap": _positive(thresholds.get("max_endpoint_gap"), "max_endpoint_gap"),
    }
    if stability_thresholds["min_hypervolume_ratio"] > 1.0:
        raise ValueError("min_hypervolume_ratio must not exceed one")

    decision = problem.get("decision")
    if not isinstance(decision, dict):
        raise ValueError("decision must be an object")
    primary_weights = _weights(decision.get("weights"), len(objectives), "decision.weights")
    raw_sensitivity = decision.get("sensitivity_weights")
    if not isinstance(raw_sensitivity, list) or not raw_sensitivity:
        raise ValueError("decision.sensitivity_weights must be a non-empty list")
    sensitivity_weights = [
        _weights(value, len(objectives), f"decision.sensitivity_weights[{index}]")
        for index, value in enumerate(raw_sensitivity)
    ]
    material_change_threshold = _positive(
        decision.get("material_change_threshold", 0.15), "decision.material_change_threshold"
    )

    reference = problem.get("reference_front")
    if not isinstance(reference, dict):
        raise ValueError("reference_front must be an object")
    method = reference.get("method")
    source = _non_empty(reference.get("source"), "reference_front.source")
    reference_record: dict[str, Any] = {"method": method, "source": source}
    if method == "dense_grid":
        if len(names) != 2 or len(objectives) != 2:
            raise ValueError("dense_grid reference requires exactly two variables and two objectives")
        points = _integer(reference.get("points_per_variable"), "reference_front.points_per_variable", 21, 1001)
        if points**2 > 300000:
            raise ValueError("dense_grid reference is limited to 300000 grid candidates")
        reference_record["points_per_variable"] = points
    elif method == "external_csv":
        path = _non_empty(reference.get("path"), "reference_front.path")
        sha256 = _non_empty(reference.get("sha256"), "reference_front.sha256").lower()
        if len(sha256) != 64 or any(character not in "0123456789abcdef" for character in sha256):
            raise ValueError("reference_front.sha256 must be a lowercase SHA-256 digest")
        reference_record.update({"path": path, "sha256": sha256})
    else:
        raise ValueError("reference_front.method must be dense_grid or external_csv")

    return {
        "names": names,
        "units": units,
        "sources": sources,
        "lower": np.asarray(lower, dtype=float),
        "upper": np.asarray(upper, dtype=float),
        "objectives": objective_records,
        "constraints": constraints,
        "population_size": population_size,
        "generations": generations,
        "seeds": seeds,
        "feasibility_tolerance": feasibility_tolerance,
        "duplicate_tolerance": duplicate_tolerance,
        "stability_thresholds": stability_thresholds,
        "primary_weights": primary_weights,
        "sensitivity_weights": sensitivity_weights,
        "material_change_threshold": material_change_threshold,
        "reference": reference_record,
    }


def _values(metadata: dict[str, Any], solution: np.ndarray) -> dict[str, float]:
    return dict(zip(metadata["names"], map(float, solution)))


def _objective_values(metadata: dict[str, Any], solution: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    values = _values(metadata, solution)
    raw = np.asarray([_expression_value(record["tree"], values) for record in metadata["objectives"]], dtype=float)
    factors = np.asarray([record["factor"] for record in metadata["objectives"]])
    return raw, raw * factors


def _constraint_rows(metadata: dict[str, Any], solution: np.ndarray) -> list[dict[str, Any]]:
    values = _values(metadata, solution)
    rows: list[dict[str, Any]] = []
    for record in metadata["constraints"]:
        activity = _expression_value(record["tree"], values)
        if record["sense"] == "<=":
            residual = record["rhs"] - activity
            violation = max(0.0, -residual)
        elif record["sense"] == ">=":
            residual = activity - record["rhs"]
            violation = max(0.0, -residual)
        else:
            residual = activity - record["rhs"]
            violation = abs(residual)
        rows.append({
            "constraint": record["name"], "sense": record["sense"],
            "expression": record["expression"], "rhs": record["rhs"],
            "activity": activity, "slack_or_residual": residual,
            "violation": violation, "unit": record["unit"], "source": record["source"],
        })
    return rows


def _checks(metadata: dict[str, Any], solution: np.ndarray) -> dict[str, Any]:
    raw, internal = _objective_values(metadata, solution)
    rows = _constraint_rows(metadata, solution)
    bound_violation = float(max(
        np.max(np.maximum(metadata["lower"] - solution, 0.0)),
        np.max(np.maximum(solution - metadata["upper"], 0.0)),
    ))
    constraint_violation = float(max(row["violation"] for row in rows))
    feasible = bool(
        np.isfinite(raw).all() and math.isfinite(constraint_violation)
        and bound_violation <= metadata["feasibility_tolerance"]
        and constraint_violation <= metadata["feasibility_tolerance"]
    )
    return {
        "raw": raw, "internal": internal, "rows": rows,
        "bound_violation": bound_violation,
        "constraint_violation": constraint_violation, "feasible": feasible,
    }


class _ExpressionProblem(Problem):
    def __init__(self, metadata: dict[str, Any]) -> None:
        self.metadata = metadata
        inequalities = sum(record["sense"] != "=" for record in metadata["constraints"])
        equalities = sum(record["sense"] == "=" for record in metadata["constraints"])
        super().__init__(
            n_var=len(metadata["names"]), n_obj=len(metadata["objectives"]),
            n_ieq_constr=inequalities, n_eq_constr=equalities,
            xl=metadata["lower"], xu=metadata["upper"],
        )

    def _evaluate(self, solutions: np.ndarray, out: dict[str, Any], *args: Any, **kwargs: Any) -> None:
        objective_rows: list[np.ndarray] = []
        inequality_rows: list[list[float]] = []
        equality_rows: list[list[float]] = []
        for solution in solutions:
            _, internal = _objective_values(self.metadata, solution)
            objective_rows.append(np.where(np.isfinite(internal), internal, 1e100))
            inequalities: list[float] = []
            equalities: list[float] = []
            values = _values(self.metadata, solution)
            for record in self.metadata["constraints"]:
                activity = _expression_value(record["tree"], values)
                if not math.isfinite(activity):
                    activity = 1e100
                if record["sense"] == "<=":
                    inequalities.append(activity - record["rhs"])
                elif record["sense"] == ">=":
                    inequalities.append(record["rhs"] - activity)
                else:
                    equalities.append(activity - record["rhs"])
            inequality_rows.append(inequalities)
            equality_rows.append(equalities)
        out["F"] = np.asarray(objective_rows)
        if self.n_ieq_constr:
            out["G"] = np.asarray(inequality_rows)
        if self.n_eq_constr:
            out["H"] = np.asarray(equality_rows)


def _nondominated_indices(values: np.ndarray, tolerance: float) -> np.ndarray:
    keep: list[int] = []
    for index, current in enumerate(values):
        dominated = False
        for other_index, other in enumerate(values):
            if index == other_index:
                continue
            if np.all(other <= current + tolerance) and np.any(other < current - tolerance):
                dominated = True
                break
        if not dominated:
            keep.append(index)
    return np.asarray(keep, dtype=int)


def _nondominated_2d(values: np.ndarray, tolerance: float) -> np.ndarray:
    order = np.lexsort((values[:, 1], values[:, 0]))
    keep: list[int] = []
    best_second = math.inf
    for index in order:
        if values[index, 1] < best_second - tolerance:
            keep.append(int(index))
            best_second = float(values[index, 1])
    return np.asarray(keep, dtype=int)


def _deduplicate(solutions: np.ndarray, objectives: np.ndarray, tolerance: float) -> np.ndarray:
    combined = np.column_stack([solutions, objectives])
    keys = np.round(combined / tolerance).astype(np.int64)
    _, indices = np.unique(keys, axis=0, return_index=True)
    return np.sort(indices)


def _dense_reference(metadata: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    points = metadata["reference"]["points_per_variable"]
    axes = [np.linspace(metadata["lower"][index], metadata["upper"][index], points) for index in range(2)]
    feasible_solutions: list[np.ndarray] = []
    internal_values: list[np.ndarray] = []
    for first in axes[0]:
        for second in axes[1]:
            solution = np.asarray([first, second], dtype=float)
            checks = _checks(metadata, solution)
            if checks["feasible"]:
                feasible_solutions.append(solution)
                internal_values.append(checks["internal"])
    if not feasible_solutions:
        raise ValueError("dense_grid reference produced no feasible candidates")
    solutions = np.asarray(feasible_solutions)
    values = np.asarray(internal_values)
    indices = _nondominated_2d(values, metadata["duplicate_tolerance"])
    return solutions[indices], values[indices], {
        "method": "dense_grid", "source": metadata["reference"]["source"],
        "points_per_variable": points, "grid_candidates": points**2,
        "feasible_grid_candidates": len(solutions),
    }


def _external_reference(metadata: dict[str, Any], input_path: Path) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    path = (input_path.parent / metadata["reference"]["path"]).resolve()
    if not path.is_file():
        raise ValueError(f"reference front CSV not found: {path}")
    actual_hash = _sha256(path)
    if actual_hash != metadata["reference"]["sha256"]:
        raise ValueError("reference front CSV SHA-256 does not match the declared binding")
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError("reference front CSV must contain at least one row")
    try:
        raw = np.asarray([[float(row[record["name"]]) for record in metadata["objectives"]] for row in rows])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("reference front CSV objective columns must be finite numeric values") from exc
    if not np.isfinite(raw).all():
        raise ValueError("reference front CSV objective columns must be finite numeric values")
    factors = np.asarray([record["factor"] for record in metadata["objectives"]])
    internal = raw * factors
    if len(_nondominated_indices(internal, metadata["duplicate_tolerance"])) != len(internal):
        raise ValueError("reference front CSV contains dominated objective rows")
    return np.empty((len(raw), 0)), internal, {
        "method": "external_csv", "source": metadata["reference"]["source"],
        "path": str(path), "sha256": actual_hash,
    }


def _reference_front(metadata: dict[str, Any], input_path: Path) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    if metadata["reference"]["method"] == "dense_grid":
        solutions, values, evidence = _dense_reference(metadata)
    else:
        solutions, values, evidence = _external_reference(metadata, input_path)
    ranges = np.ptp(values, axis=0)
    if np.any(ranges <= metadata["duplicate_tolerance"]):
        raise ValueError("reference front has a zero-range objective and cannot be normalized")
    evidence["front_points"] = len(values)
    evidence["validated_nondominated"] = True
    return solutions, values, evidence


def _solution_record(metadata: dict[str, Any], solution_id: str, solution: np.ndarray, checks: dict[str, Any]) -> dict[str, Any]:
    record: dict[str, Any] = {
        "solution_id": solution_id, "feasible": checks["feasible"],
        "maximum_bound_violation": checks["bound_violation"],
        "maximum_constraint_violation": checks["constraint_violation"],
    }
    record.update({name: float(value) for name, value in zip(metadata["names"], solution)})
    for objective, raw, internal in zip(metadata["objectives"], checks["raw"], checks["internal"]):
        record[objective["name"]] = float(raw)
        record[f"internal_{objective['name']}"] = float(internal)
    return record


def _seed_metrics(seed: int, values: np.ndarray, reference_normalized: np.ndarray, ideal: np.ndarray, ranges: np.ndarray, reference_hv: float, reference_point: np.ndarray) -> dict[str, Any]:
    normalized = (values - ideal) / ranges
    igd = float(IGD(reference_normalized).do(normalized))
    hypervolume = float(HV(ref_point=reference_point).do(normalized))
    endpoint_gaps = np.maximum(np.min(normalized, axis=0), 0.0)
    return {
        "seed": seed, "front_points": len(values), "normalized_igd": igd,
        "hypervolume": hypervolume, "hypervolume_ratio": hypervolume / reference_hv,
        "maximum_endpoint_gap": float(np.max(endpoint_gaps)),
        "objective_range_coverage": [float(value) for value in np.clip(np.ptp(values, axis=0) / ranges, 0.0, 1.0)],
    }


def _select_compromise(normalized: np.ndarray, weights: np.ndarray) -> tuple[int, float]:
    scores = np.max(normalized * weights, axis=1) + 0.001 * np.sum(normalized * weights, axis=1)
    index = int(np.argmin(scores))
    return index, float(scores[index])


def _write_plot(metadata: dict[str, Any], seed_fronts: list[dict[str, Any]], reference_values: np.ndarray, selected_values: np.ndarray, output_path: Path) -> None:
    if len(metadata["objectives"]) != 2:
        return
    first, second = metadata["objectives"]
    factors = np.asarray([first["factor"], second["factor"]])
    reference_raw = reference_values / factors
    with plt.rc_context({"figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white"}):
        figure, axis = plt.subplots(figsize=(7.2, 5.0), layout="constrained")
        axis.plot(reference_raw[:, 0], reference_raw[:, 1], color="#222222", linewidth=1.5, linestyle="--", label="Validated dense-grid reference", zorder=2)
        colors = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#56B4E9"]
        markers = ["o", "s", "^", "D", "v"]
        for index, front in enumerate(seed_fronts):
            raw = front["values"] / factors
            axis.scatter(raw[:, 0], raw[:, 1], s=17, facecolors="none", edgecolors=colors[index % len(colors)], marker=markers[index % len(markers)], linewidths=0.8, label=f"NSGA-II seed {front['seed']}", zorder=3)
        selected_raw = selected_values / factors
        axis.scatter([selected_raw[0]], [selected_raw[1]], s=85, color="#F0E442", edgecolor="#000000", marker="*", linewidth=0.9, label="Preference-conditioned compromise", zorder=5)
        axis.set_xlabel(f"{first['name']} ({first['unit']})")
        axis.set_ylabel(f"{second['name']} ({second['unit']})")
        axis.grid(True, color="#D9D9D9", linewidth=0.6)
        axis.legend(frameon=True, fontsize=8)
        figure.savefig(output_path, dpi=180, transparent=False)
        plt.close(figure)


def run(input_path: Path, output_dir: Path) -> dict[str, Any]:
    started = time.perf_counter()
    input_path = input_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists():
        raise ValueError("output directory already exists; choose a new path to preserve evidence")
    metadata = _parse_problem(_load_problem(input_path))
    reference_solutions, reference_values, reference_evidence = _reference_front(metadata, input_path)
    ideal = np.min(reference_values, axis=0)
    nadir = np.max(reference_values, axis=0)
    ranges = nadir - ideal
    reference_normalized = (reference_values - ideal) / ranges
    reference_point = np.full(len(metadata["objectives"]), 1.1)
    reference_hv = float(HV(ref_point=reference_point).do(reference_normalized))
    if reference_hv <= 0:
        raise ValueError("validated reference front has non-positive hypervolume")

    problem = _ExpressionProblem(metadata)
    seed_fronts: list[dict[str, Any]] = []
    seed_rows: list[dict[str, Any]] = []
    all_solutions: list[np.ndarray] = []
    all_values: list[np.ndarray] = []
    for seed in metadata["seeds"]:
        result = minimize(problem, NSGA2(pop_size=metadata["population_size"], eliminate_duplicates=True), ("n_gen", metadata["generations"]), seed=seed, verbose=False)
        if result.X is None:
            raise ValueError(f"NSGA-II seed {seed} returned no solutions")
        solutions = np.atleast_2d(np.asarray(result.X, dtype=float))
        checked = [(solution, _checks(metadata, solution)) for solution in solutions]
        checked = [item for item in checked if item[1]["feasible"]]
        if not checked:
            raise ValueError(f"NSGA-II seed {seed} returned no independently feasible solutions")
        feasible_solutions = np.asarray([item[0] for item in checked])
        feasible_values = np.asarray([item[1]["internal"] for item in checked])
        nondominated = _nondominated_indices(feasible_values, metadata["duplicate_tolerance"])
        feasible_solutions = feasible_solutions[nondominated]
        feasible_values = feasible_values[nondominated]
        metrics = _seed_metrics(seed, feasible_values, reference_normalized, ideal, ranges, reference_hv, reference_point)
        metrics["maximum_bound_violation"] = float(max(_checks(metadata, solution)["bound_violation"] for solution in feasible_solutions))
        metrics["maximum_constraint_violation"] = float(max(_checks(metadata, solution)["constraint_violation"] for solution in feasible_solutions))
        seed_rows.append(metrics)
        seed_fronts.append({"seed": seed, "solutions": feasible_solutions, "values": feasible_values})
        all_solutions.extend(feasible_solutions)
        all_values.extend(feasible_values)

    merged_solutions = np.asarray(all_solutions)
    merged_values = np.asarray(all_values)
    unique = _deduplicate(merged_solutions, merged_values, metadata["duplicate_tolerance"])
    merged_solutions, merged_values = merged_solutions[unique], merged_values[unique]
    nondominated = _nondominated_indices(merged_values, metadata["duplicate_tolerance"])
    merged_solutions, merged_values = merged_solutions[nondominated], merged_values[nondominated]
    merged_normalized = (merged_values - ideal) / ranges

    primary_index, primary_score = _select_compromise(merged_normalized, metadata["primary_weights"])
    weight_sets = [metadata["primary_weights"]] + metadata["sensitivity_weights"]
    sensitivity_rows: list[dict[str, Any]] = []
    selection_distances: list[float] = []
    for index, weights in enumerate(weight_sets):
        selected_index, score = _select_compromise(merged_normalized, weights)
        checks = _checks(metadata, merged_solutions[selected_index])
        row = {
            "weight_set": "primary" if index == 0 else f"sensitivity_{index}",
            "weights": json.dumps(weights.tolist(), separators=(",", ":")),
            "solution_id": f"P{selected_index + 1:04d}", "weighted_chebyshev_score": score,
        }
        row.update({name: float(value) for name, value in zip(metadata["names"], merged_solutions[selected_index])})
        row.update({objective["name"]: float(value) for objective, value in zip(metadata["objectives"], checks["raw"])})
        sensitivity_rows.append(row)
        selection_distances.append(float(np.linalg.norm(merged_normalized[selected_index] - merged_normalized[primary_index])))

    thresholds = metadata["stability_thresholds"]
    hypervolume_ratios = [row["hypervolume_ratio"] for row in seed_rows]
    stability_checks = {
        "all_seed_igd_within_threshold": all(row["normalized_igd"] <= thresholds["max_normalized_igd"] for row in seed_rows),
        "all_seed_hypervolume_ratios_within_threshold": all(row["hypervolume_ratio"] >= thresholds["min_hypervolume_ratio"] for row in seed_rows),
        "hypervolume_ratio_range_within_threshold": max(hypervolume_ratios) - min(hypervolume_ratios) <= thresholds["max_hypervolume_ratio_range"],
        "all_seed_endpoint_gaps_within_threshold": all(row["maximum_endpoint_gap"] <= thresholds["max_endpoint_gap"] for row in seed_rows),
    }
    stability_passed = all(stability_checks.values())

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}-", dir=output_dir.parent))
    try:
        pareto_records: list[dict[str, Any]] = []
        constraint_records: list[dict[str, Any]] = []
        for index, solution in enumerate(merged_solutions):
            solution_id = f"P{index + 1:04d}"
            checks = _checks(metadata, solution)
            record = _solution_record(metadata, solution_id, solution, checks)
            record["selected_primary"] = index == primary_index
            pareto_records.append(record)
            constraint_records.extend({"solution_id": solution_id, **row} for row in checks["rows"])
        pd.DataFrame.from_records(pareto_records).to_csv(temporary / "pareto_solutions.csv", index=False)
        pd.DataFrame.from_records(constraint_records).to_csv(temporary / "constraint_check.csv", index=False)
        pd.DataFrame.from_records(seed_rows).to_csv(temporary / "seed_stability.csv", index=False)
        pd.DataFrame.from_records(sensitivity_rows).to_csv(temporary / "compromise_sensitivity.csv", index=False)

        seed_front_records: list[dict[str, Any]] = []
        for front in seed_fronts:
            for point_index, solution in enumerate(front["solutions"], start=1):
                record = _solution_record(metadata, f"S{front['seed']}-{point_index:04d}", solution, _checks(metadata, solution))
                record["seed"] = front["seed"]
                seed_front_records.append(record)
        pd.DataFrame.from_records(seed_front_records).to_csv(temporary / "seed_fronts.csv", index=False)

        reference_records: list[dict[str, Any]] = []
        factors = np.asarray([record["factor"] for record in metadata["objectives"]])
        for index, values in enumerate(reference_values):
            record: dict[str, Any] = {"reference_id": f"R{index + 1:05d}"}
            if reference_solutions.shape[1]:
                record.update({name: float(value) for name, value in zip(metadata["names"], reference_solutions[index])})
            record.update({objective["name"]: float(value) for objective, value in zip(metadata["objectives"], values / factors)})
            reference_records.append(record)
        pd.DataFrame.from_records(reference_records).to_csv(temporary / "reference_front.csv", index=False)
        _write_plot(metadata, seed_fronts, reference_values, merged_values[primary_index], temporary / "pareto_front.png")

        selected_checks = _checks(metadata, merged_solutions[primary_index])
        objective_evidence = [{
            "name": record["name"], "sense": record["sense"],
            "expression": record["expression"], "unit": record["unit"], "source": record["source"],
            "ideal_internal": float(ideal[index]), "nadir_internal": float(nadir[index]),
            "normalization_range": float(ranges[index]),
        } for index, record in enumerate(metadata["objectives"])]
        evidence = {
            "input": str(input_path), "input_sha256": _sha256(input_path),
            "runtime": {"python": platform.python_version(), "numpy": np.__version__, "pymoo": importlib.metadata.version("pymoo"), "elapsed_seconds": time.perf_counter() - started},
            "solver": {"algorithm": "NSGA-II", "population_size": metadata["population_size"], "generations": metadata["generations"], "seeds": metadata["seeds"], "feasibility_tolerance": metadata["feasibility_tolerance"], "duplicate_tolerance": metadata["duplicate_tolerance"]},
            "claim_scope": "heuristic approximation of a constrained Pareto front validated against the declared reference",
            "variables": [{"name": name, "lower": float(metadata["lower"][index]), "upper": float(metadata["upper"][index]), "unit": metadata["units"][index], "source": metadata["sources"][index]} for index, name in enumerate(metadata["names"])],
            "objectives": objective_evidence,
            "constraints": [{key: value for key, value in record.items() if key != "tree"} for record in metadata["constraints"]],
            "reference_front": {**reference_evidence, "ideal_internal": ideal.tolist(), "nadir_internal": nadir.tolist(), "normalization_ranges": ranges.tolist(), "hypervolume_reference_point_normalized": reference_point.tolist(), "reference_hypervolume": reference_hv},
            "seed_stability": {"thresholds_declared_before_run": thresholds, "per_seed": seed_rows, "checks": stability_checks, "passed": stability_passed},
            "merged_front": {"points": len(merged_solutions), "independently_feasible": True, "nondominance_recomputed": True, "maximum_bound_violation": float(max(_checks(metadata, value)["bound_violation"] for value in merged_solutions)), "maximum_constraint_violation": float(max(_checks(metadata, value)["constraint_violation"] for value in merged_solutions))},
            "compromise": {
                "method": "normalized weighted Chebyshev with 0.001 weighted-sum tie break",
                "formula": "max_j(w_j * normalized_f_j) + 0.001 * sum_j(w_j * normalized_f_j)",
                "weights": metadata["primary_weights"].tolist(),
                "selected_solution_id": f"P{primary_index + 1:04d}", "selected_score": primary_score,
                "selected_variables": {name: float(value) for name, value in zip(metadata["names"], merged_solutions[primary_index])},
                "selected_objectives": {objective["name"]: float(value) for objective, value in zip(metadata["objectives"], selected_checks["raw"])},
                "preference_conditioned": True,
                "sensitivity_material_change_threshold": metadata["material_change_threshold"],
                "maximum_normalized_selection_distance": max(selection_distances),
                "material_region_change": max(selection_distances) >= metadata["material_change_threshold"],
            },
            "success": stability_passed,
            "warnings": [
                "NSGA-II is a heuristic search and does not prove global optimality",
                "Pareto nondominance does not identify one objectively best solution",
                "compromise weights express preferences rather than discovered truth",
                "normalization bounds affect the preference-conditioned compromise selection",
                "a dense-grid reference is a resolution-limited validation approximation",
            ],
            "outputs": ["pareto_solutions.csv", "constraint_check.csv", "seed_stability.csv", "compromise_sensitivity.csv", "seed_fronts.csv", "reference_front.csv", *(["pareto_front.png"] if len(metadata["objectives"]) == 2 else [])],
        }
        (temporary / "run.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        temporary.rename(output_dir)
        return evidence
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        evidence = run(args.input, args.output)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if not evidence["success"]:
        print("ERROR: declared Pareto stability thresholds were not met", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

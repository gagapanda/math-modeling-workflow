"""Solve an auditable continuous linear-programming problem with HiGHS."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import linprog


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _finite_vector(value: Any, name: str, length: int) -> np.ndarray:
    try:
        vector = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if vector.ndim != 1 or len(vector) != length:
        raise ValueError(f"{name} must have length {length}")
    if not np.isfinite(vector).all():
        raise ValueError(f"{name} must contain finite values")
    return vector


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


def _parse_problem(problem: dict[str, Any]) -> tuple[np.ndarray, list[tuple[float | None, float | None]], dict[str, Any]]:
    sense = problem.get("sense", "minimize")
    if sense not in {"minimize", "maximize"}:
        raise ValueError("sense must be minimize or maximize")
    variables = problem.get("variables")
    if not isinstance(variables, list) or not variables:
        raise ValueError("variables must be a non-empty list")
    names: list[str] = []
    bounds: list[tuple[float | None, float | None]] = []
    variable_units: list[str] = []
    for item in variables:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip():
            raise ValueError("each variable requires a non-empty name")
        name = item["name"].strip()
        if name in names:
            raise ValueError(f"duplicate variable name: {name}")
        names.append(name)
        lower = item.get("lower", 0.0)
        upper = item.get("upper")
        for bound, label in ((lower, "lower"), (upper, "upper")):
            if bound is not None and (not isinstance(bound, (int, float)) or not np.isfinite(bound)):
                raise ValueError(f"{name} {label} bound must be finite or null")
        if lower is not None and upper is not None and lower > upper:
            raise ValueError(f"{name} lower bound exceeds upper bound")
        bounds.append((float(lower) if lower is not None else None, float(upper) if upper is not None else None))
        variable_units.append(str(item.get("unit", "unspecified")))
    objective = problem.get("objective")
    if not isinstance(objective, dict):
        raise ValueError("objective must be an object")
    coefficients = _finite_vector(objective.get("coefficients"), "objective coefficients", len(names))
    constraints = problem.get("constraints", [])
    if not isinstance(constraints, list):
        raise ValueError("constraints must be a list")
    constraint_records: list[dict[str, Any]] = []
    constraint_names: set[str] = set()
    for index, item in enumerate(constraints, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"constraint {index} must be an object")
        name = str(item.get("name", f"constraint_{index}")).strip()
        if not name:
            raise ValueError(f"constraint {index} requires a non-empty name")
        if name in constraint_names:
            raise ValueError(f"duplicate constraint name: {name}")
        constraint_names.add(name)
        relation = item.get("sense")
        if relation not in {"<=", ">=", "="}:
            raise ValueError(f"constraint {name} sense must be <=, >=, or =")
        coefficients_row = _finite_vector(item.get("coefficients"), f"{name} coefficients", len(names))
        rhs = item.get("rhs")
        if not isinstance(rhs, (int, float)) or not np.isfinite(rhs):
            raise ValueError(f"{name} rhs must be finite")
        constraint_records.append(
            {
                "name": name,
                "sense": relation,
                "coefficients": coefficients_row.tolist(),
                "rhs": float(rhs),
                "unit": str(item.get("unit", "unspecified")),
            }
        )
    metadata = {
        "sense": sense,
        "variable_names": names,
        "variable_units": variable_units,
        "objective_unit": str(objective.get("unit", "unspecified")),
        "objective_coefficients": coefficients.tolist(),
        "constraints": constraint_records,
    }
    return coefficients, bounds, metadata


def _solve(
    coefficients: np.ndarray,
    bounds: list[tuple[float | None, float | None]],
    metadata: dict[str, Any],
    rhs_overrides: dict[str, float] | None = None,
):
    objective = coefficients if metadata["sense"] == "minimize" else -coefficients
    a_ub: list[list[float]] = []
    b_ub: list[float] = []
    a_eq: list[list[float]] = []
    b_eq: list[float] = []
    locations: list[tuple[str, str, int]] = []
    for record in metadata["constraints"]:
        row = np.asarray(record["coefficients"], dtype=float)
        rhs = (rhs_overrides or {}).get(record["name"], float(record["rhs"]))
        if record["sense"] == "<=":
            a_ub.append(row.tolist())
            b_ub.append(rhs)
            locations.append((record["name"], "ub", len(a_ub) - 1))
        elif record["sense"] == ">=":
            a_ub.append((-row).tolist())
            b_ub.append(-rhs)
            locations.append((record["name"], "ub", len(a_ub) - 1))
        else:
            a_eq.append(row.tolist())
            b_eq.append(rhs)
            locations.append((record["name"], "eq", len(a_eq) - 1))
    result = linprog(
        c=objective,
        A_ub=np.asarray(a_ub, dtype=float) if a_ub else None,
        b_ub=np.asarray(b_ub, dtype=float) if b_ub else None,
        A_eq=np.asarray(a_eq, dtype=float) if a_eq else None,
        b_eq=np.asarray(b_eq, dtype=float) if b_eq else None,
        bounds=bounds,
        method="highs",
    )
    return result, locations


def _constraint_evidence(metadata: dict[str, Any], solution: np.ndarray | None) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for record in metadata["constraints"]:
        activity = float(np.dot(record["coefficients"], solution)) if solution is not None else None
        rhs = float(record["rhs"])
        if activity is None:
            slack = None
            violation = None
        elif record["sense"] == "<=":
            slack = rhs - activity
            violation = max(0.0, -slack)
        elif record["sense"] == ">=":
            slack = activity - rhs
            violation = max(0.0, -slack)
        else:
            slack = activity - rhs
            violation = abs(slack)
        rows.append({
            "constraint": record["name"],
            "sense": record["sense"],
            "rhs": rhs,
            "activity": activity,
            "slack_or_residual": slack,
            "violation": violation,
            "unit": record["unit"],
        })
    return pd.DataFrame.from_records(rows)


def _maximum_bound_violation(
    solution: np.ndarray | None, bounds: list[tuple[float | None, float | None]]
) -> float:
    if solution is None:
        return 0.0
    violations = []
    for value, (lower, upper) in zip(solution, bounds):
        violations.append(max(0.0, lower - value) if lower is not None else 0.0)
        violations.append(max(0.0, value - upper) if upper is not None else 0.0)
    return float(max(violations, default=0.0))


def run(input_path: Path, output_dir: Path, sensitivity: float = 0.1) -> dict[str, Any]:
    if not 0 <= sensitivity < 1 or not np.isfinite(sensitivity):
        raise ValueError("sensitivity must be finite and in [0, 1)")
    input_path = input_path.expanduser().resolve()
    problem = _load_problem(input_path)
    coefficients, bounds, metadata = _parse_problem(problem)
    result, _ = _solve(coefficients, bounds, metadata)
    solution = result.x if result.success and result.x is not None else None
    constraints = _constraint_evidence(metadata, solution)
    max_violation = (
        float(constraints["violation"].max()) if solution is not None and not constraints.empty else 0.0
    )
    objective_value = (
        float(np.dot(coefficients, solution)) if solution is not None else None
    )
    max_bound_violation = _maximum_bound_violation(solution, bounds)
    baseline_value = problem.get("baseline_solution")
    baseline_solution = (
        _finite_vector(baseline_value, "baseline_solution", len(bounds))
        if baseline_value is not None
        else None
    )
    baseline_constraints = _constraint_evidence(metadata, baseline_solution)
    baseline_constraint_violation = (
        float(baseline_constraints["violation"].max())
        if baseline_solution is not None and not baseline_constraints.empty
        else 0.0
    )
    baseline_bound_violation = _maximum_bound_violation(baseline_solution, bounds)
    baseline_feasible = (
        baseline_solution is not None
        and baseline_constraint_violation <= 1e-7
        and baseline_bound_violation <= 1e-7
    )
    baseline_objective = (
        float(np.dot(coefficients, baseline_solution)) if baseline_solution is not None else None
    )
    improvement = None
    if objective_value is not None and baseline_objective is not None and baseline_feasible:
        improvement = (
            objective_value - baseline_objective
            if metadata["sense"] == "maximize"
            else baseline_objective - objective_value
        )
    sensitivity_rows: list[dict[str, Any]] = []
    if sensitivity:
        for record in metadata["constraints"]:
            original_rhs = float(record["rhs"])
            delta = abs(original_rhs) * sensitivity
            for direction in ("down", "up"):
                perturbed_rhs = (
                    original_rhs - delta if direction == "down" else original_rhs + delta
                )
                perturbed, _ = _solve(
                    coefficients, bounds, metadata, {record["name"]: perturbed_rhs}
                )
                sensitivity_rows.append({
                    "constraint": record["name"],
                    "direction": direction,
                    "original_rhs": original_rhs,
                    "perturbed_rhs": perturbed_rhs,
                    "status": int(perturbed.status),
                    "success": bool(perturbed.success),
                    "objective": float(np.dot(coefficients, perturbed.x)) if perturbed.success and perturbed.x is not None else None,
                })
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    variable_rows = []
    for name, value, bound in zip(metadata["variable_names"], solution if solution is not None else [None] * len(bounds), bounds):
        variable_rows.append({
            "variable": name,
            "value": value,
            "lower": bound[0],
            "upper": bound[1],
            "lower_violation": max(0.0, bound[0] - value) if value is not None and bound[0] is not None else 0.0 if value is not None else None,
            "upper_violation": max(0.0, value - bound[1]) if value is not None and bound[1] is not None else 0.0 if value is not None else None,
            "unit": metadata["variable_units"][len(variable_rows)],
        })
    pd.DataFrame.from_records(variable_rows).to_csv(output_dir / "solution.csv", index=False)
    constraints.to_csv(output_dir / "constraint_check.csv", index=False)
    pd.DataFrame.from_records(sensitivity_rows).to_csv(output_dir / "rhs_sensitivity.csv", index=False)
    warnings: list[str] = []
    if any(unit == "unspecified" for unit in metadata["variable_units"] + [metadata["objective_unit"]] + [record["unit"] for record in metadata["constraints"]]):
        warnings.append("one or more variables, objective, or constraints have unspecified units")
    if result.status == 3:
        warnings.append("problem is unbounded; add a meaningful bound or constraint before interpreting")
    if sensitivity and any(float(record["rhs"]) == 0 for record in metadata["constraints"]):
        warnings.append("relative RHS sensitivity leaves zero-valued right-hand sides unchanged")
    evidence = {
        "input": str(input_path),
        "input_sha256": _sha256(input_path),
        "sense": metadata["sense"],
        "variables": metadata["variable_names"],
        "variable_units": metadata["variable_units"],
        "objective_unit": metadata["objective_unit"],
        "constraints": len(metadata["constraints"]),
        "solver": "scipy.optimize.linprog(method=highs)",
        "status": int(result.status),
        "success": bool(result.success),
        "message": str(result.message),
        "objective_value": objective_value,
        "maximum_constraint_violation": max_violation,
        "maximum_bound_violation": max_bound_violation,
        "feasibility_passed": bool(
            result.success and max_violation <= 1e-7 and max_bound_violation <= 1e-7
        ),
        "baseline_provided": baseline_solution is not None,
        "baseline_feasible": baseline_feasible if baseline_solution is not None else None,
        "baseline_objective_value": baseline_objective,
        "objective_improvement_over_baseline": improvement,
        "sensitivity": sensitivity,
        "sensitivity_cases": len(sensitivity_rows),
        "warnings": warnings,
        "outputs": ["solution.csv", "constraint_check.csv", "rhs_sensitivity.csv"],
    }
    (output_dir / "run.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--sensitivity", type=float, default=0.1)
    args = parser.parse_args()
    try:
        evidence = run(args.input, args.output, args.sensitivity)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if not evidence["success"]:
        print(f"ERROR: solver status {evidence['status']}: {evidence['message']}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

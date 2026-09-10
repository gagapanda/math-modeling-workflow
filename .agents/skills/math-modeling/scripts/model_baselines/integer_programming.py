"""Solve an auditable mixed-integer linear program with SciPy HiGHS."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp


TOLERANCE = 1e-7


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


def _parse_problem(problem: dict[str, Any]) -> dict[str, Any]:
    sense = problem.get("sense", "minimize")
    if sense not in {"minimize", "maximize"}:
        raise ValueError("sense must be minimize or maximize")
    variables = problem.get("variables")
    if not isinstance(variables, list) or not variables:
        raise ValueError("variables must be a non-empty list")

    names: list[str] = []
    units: list[str] = []
    types: list[str] = []
    lower: list[float] = []
    upper: list[float] = []
    integrality: list[int] = []
    for item in variables:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("name"), str)
            or not item["name"].strip()
        ):
            raise ValueError("each variable requires a non-empty name")
        name = item["name"].strip()
        if name in names:
            raise ValueError(f"duplicate variable name: {name}")
        variable_type = item.get("type", "continuous")
        if variable_type not in {"continuous", "integer", "binary"}:
            raise ValueError(f"{name} type must be continuous, integer, or binary")
        raw_lower = item.get("lower", 0.0)
        raw_upper = item.get("upper")
        if variable_type == "binary":
            if raw_lower not in (None, 0, 0.0) or raw_upper not in (None, 1, 1.0):
                raise ValueError(f"binary variable {name} must use bounds 0 and 1")
            raw_lower, raw_upper = 0.0, 1.0
        for bound, label in ((raw_lower, "lower"), (raw_upper, "upper")):
            if bound is not None and (
                not isinstance(bound, (int, float)) or not np.isfinite(bound)
            ):
                raise ValueError(f"{name} {label} bound must be finite or null")
        if raw_lower is not None and raw_upper is not None and raw_lower > raw_upper:
            raise ValueError(f"{name} lower bound exceeds upper bound")
        names.append(name)
        units.append(str(item.get("unit", "unspecified")))
        types.append(variable_type)
        lower.append(float(raw_lower) if raw_lower is not None else -np.inf)
        upper.append(float(raw_upper) if raw_upper is not None else np.inf)
        integrality.append(0 if variable_type == "continuous" else 1)
    if not any(integrality):
        raise ValueError(
            "integer programming requires at least one integer or binary variable"
        )

    objective = problem.get("objective")
    if not isinstance(objective, dict):
        raise ValueError("objective must be an object")
    coefficients = _finite_vector(
        objective.get("coefficients"), "objective coefficients", len(names)
    )
    constraints = problem.get("constraints", [])
    if not isinstance(constraints, list):
        raise ValueError("constraints must be a list")
    constraint_names: set[str] = set()
    records: list[dict[str, Any]] = []
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
        rhs = item.get("rhs")
        if not isinstance(rhs, (int, float)) or not np.isfinite(rhs):
            raise ValueError(f"{name} rhs must be finite")
        records.append(
            {
                "name": name,
                "sense": relation,
                "coefficients": _finite_vector(
                    item.get("coefficients"),
                    f"{name} coefficients",
                    len(names),
                ).tolist(),
                "rhs": float(rhs),
                "unit": str(item.get("unit", "unspecified")),
            }
        )
    return {
        "sense": sense,
        "names": names,
        "units": units,
        "types": types,
        "lower": np.asarray(lower, dtype=float),
        "upper": np.asarray(upper, dtype=float),
        "integrality": np.asarray(integrality, dtype=int),
        "coefficients": coefficients,
        "objective_unit": str(objective.get("unit", "unspecified")),
        "constraints": records,
    }


def _linear_constraint(metadata: dict[str, Any]) -> LinearConstraint | None:
    if not metadata["constraints"]:
        return None
    matrix: list[list[float]] = []
    lower: list[float] = []
    upper: list[float] = []
    for record in metadata["constraints"]:
        matrix.append(record["coefficients"])
        rhs = record["rhs"]
        if record["sense"] == "<=":
            lower.append(-np.inf)
            upper.append(rhs)
        elif record["sense"] == ">=":
            lower.append(rhs)
            upper.append(np.inf)
        else:
            lower.append(rhs)
            upper.append(rhs)
    return LinearConstraint(np.asarray(matrix, dtype=float), lower, upper)


def _solve(
    metadata: dict[str, Any],
    integrality: np.ndarray,
    time_limit: float | None,
    mip_rel_gap: float | None,
):
    objective = (
        metadata["coefficients"]
        if metadata["sense"] == "minimize"
        else -metadata["coefficients"]
    )
    options: dict[str, float | bool] = {"presolve": True}
    if time_limit is not None:
        options["time_limit"] = time_limit
    if mip_rel_gap is not None:
        options["mip_rel_gap"] = mip_rel_gap
    return milp(
        c=objective,
        integrality=integrality,
        bounds=Bounds(metadata["lower"], metadata["upper"]),
        constraints=_linear_constraint(metadata),
        options=options,
    )


def _constraint_evidence(
    metadata: dict[str, Any], solution: np.ndarray | None
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for record in metadata["constraints"]:
        activity = (
            float(np.dot(record["coefficients"], solution))
            if solution is not None
            else None
        )
        rhs = record["rhs"]
        if activity is None:
            slack, violation = None, None
        elif record["sense"] == "<=":
            slack = rhs - activity
            violation = max(0.0, -slack)
        elif record["sense"] == ">=":
            slack = activity - rhs
            violation = max(0.0, -slack)
        else:
            slack = activity - rhs
            violation = abs(slack)
        rows.append(
            {
                "constraint": record["name"],
                "sense": record["sense"],
                "rhs": rhs,
                "activity": activity,
                "slack_or_residual": slack,
                "violation": violation,
                "unit": record["unit"],
            }
        )
    return pd.DataFrame.from_records(rows)


def _candidate_checks(
    metadata: dict[str, Any],
    solution: np.ndarray | None,
    enforce_integrality: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, float | bool]]:
    constraints = _constraint_evidence(metadata, solution)
    variable_rows: list[dict[str, Any]] = []
    max_bound = 0.0
    max_integer = 0.0
    values = solution if solution is not None else [None] * len(metadata["names"])
    for index, (name, value) in enumerate(zip(metadata["names"], values)):
        if value is None:
            lower_violation = upper_violation = integer_distance = None
        else:
            lower_violation = max(0.0, metadata["lower"][index] - value)
            upper_violation = max(0.0, value - metadata["upper"][index])
            integer_distance = (
                abs(value - round(value))
                if metadata["integrality"][index]
                else 0.0
            )
            max_bound = max(max_bound, lower_violation, upper_violation)
            max_integer = max(max_integer, integer_distance)
        variable_rows.append(
            {
                "variable": name,
                "type": metadata["types"][index],
                "value": value,
                "lower": metadata["lower"][index],
                "upper": metadata["upper"][index],
                "lower_violation": lower_violation,
                "upper_violation": upper_violation,
                "integer_distance": integer_distance,
                "unit": metadata["units"][index],
            }
        )
    max_constraint = (
        float(constraints["violation"].max())
        if solution is not None and not constraints.empty
        else 0.0
    )
    checks: dict[str, float | bool] = {
        "maximum_constraint_violation": max_constraint,
        "maximum_bound_violation": float(max_bound),
        "maximum_integrality_violation": float(max_integer),
        "candidate_feasible": bool(
            solution is not None
            and max_constraint <= TOLERANCE
            and max_bound <= TOLERANCE
            and (not enforce_integrality or max_integer <= TOLERANCE)
        ),
    }
    return pd.DataFrame.from_records(variable_rows), constraints, checks


def _original_objective(
    metadata: dict[str, Any], solution: np.ndarray | None
) -> float | None:
    if solution is None:
        return None
    return float(np.dot(metadata["coefficients"], solution))


def _solution_class(status: int, candidate_feasible: bool) -> str:
    if status == 0 and candidate_feasible:
        return "optimal"
    if status == 1 and candidate_feasible:
        return "feasible_limit_reached"
    if status == 1:
        return "limit_reached_without_feasible_candidate"
    if status == 2:
        return "infeasible"
    if status == 3:
        return "unbounded"
    return "other_failure"


def _optional_number(result: Any, name: str) -> float | None:
    value = getattr(result, name, None)
    if value is None or not np.isfinite(value):
        return None
    return float(value)


def run(
    input_path: Path,
    output_dir: Path,
    time_limit: float | None = None,
    mip_rel_gap: float | None = None,
) -> dict[str, Any]:
    if time_limit is not None and (time_limit <= 0 or not np.isfinite(time_limit)):
        raise ValueError("time_limit must be finite and positive")
    if mip_rel_gap is not None and (
        mip_rel_gap < 0 or not np.isfinite(mip_rel_gap)
    ):
        raise ValueError("mip_rel_gap must be finite and non-negative")
    input_path = input_path.expanduser().resolve()
    problem = _load_problem(input_path)
    metadata = _parse_problem(problem)
    result = _solve(metadata, metadata["integrality"], time_limit, mip_rel_gap)
    solution = np.asarray(result.x, dtype=float) if result.x is not None else None
    variables, constraints, checks = _candidate_checks(metadata, solution)
    objective_value = _original_objective(metadata, solution)
    solution_class = _solution_class(
        int(result.status), bool(checks["candidate_feasible"])
    )

    relaxation = _solve(
        metadata, np.zeros_like(metadata["integrality"]), time_limit, None
    )
    relaxation_solution = (
        np.asarray(relaxation.x, dtype=float) if relaxation.x is not None else None
    )
    relaxation_objective = _original_objective(metadata, relaxation_solution)
    relaxation_difference = None
    if objective_value is not None and relaxation_objective is not None:
        relaxation_difference = (
            relaxation_objective - objective_value
            if metadata["sense"] == "maximize"
            else objective_value - relaxation_objective
        )

    baseline_value = problem.get("baseline_solution")
    baseline = (
        _finite_vector(
            baseline_value, "baseline_solution", len(metadata["names"])
        )
        if baseline_value is not None
        else None
    )
    _, _, baseline_checks = _candidate_checks(metadata, baseline)
    baseline_objective = _original_objective(metadata, baseline)
    improvement = None
    if (
        objective_value is not None
        and baseline_objective is not None
        and baseline_checks["candidate_feasible"]
    ):
        improvement = (
            objective_value - baseline_objective
            if metadata["sense"] == "maximize"
            else baseline_objective - objective_value
        )

    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    variables.to_csv(output_dir / "solution.csv", index=False)
    constraints.to_csv(output_dir / "constraint_check.csv", index=False)
    relaxation_variables, _, relaxation_checks = _candidate_checks(
        metadata, relaxation_solution, enforce_integrality=False
    )
    relaxation_variables.to_csv(output_dir / "lp_relaxation.csv", index=False)

    warnings: list[str] = []
    if solution_class == "feasible_limit_reached":
        warnings.append(
            "a feasible candidate exists, but the limit prevented proof of optimality"
        )
    if solution_class == "unbounded":
        warnings.append("problem is unbounded; inspect missing bounds or constraints")
    if any(
        unit == "unspecified"
        for unit in metadata["units"]
        + [metadata["objective_unit"]]
        + [record["unit"] for record in metadata["constraints"]]
    ):
        warnings.append(
            "one or more variables, objective, or constraints have unspecified units"
        )

    transformed_dual = _optional_number(result, "mip_dual_bound")
    dual_bound = (
        transformed_dual
        if transformed_dual is None or metadata["sense"] == "minimize"
        else -transformed_dual
    )
    node_count = _optional_number(result, "mip_node_count")
    evidence = {
        "input": str(input_path),
        "input_sha256": _sha256(input_path),
        "sense": metadata["sense"],
        "variables": len(metadata["names"]),
        "integer_variables": int(metadata["integrality"].sum()),
        "binary_variables": metadata["types"].count("binary"),
        "constraints": len(metadata["constraints"]),
        "solver": "scipy.optimize.milp (HiGHS)",
        "status": int(result.status),
        "success": bool(result.success),
        "solution_class": solution_class,
        "message": str(result.message),
        "candidate_available": solution is not None,
        "proven_optimal": solution_class == "optimal",
        "objective_value": objective_value,
        **checks,
        "mip_gap": _optional_number(result, "mip_gap"),
        "mip_dual_bound": dual_bound,
        "mip_node_count": int(node_count) if node_count is not None else None,
        "time_limit": time_limit,
        "requested_mip_rel_gap": mip_rel_gap,
        "lp_relaxation_status": int(relaxation.status),
        "lp_relaxation_feasible": relaxation_checks["candidate_feasible"],
        "lp_relaxation_objective": relaxation_objective,
        "objective_difference_from_lp_relaxation": relaxation_difference,
        "baseline_provided": baseline is not None,
        "baseline_feasible": (
            baseline_checks["candidate_feasible"] if baseline is not None else None
        ),
        "baseline_objective_value": baseline_objective,
        "objective_improvement_over_baseline": improvement,
        "warnings": warnings,
        "outputs": ["solution.csv", "constraint_check.csv", "lp_relaxation.csv"],
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
    parser.add_argument("--time-limit", type=float)
    parser.add_argument("--mip-rel-gap", type=float)
    args = parser.parse_args()
    try:
        evidence = run(args.input, args.output, args.time_limit, args.mip_rel_gap)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if evidence["solution_class"] == "optimal":
        return 0
    if evidence["solution_class"] == "feasible_limit_reached":
        print(
            "WARNING: feasible candidate found without proof of optimality",
            file=sys.stderr,
        )
        return 3
    print(
        f"ERROR: solver status {evidence['status']}: {evidence['message']}",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

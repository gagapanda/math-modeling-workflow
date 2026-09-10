"""Run an auditable multi-start continuous nonlinear optimization baseline."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
from scipy.optimize import minimize


ALLOWED_BINARY_OPERATORS = {
    ast.Add: lambda left, right: left + right,
    ast.Sub: lambda left, right: left - right,
    ast.Mult: lambda left, right: left * right,
    ast.Div: lambda left, right: left / right,
    ast.Pow: lambda left, right: left**right,
}
ALLOWED_UNARY_OPERATORS = {
    ast.UAdd: lambda value: value,
    ast.USub: lambda value: -value,
}
ALLOWED_FUNCTIONS: dict[str, Callable[[float], float]] = {
    "abs": abs,
    "cos": math.cos,
    "exp": math.exp,
    "log": math.log,
    "sin": math.sin,
    "sqrt": math.sqrt,
    "tanh": math.tanh,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _finite_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number")
    return number


def _non_empty(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


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


def _validate_expression(
    expression: object, variable_names: set[str], label: str
) -> ast.Expression:
    expression = _non_empty(expression, f"{label}.expression")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"{label}.expression is invalid: {exc.msg}") from exc
    operator_nodes = tuple(ALLOWED_BINARY_OPERATORS) + tuple(ALLOWED_UNARY_OPERATORS)
    function_name_nodes = {
        id(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    for node in ast.walk(tree):
        if isinstance(node, (ast.Expression, ast.Load)):
            continue
        if isinstance(node, ast.BinOp):
            if type(node.op) not in ALLOWED_BINARY_OPERATORS:
                raise ValueError(f"{label}.expression contains an unsupported operator")
            continue
        if isinstance(node, ast.UnaryOp):
            if type(node.op) not in ALLOWED_UNARY_OPERATORS:
                raise ValueError(
                    f"{label}.expression contains an unsupported unary operator"
                )
            continue
        if isinstance(node, operator_nodes):
            continue
        if isinstance(node, ast.Name):
            valid_variable = node.id in variable_names
            valid_function = (
                node.id in ALLOWED_FUNCTIONS and id(node) in function_name_nodes
            )
            if not valid_variable and not valid_function:
                raise ValueError(
                    f"{label}.expression references unknown name: {node.id}"
                )
            continue
        if isinstance(node, ast.Call):
            if (
                not isinstance(node.func, ast.Name)
                or node.func.id not in ALLOWED_FUNCTIONS
                or len(node.args) != 1
                or node.keywords
            ):
                raise ValueError(
                    f"{label}.expression contains a forbidden function call"
                )
            continue
        if isinstance(node, ast.Constant):
            _finite_number(node.value, f"{label}.expression constant")
            continue
        raise ValueError(
            f"{label}.expression contains forbidden syntax: {type(node).__name__}"
        )
    return tree


def _evaluate(node: ast.AST, values: dict[str, float]) -> float:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body, values)
    if isinstance(node, ast.Name):
        return values[node.id]
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.BinOp):
        operation = ALLOWED_BINARY_OPERATORS[type(node.op)]
        return float(operation(_evaluate(node.left, values), _evaluate(node.right, values)))
    if isinstance(node, ast.UnaryOp):
        operation = ALLOWED_UNARY_OPERATORS[type(node.op)]
        return float(operation(_evaluate(node.operand, values)))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return float(ALLOWED_FUNCTIONS[node.func.id](_evaluate(node.args[0], values)))
    raise AssertionError(f"unexpected expression node: {type(node).__name__}")


def _parse_problem(problem: dict[str, Any]) -> dict[str, Any]:
    if "objectives" in problem:
        raise ValueError("multiple objectives are not supported; provide one objective")
    sense = problem.get("sense", "minimize")
    if sense not in {"minimize", "maximize"}:
        raise ValueError("sense must be minimize or maximize")
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
        if name in names or name in ALLOWED_FUNCTIONS:
            raise ValueError(f"duplicate or reserved variable name: {name}")
        if item.get("type", "continuous") != "continuous":
            raise ValueError("nonlinear baseline supports continuous variables only")
        low = _finite_number(item.get("lower"), f"variable {name} lower")
        high = _finite_number(item.get("upper"), f"variable {name} upper")
        if low >= high:
            raise ValueError(f"variable {name} lower must be less than upper")
        names.append(name)
        units.append(_non_empty(item.get("unit"), f"variable {name} unit"))
        sources.append(_non_empty(item.get("source"), f"variable {name} source"))
        lower.append(low)
        upper.append(high)

    objective = problem.get("objective")
    if not isinstance(objective, dict):
        raise ValueError("objective must be an object")
    objective_tree = _validate_expression(objective.get("expression"), set(names), "objective")
    objective_unit = _non_empty(objective.get("unit"), "objective.unit")
    objective_source = _non_empty(objective.get("source"), "objective.source")

    raw_constraints = problem.get("constraints", [])
    if not isinstance(raw_constraints, list):
        raise ValueError("constraints must be a list")
    constraints: list[dict[str, Any]] = []
    constraint_names: set[str] = set()
    for index, item in enumerate(raw_constraints, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"constraint {index} must be an object")
        name = _non_empty(item.get("name"), f"constraint {index} name")
        if name in constraint_names:
            raise ValueError(f"duplicate constraint name: {name}")
        constraint_names.add(name)
        relation = item.get("sense")
        if relation not in {"<=", ">=", "="}:
            raise ValueError(f"constraint {name} sense must be <=, >=, or =")
        constraints.append(
            {
                "name": name,
                "sense": relation,
                "tree": _validate_expression(item.get("expression"), set(names), f"constraint {name}"),
                "expression": item.get("expression"),
                "rhs": _finite_number(item.get("rhs"), f"constraint {name} rhs"),
                "unit": _non_empty(item.get("unit"), f"constraint {name} unit"),
                "source": _non_empty(item.get("source"), f"constraint {name} source"),
            }
        )

    solver = problem.get("solver", {})
    if not isinstance(solver, dict):
        raise ValueError("solver must be an object")
    starts = solver.get("starts", 12)
    seed = solver.get("seed", 0)
    maxiter = solver.get("maxiter", 1000)
    if isinstance(starts, bool) or not isinstance(starts, int) or not 3 <= starts <= 500:
        raise ValueError("solver.starts must be an integer from 3 to 500")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**32 - 1:
        raise ValueError("solver.seed must be an integer from 0 to 2^32-1")
    if isinstance(maxiter, bool) or not isinstance(maxiter, int) or not 1 <= maxiter <= 100000:
        raise ValueError("solver.maxiter must be an integer from 1 to 100000")
    ftol = _finite_number(solver.get("ftol", 1e-9), "solver.ftol")
    feasibility_tolerance = _finite_number(
        solver.get("feasibility_tolerance", 1e-7),
        "solver.feasibility_tolerance",
    )
    objective_tolerance = _finite_number(
        solver.get("objective_tolerance", 1e-6), "solver.objective_tolerance"
    )
    if ftol <= 0 or feasibility_tolerance <= 0 or objective_tolerance <= 0:
        raise ValueError("solver tolerances must be positive")

    initial_solution = problem.get("initial_solution")
    baseline_solution = problem.get("baseline_solution")
    reference = problem.get("analytical_reference")
    metadata = {
        "sense": sense,
        "names": names,
        "units": units,
        "sources": sources,
        "lower": np.asarray(lower),
        "upper": np.asarray(upper),
        "objective_tree": objective_tree,
        "objective_expression": objective.get("expression"),
        "objective_unit": objective_unit,
        "objective_source": objective_source,
        "constraints": constraints,
        "starts": starts,
        "seed": seed,
        "maxiter": maxiter,
        "ftol": ftol,
        "feasibility_tolerance": feasibility_tolerance,
        "objective_tolerance": objective_tolerance,
    }
    metadata["initial_solution"] = _solution_vector(initial_solution, metadata, "initial_solution") if initial_solution is not None else None
    metadata["baseline_solution"] = _solution_vector(baseline_solution, metadata, "baseline_solution") if baseline_solution is not None else None
    metadata["analytical_reference"] = _parse_reference(reference, metadata) if reference is not None else None
    return metadata


def _solution_vector(value: object, metadata: dict[str, Any], label: str) -> np.ndarray:
    try:
        vector = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if vector.ndim != 1 or len(vector) != len(metadata["names"]):
        raise ValueError(f"{label} must have length {len(metadata['names'])}")
    if not np.isfinite(vector).all():
        raise ValueError(f"{label} must contain finite values")
    if np.any(vector < metadata["lower"]) or np.any(vector > metadata["upper"]):
        raise ValueError(f"{label} must lie within all variable bounds")
    return vector


def _parse_reference(value: object, metadata: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("analytical_reference must be an object")
    tolerance = _finite_number(
        value.get("tolerance", 1e-5), "analytical_reference.tolerance"
    )
    if tolerance <= 0:
        raise ValueError("analytical_reference.tolerance must be positive")
    return {
        "solution": _solution_vector(value.get("solution"), metadata, "analytical_reference.solution"),
        "objective": _finite_number(value.get("objective"), "analytical_reference.objective"),
        "tolerance": tolerance,
        "source": _non_empty(value.get("source"), "analytical_reference.source"),
    }


def _values(metadata: dict[str, Any], solution: np.ndarray) -> dict[str, float]:
    return dict(zip(metadata["names"], map(float, solution)))


def _expression_value(tree: ast.Expression, values: dict[str, float]) -> float:
    try:
        value = _evaluate(tree, values)
    except (ArithmeticError, OverflowError, ValueError):
        return math.nan
    return value if math.isfinite(value) else math.nan


def _objective_value(metadata: dict[str, Any], solution: np.ndarray) -> float:
    return _expression_value(metadata["objective_tree"], _values(metadata, solution))


def _constraint_rows(metadata: dict[str, Any], solution: np.ndarray) -> list[dict[str, Any]]:
    values = _values(metadata, solution)
    rows: list[dict[str, Any]] = []
    for record in metadata["constraints"]:
        activity = _expression_value(record["tree"], values)
        rhs = record["rhs"]
        if not math.isfinite(activity):
            residual = math.nan
            violation = math.inf
        elif record["sense"] == "<=":
            residual = rhs - activity
            violation = max(0.0, -residual)
        elif record["sense"] == ">=":
            residual = activity - rhs
            violation = max(0.0, -residual)
        else:
            residual = activity - rhs
            violation = abs(residual)
        rows.append(
            {
                "constraint": record["name"],
                "sense": record["sense"],
                "expression": record["expression"],
                "rhs": rhs,
                "activity": activity,
                "slack_or_residual": residual,
                "violation": violation,
                "unit": record["unit"],
                "source": record["source"],
            }
        )
    return rows


def _candidate_checks(metadata: dict[str, Any], solution: np.ndarray) -> dict[str, Any]:
    rows = _constraint_rows(metadata, solution)
    bound_violation = float(
        max(
            np.max(np.maximum(metadata["lower"] - solution, 0)),
            np.max(np.maximum(solution - metadata["upper"], 0)),
        )
    )
    constraint_violation = float(max((row["violation"] for row in rows), default=0.0))
    objective = _objective_value(metadata, solution)
    feasible = bool(
        math.isfinite(objective)
        and math.isfinite(constraint_violation)
        and bound_violation <= metadata["feasibility_tolerance"]
        and constraint_violation <= metadata["feasibility_tolerance"]
    )
    return {
        "objective": objective,
        "maximum_constraint_violation": constraint_violation,
        "maximum_bound_violation": bound_violation,
        "feasible": feasible,
        "constraint_rows": rows,
    }


def _scipy_constraints(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    constraints = []
    for record in metadata["constraints"]:
        def function(solution: np.ndarray, current: dict[str, Any] = record) -> float:
            activity = _expression_value(current["tree"], _values(metadata, solution))
            if not math.isfinite(activity):
                return -1e100
            if current["sense"] == "<=":
                return current["rhs"] - activity
            return activity - current["rhs"]

        constraints.append(
            {"type": "eq" if record["sense"] == "=" else "ineq", "fun": function}
        )
    return constraints


def _start_points(metadata: dict[str, Any]) -> list[np.ndarray]:
    points: list[np.ndarray] = []
    if metadata["initial_solution"] is not None:
        points.append(metadata["initial_solution"].copy())
    midpoint = (metadata["lower"] + metadata["upper"]) / 2
    if not points or not np.array_equal(points[0], midpoint):
        points.append(midpoint)
    rng = np.random.default_rng(metadata["seed"])
    while len(points) < metadata["starts"]:
        points.append(rng.uniform(metadata["lower"], metadata["upper"]))
    return points[: metadata["starts"]]


def run(input_path: Path, output_dir: Path) -> dict[str, Any]:
    input_path = input_path.expanduser().resolve()
    metadata = _parse_problem(_load_problem(input_path))
    direction = 1.0 if metadata["sense"] == "minimize" else -1.0

    def objective(solution: np.ndarray) -> float:
        value = _objective_value(metadata, solution)
        return direction * value if math.isfinite(value) else 1e100

    records: list[dict[str, Any]] = []
    candidates: list[tuple[Any, dict[str, Any]]] = []
    for start_id, start in enumerate(_start_points(metadata), start=1):
        result = minimize(
            objective,
            start,
            method="SLSQP",
            bounds=list(zip(metadata["lower"], metadata["upper"])),
            constraints=_scipy_constraints(metadata),
            options={"maxiter": metadata["maxiter"], "ftol": metadata["ftol"], "disp": False},
        )
        solution = np.asarray(result.x, dtype=float)
        checks = _candidate_checks(metadata, solution)
        candidates.append((result, checks))
        record = {
            "start_id": start_id,
            "solver_success": bool(result.success),
            "status": int(result.status),
            "message": str(result.message),
            "iterations": int(getattr(result, "nit", 0)),
            "function_evaluations": int(getattr(result, "nfev", 0)),
            "objective": checks["objective"],
            "feasible": checks["feasible"],
            "maximum_constraint_violation": checks["maximum_constraint_violation"],
            "maximum_bound_violation": checks["maximum_bound_violation"],
        }
        record.update({f"initial_{name}": float(value) for name, value in zip(metadata["names"], start)})
        record.update({f"solution_{name}": float(value) for name, value in zip(metadata["names"], solution)})
        records.append(record)

    eligible = [
        (index, result, checks)
        for index, (result, checks) in enumerate(candidates)
        if result.success and checks["feasible"]
    ]
    if eligible:
        key = (lambda item: item[2]["objective"]) if metadata["sense"] == "minimize" else (lambda item: -item[2]["objective"])
        selected_index, selected_result, selected_checks = min(eligible, key=key)
        selected_solution = np.asarray(selected_result.x, dtype=float)
    else:
        selected_index = None
        selected_solution = None
        selected_checks = None

    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame.from_records(records).to_csv(output_dir / "multistart.csv", index=False)

    solution_rows: list[dict[str, Any]] = []
    constraint_rows: list[dict[str, Any]] = []
    if selected_solution is not None and selected_checks is not None:
        for index, (name, value) in enumerate(zip(metadata["names"], selected_solution)):
            solution_rows.append(
                {
                    "variable": name,
                    "value": float(value),
                    "lower": float(metadata["lower"][index]),
                    "upper": float(metadata["upper"][index]),
                    "unit": metadata["units"][index],
                    "source": metadata["sources"][index],
                }
            )
        constraint_rows = selected_checks["constraint_rows"]
    pd.DataFrame.from_records(
        solution_rows, columns=["variable", "value", "lower", "upper", "unit", "source"]
    ).to_csv(output_dir / "solution.csv", index=False)
    pd.DataFrame.from_records(
        constraint_rows,
        columns=["constraint", "sense", "expression", "rhs", "activity", "slack_or_residual", "violation", "unit", "source"],
    ).to_csv(output_dir / "constraint_check.csv", index=False)

    successful_objectives = [record["objective"] for record in records if record["solver_success"] and record["feasible"]]
    best_objective = selected_checks["objective"] if selected_checks is not None else None
    near_best = 0
    if best_objective is not None:
        near_best = sum(abs(value - best_objective) <= metadata["objective_tolerance"] for value in successful_objectives)

    baseline = None
    if metadata["baseline_solution"] is not None:
        baseline_checks = _candidate_checks(metadata, metadata["baseline_solution"])
        improvement = None
        if baseline_checks["feasible"] and best_objective is not None:
            improvement = baseline_checks["objective"] - best_objective if metadata["sense"] == "minimize" else best_objective - baseline_checks["objective"]
        baseline = {
            "feasible": baseline_checks["feasible"],
            "objective": baseline_checks["objective"],
            "objective_improvement": improvement,
            "maximum_constraint_violation": baseline_checks["maximum_constraint_violation"],
            "maximum_bound_violation": baseline_checks["maximum_bound_violation"],
        }

    reference_evidence = None
    reference = metadata["analytical_reference"]
    if reference is not None:
        if selected_solution is None or best_objective is None:
            reference_evidence = {"passed": False, "source": reference["source"], "tolerance": reference["tolerance"]}
        else:
            solution_error = float(np.max(np.abs(selected_solution - reference["solution"])))
            objective_error = abs(best_objective - reference["objective"])
            reference_evidence = {
                "passed": solution_error <= reference["tolerance"] and objective_error <= reference["tolerance"],
                "source": reference["source"],
                "tolerance": reference["tolerance"],
                "maximum_solution_absolute_error": solution_error,
                "objective_absolute_error": objective_error,
            }

    warnings = [
        "SLSQP and multi-start agreement do not prove global optimality",
        "finite differences are used; independently verify derivatives or KKT conditions for high-stakes claims",
    ]
    if eligible and near_best < len(eligible):
        warnings.append("successful starts converged to materially different objective values")
    if not eligible:
        warnings.append("no solver-successful feasible candidate was found")
    evidence = {
        "input": str(input_path),
        "input_sha256": _sha256(input_path),
        "solver": "scipy.optimize.minimize(method=SLSQP)",
        "claim_scope": "best solver-successful feasible local candidate across declared starts",
        "sense": metadata["sense"],
        "objective_expression": metadata["objective_expression"],
        "objective_unit": metadata["objective_unit"],
        "objective_source": metadata["objective_source"],
        "variables": metadata["names"],
        "starts_requested": metadata["starts"],
        "seed": metadata["seed"],
        "successful_feasible_starts": len(eligible),
        "near_best_starts": near_best,
        "objective_tolerance": metadata["objective_tolerance"],
        "objective_range_across_successful_starts": (max(successful_objectives) - min(successful_objectives)) if successful_objectives else None,
        "selected_start_id": selected_index + 1 if selected_index is not None else None,
        "success": selected_solution is not None,
        "objective_value": best_objective,
        "maximum_constraint_violation": selected_checks["maximum_constraint_violation"] if selected_checks is not None else None,
        "maximum_bound_violation": selected_checks["maximum_bound_violation"] if selected_checks is not None else None,
        "baseline": baseline,
        "analytical_reference": reference_evidence,
        "warnings": warnings,
        "outputs": ["solution.csv", "constraint_check.csv", "multistart.csv"],
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
    args = parser.parse_args()
    try:
        evidence = run(args.input, args.output)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if not evidence["success"]:
        print("ERROR: no solver-successful feasible local candidate was found", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

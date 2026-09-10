"""Solve and validate an auditable ordinary differential equation initial-value problem."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy
from scipy.integrate import solve_ivp


ALLOWED_BINARY_OPERATORS = {
    ast.Add: lambda left, right: left + right,
    ast.Sub: lambda left, right: left - right,
    ast.Mult: lambda left, right: left * right,
    ast.Div: lambda left, right: left / right,
    ast.Pow: lambda left, right: left**right,
}
ALLOWED_UNARY_OPERATORS = {ast.UAdd: lambda value: value, ast.USub: lambda value: -value}
ALLOWED_FUNCTIONS: dict[str, Callable[[float], float]] = {
    "abs": abs,
    "cos": math.cos,
    "exp": math.exp,
    "log": math.log,
    "sin": math.sin,
    "sqrt": math.sqrt,
    "tanh": math.tanh,
}
ALLOWED_METHODS = {"RK45", "RK23", "DOP853", "Radau", "BDF", "LSODA"}
RESERVED_NAMES = set(ALLOWED_FUNCTIONS) | {"t"}


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
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number")
    return number


def _positive(value: Any, label: str) -> float:
    number = _number(value, label)
    if number <= 0:
        raise ValueError(f"{label} must be positive")
    return number


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


def _validate_expression(expression: Any, names: set[str], label: str) -> ast.Expression:
    expression = _text(expression, f"{label}.expression")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"{label}.expression is invalid: {exc.msg}") from exc
    operator_nodes = tuple(ALLOWED_BINARY_OPERATORS) + tuple(ALLOWED_UNARY_OPERATORS)
    function_names = {
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
                raise ValueError(f"{label}.expression contains an unsupported unary operator")
            continue
        if isinstance(node, operator_nodes):
            continue
        if isinstance(node, ast.Name):
            valid_name = node.id in names
            valid_function = node.id in ALLOWED_FUNCTIONS and id(node) in function_names
            if not valid_name and not valid_function:
                raise ValueError(f"{label}.expression references unknown name: {node.id}")
            continue
        if isinstance(node, ast.Call):
            if (
                not isinstance(node.func, ast.Name)
                or node.func.id not in ALLOWED_FUNCTIONS
                or len(node.args) != 1
                or node.keywords
            ):
                raise ValueError(f"{label}.expression contains a forbidden function call")
            continue
        if isinstance(node, ast.Constant):
            _number(node.value, f"{label}.expression constant")
            continue
        raise ValueError(f"{label}.expression contains forbidden syntax: {type(node).__name__}")
    return tree


def _evaluate(node: ast.AST, values: dict[str, float]) -> float:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body, values)
    if isinstance(node, ast.Name):
        return values[node.id]
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.BinOp):
        return float(ALLOWED_BINARY_OPERATORS[type(node.op)](_evaluate(node.left, values), _evaluate(node.right, values)))
    if isinstance(node, ast.UnaryOp):
        return float(ALLOWED_UNARY_OPERATORS[type(node.op)](_evaluate(node.operand, values)))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return float(ALLOWED_FUNCTIONS[node.func.id](_evaluate(node.args[0], values)))
    raise AssertionError(f"unexpected expression node: {type(node).__name__}")


def _expression_value(tree: ast.Expression, values: dict[str, float], label: str) -> float:
    try:
        value = _evaluate(tree, values)
    except (ArithmeticError, OverflowError, ValueError) as exc:
        raise ValueError(f"{label} could not be evaluated with finite values") from exc
    if not math.isfinite(value):
        raise ValueError(f"{label} returned a non-finite value")
    return value


def _parse_named_records(value: Any, label: str, value_key: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty list")
    records: list[dict[str, Any]] = []
    names: set[str] = set()
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"{label} {index} must be an object")
        name = item.get("name")
        if not isinstance(name, str) or not name.isidentifier():
            raise ValueError(f"{label} {index} name must be a valid identifier")
        if name in names or name in RESERVED_NAMES or f"initial_{name}" in names:
            raise ValueError(f"duplicate or reserved {label[:-1]} name: {name}")
        names.add(name)
        records.append({
            "name": name,
            value_key: _number(item.get(value_key), f"{label} {name} {value_key}"),
            "unit": _text(item.get("unit"), f"{label} {name} unit"),
            "source": _text(item.get("source"), f"{label} {name} source"),
        })
    return records


def _parse_problem(problem: dict[str, Any]) -> dict[str, Any]:
    time = problem.get("time")
    if not isinstance(time, dict):
        raise ValueError("time must be an object")
    start = _number(time.get("start"), "time.start")
    end = _number(time.get("end"), "time.end")
    if start >= end:
        raise ValueError("time.start must be less than time.end")
    evaluation_points = time.get("evaluation_points")
    if isinstance(evaluation_points, bool) or not isinstance(evaluation_points, int) or not 2 <= evaluation_points <= 100000:
        raise ValueError("time.evaluation_points must be an integer from 2 to 100000")
    time_unit = _text(time.get("unit"), "time.unit")

    states = _parse_named_records(problem.get("states"), "states", "initial")
    raw_parameters = problem.get("parameters", [])
    if not isinstance(raw_parameters, list):
        raise ValueError("parameters must be a list")
    parameters = _parse_named_records(raw_parameters, "parameters", "value") if raw_parameters else []
    state_names = [record["name"] for record in states]
    parameter_names = [record["name"] for record in parameters]
    collisions = set(state_names) & set(parameter_names)
    if collisions:
        raise ValueError(f"state and parameter names must be distinct: {sorted(collisions)[0]}")
    initial_names = {f"initial_{name}" for name in state_names}
    all_names = set(state_names) | set(parameter_names) | initial_names | {"t"}

    equations = problem.get("equations")
    if not isinstance(equations, list) or len(equations) != len(states):
        raise ValueError("equations must contain exactly one equation per state")
    parsed_equations: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(equations, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"equation {index} must be an object")
        state = _text(item.get("state"), f"equation {index} state")
        if state not in state_names:
            raise ValueError(f"equation {index} references unknown state: {state}")
        if state in parsed_equations:
            raise ValueError(f"duplicate equation for state: {state}")
        expression = _text(item.get("expression"), f"equation {state}.expression")
        parsed_equations[state] = {
            "expression": expression,
            "tree": _validate_expression(expression, all_names, f"equation {state}"),
            "unit": _text(item.get("unit"), f"equation {state} unit"),
            "source": _text(item.get("source"), f"equation {state} source"),
        }
    missing = [name for name in state_names if name not in parsed_equations]
    if missing:
        raise ValueError(f"missing equation for state: {missing[0]}")

    solver = problem.get("solver")
    if not isinstance(solver, dict):
        raise ValueError("solver must be an object")
    method = solver.get("method", "RK45")
    if method not in ALLOWED_METHODS:
        raise ValueError(f"solver.method must be one of: {', '.join(sorted(ALLOWED_METHODS))}")
    rtol = _positive(solver.get("rtol", 1e-7), "solver.rtol")
    atol = _positive(solver.get("atol", 1e-9), "solver.atol")
    max_step = _positive(solver.get("max_step", end - start), "solver.max_step")
    if rtol >= 1 or atol >= 1:
        raise ValueError("solver.rtol and solver.atol must be less than one")

    sensitivity = problem.get("sensitivity")
    if not isinstance(sensitivity, dict):
        raise ValueError("sensitivity must be an object")
    tolerance_factor = _positive(sensitivity.get("tolerance_factor", 0.1), "sensitivity.tolerance_factor")
    max_step_factor = _positive(sensitivity.get("max_step_factor", 0.5), "sensitivity.max_step_factor")
    if tolerance_factor >= 1 or max_step_factor >= 1:
        raise ValueError("sensitivity factors must be less than one")
    endpoint_absolute_tolerance = _positive(sensitivity.get("endpoint_absolute_tolerance"), "sensitivity.endpoint_absolute_tolerance")
    trajectory_absolute_tolerance = _positive(sensitivity.get("trajectory_absolute_tolerance"), "sensitivity.trajectory_absolute_tolerance")

    raw_invariants = problem.get("invariants", [])
    if not isinstance(raw_invariants, list):
        raise ValueError("invariants must be a list")
    invariants: list[dict[str, Any]] = []
    invariant_names: set[str] = set()
    initial_values = {record["name"]: record["initial"] for record in states}
    parameter_values = {record["name"]: record["value"] for record in parameters}
    initial_context = {**initial_values, **parameter_values, **{f"initial_{name}": value for name, value in initial_values.items()}, "t": start}
    for index, item in enumerate(raw_invariants, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"invariant {index} must be an object")
        name = _text(item.get("name"), f"invariant {index} name")
        if name in invariant_names:
            raise ValueError(f"duplicate invariant name: {name}")
        invariant_names.add(name)
        expression = _text(item.get("expression"), f"invariant {name}.expression")
        tree = _validate_expression(expression, all_names, f"invariant {name}")
        expected_raw = item.get("expected", "initial")
        expected = _expression_value(tree, initial_context, f"invariant {name}") if expected_raw == "initial" else _number(expected_raw, f"invariant {name} expected")
        invariants.append({
            "name": name, "expression": expression, "tree": tree, "expected": expected,
            "unit": _text(item.get("unit"), f"invariant {name} unit"),
            "source": _text(item.get("source"), f"invariant {name} source"),
            "absolute_tolerance": _positive(item.get("absolute_tolerance"), f"invariant {name} absolute_tolerance"),
        })

    raw_reference = problem.get("reference_solution")
    reference = None
    if raw_reference is not None:
        if not isinstance(raw_reference, dict):
            raise ValueError("reference_solution must be an object")
        expressions = raw_reference.get("expressions")
        if not isinstance(expressions, list) or len(expressions) != len(states):
            raise ValueError("reference_solution.expressions must contain exactly one expression per state")
        reference_names = {"t"} | set(parameter_names) | initial_names
        parsed_reference: dict[str, dict[str, Any]] = {}
        for index, item in enumerate(expressions, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"reference expression {index} must be an object")
            state = _text(item.get("state"), f"reference expression {index} state")
            if state not in state_names:
                raise ValueError(f"reference expression {index} references unknown state: {state}")
            if state in parsed_reference:
                raise ValueError(f"duplicate reference expression for state: {state}")
            expression = _text(item.get("expression"), f"reference expression {state}.expression")
            parsed_reference[state] = {"expression": expression, "tree": _validate_expression(expression, reference_names, f"reference expression {state}")}
        if set(parsed_reference) != set(state_names):
            raise ValueError("reference_solution.expressions must cover every state")
        reference = {
            "expressions": parsed_reference,
            "source": _text(raw_reference.get("source"), "reference_solution.source"),
            "absolute_tolerance": _positive(raw_reference.get("absolute_tolerance"), "reference_solution.absolute_tolerance"),
            "relative_tolerance": _positive(raw_reference.get("relative_tolerance"), "reference_solution.relative_tolerance"),
        }

    return {
        "start": start, "end": end, "evaluation_points": evaluation_points, "time_unit": time_unit,
        "states": states, "state_names": state_names, "parameters": parameters,
        "parameter_values": parameter_values, "initial_values": initial_values,
        "equations": parsed_equations, "method": method, "rtol": rtol, "atol": atol,
        "max_step": max_step, "tolerance_factor": tolerance_factor, "max_step_factor": max_step_factor,
        "endpoint_absolute_tolerance": endpoint_absolute_tolerance,
        "trajectory_absolute_tolerance": trajectory_absolute_tolerance,
        "invariants": invariants, "reference": reference,
    }


def _context(metadata: dict[str, Any], time: float, state: np.ndarray) -> dict[str, float]:
    return {
        "t": float(time),
        **metadata["parameter_values"],
        **metadata["initial_values"],
        **{f"initial_{name}": value for name, value in metadata["initial_values"].items()},
        **dict(zip(metadata["state_names"], map(float, state))),
    }


def _solve(metadata: dict[str, Any], rtol: float, atol: float, max_step: float) -> Any:
    evaluation_times = np.linspace(metadata["start"], metadata["end"], metadata["evaluation_points"])
    initial = np.asarray([record["initial"] for record in metadata["states"]], dtype=float)

    def derivative(time: float, state: np.ndarray) -> np.ndarray:
        values = _context(metadata, time, state)
        return np.asarray([
            _expression_value(metadata["equations"][name]["tree"], values, f"equation {name}")
            for name in metadata["state_names"]
        ])

    result = solve_ivp(
        derivative, (metadata["start"], metadata["end"]), initial, method=metadata["method"],
        t_eval=evaluation_times, rtol=rtol, atol=atol, max_step=max_step,
    )
    if not result.success:
        raise RuntimeError(f"ODE solver failed: {result.message}")
    if result.y.shape != (len(initial), len(evaluation_times)) or not np.array_equal(result.t, evaluation_times):
        raise RuntimeError("ODE solver did not return every requested evaluation point")
    if not np.isfinite(result.y).all():
        raise RuntimeError("ODE solver returned non-finite state values")
    if not np.allclose(result.y[:, 0], initial, rtol=0, atol=max(atol, 1e-14)):
        raise RuntimeError("ODE solver did not reproduce the declared initial conditions")
    for column, time in enumerate(result.t):
        derivative(time, result.y[:, column])
    return result


def _solver_record(label: str, result: Any, rtol: float, atol: float, max_step: float, primary: Any) -> dict[str, Any]:
    differences = np.abs(result.y - primary.y)
    return {
        "run": label, "rtol": rtol, "atol": atol, "max_step": max_step,
        "success": bool(result.success), "status": int(result.status), "message": str(result.message),
        "nfev": int(result.nfev), "njev": int(result.njev), "nlu": int(result.nlu),
        "maximum_trajectory_absolute_change": float(np.max(differences)),
        "maximum_endpoint_absolute_change": float(np.max(differences[:, -1])),
    }


def _write_plot(metadata: dict[str, Any], result: Any, output_path: Path) -> None:
    colors = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9"]
    markers = ["o", "s", "^", "D", "v", "P"]
    stride = max(1, metadata["evaluation_points"] // 18)
    with plt.rc_context({"figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white"}):
        figure, axis = plt.subplots(figsize=(7.2, 4.8), layout="constrained")
        for index, record in enumerate(metadata["states"]):
            axis.plot(result.t, result.y[index], color=colors[index % len(colors)], marker=markers[index % len(markers)], markevery=stride, markersize=3.5, linewidth=1.5, label=f"{record['name']} ({record['unit']})")
        axis.set_xlabel(f"Time ({metadata['time_unit']})")
        axis.set_ylabel("State value (see legend for units)")
        axis.grid(True, color="#D9D9D9", linewidth=0.6)
        axis.legend(frameon=True)
        figure.savefig(output_path, dpi=180, transparent=False)
        plt.close(figure)


def run(input_path: Path, output_dir: Path) -> dict[str, Any]:
    input_path = input_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists():
        raise ValueError("output directory already exists; choose a new path to preserve evidence")
    metadata = _parse_problem(_load_problem(input_path))
    primary = _solve(metadata, metadata["rtol"], metadata["atol"], metadata["max_step"])
    tighter = _solve(metadata, metadata["rtol"] * metadata["tolerance_factor"], metadata["atol"] * metadata["tolerance_factor"], metadata["max_step"])
    smaller_step = _solve(metadata, metadata["rtol"], metadata["atol"], metadata["max_step"] * metadata["max_step_factor"])

    solver_rows = [
        _solver_record("primary", primary, metadata["rtol"], metadata["atol"], metadata["max_step"], primary),
        _solver_record("tighter_tolerances", tighter, metadata["rtol"] * metadata["tolerance_factor"], metadata["atol"] * metadata["tolerance_factor"], metadata["max_step"], primary),
        _solver_record("smaller_max_step", smaller_step, metadata["rtol"], metadata["atol"], metadata["max_step"] * metadata["max_step_factor"], primary),
    ]
    trajectory_change = max(row["maximum_trajectory_absolute_change"] for row in solver_rows[1:])
    endpoint_change = max(row["maximum_endpoint_absolute_change"] for row in solver_rows[1:])
    sensitivity_passed = trajectory_change <= metadata["trajectory_absolute_tolerance"] and endpoint_change <= metadata["endpoint_absolute_tolerance"]

    invariant_rows: list[dict[str, Any]] = []
    invariant_summary: list[dict[str, Any]] = []
    for invariant in metadata["invariants"]:
        maximum_residual = 0.0
        for column, time in enumerate(primary.t):
            value = _expression_value(invariant["tree"], _context(metadata, time, primary.y[:, column]), f"invariant {invariant['name']}")
            residual = value - invariant["expected"]
            maximum_residual = max(maximum_residual, abs(residual))
            invariant_rows.append({"time": float(time), "invariant": invariant["name"], "value": value, "expected": invariant["expected"], "residual": residual, "absolute_residual": abs(residual), "tolerance": invariant["absolute_tolerance"], "unit": invariant["unit"], "passed": abs(residual) <= invariant["absolute_tolerance"]})
        invariant_summary.append({"name": invariant["name"], "expression": invariant["expression"], "expected": invariant["expected"], "unit": invariant["unit"], "source": invariant["source"], "absolute_tolerance": invariant["absolute_tolerance"], "maximum_absolute_residual": maximum_residual, "passed": maximum_residual <= invariant["absolute_tolerance"]})

    reference_rows: list[dict[str, Any]] = []
    reference_summary = None
    reference_passed = True
    if metadata["reference"] is not None:
        reference = metadata["reference"]
        maximum_absolute_error = 0.0
        maximum_relative_error = 0.0
        initial_context = {**metadata["parameter_values"], **{f"initial_{name}": value for name, value in metadata["initial_values"].items()}}
        for state_index, state in enumerate(metadata["state_names"]):
            tree = reference["expressions"][state]["tree"]
            for column, time in enumerate(primary.t):
                reference_value = _expression_value(tree, {**initial_context, "t": float(time)}, f"reference expression {state}")
                numerical = float(primary.y[state_index, column])
                absolute_error = abs(numerical - reference_value)
                relative_error = absolute_error / max(abs(reference_value), reference["absolute_tolerance"])
                maximum_absolute_error = max(maximum_absolute_error, absolute_error)
                maximum_relative_error = max(maximum_relative_error, relative_error)
                reference_rows.append({"time": float(time), "state": state, "numerical": numerical, "reference": reference_value, "absolute_error": absolute_error, "relative_error": relative_error, "unit": metadata["states"][state_index]["unit"]})
        reference_passed = maximum_absolute_error <= reference["absolute_tolerance"] and maximum_relative_error <= reference["relative_tolerance"]
        reference_summary = {"source": reference["source"], "absolute_tolerance": reference["absolute_tolerance"], "relative_tolerance": reference["relative_tolerance"], "maximum_absolute_error": maximum_absolute_error, "maximum_relative_error": maximum_relative_error, "passed": reference_passed}

    invariant_passed = all(record["passed"] for record in invariant_summary)
    success = sensitivity_passed and invariant_passed and reference_passed
    output_names = ["trajectory.csv", "invariant_check.csv", "solver_sensitivity.csv", "trajectory.png"]
    if metadata["reference"] is not None:
        output_names.append("reference_check.csv")
    evidence = {
        "input": str(input_path), "input_sha256": _sha256(input_path),
        "runtime": {"python": sys.version.split()[0], "numpy": np.__version__, "scipy": scipy.__version__, "matplotlib": matplotlib.__version__},
        "solver": f"scipy.integrate.solve_ivp(method={metadata['method']})",
        "claim_scope": "numerical initial-value trajectory under the declared equations, parameters, units, and time span",
        "time": {"start": metadata["start"], "end": metadata["end"], "evaluation_points": metadata["evaluation_points"], "unit": metadata["time_unit"]},
        "states": metadata["states"], "parameters": metadata["parameters"],
        "equations": [{"state": name, **{key: value for key, value in metadata["equations"][name].items() if key != "tree"}} for name in metadata["state_names"]],
        "primary_solver": solver_rows[0],
        "sensitivity": {"passed": sensitivity_passed, "endpoint_absolute_tolerance": metadata["endpoint_absolute_tolerance"], "trajectory_absolute_tolerance": metadata["trajectory_absolute_tolerance"], "maximum_endpoint_absolute_change": endpoint_change, "maximum_trajectory_absolute_change": trajectory_change},
        "invariants": invariant_summary, "reference_solution": reference_summary,
        "initial_conditions_reproduced": True, "finite_trajectory_and_derivatives": True,
        "success": success,
        "warnings": ["solver success does not validate the scientific meaning of the equations or parameters", "tolerance and max-step stability are numerical evidence, not parameter or structural uncertainty", "declared invariants require an independent derivation before they can support a conservation claim"],
        "outputs": sorted(output_names),
    }

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}-", dir=output_dir.parent))
    try:
        trajectory = {"time": primary.t}
        trajectory.update({name: primary.y[index] for index, name in enumerate(metadata["state_names"])})
        pd.DataFrame(trajectory).to_csv(temporary / "trajectory.csv", index=False)
        pd.DataFrame.from_records(invariant_rows, columns=["time", "invariant", "value", "expected", "residual", "absolute_residual", "tolerance", "unit", "passed"]).to_csv(temporary / "invariant_check.csv", index=False)
        pd.DataFrame.from_records(solver_rows).to_csv(temporary / "solver_sensitivity.csv", index=False)
        if metadata["reference"] is not None:
            pd.DataFrame.from_records(reference_rows).to_csv(temporary / "reference_check.csv", index=False)
        _write_plot(metadata, primary, temporary / "trajectory.png")
        (temporary / "run.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
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
        evidence = run(args.input, args.output)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if not evidence["success"]:
        print("ERROR: declared ODE validation thresholds were not met", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

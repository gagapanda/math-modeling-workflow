"""Run an auditable Monte Carlo uncertainty-propagation baseline."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm, t


ALLOWED_DISTRIBUTIONS = {
    "bernoulli",
    "constant",
    "exponential",
    "lognormal",
    "normal",
    "triangular",
    "uniform",
}
ALLOWED_BINARY_OPERATORS = {
    ast.Add: np.add,
    ast.Sub: np.subtract,
    ast.Mult: np.multiply,
    ast.Div: np.divide,
    ast.Pow: np.power,
}
ALLOWED_UNARY_OPERATORS = {
    ast.UAdd: lambda value: value,
    ast.USub: np.negative,
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


def _require_keys(
    parameters: dict, required: set[str], distribution: str
) -> None:
    missing = sorted(required - set(parameters))
    extra = sorted(set(parameters) - required)
    if missing:
        raise ValueError(
            f"{distribution} parameters missing: {', '.join(missing)}"
        )
    if extra:
        raise ValueError(
            f"{distribution} parameters not recognized: {', '.join(extra)}"
        )


def _validate_variable(raw: object, index: int) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"variables[{index}] must be an object")
    name = raw.get("name")
    if not isinstance(name, str) or not name.isidentifier():
        raise ValueError(
            f"variables[{index}].name must be a valid identifier"
        )
    distribution = raw.get("distribution")
    if distribution not in ALLOWED_DISTRIBUTIONS:
        allowed = ", ".join(sorted(ALLOWED_DISTRIBUTIONS))
        raise ValueError(
            f"variable {name} distribution must be one of: {allowed}"
        )
    source = raw.get("source")
    if not isinstance(source, str) or not source.strip():
        raise ValueError(
            f"variable {name} must declare a non-empty distribution source"
        )
    unit = raw.get("unit")
    if not isinstance(unit, str) or not unit.strip():
        raise ValueError(f"variable {name} must declare a non-empty unit")
    parameters = raw.get("parameters", {})
    if not isinstance(parameters, dict):
        raise ValueError(f"variable {name} parameters must be an object")

    required = {
        "constant": {"value"},
        "normal": {"mean", "std"},
        "uniform": {"low", "high"},
        "triangular": {"left", "mode", "right"},
        "exponential": {"scale"},
        "lognormal": {"mean_log", "sigma_log"},
        "bernoulli": {"probability"},
    }[distribution]
    _require_keys(parameters, required, distribution)
    values = {
        key: _finite_number(value, f"variable {name} parameter {key}")
        for key, value in parameters.items()
    }
    if distribution == "normal" and values["std"] <= 0:
        raise ValueError(f"variable {name} normal std must be positive")
    if distribution == "uniform" and values["low"] >= values["high"]:
        raise ValueError(
            f"variable {name} uniform low must be less than high"
        )
    if distribution == "triangular" and not (
        values["left"] <= values["mode"] <= values["right"]
        and values["left"] < values["right"]
    ):
        raise ValueError(
            f"variable {name} triangular parameters must satisfy "
            "left <= mode <= right and left < right"
        )
    if distribution == "exponential" and values["scale"] <= 0:
        raise ValueError(
            f"variable {name} exponential scale must be positive"
        )
    if distribution == "lognormal" and values["sigma_log"] <= 0:
        raise ValueError(
            f"variable {name} lognormal sigma_log must be positive"
        )
    if distribution == "bernoulli" and not (
        0 <= values["probability"] <= 1
    ):
        raise ValueError(
            f"variable {name} Bernoulli probability must be in [0, 1]"
        )
    return {
        **raw,
        "name": name,
        "distribution": distribution,
        "parameters": values,
    }


def _validate_expression(
    expression: object, variable_names: set[str]
) -> ast.Expression:
    if not isinstance(expression, str) or not expression.strip():
        raise ValueError("target.expression must be a non-empty string")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError(
            f"target.expression is invalid: {exc.msg}"
        ) from exc
    operator_nodes = tuple(ALLOWED_BINARY_OPERATORS) + tuple(
        ALLOWED_UNARY_OPERATORS
    )
    for node in ast.walk(tree):
        if isinstance(node, (ast.Expression, ast.Load)):
            continue
        if isinstance(node, ast.BinOp):
            if type(node.op) not in ALLOWED_BINARY_OPERATORS:
                raise ValueError(
                    "target.expression contains an unsupported operator"
                )
            continue
        if isinstance(node, ast.UnaryOp):
            if type(node.op) not in ALLOWED_UNARY_OPERATORS:
                raise ValueError(
                    "target.expression contains an unsupported unary operator"
                )
            continue
        if isinstance(node, operator_nodes):
            continue
        if isinstance(node, ast.Name):
            if node.id not in variable_names:
                raise ValueError(
                    "target.expression references unknown variable: "
                    f"{node.id}"
                )
            continue
        if isinstance(node, ast.Constant):
            _finite_number(node.value, "target.expression constant")
            continue
        raise ValueError(
            "target.expression contains forbidden syntax: "
            f"{type(node).__name__}"
        )
    return tree


def _evaluate(
    node: ast.AST, values: dict[str, np.ndarray]
) -> np.ndarray | float:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body, values)
    if isinstance(node, ast.Name):
        return values[node.id]
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.BinOp):
        operation = ALLOWED_BINARY_OPERATORS[type(node.op)]
        with np.errstate(all="ignore"):
            return operation(
                _evaluate(node.left, values),
                _evaluate(node.right, values),
            )
    if isinstance(node, ast.UnaryOp):
        operation = ALLOWED_UNARY_OPERATORS[type(node.op)]
        return operation(_evaluate(node.operand, values))
    raise AssertionError(
        f"unexpected expression node: {type(node).__name__}"
    )


def _sample(
    variable: dict, rng: np.random.Generator, size: int
) -> np.ndarray:
    distribution = variable["distribution"]
    parameters = variable["parameters"]
    if distribution == "constant":
        return np.full(size, parameters["value"], dtype=float)
    if distribution == "normal":
        return rng.normal(parameters["mean"], parameters["std"], size)
    if distribution == "uniform":
        return rng.uniform(parameters["low"], parameters["high"], size)
    if distribution == "triangular":
        return rng.triangular(
            parameters["left"],
            parameters["mode"],
            parameters["right"],
            size,
        )
    if distribution == "exponential":
        return rng.exponential(parameters["scale"], size)
    if distribution == "lognormal":
        return rng.lognormal(
            parameters["mean_log"], parameters["sigma_log"], size
        )
    if distribution == "bernoulli":
        return rng.binomial(
            1, parameters["probability"], size
        ).astype(float)
    raise AssertionError(f"unexpected distribution: {distribution}")


def _simulate(
    variables: list[dict],
    expression: ast.Expression,
    iterations: int,
    seed: int,
) -> tuple[dict[str, np.ndarray], np.ndarray]:
    rng = np.random.default_rng(seed)
    samples = {
        variable["name"]: _sample(variable, rng, iterations)
        for variable in variables
    }
    output = np.asarray(_evaluate(expression, samples), dtype=float)
    if output.ndim == 0:
        output = np.full(iterations, float(output), dtype=float)
    if output.shape != (iterations,):
        raise ValueError(
            "target.expression must produce one output per simulation iteration"
        )
    if not np.isfinite(output).all():
        raise ValueError(
            "target.expression produced non-finite outputs; "
            "check division, powers, and distribution support"
        )
    return samples, output


def _mean_interval(
    values: np.ndarray, confidence_level: float
) -> tuple[float, float, float]:
    mean = float(np.mean(values))
    standard_error = float(
        np.std(values, ddof=1) / math.sqrt(len(values))
    )
    critical = float(
        t.ppf((1 + confidence_level) / 2, df=len(values) - 1)
    )
    return mean, standard_error, critical * standard_error


def _wilson_interval(
    successes: int, total: int, confidence_level: float
) -> tuple[float, float]:
    probability = successes / total
    z = float(norm.ppf((1 + confidence_level) / 2))
    denominator = 1 + z * z / total
    center = (probability + z * z / (2 * total)) / denominator
    radius = (
        z
        * math.sqrt(
            probability * (1 - probability) / total
            + z * z / (4 * total * total)
        )
        / denominator
    )
    return center - radius, center + radius


def _threshold_mask(
    values: np.ndarray, operator: str, threshold: float
) -> np.ndarray:
    operation = {
        "<": np.less,
        "<=": np.less_equal,
        ">": np.greater,
        ">=": np.greater_equal,
    }[operator]
    return operation(values, threshold)


def _summary(
    values: np.ndarray,
    confidence_level: float,
    threshold: float | None,
    operator: str | None,
) -> dict:
    mean, standard_error, margin = _mean_interval(
        values, confidence_level
    )
    tail = (1 - confidence_level) / 2
    record: dict[str, object] = {
        "mean": mean,
        "standard_deviation": float(np.std(values, ddof=1)),
        "monte_carlo_standard_error": standard_error,
        "mean_confidence_lower": mean - margin,
        "mean_confidence_upper": mean + margin,
        "distribution_lower_quantile": float(
            np.quantile(values, tail)
        ),
        "median": float(np.median(values)),
        "distribution_upper_quantile": float(
            np.quantile(values, 1 - tail)
        ),
        "minimum": float(np.min(values)),
        "maximum": float(np.max(values)),
    }
    if threshold is not None and operator is not None:
        successes = int(
            _threshold_mask(values, operator, threshold).sum()
        )
        lower, upper = _wilson_interval(
            successes, len(values), confidence_level
        )
        record.update(
            {
                "threshold": threshold,
                "threshold_operator": operator,
                "threshold_event_count": successes,
                "threshold_probability": successes / len(values),
                "threshold_probability_confidence_lower": lower,
                "threshold_probability_confidence_upper": upper,
            }
        )
    return record


def _checkpoints(iterations: int, requested: int) -> list[int]:
    start = min(100, iterations)
    points = np.geomspace(
        start, iterations, num=requested, dtype=int
    )
    return sorted(set([start, *points.tolist(), iterations]))


def _validate_config(raw: object) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("input JSON must be an object")
    if "correlation" in raw or "correlations" in raw:
        raise ValueError(
            "correlated inputs are not supported by this baseline; "
            "use a validated joint sampler"
        )
    variables_raw = raw.get("variables")
    if not isinstance(variables_raw, list) or not variables_raw:
        raise ValueError("variables must be a non-empty array")
    variables = [
        _validate_variable(item, index)
        for index, item in enumerate(variables_raw)
    ]
    names = [variable["name"] for variable in variables]
    if len(names) != len(set(names)):
        raise ValueError("variable names must be unique")

    target = raw.get("target")
    if not isinstance(target, dict):
        raise ValueError("target must be an object")
    target_name = target.get("name")
    target_unit = target.get("unit")
    if not isinstance(target_name, str) or not target_name.strip():
        raise ValueError("target.name must be a non-empty string")
    if not isinstance(target_unit, str) or not target_unit.strip():
        raise ValueError("target.unit must be a non-empty string")
    expression = _validate_expression(
        target.get("expression"), set(names)
    )
    threshold = target.get("threshold")
    operator = target.get("threshold_operator")
    if (threshold is None) != (operator is None):
        raise ValueError(
            "target threshold and threshold_operator must be provided together"
        )
    if threshold is not None:
        threshold = _finite_number(threshold, "target.threshold")
        if operator not in {"<", "<=", ">", ">="}:
            raise ValueError(
                "target.threshold_operator must be <, <=, >, or >="
            )

    simulation = raw.get("simulation", {})
    if not isinstance(simulation, dict):
        raise ValueError("simulation must be an object")
    iterations = simulation.get("iterations", 10_000)
    seed = simulation.get("seed", 42)
    replications = simulation.get("replications", 4)
    confidence_level = simulation.get("confidence_level", 0.95)
    convergence_points = simulation.get("convergence_points", 12)
    sample_output_limit = simulation.get("sample_output_limit", 10_000)
    integer_fields = (
        (iterations, "iterations", 100, 5_000_000),
        (replications, "replications", 2, 100),
        (convergence_points, "convergence_points", 3, 100),
        (sample_output_limit, "sample_output_limit", 0, 100_000),
    )
    for value, label, minimum, maximum in integer_fields:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not minimum <= value <= maximum
        ):
            raise ValueError(
                f"simulation.{label} must be an integer "
                f"in [{minimum}, {maximum}]"
            )
    if (
        isinstance(seed, bool)
        or not isinstance(seed, int)
        or not 0 <= seed <= 2**32 - 1
    ):
        raise ValueError(
            "simulation.seed must be an integer in [0, 2^32 - 1]"
        )
    confidence_level = _finite_number(
        confidence_level, "simulation.confidence_level"
    )
    if not 0.5 < confidence_level < 1:
        raise ValueError(
            "simulation.confidence_level must be in (0.5, 1)"
        )

    analytical = raw.get("analytical", {})
    if not isinstance(analytical, dict):
        raise ValueError("analytical must be an object")
    allowed_analytical = {
        "expected_mean",
        "expected_threshold_probability",
    }
    unknown = sorted(set(analytical) - allowed_analytical)
    if unknown:
        raise ValueError(
            f"analytical fields not recognized: {', '.join(unknown)}"
        )
    analytical = {
        key: _finite_number(value, f"analytical.{key}")
        for key, value in analytical.items()
    }
    if (
        "expected_threshold_probability" in analytical
        and not 0
        <= analytical["expected_threshold_probability"]
        <= 1
    ):
        raise ValueError(
            "analytical.expected_threshold_probability must be in [0, 1]"
        )
    if (
        "expected_threshold_probability" in analytical
        and threshold is None
    ):
        raise ValueError(
            "analytical expected threshold probability requires "
            "a target threshold"
        )

    return {
        "variables": variables,
        "target": {
            **target,
            "name": target_name,
            "unit": target_unit,
            "threshold": threshold,
            "threshold_operator": operator,
        },
        "expression_tree": expression,
        "simulation": {
            "iterations": iterations,
            "seed": seed,
            "replications": replications,
            "confidence_level": confidence_level,
            "convergence_points": convergence_points,
            "sample_output_limit": sample_output_limit,
        },
        "analytical": analytical,
    }


def run(input_path: Path, output_dir: Path) -> dict:
    input_path = input_path.expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"input file not found: {input_path}")
    raw = json.loads(input_path.read_text(encoding="utf-8"))
    config = _validate_config(raw)
    variables = config["variables"]
    target = config["target"]
    simulation = config["simulation"]
    iterations = simulation["iterations"]
    confidence_level = simulation["confidence_level"]
    threshold = target["threshold"]
    operator = target["threshold_operator"]

    samples, output = _simulate(
        variables,
        config["expression_tree"],
        iterations,
        simulation["seed"],
    )
    summary = _summary(
        output, confidence_level, threshold, operator
    )
    convergence_records = []
    for count in _checkpoints(
        iterations, simulation["convergence_points"]
    ):
        convergence_records.append(
            {
                "iterations": count,
                **_summary(
                    output[:count],
                    confidence_level,
                    threshold,
                    operator,
                ),
            }
        )

    replication_records = []
    for index in range(simulation["replications"]):
        replication_seed = (simulation["seed"] + index) % (2**32)
        _, replication_output = _simulate(
            variables,
            config["expression_tree"],
            iterations,
            replication_seed,
        )
        replication_records.append(
            {
                "replication": index + 1,
                "seed": replication_seed,
                **_summary(
                    replication_output,
                    confidence_level,
                    threshold,
                    operator,
                ),
            }
        )

    analytical = config["analytical"]
    analytical_checks: dict[str, object] = {}
    if "expected_mean" in analytical:
        expected = analytical["expected_mean"]
        analytical_checks.update(
            {
                "expected_mean": expected,
                "mean_absolute_error": abs(
                    float(summary["mean"]) - expected
                ),
                "expected_mean_in_confidence_interval": bool(
                    summary["mean_confidence_lower"]
                    <= expected
                    <= summary["mean_confidence_upper"]
                ),
            }
        )
    if "expected_threshold_probability" in analytical:
        expected = analytical["expected_threshold_probability"]
        analytical_checks.update(
            {
                "expected_threshold_probability": expected,
                "threshold_probability_absolute_error": abs(
                    float(summary["threshold_probability"]) - expected
                ),
                "expected_threshold_probability_in_confidence_interval": bool(
                    summary["threshold_probability_confidence_lower"]
                    <= expected
                    <= summary[
                        "threshold_probability_confidence_upper"
                    ]
                ),
            }
        )

    warnings = ["input variables are sampled independently"]
    if iterations < 1_000:
        warnings.append(
            "fewer than 1000 iterations; Monte Carlo uncertainty may be large"
        )
    requested_sample_limit = simulation["sample_output_limit"]
    sample_count = min(iterations, requested_sample_limit)
    if sample_count < iterations:
        warnings.append(
            f"samples.csv is truncated to the first {sample_count} "
            f"of {iterations} iterations"
        )
    replication_means = np.array(
        [record["mean"] for record in replication_records],
        dtype=float,
    )
    replication_mean_range = float(
        np.max(replication_means) - np.min(replication_means)
    )

    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "target": target["name"],
                "unit": target["unit"],
                **summary,
            }
        ]
    ).to_csv(output_dir / "summary.csv", index=False)
    pd.DataFrame(convergence_records).to_csv(
        output_dir / "convergence.csv", index=False
    )
    pd.DataFrame(replication_records).to_csv(
        output_dir / "replications.csv", index=False
    )
    sample_frame = pd.DataFrame(
        {
            name: values[:sample_count]
            for name, values in samples.items()
        }
    )
    sample_frame[target["name"]] = output[:sample_count]
    sample_frame.insert(
        0, "iteration", np.arange(1, sample_count + 1)
    )
    sample_frame.to_csv(output_dir / "samples.csv", index=False)

    evidence = {
        "input": str(input_path),
        "input_sha256": _sha256(input_path),
        "method": "independent Monte Carlo sampling",
        "target": target,
        "variables": variables,
        "simulation": simulation,
        "summary": summary,
        "replication_mean_range": replication_mean_range,
        "analytical_checks": analytical_checks,
        "warnings": warnings,
        "outputs": [
            "summary.csv",
            "convergence.csv",
            "replications.csv",
            "samples.csv",
        ],
    }
    (output_dir / "run.json").write_text(
        json.dumps(
            evidence,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        run(args.input, args.output)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

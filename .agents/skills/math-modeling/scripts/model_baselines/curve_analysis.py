"""Fit and validate an auditable univariate curve with uncertainty intervals."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy
from numpy.polynomial import Polynomial
from scipy.interpolate import PchipInterpolator


CANDIDATE_DEGREES = {"linear": 1, "quadratic": 2, "cubic": 3}
COMPLEXITY_ORDER = {"linear": 1, "quadratic": 2, "cubic": 3, "pchip": 4}
ALLOWED_CANDIDATES = set(COMPLEXITY_ORDER)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _parse_candidates(value: str) -> list[str]:
    candidates = [item.strip().lower() for item in value.split(",") if item.strip()]
    if not candidates:
        raise ValueError("candidates cannot be empty")
    if len(candidates) != len(set(candidates)):
        raise ValueError("candidates must be unique")
    unknown = [item for item in candidates if item not in ALLOWED_CANDIDATES]
    if unknown:
        raise ValueError(f"unsupported candidate: {unknown[0]}")
    if "linear" not in candidates:
        raise ValueError("candidates must include the transparent linear baseline")
    return candidates


def _metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    residual = actual - predicted
    return {
        "mae": float(np.mean(np.abs(residual))),
        "rmse": float(np.sqrt(np.mean(residual**2))),
        "maximum_absolute_error": float(np.max(np.abs(residual))),
    }


def _fit_model(name: str, x: np.ndarray, y: np.ndarray) -> dict[str, Any]:
    if name in CANDIDATE_DEGREES:
        degree = CANDIDATE_DEGREES[name]
        if len(x) <= degree:
            raise ValueError(f"{name} requires more than {degree} fitting points")
        center = float(np.mean(x))
        scale = float((np.max(x) - np.min(x)) / 2)
        if not scale > 0:
            raise ValueError("x values must span a non-zero range")
        normalized = (x - center) / scale
        coefficients = np.polynomial.polynomial.polyfit(normalized, y, degree)
        if not np.isfinite(coefficients).all():
            raise ValueError(f"{name} fitting produced non-finite coefficients")
        return {
            "name": name,
            "center": center,
            "scale": scale,
            "coefficients": coefficients,
        }
    order = np.argsort(x, kind="stable")
    return {
        "name": "pchip",
        "x": x[order].copy(),
        "y": y[order].copy(),
    }


def _predict(model: dict[str, Any], x: np.ndarray) -> np.ndarray:
    if model["name"] in CANDIDATE_DEGREES:
        normalized = (x - model["center"]) / model["scale"]
        predicted = np.polynomial.polynomial.polyval(
            normalized, model["coefficients"]
        )
    else:
        interpolator = PchipInterpolator(model["x"], model["y"], extrapolate=False)
        predicted = interpolator(x)
    predicted = np.asarray(predicted, dtype=float)
    if predicted.shape != x.shape or not np.isfinite(predicted).all():
        raise ValueError(f"{model['name']} prediction left the interpolation range")
    return predicted


def _split_data(
    row_count: int, test_fraction: float, seed: int
) -> tuple[np.ndarray, np.ndarray]:
    test_count = max(3, int(math.ceil(row_count * test_fraction)))
    if row_count - test_count < 10:
        raise ValueError("test fraction must leave at least ten development rows")
    rng = np.random.default_rng(seed)
    interior = np.arange(1, row_count - 1, dtype=int)
    test = np.sort(rng.choice(interior, size=test_count, replace=False))
    development = np.setdiff1d(np.arange(row_count, dtype=int), test)
    return development, test


def _folds(development_count: int, fold_count: int, seed: int) -> list[np.ndarray]:
    if fold_count < 3:
        raise ValueError("folds must be at least three")
    interior = np.arange(1, development_count - 1, dtype=int)
    if len(interior) < fold_count:
        raise ValueError("folds exceed the available interior development points")
    rng = np.random.default_rng(seed + 1)
    return [np.sort(part) for part in np.array_split(rng.permutation(interior), fold_count)]


def _cross_validate(
    candidates: list[str],
    x: np.ndarray,
    y: np.ndarray,
    fold_indices: list[np.ndarray],
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    summaries: list[dict[str, Any]] = []
    residual_frames: dict[str, pd.DataFrame] = {}
    all_indices = np.arange(len(x), dtype=int)
    for candidate in candidates:
        records: list[dict[str, Any]] = []
        fold_rmse: list[float] = []
        for fold, validation in enumerate(fold_indices, start=1):
            train = np.setdiff1d(all_indices, validation)
            model = _fit_model(candidate, x[train], y[train])
            prediction = _predict(model, x[validation])
            residual = y[validation] - prediction
            fold_rmse.append(float(np.sqrt(np.mean(residual**2))))
            for position, predicted, error in zip(validation, prediction, residual):
                records.append(
                    {
                        "candidate": candidate,
                        "fold": fold,
                        "development_position": int(position),
                        "x": float(x[position]),
                        "actual": float(y[position]),
                        "prediction": float(predicted),
                        "residual": float(error),
                    }
                )
        frame = pd.DataFrame.from_records(records).sort_values(
            "development_position", ignore_index=True
        )
        metrics = _metrics(
            frame["actual"].to_numpy(), frame["prediction"].to_numpy()
        )
        fold_array = np.asarray(fold_rmse, dtype=float)
        summaries.append(
            {
                "candidate": candidate,
                "complexity_order": COMPLEXITY_ORDER[candidate],
                "cross_validation_points": len(frame),
                "cross_validation_mae": metrics["mae"],
                "cross_validation_rmse": metrics["rmse"],
                "mean_fold_rmse": float(np.mean(fold_array)),
                "fold_rmse_standard_deviation": float(
                    np.std(fold_array, ddof=1)
                ),
                "fold_rmse_standard_error": float(
                    np.std(fold_array, ddof=1) / math.sqrt(len(fold_array))
                ),
            }
        )
        residual_frames[candidate] = frame
    return pd.DataFrame.from_records(summaries), residual_frames


def _select_candidate(summary: pd.DataFrame) -> tuple[str, float, str]:
    best_index = summary["mean_fold_rmse"].idxmin()
    threshold = float(
        summary.loc[best_index, "mean_fold_rmse"]
        + summary.loc[best_index, "fold_rmse_standard_error"]
    )
    eligible = summary[summary["mean_fold_rmse"] <= threshold].sort_values(
        ["complexity_order", "mean_fold_rmse", "candidate"], ignore_index=True
    )
    selected = str(eligible.iloc[0]["candidate"])
    rule = (
        "lowest-complexity candidate within one standard error of the lowest "
        "mean fold RMSE"
    )
    return selected, threshold, rule


def _original_coefficients(model: dict[str, Any]) -> np.ndarray:
    normalized_x = Polynomial(
        [-model["center"] / model["scale"], 1 / model["scale"]]
    )
    return Polynomial(model["coefficients"])(normalized_x).coef


def _bootstrap(
    selected: str,
    x: np.ndarray,
    y: np.ndarray,
    residuals: np.ndarray,
    grid_x: np.ndarray,
    test_x: np.ndarray,
    iterations: int,
    confidence_level: float,
    seed: int,
) -> dict[str, Any]:
    if iterations < 200 or iterations > 10000:
        raise ValueError("bootstrap iterations must be from 200 to 10000")
    if not 0.8 <= confidence_level < 1:
        raise ValueError("confidence level must be from 0.8 up to but not including 1")
    base_model = _fit_model(selected, x, y)
    fitted = _predict(base_model, x)
    centered_residuals = residuals - float(np.mean(residuals))
    if len(centered_residuals) < 3 or not np.any(np.abs(centered_residuals) > 0):
        raise ValueError("cross-validation residuals do not support bootstrap intervals")
    rng = np.random.default_rng(seed + 2)
    grid_mean = np.empty((iterations, len(grid_x)), dtype=float)
    grid_prediction = np.empty_like(grid_mean)
    test_mean = np.empty((iterations, len(test_x)), dtype=float)
    test_prediction = np.empty_like(test_mean)
    parameter_samples: list[np.ndarray] = []
    for iteration in range(iterations):
        sampled = rng.choice(centered_residuals, size=len(x), replace=True)
        bootstrap_model = _fit_model(selected, x, fitted + sampled)
        grid_values = _predict(bootstrap_model, grid_x)
        test_values = _predict(bootstrap_model, test_x)
        grid_mean[iteration] = grid_values
        test_mean[iteration] = test_values
        grid_prediction[iteration] = grid_values + rng.choice(
            centered_residuals, size=len(grid_x), replace=True
        )
        test_prediction[iteration] = test_values + rng.choice(
            centered_residuals, size=len(test_x), replace=True
        )
        if selected in CANDIDATE_DEGREES:
            parameter_samples.append(_original_coefficients(bootstrap_model))
    tail = (1 - confidence_level) / 2
    quantiles = [tail, 1 - tail]
    result: dict[str, Any] = {
        "grid_mean": np.quantile(grid_mean, quantiles, axis=0),
        "grid_prediction": np.quantile(grid_prediction, quantiles, axis=0),
        "test_mean": np.quantile(test_mean, quantiles, axis=0),
        "test_prediction": np.quantile(test_prediction, quantiles, axis=0),
        "parameter_samples": None,
        "centered_residual_standard_deviation": float(
            np.std(centered_residuals, ddof=1)
        ),
    }
    if parameter_samples:
        result["parameter_samples"] = np.vstack(parameter_samples)
    return result


def _correlation(left: np.ndarray, right: np.ndarray) -> float | None:
    if np.std(left) == 0 or np.std(right) == 0:
        return None
    value = float(np.corrcoef(left, right)[0, 1])
    return value if math.isfinite(value) else None


def _write_plot(
    development: pd.DataFrame,
    test: pd.DataFrame,
    curve: pd.DataFrame,
    residuals: pd.DataFrame,
    x_column: str,
    y_column: str,
    x_unit: str,
    y_unit: str,
    selected: str,
    path: Path,
) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(7.2, 6.2), sharex=True)
    axes[0].fill_between(
        curve["x"], curve["prediction_lower"], curve["prediction_upper"],
        color="#D8DEE9", label="Prediction interval"
    )
    axes[0].fill_between(
        curve["x"], curve["mean_lower"], curve["mean_upper"],
        color="#88C0D0", label="Mean-response interval"
    )
    axes[0].plot(curve["x"], curve["fitted"], color="#2E3440", label=selected)
    axes[0].scatter(development["x"], development["y"], s=19, color="#5E81AC", label="Development")
    axes[0].scatter(test["x"], test["actual"], s=28, marker="x", color="#BF616A", label="Held-out test")
    axes[0].set_ylabel(f"{y_column} ({y_unit})")
    axes[0].legend(frameon=False, ncol=2)
    axes[0].grid(alpha=0.2)
    axes[1].axhline(0, color="#2E3440", linewidth=1)
    axes[1].scatter(residuals["x"], residuals["residual"], s=20, color="#B48EAD")
    axes[1].set_xlabel(f"{x_column} ({x_unit})")
    axes[1].set_ylabel(f"CV residual ({y_unit})")
    axes[1].grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def run(
    input_path: Path,
    output_dir: Path,
    x_column: str,
    y_column: str,
    x_unit: str,
    y_unit: str,
    source_note: str,
    candidates_arg: str,
    test_fraction: float,
    folds: int,
    bootstrap_iterations: int,
    confidence_level: float,
    seed: int,
    grid_points: int,
) -> dict[str, Any]:
    input_path = input_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"input file not found: {input_path}")
    if output_dir.exists():
        raise ValueError(f"output directory already exists: {output_dir}")
    x_column = _text(x_column, "x column")
    y_column = _text(y_column, "y column")
    x_unit = _text(x_unit, "x unit")
    y_unit = _text(y_unit, "y unit")
    source_note = _text(source_note, "source note")
    if x_column == y_column:
        raise ValueError("x and y columns must be different")
    if not 0 < test_fraction < 0.5:
        raise ValueError("test fraction must be greater than zero and less than 0.5")
    if grid_points < 50 or grid_points > 5000:
        raise ValueError("grid points must be from 50 to 5000")
    candidates = _parse_candidates(candidates_arg)
    frame = pd.read_csv(input_path)
    missing = [column for column in (x_column, y_column) if column not in frame.columns]
    if missing:
        raise ValueError(f"missing column: {missing[0]}")
    numeric = frame[[x_column, y_column]].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any() or not np.isfinite(numeric.to_numpy()).all():
        raise ValueError("x and y must contain complete finite numeric values")
    if len(numeric) < 15:
        raise ValueError("curve analysis requires at least fifteen rows")
    if numeric[x_column].duplicated().any():
        raise ValueError("x values must be unique; repeated measurements require an explicit aggregation or measurement model")
    sorted_frame = numeric.sort_values(x_column, kind="stable").reset_index(names="source_row")
    x = sorted_frame[x_column].to_numpy(dtype=float)
    y = sorted_frame[y_column].to_numpy(dtype=float)
    if not np.all(np.diff(x) > 0):
        raise ValueError("x values must be strictly increasing after sorting")
    development_index, test_index = _split_data(len(sorted_frame), test_fraction, seed)
    development = sorted_frame.iloc[development_index].reset_index(drop=True)
    test = sorted_frame.iloc[test_index].reset_index(drop=True)
    dev_x = development[x_column].to_numpy(dtype=float)
    dev_y = development[y_column].to_numpy(dtype=float)
    test_x = test[x_column].to_numpy(dtype=float)
    test_y = test[y_column].to_numpy(dtype=float)
    fold_indices = _folds(len(development), folds, seed)
    candidate_summary, residual_frames = _cross_validate(
        candidates, dev_x, dev_y, fold_indices
    )
    selected, selection_threshold, selection_rule = _select_candidate(candidate_summary)
    candidate_summary["selected"] = candidate_summary["candidate"] == selected
    candidate_summary["one_standard_error_threshold"] = selection_threshold
    model = _fit_model(selected, dev_x, dev_y)
    linear_model = _fit_model("linear", dev_x, dev_y)
    test_prediction = _predict(model, test_x)
    linear_test_prediction = _predict(linear_model, test_x)
    test_metrics = _metrics(test_y, test_prediction)
    linear_test_metrics = _metrics(test_y, linear_test_prediction)
    selected_residuals = residual_frames[selected].copy()
    grid_x = np.linspace(float(dev_x.min()), float(dev_x.max()), grid_points)
    bootstrap = _bootstrap(
        selected, dev_x, dev_y, selected_residuals["residual"].to_numpy(),
        grid_x, test_x, bootstrap_iterations, confidence_level, seed
    )
    fitted_grid = _predict(model, grid_x)
    curve = pd.DataFrame(
        {
            "x": grid_x,
            "fitted": fitted_grid,
            "mean_lower": bootstrap["grid_mean"][0],
            "mean_upper": bootstrap["grid_mean"][1],
            "prediction_lower": bootstrap["grid_prediction"][0],
            "prediction_upper": bootstrap["grid_prediction"][1],
            "x_unit": x_unit,
            "y_unit": y_unit,
            "range_class": "interpolation_within_development_range",
        }
    )
    test_output = pd.DataFrame(
        {
            "source_row": test["source_row"].astype(int),
            "x": test_x,
            "actual": test_y,
            "prediction": test_prediction,
            "linear_baseline_prediction": linear_test_prediction,
            "residual": test_y - test_prediction,
            "mean_lower": bootstrap["test_mean"][0],
            "mean_upper": bootstrap["test_mean"][1],
            "prediction_lower": bootstrap["test_prediction"][0],
            "prediction_upper": bootstrap["test_prediction"][1],
        }
    ).sort_values("x", ignore_index=True)
    test_output["inside_prediction_interval"] = (
        (test_output["actual"] >= test_output["prediction_lower"])
        & (test_output["actual"] <= test_output["prediction_upper"])
    )
    selected_residuals["x_unit"] = x_unit
    selected_residuals["y_unit"] = y_unit
    parameter_rows: list[dict[str, Any]] = []
    if selected in CANDIDATE_DEGREES:
        estimates = _original_coefficients(model)
        samples = bootstrap["parameter_samples"]
        tail = (1 - confidence_level) / 2
        bounds = np.quantile(samples, [tail, 1 - tail], axis=0)
        for power, estimate in enumerate(estimates):
            parameter_rows.append(
                {
                    "parameter": f"x_power_{power}",
                    "power": power,
                    "estimate": float(estimate),
                    "confidence_lower": float(bounds[0, power]),
                    "confidence_upper": float(bounds[1, power]),
                    "unit": y_unit if power == 0 else f"{y_unit}/({x_unit}^{power})",
                }
            )
    parameter_frame = pd.DataFrame.from_records(
        parameter_rows,
        columns=["parameter", "power", "estimate", "confidence_lower", "confidence_upper", "unit"],
    )
    cv_fitted = selected_residuals["prediction"].to_numpy(dtype=float)
    cv_residual = selected_residuals["residual"].to_numpy(dtype=float)
    evidence = {
        "input": str(input_path),
        "input_sha256": _sha256(input_path),
        "runtime": {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scipy": scipy.__version__,
            "matplotlib": matplotlib.__version__,
        },
        "claim_scope": "univariate interpolation-range curve comparison and held-out prediction under the declared columns, units, split, and residual-bootstrap assumptions",
        "columns": {"x": x_column, "y": y_column},
        "units": {"x": x_unit, "y": y_unit},
        "source_note": source_note,
        "rows": len(sorted_frame),
        "development_rows": len(development),
        "test_rows": len(test),
        "split": {
            "method": "fixed-seed random interior holdout with both observed endpoints retained in development",
            "test_fraction": test_fraction,
            "seed": seed,
            "development_x_range": [float(dev_x.min()), float(dev_x.max())],
            "all_test_points_within_development_range": bool(
                np.all((test_x >= dev_x.min()) & (test_x <= dev_x.max()))
            ),
        },
        "candidates": candidates,
        "cross_validation_folds": folds,
        "selection": {
            "selected_candidate": selected,
            "rule": selection_rule,
            "one_standard_error_threshold": selection_threshold,
        },
        "held_out_test_metrics": test_metrics,
        "linear_baseline_test_metrics": linear_test_metrics,
        "beats_linear_baseline_test_rmse": test_metrics["rmse"] < linear_test_metrics["rmse"],
        "uncertainty": {
            "method": "fixed-x cross-validation residual bootstrap",
            "iterations": bootstrap_iterations,
            "confidence_level": confidence_level,
            "cross_validation_residual_standard_deviation": bootstrap["centered_residual_standard_deviation"],
            "test_prediction_interval_empirical_coverage": float(
                test_output["inside_prediction_interval"].mean()
            ),
            "parameter_intervals_available": bool(parameter_rows),
            "assumption": "cross-validation residuals are exchangeable over the fitted range; intervals are conditional on the selected model and observed x values",
        },
        "residual_diagnostics": {
            "cross_validation_residual_mean": float(np.mean(cv_residual)),
            "cross_validation_residual_standard_deviation": float(np.std(cv_residual, ddof=1)),
            "maximum_absolute_cross_validation_residual": float(np.max(np.abs(cv_residual))),
            "residual_fitted_pearson_correlation": _correlation(cv_residual, cv_fitted),
            "absolute_residual_x_pearson_correlation": _correlation(np.abs(cv_residual), selected_residuals["x"].to_numpy(dtype=float)),
        },
        "warnings": [
            "intervals quantify residual-bootstrap uncertainty conditional on the selected candidate and do not include measurement-error, structural, or definition uncertainty",
            "the curve grid is restricted to the observed development range; this run does not validate extrapolation",
            "held-out performance supports only the declared split and data-generating context, not causality",
            "repeated x values require an explicit measurement or aggregation model and are not silently averaged",
        ],
        "outputs": [
            "candidate_metrics.csv", "cross_validation_residuals.csv",
            "curve.csv", "test_predictions.csv", "model_parameters.csv",
            "fit_diagnostics.png"
        ],
    }
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}-", dir=output_dir.parent))
    try:
        candidate_summary.to_csv(temporary / "candidate_metrics.csv", index=False)
        selected_residuals.to_csv(temporary / "cross_validation_residuals.csv", index=False)
        curve.to_csv(temporary / "curve.csv", index=False)
        test_output.to_csv(temporary / "test_predictions.csv", index=False)
        parameter_frame.to_csv(temporary / "model_parameters.csv", index=False)
        _write_plot(
            development.rename(columns={x_column: "x", y_column: "y"}),
            test_output, curve, selected_residuals, x_column, y_column, x_unit, y_unit,
            selected, temporary / "fit_diagnostics.png"
        )
        (temporary / "run.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, output_dir)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--x-column", required=True)
    parser.add_argument("--y-column", required=True)
    parser.add_argument("--x-unit", required=True)
    parser.add_argument("--y-unit", required=True)
    parser.add_argument("--source-note", required=True)
    parser.add_argument("--candidates", default="linear,quadratic,cubic,pchip")
    parser.add_argument("--test-fraction", type=float, default=0.2)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--bootstrap-iterations", type=int, default=1000)
    parser.add_argument("--confidence-level", type=float, default=0.95)
    parser.add_argument("--seed", type=int, default=20260817)
    parser.add_argument("--grid-points", type=int, default=201)
    args = parser.parse_args()
    try:
        run(
            args.input, args.output, args.x_column, args.y_column, args.x_unit,
            args.y_unit, args.source_note, args.candidates, args.test_fraction,
            args.folds, args.bootstrap_iterations, args.confidence_level, args.seed,
            args.grid_points
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

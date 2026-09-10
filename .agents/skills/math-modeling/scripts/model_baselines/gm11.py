"""Fit an auditable GM(1,1) small-sample forecasting baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_values(values: np.ndarray, minimum_length: int = 4) -> None:
    if values.ndim != 1:
        raise ValueError("values must be a one-dimensional sequence")
    if len(values) < minimum_length:
        raise ValueError(f"GM(1,1) requires at least {minimum_length} observations")
    if not np.isfinite(values).all():
        raise ValueError("GM(1,1) requires finite sequence values")
    if (values <= 0).any():
        raise ValueError("GM(1,1) requires strictly positive sequence values")


def fit(values: np.ndarray) -> tuple[float, float, np.ndarray]:
    """Estimate a and b, returning fitted values on the original scale."""
    values = np.asarray(values, dtype=float)
    _validate_values(values)
    accumulated = np.cumsum(values)
    background = 0.5 * (accumulated[1:] + accumulated[:-1])
    design = np.column_stack((-background, np.ones(len(background))))
    a, b = np.linalg.lstsq(design, values[1:], rcond=None)[0]
    return float(a), float(b), forecast(values[0], a, b, len(values))


def forecast(first_value: float, a: float, b: float, periods: int) -> np.ndarray:
    if periods < 1:
        raise ValueError("forecast periods must be positive")
    if first_value <= 0 or not np.isfinite(first_value):
        raise ValueError("first_value must be finite and positive")
    index = np.arange(periods, dtype=float)
    if abs(a) < 1e-12:
        accumulated = first_value + b * index
    else:
        accumulated = (first_value - b / a) * np.exp(-a * index) + b / a
    values = np.empty(periods, dtype=float)
    values[0] = first_value
    values[1:] = np.diff(accumulated)
    return values


def _mape(actual: np.ndarray, predicted: np.ndarray) -> float:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    usable = actual != 0
    if not usable.any():
        return float("nan")
    return float(np.mean(np.abs((actual[usable] - predicted[usable]) / actual[usable])) * 100)


def _precision_grade(mape: float) -> str:
    if not np.isfinite(mape):
        return "not_available"
    if mape < 1:
        return "excellent"
    if mape < 5:
        return "good"
    if mape < 10:
        return "acceptable"
    return "poor"


def rolling_validation(values: np.ndarray, minimum_train: int = 4) -> pd.DataFrame:
    values = np.asarray(values, dtype=float)
    if minimum_train < 4:
        raise ValueError("minimum_train must be at least 4")
    _validate_values(values, minimum_train)
    records: list[dict[str, float | int | bool]] = []
    for origin in range(minimum_train, len(values)):
        train = values[:origin]
        a, b, _ = fit(train)
        gm_prediction = float(forecast(train[0], a, b, origin + 1)[-1])
        naive_prediction = float(train[-1])
        actual = float(values[origin])
        gm_error = abs((actual - gm_prediction) / actual) * 100
        naive_error = abs((actual - naive_prediction) / actual) * 100
        records.append(
            {
                "origin": origin,
                "actual": actual,
                "gm11_forecast": gm_prediction,
                "naive_forecast": naive_prediction,
                "gm11_abs_pct_error": gm_error,
                "naive_abs_pct_error": naive_error,
                "gm11_better": gm_error < naive_error,
            }
        )
    return pd.DataFrame.from_records(records)


def run(
    input_path: Path,
    output_dir: Path,
    column: str,
    periods: int = 3,
    minimum_train: int = 4,
) -> dict:
    input_path = input_path.expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"input file not found: {input_path}")
    if periods < 1:
        raise ValueError("periods must be positive")
    if minimum_train < 4:
        raise ValueError("minimum_train must be at least 4")
    frame = pd.read_csv(input_path)
    if column not in frame.columns:
        raise ValueError(f"missing sequence column: {column}")
    values = pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=float)
    _validate_values(values, minimum_train)
    a, b, fitted = fit(values)
    all_values = forecast(values[0], a, b, len(values) + periods)
    residuals = values - fitted
    result = pd.DataFrame(
        {
            "step": np.arange(1, len(values) + periods + 1),
            "actual": list(values) + [np.nan] * periods,
            "gm11_value": all_values,
            "type": ["fitted"] * len(values) + ["forecast"] * periods,
        }
    )
    result["residual"] = result["actual"] - result["gm11_value"]
    validation = rolling_validation(values, minimum_train)
    fit_mape = _mape(values, fitted)
    s1 = float(np.std(values, ddof=1)) if len(values) > 1 else float("nan")
    s2 = float(np.std(residuals, ddof=1)) if len(residuals) > 1 else float("nan")
    posterior_ratio = s2 / s1 if s1 > 0 else float("nan")
    differences = np.diff(values)
    signs = set(np.sign(differences[differences != 0]))
    warnings: list[str] = []
    if len(signs) > 1:
        warnings.append("sequence is not monotonic; short-horizon use requires extra scrutiny")
    if periods > max(1, len(values) // 2):
        warnings.append("forecast horizon exceeds half the observed sequence length")
    if validation.empty:
        warnings.append("rolling validation is unavailable because no holdout observation remains")
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_dir / "gm11_forecast.csv", index=False)
    validation.to_csv(output_dir / "rolling_validation.csv", index=False)
    rolling_gm11_mape = (
        float(validation["gm11_abs_pct_error"].mean()) if not validation.empty else None
    )
    rolling_naive_mape = (
        float(validation["naive_abs_pct_error"].mean()) if not validation.empty else None
    )
    evidence = {
        "input": str(input_path),
        "input_sha256": _sha256(input_path),
        "column": column,
        "observations": len(values),
        "periods": periods,
        "minimum_train": minimum_train,
        "a": a,
        "b": b,
        "fit_mape_percent": fit_mape,
        "posterior_error_ratio_c": posterior_ratio if np.isfinite(posterior_ratio) else None,
        "precision_grade": _precision_grade(fit_mape),
        "rolling_validation_points": len(validation),
        "rolling_gm11_mape_percent": rolling_gm11_mape,
        "rolling_naive_mape_percent": rolling_naive_mape,
        "rolling_gm11_better_count": int(validation["gm11_better"].sum()) if not validation.empty else 0,
        "warnings": warnings,
        "outputs": ["gm11_forecast.csv", "rolling_validation.csv"],
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
    parser.add_argument("--column", required=True)
    parser.add_argument("--periods", type=int, default=3)
    parser.add_argument("--minimum-train", type=int, default=4)
    args = parser.parse_args()
    try:
        run(args.input, args.output, args.column, args.periods, args.minimum_train)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

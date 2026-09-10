"""Run auditable univariate time-series baselines with rolling validation."""

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


def _validate_parameters(window: int, alpha: float, minimum_train: int, periods: int) -> None:
    if window < 1:
        raise ValueError("window must be positive")
    if not 0 < alpha <= 1 or not np.isfinite(alpha):
        raise ValueError("alpha must be finite and in (0, 1]")
    if minimum_train < 3:
        raise ValueError("minimum_train must be at least 3")
    if window > minimum_train:
        raise ValueError("window cannot exceed minimum_train")
    if periods < 1:
        raise ValueError("periods must be positive")


def _parse_time(values: pd.Series) -> tuple[np.ndarray, str, np.ndarray]:
    if values.isna().any():
        raise ValueError("time column must not contain missing values")
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().all():
        parsed = numeric.to_numpy(dtype=float)
        if not np.isfinite(parsed).all():
            raise ValueError("time column must contain finite values")
        return parsed, "numeric", parsed
    datetimes = pd.to_datetime(values, errors="coerce", utc=True)
    if datetimes.isna().any():
        raise ValueError("time column must be entirely numeric or datetime-like")
    comparable = datetimes.astype("int64").to_numpy(dtype=np.int64)
    return comparable, "datetime", datetimes.to_numpy()


def _validate_series(times: np.ndarray, values: np.ndarray, minimum_train: int) -> None:
    if len(values) <= minimum_train:
        raise ValueError("series must leave at least one observation for rolling validation")
    if not np.isfinite(values).all():
        raise ValueError("value column must contain complete finite numeric values")
    differences = np.diff(times)
    if (differences == 0).any():
        raise ValueError("time column must contain unique values")
    if (differences < 0).any():
        raise ValueError("time column must be strictly increasing in input order")


def _ses_level(values: np.ndarray, alpha: float) -> float:
    level = float(values[0])
    for value in values[1:]:
        level = alpha * float(value) + (1 - alpha) * level
    return level


def rolling_validation(
    times: np.ndarray,
    values: np.ndarray,
    window: int,
    alpha: float,
    minimum_train: int,
) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for origin in range(minimum_train, len(values)):
        train = values[:origin]
        actual = float(values[origin])
        records.append(
            {
                "origin": origin,
                "time": times[origin],
                "actual": actual,
                "persistence": float(train[-1]),
                "moving_average": float(np.mean(train[-window:])),
                "exp_smoothing": _ses_level(train, alpha),
            }
        )
    result = pd.DataFrame.from_records(records)
    for model in ("persistence", "moving_average", "exp_smoothing"):
        result[f"{model}_error"] = result["actual"] - result[model]
    return result


def _metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float | int | None]:
    error = actual - predicted
    nonzero = actual != 0
    mape = (
        float(np.mean(np.abs(error[nonzero] / actual[nonzero])) * 100)
        if nonzero.any()
        else None
    )
    return {
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error**2))),
        "mape_percent": mape,
        "mape_used_count": int(nonzero.sum()),
        "zero_actuals_excluded_from_mape": int((~nonzero).sum()),
    }


def _future_times(
    comparable_times: np.ndarray,
    parsed_times: np.ndarray,
    time_kind: str,
    periods: int,
) -> tuple[list[object], bool]:
    differences = np.diff(comparable_times)
    step = differences[-1]
    regular = bool(np.allclose(differences, step, rtol=1e-9, atol=0))
    if time_kind == "numeric":
        last = float(parsed_times[-1])
        return [last + float(step) * offset for offset in range(1, periods + 1)], regular
    last = pd.Timestamp(parsed_times[-1])
    delta = pd.to_timedelta(int(step), unit="ns")
    return [str(last + delta * offset) for offset in range(1, periods + 1)], regular


def _recursive_moving_average(values: np.ndarray, window: int, periods: int) -> list[float]:
    history = [float(value) for value in values]
    forecasts: list[float] = []
    for _ in range(periods):
        prediction = float(np.mean(history[-window:]))
        forecasts.append(prediction)
        history.append(prediction)
    return forecasts


def run(
    input_path: Path,
    output_dir: Path,
    time_column: str,
    value_column: str,
    window: int = 3,
    alpha: float = 0.4,
    minimum_train: int = 5,
    periods: int = 3,
) -> dict:
    _validate_parameters(window, alpha, minimum_train, periods)
    input_path = input_path.expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"input file not found: {input_path}")
    frame = pd.read_csv(input_path)
    missing = [column for column in (time_column, value_column) if column not in frame.columns]
    if missing:
        raise ValueError(f"missing columns: {', '.join(missing)}")
    if time_column == value_column:
        raise ValueError("time column and value column must be different")
    comparable_times, time_kind, parsed_times = _parse_time(frame[time_column])
    numeric_values = pd.to_numeric(frame[value_column], errors="coerce")
    values = numeric_values.to_numpy(dtype=float)
    _validate_series(comparable_times, values, minimum_train)

    output_times = (
        parsed_times.astype(float)
        if time_kind == "numeric"
        else np.array([str(pd.Timestamp(value)) for value in parsed_times], dtype=object)
    )
    validation = rolling_validation(
        output_times, values, window, alpha, minimum_train
    )
    models = ("persistence", "moving_average", "exp_smoothing")
    metric_records = []
    metrics_by_model: dict[str, dict[str, float | int | None]] = {}
    actual = validation["actual"].to_numpy(dtype=float)
    for model in models:
        model_metrics = _metrics(actual, validation[model].to_numpy(dtype=float))
        metrics_by_model[model] = model_metrics
        metric_records.append({"model": model, **model_metrics})
    best_model = min(models, key=lambda name: float(metrics_by_model[name]["rmse"]))

    future_times, regular_intervals = _future_times(
        comparable_times, parsed_times, time_kind, periods
    )
    future = pd.DataFrame(
        {
            "step_ahead": np.arange(1, periods + 1),
            "time": future_times,
            "persistence": [float(values[-1])] * periods,
            "moving_average": _recursive_moving_average(values, window, periods),
            "exp_smoothing": [_ses_level(values, alpha)] * periods,
        }
    )
    future["selected_model"] = best_model
    future["selected_forecast"] = future[best_model]

    warnings: list[str] = []
    if not regular_intervals:
        warnings.append(
            "time intervals are irregular; future timestamps extend the last observed interval"
        )
    if periods > max(1, len(values) // 2):
        warnings.append("forecast horizon exceeds half the observed series length")
    zero_count = int((actual == 0).sum())
    if zero_count:
        warnings.append(
            f"MAPE excludes {zero_count} rolling validation observations with zero actual values"
        )

    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    validation.to_csv(output_dir / "rolling_predictions.csv", index=False)
    pd.DataFrame(metric_records).to_csv(output_dir / "metrics.csv", index=False)
    future.to_csv(output_dir / "future_forecast.csv", index=False)
    evidence = {
        "input": str(input_path),
        "input_sha256": _sha256(input_path),
        "time_column": time_column,
        "time_kind": time_kind,
        "value_column": value_column,
        "observations": len(values),
        "window": window,
        "alpha": alpha,
        "minimum_train": minimum_train,
        "periods": periods,
        "rolling_validation_points": len(validation),
        "metrics": metrics_by_model,
        "best_rolling_rmse_model": best_model,
        "moving_average_beats_persistence_rmse": (
            metrics_by_model["moving_average"]["rmse"]
            < metrics_by_model["persistence"]["rmse"]
        ),
        "exp_smoothing_beats_persistence_rmse": (
            metrics_by_model["exp_smoothing"]["rmse"]
            < metrics_by_model["persistence"]["rmse"]
        ),
        "regular_time_intervals": regular_intervals,
        "future_time_rule": "extend_last_observed_interval",
        "warnings": warnings,
        "outputs": [
            "rolling_predictions.csv",
            "metrics.csv",
            "future_forecast.csv",
        ],
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
    parser.add_argument("--time-column", required=True)
    parser.add_argument("--value-column", required=True)
    parser.add_argument("--window", type=int, default=3)
    parser.add_argument("--alpha", type=float, default=0.4)
    parser.add_argument("--minimum-train", type=int, default=5)
    parser.add_argument("--periods", type=int, default=3)
    args = parser.parse_args()
    try:
        run(
            args.input,
            args.output,
            args.time_column,
            args.value_column,
            args.window,
            args.alpha,
            args.minimum_train,
            args.periods,
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

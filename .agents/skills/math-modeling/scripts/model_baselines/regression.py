"""Train an auditable numeric regression baseline with explicit split semantics."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.dummy import DummyRegressor
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupShuffleSplit, train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _csv_items(value: str) -> list[str]:
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items:
        raise ValueError("features cannot be empty")
    if len(set(items)) != len(items):
        raise ValueError("features must be unique")
    return items


def _metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float | None]:
    rmse = float(np.sqrt(mean_squared_error(actual, predicted)))
    r2 = float(r2_score(actual, predicted)) if len(actual) >= 2 else float("nan")
    return {
        "mae": float(mean_absolute_error(actual, predicted)),
        "rmse": rmse,
        "r2": r2 if np.isfinite(r2) else None,
    }


def _split_indices(
    frame: pd.DataFrame,
    split: str,
    test_size: float,
    seed: int,
    group_column: str | None,
) -> tuple[np.ndarray, np.ndarray, dict]:
    indices = np.arange(len(frame), dtype=int)
    if split == "time":
        test_count = max(1, int(math.ceil(len(frame) * test_size)))
        if len(frame) - test_count < 2:
            raise ValueError("time split must leave at least two training rows")
        return indices[:-test_count], indices[-test_count:], {"time_order": "input_row_order"}
    if split == "group":
        if group_column is None:
            raise ValueError("group split requires --group-column")
        if group_column not in frame.columns:
            raise ValueError(f"missing group column: {group_column}")
        groups = frame[group_column]
        if groups.isna().any() or groups.nunique() < 2:
            raise ValueError("group column requires at least two non-missing groups")
        splitter = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=seed)
        train, test = next(splitter.split(indices, groups=groups))
        train_groups = sorted(str(value) for value in groups.iloc[train].unique())
        test_groups = sorted(str(value) for value in groups.iloc[test].unique())
        if set(train_groups) & set(test_groups):
            raise RuntimeError("group leakage detected after split")
        return train, test, {"train_groups": train_groups, "test_groups": test_groups}
    train, test = train_test_split(indices, test_size=test_size, random_state=seed)
    return np.sort(train), np.sort(test), {}


def run(
    input_path: Path,
    output_dir: Path,
    target: str,
    features_arg: str,
    model_name: str = "linear",
    split: str = "random",
    test_size: float = 0.25,
    seed: int = 42,
    group_column: str | None = None,
    alpha: float = 1.0,
) -> dict:
    input_path = input_path.expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"input file not found: {input_path}")
    if not 0 < test_size < 1:
        raise ValueError("test_size must be between 0 and 1")
    if model_name not in {"linear", "ridge"}:
        raise ValueError("model must be linear or ridge")
    if split not in {"random", "time", "group"}:
        raise ValueError("split must be random, time, or group")
    if alpha < 0 or not np.isfinite(alpha):
        raise ValueError("alpha must be finite and non-negative")
    frame = pd.read_csv(input_path)
    features = _csv_items(features_arg)
    required = features + [target]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"missing columns: {', '.join(missing)}")
    if target in features:
        raise ValueError("target cannot also be a feature")
    numeric = frame[required].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any():
        raise ValueError("features and target must contain complete numeric values")
    if len(numeric) < 6:
        raise ValueError("regression baseline requires at least six rows")
    train_index, test_index, split_evidence = _split_indices(
        frame, split, test_size, seed, group_column
    )
    x_train = numeric.iloc[train_index][features]
    x_test = numeric.iloc[test_index][features]
    y_train = numeric.iloc[train_index][target]
    y_test = numeric.iloc[test_index][target]
    estimator = LinearRegression() if model_name == "linear" else Ridge(alpha=alpha)
    model = make_pipeline(StandardScaler(), estimator)
    model.fit(x_train, y_train)
    prediction = model.predict(x_test)
    baseline = DummyRegressor(strategy="mean")
    baseline.fit(x_train, y_train)
    baseline_prediction = baseline.predict(x_test)
    model_metrics = _metrics(y_test.to_numpy(), prediction)
    baseline_metrics = _metrics(y_test.to_numpy(), baseline_prediction)
    result = pd.DataFrame(
        {
            "row": test_index,
            "actual": y_test.to_numpy(),
            "prediction": prediction,
            "mean_baseline": baseline_prediction,
            "residual": y_test.to_numpy() - prediction,
        }
    ).sort_values("row", ignore_index=True)
    fitted_estimator = model[-1]
    coefficients = pd.DataFrame(
        {
            "feature": features,
            "standardized_coefficient": fitted_estimator.coef_,
        }
    )
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_dir / "predictions.csv", index=False)
    coefficients.to_csv(output_dir / "coefficients.csv", index=False)
    evidence = {
        "input": str(input_path),
        "input_sha256": _sha256(input_path),
        "target": target,
        "features": features,
        "model": model_name,
        "alpha": alpha if model_name == "ridge" else None,
        "split": split,
        "test_size": test_size,
        "seed": seed,
        "group_column": group_column,
        "rows": len(frame),
        "train_rows": len(train_index),
        "test_rows": len(test_index),
        "split_evidence": split_evidence,
        "model_metrics": model_metrics,
        "mean_baseline_metrics": baseline_metrics,
        "beats_mean_baseline_rmse": model_metrics["rmse"] < baseline_metrics["rmse"],
        "coefficient_scale": "standardized_features",
        "outputs": ["predictions.csv", "coefficients.csv"],
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
    parser.add_argument("--target", required=True)
    parser.add_argument("--features", required=True)
    parser.add_argument("--model", choices=("linear", "ridge"), default="linear")
    parser.add_argument("--split", choices=("random", "time", "group"), default="random")
    parser.add_argument("--test-size", type=float, default=0.25)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--group-column")
    parser.add_argument("--alpha", type=float, default=1.0)
    args = parser.parse_args()
    try:
        run(
            args.input,
            args.output,
            args.target,
            args.features,
            args.model,
            args.split,
            args.test_size,
            args.seed,
            args.group_column,
            args.alpha,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

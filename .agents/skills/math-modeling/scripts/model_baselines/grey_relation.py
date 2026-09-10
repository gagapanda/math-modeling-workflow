"""Compute auditable grey relational grades with sensitivity baselines."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _csv_items(value: str, label: str) -> list[str]:
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items:
        raise ValueError(f"{label} cannot be empty")
    if len(set(items)) != len(items):
        raise ValueError(f"{label} must be unique")
    return items


def _rho_values(value: str) -> list[float]:
    values = [float(item) for item in _csv_items(value, "sensitivity rhos")]
    if any(not np.isfinite(item) or not 0 < item <= 1 for item in values):
        raise ValueError("all rho values must be finite and in (0, 1]")
    return values


def _normalize(values: pd.Series, method: str) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.isna().any() or not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise ValueError(f"column {values.name} contains missing or non-finite values")
    if numeric.nunique() <= 1:
        raise ValueError(f"column {values.name} is constant and has no comparable shape")
    if method == "minmax":
        return (numeric - numeric.min()) / (numeric.max() - numeric.min())
    if method == "mean":
        mean = float(numeric.mean())
        if np.isclose(mean, 0.0):
            raise ValueError(f"column {values.name} has zero mean and cannot use mean normalization")
        return numeric / mean
    if method == "initial":
        initial = float(numeric.iloc[0])
        if np.isclose(initial, 0.0):
            raise ValueError(f"column {values.name} starts at zero and cannot use initial normalization")
        return numeric / initial
    raise ValueError("normalization must be minmax, mean, or initial")


def calculate(
    frame: pd.DataFrame,
    reference_column: str,
    columns: list[str],
    rho: float,
    normalization: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not 0 < rho <= 1 or not np.isfinite(rho):
        raise ValueError("rho must be finite and in (0, 1]")
    selected = [reference_column] + columns
    normalized = pd.DataFrame(
        {column: _normalize(frame[column], normalization) for column in selected}
    )
    differences = normalized[columns].sub(normalized[reference_column], axis=0).abs()
    delta_min = float(differences.min().min())
    delta_max = float(differences.max().max())
    if np.isclose(delta_max, 0.0):
        coefficients = pd.DataFrame(1.0, index=differences.index, columns=columns)
    else:
        coefficients = (delta_min + rho * delta_max) / (differences + rho * delta_max)
    grades = coefficients.mean(axis=0).rename("grade").reset_index()
    grades.columns = ["column", "grade"]
    grades["rank"] = grades["grade"].rank(ascending=False, method="min").astype(int)
    grades = grades.sort_values(["rank", "column"], ignore_index=True)
    return normalized, differences, coefficients, grades


def _correlation_baselines(
    frame: pd.DataFrame, reference_column: str, columns: list[str]
) -> pd.DataFrame:
    reference = pd.to_numeric(frame[reference_column], errors="raise").to_numpy(dtype=float)
    records = []
    for column in columns:
        values = pd.to_numeric(frame[column], errors="raise").to_numpy(dtype=float)
        pearson = pearsonr(reference, values)
        spearman = spearmanr(reference, values)
        records.append(
            {
                "column": column,
                "pearson_r": float(pearson.statistic),
                "pearson_pvalue": float(pearson.pvalue),
                "spearman_rho": float(spearman.statistic),
                "spearman_pvalue": float(spearman.pvalue),
            }
        )
    return pd.DataFrame.from_records(records)


def run(
    input_path: Path,
    output_dir: Path,
    reference_column: str,
    columns_arg: str,
    rho: float = 0.5,
    normalization: str = "minmax",
    sensitivity_rhos_arg: str = "0.2,0.5,0.8",
    sensitivity_normalizations_arg: str = "minmax,mean,initial",
) -> dict:
    input_path = input_path.expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"input file not found: {input_path}")
    frame = pd.read_csv(input_path)
    if len(frame) < 4:
        raise ValueError("grey relation requires at least four aligned observations")
    columns = _csv_items(columns_arg, "columns")
    if reference_column in columns:
        raise ValueError("reference column cannot also be a comparison column")
    missing = [column for column in [reference_column] + columns if column not in frame.columns]
    if missing:
        raise ValueError(f"missing columns: {', '.join(missing)}")
    sensitivity_rhos = _rho_values(sensitivity_rhos_arg)
    sensitivity_normalizations = _csv_items(
        sensitivity_normalizations_arg, "sensitivity normalizations"
    )
    invalid_normalizations = sorted(
        set(sensitivity_normalizations) - {"minmax", "mean", "initial"}
    )
    if invalid_normalizations:
        raise ValueError(
            f"unsupported sensitivity normalizations: {', '.join(invalid_normalizations)}"
        )
    normalized, differences, coefficients, grades = calculate(
        frame, reference_column, columns, rho, normalization
    )
    correlations = _correlation_baselines(frame, reference_column, columns)
    sensitivity_records: list[dict[str, float | int | str]] = []
    sensitivity_warnings: list[str] = []
    for method in sensitivity_normalizations:
        for sensitivity_rho in sensitivity_rhos:
            try:
                _, _, _, sensitivity_grades = calculate(
                    frame, reference_column, columns, sensitivity_rho, method
                )
            except ValueError as exc:
                warning = f"{method} normalization unavailable: {exc}"
                if warning not in sensitivity_warnings:
                    sensitivity_warnings.append(warning)
                continue
            for record in sensitivity_grades.to_dict(orient="records"):
                sensitivity_records.append(
                    {
                        "normalization": method,
                        "rho": sensitivity_rho,
                        "column": str(record["column"]),
                        "grade": float(record["grade"]),
                        "rank": int(record["rank"]),
                    }
                )
    sensitivity = pd.DataFrame.from_records(sensitivity_records)
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    normalized.to_csv(output_dir / "normalized_sequences.csv", index=False)
    differences.to_csv(output_dir / "absolute_differences.csv", index=False)
    coefficients.to_csv(output_dir / "grey_coefficients.csv", index=False)
    grades.to_csv(output_dir / "grey_grades.csv", index=False)
    correlations.to_csv(output_dir / "correlation_baselines.csv", index=False)
    sensitivity.to_csv(output_dir / "sensitivity.csv", index=False)
    baseline_order = grades["column"].tolist()
    sensitivity_orders = []
    if not sensitivity.empty:
        for _, subset in sensitivity.groupby(["normalization", "rho"], sort=True):
            sensitivity_orders.append(subset.sort_values(["rank", "column"])["column"].tolist())
    ranking_stable = bool(
        sensitivity_orders and all(order == baseline_order for order in sensitivity_orders)
    )
    top_rank_stable = bool(
        sensitivity_orders
        and baseline_order
        and all(order and order[0] == baseline_order[0] for order in sensitivity_orders)
    )
    evidence = {
        "input": str(input_path),
        "input_sha256": _sha256(input_path),
        "reference_column": reference_column,
        "columns": columns,
        "rows": len(frame),
        "rho": rho,
        "normalization": normalization,
        "ranking": baseline_order,
        "sensitivity_cases": len(sensitivity_orders),
        "ranking_stable_across_sensitivity": ranking_stable,
        "top_rank_stable_across_sensitivity": top_rank_stable,
        "sensitivity_warnings": sensitivity_warnings,
        "outputs": [
            "normalized_sequences.csv",
            "absolute_differences.csv",
            "grey_coefficients.csv",
            "grey_grades.csv",
            "correlation_baselines.csv",
            "sensitivity.csv",
        ],
    }
    (output_dir / "run.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--reference-column", required=True)
    parser.add_argument("--columns", required=True)
    parser.add_argument("--rho", type=float, default=0.5)
    parser.add_argument(
        "--normalization", choices=("minmax", "mean", "initial"), default="minmax"
    )
    parser.add_argument("--sensitivity-rhos", default="0.2,0.5,0.8")
    parser.add_argument(
        "--sensitivity-normalizations", default="minmax,mean,initial"
    )
    args = parser.parse_args()
    try:
        run(
            args.input,
            args.output,
            args.reference_column,
            args.columns,
            args.rho,
            args.normalization,
            args.sensitivity_rhos,
            args.sensitivity_normalizations,
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

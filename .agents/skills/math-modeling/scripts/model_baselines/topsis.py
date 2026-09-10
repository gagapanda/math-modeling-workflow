"""Run an auditable TOPSIS ranking baseline on a CSV file."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def _csv_items(value: str, label: str) -> list[str]:
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items:
        raise ValueError(f"{label} cannot be empty")
    return items


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _prepare_matrix(
    frame: pd.DataFrame,
    columns: list[str],
    directions: list[str],
    standardization: str,
) -> pd.DataFrame:
    if len(columns) != len(directions):
        raise ValueError("columns and directions must have the same length")
    prepared = pd.DataFrame(index=frame.index)
    for column, direction in zip(columns, directions):
        if column not in frame.columns:
            raise ValueError(f"missing indicator column: {column}")
        if direction not in {"positive", "negative"}:
            raise ValueError("directions must be positive or negative")
        values = pd.to_numeric(frame[column], errors="coerce")
        if values.isna().any():
            raise ValueError(f"indicator column {column} contains missing or non-numeric values")
        minimum = float(values.min())
        maximum = float(values.max())
        if maximum == minimum:
            scaled = pd.Series(np.ones(len(values)), index=frame.index)
        elif standardization == "minmax":
            scaled = (values - minimum) / (maximum - minimum)
        else:
            scaled = values / float(np.sqrt(np.square(values).sum()))
        if direction == "negative":
            if standardization == "minmax":
                scaled = 1.0 - scaled
            else:
                scaled = -scaled
        prepared[column] = scaled
    if standardization == "vector":
        # Direction conversion is applied before the vector norm so all ideals are positive.
        norms = np.sqrt(np.square(prepared).sum(axis=0)).replace(0.0, 1.0)
        prepared = prepared / norms
    return prepared


def run(
    input_path: Path,
    output_dir: Path,
    columns_arg: str,
    weights_arg: str,
    directions_arg: str,
    id_column: str | None = None,
    standardization: str = "vector",
) -> dict:
    input_path = input_path.expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"input file not found: {input_path}")
    if standardization not in {"vector", "minmax"}:
        raise ValueError("standardization must be vector or minmax")
    frame = pd.read_csv(input_path)
    if frame.empty:
        raise ValueError("input CSV is empty")
    columns = _csv_items(columns_arg, "columns")
    directions = _csv_items(directions_arg, "directions")
    weight_values = np.asarray([float(item) for item in _csv_items(weights_arg, "weights")], dtype=float)
    if len(columns) != len(weight_values):
        raise ValueError("weights and columns must have the same length")
    if not np.isfinite(weight_values).all() or (weight_values < 0).any() or np.isclose(weight_values.sum(), 0.0):
        raise ValueError("weights must be finite, non-negative, and have positive sum")
    weights = weight_values / weight_values.sum()
    if id_column is not None and id_column not in frame.columns:
        raise ValueError(f"missing id column: {id_column}")

    normalized = _prepare_matrix(frame, columns, directions, standardization)
    weighted = normalized.to_numpy(dtype=float) * weights
    positive = weighted.max(axis=0)
    negative = weighted.min(axis=0)
    distance_positive = np.sqrt(np.square(weighted - positive).sum(axis=1))
    distance_negative = np.sqrt(np.square(weighted - negative).sum(axis=1))
    denominator = distance_positive + distance_negative
    closeness = np.divide(
        distance_negative,
        denominator,
        out=np.full_like(distance_negative, 0.5),
        where=denominator != 0,
    )
    result = pd.DataFrame(
        {
            "row": np.arange(len(frame), dtype=int),
            "distance_positive": distance_positive,
            "distance_negative": distance_negative,
            "closeness": closeness,
        }
    )
    if id_column is not None:
        result.insert(1, id_column, frame[id_column].to_numpy())
    result["rank"] = result["closeness"].rank(ascending=False, method="min").astype(int)
    result = result.sort_values(["rank", "row"], ignore_index=True)

    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_dir / "topsis_result.csv", index=False)
    normalized.to_csv(output_dir / "normalized_matrix.csv", index=False)
    pd.DataFrame(
        {
            "column": columns,
            "weight": weights,
            "positive_ideal": positive,
            "negative_ideal": negative,
            "direction": directions,
        }
    ).to_csv(output_dir / "ideal_solutions.csv", index=False)
    evidence = {
        "input": str(input_path),
        "input_sha256": _sha256(input_path),
        "columns": columns,
        "directions": directions,
        "weights": weights.tolist(),
        "standardization": standardization,
        "rows": len(frame),
        "outputs": [
            "topsis_result.csv",
            "normalized_matrix.csv",
            "ideal_solutions.csv",
        ],
    }
    (output_dir / "run.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--columns", required=True, help="Comma-separated indicator columns")
    parser.add_argument("--weights", required=True, help="Comma-separated non-negative weights")
    parser.add_argument("--directions", required=True, help="Comma-separated positive/negative directions")
    parser.add_argument("--id-column", help="Optional solution identifier column")
    parser.add_argument("--standardization", choices=("vector", "minmax"), default="vector")
    args = parser.parse_args()
    try:
        run(
            args.input,
            args.output,
            args.columns,
            args.weights,
            args.directions,
            args.id_column,
            args.standardization,
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

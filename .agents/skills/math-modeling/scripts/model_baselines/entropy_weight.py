"""Compute auditable entropy weights and evaluation scores from CSV data."""

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


def _normalize(
    frame: pd.DataFrame, columns: list[str], directions: list[str]
) -> tuple[pd.DataFrame, list[str]]:
    if len(columns) != len(directions):
        raise ValueError("columns and directions must have the same length")
    normalized = pd.DataFrame(index=frame.index)
    constant_columns: list[str] = []
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
            normalized[column] = 0.0
            constant_columns.append(column)
        elif direction == "positive":
            normalized[column] = (values - minimum) / (maximum - minimum)
        else:
            normalized[column] = (maximum - values) / (maximum - minimum)
    return normalized, constant_columns


def _entropy_weights(
    normalized: pd.DataFrame, constant_columns: list[str]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    matrix = normalized.to_numpy(dtype=float)
    sample_count, indicator_count = matrix.shape
    if sample_count < 2:
        raise ValueError("at least two samples are required")
    proportions = np.zeros_like(matrix)
    entropy = np.ones(indicator_count, dtype=float)
    constant_set = set(constant_columns)
    for index, column in enumerate(normalized.columns):
        if column in constant_set:
            proportions[:, index] = 1.0 / sample_count
            continue
        total = float(matrix[:, index].sum())
        if total <= 0:
            raise ValueError(f"normalized indicator {column} has no positive information")
        proportions[:, index] = matrix[:, index] / total
        positive = proportions[:, index] > 0
        entropy[index] = -float(
            np.sum(proportions[positive, index] * np.log(proportions[positive, index]))
            / np.log(sample_count)
        )
    diversity = np.clip(1.0 - entropy, 0.0, None)
    if np.isclose(diversity.sum(), 0.0):
        raise ValueError("all indicators have zero information diversity")
    weights = diversity / diversity.sum()
    return entropy, diversity, weights


def run(
    input_path: Path,
    output_dir: Path,
    columns_arg: str,
    directions_arg: str,
    id_column: str | None = None,
) -> dict:
    input_path = input_path.expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"input file not found: {input_path}")
    frame = pd.read_csv(input_path)
    if frame.empty:
        raise ValueError("input CSV is empty")
    columns = _csv_items(columns_arg, "columns")
    directions = _csv_items(directions_arg, "directions")
    if id_column is not None and id_column not in frame.columns:
        raise ValueError(f"missing id column: {id_column}")
    normalized, constant_columns = _normalize(frame, columns, directions)
    entropy, diversity, weights = _entropy_weights(normalized, constant_columns)
    scores = normalized.to_numpy(dtype=float) @ weights

    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "column": columns,
            "direction": directions,
            "entropy": entropy,
            "diversity": diversity,
            "weight": weights,
            "constant": [column in constant_columns for column in columns],
        }
    ).to_csv(output_dir / "weights.csv", index=False)
    normalized.to_csv(output_dir / "normalized_matrix.csv", index=False)
    score_frame = pd.DataFrame(
        {"row": np.arange(len(frame), dtype=int), "score": scores}
    )
    if id_column is not None:
        score_frame.insert(1, id_column, frame[id_column].to_numpy())
    score_frame["rank"] = score_frame["score"].rank(
        ascending=False, method="min"
    ).astype(int)
    score_frame.sort_values(["rank", "row"], ignore_index=True).to_csv(
        output_dir / "scores.csv", index=False
    )
    evidence = {
        "input": str(input_path),
        "input_sha256": _sha256(input_path),
        "columns": columns,
        "directions": directions,
        "constant_columns": constant_columns,
        "weights": weights.tolist(),
        "rows": len(frame),
        "outputs": ["weights.csv", "normalized_matrix.csv", "scores.csv"],
    }
    (output_dir / "run.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--columns", required=True)
    parser.add_argument("--directions", required=True)
    parser.add_argument("--id-column")
    args = parser.parse_args()
    try:
        run(
            args.input,
            args.output,
            args.columns,
            args.directions,
            args.id_column,
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

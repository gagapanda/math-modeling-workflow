"""Compute auditable AHP weights, consistency, and local sensitivity."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


RI_TABLE = {
    1: 0.0,
    2: 0.0,
    3: 0.58,
    4: 0.90,
    5: 1.12,
    6: 1.24,
    7: 1.32,
    8: 1.41,
    9: 1.45,
    10: 1.49,
    11: 1.51,
    12: 1.48,
    13: 1.56,
    14: 1.57,
    15: 1.59,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_matrix(matrix: np.ndarray, tolerance: float = 1e-6) -> None:
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
        raise ValueError("AHP judgment matrix must be square")
    n = matrix.shape[0]
    if n < 1 or n > max(RI_TABLE):
        raise ValueError("AHP judgment matrix order must be between 1 and 15")
    if not np.isfinite(matrix).all() or (matrix <= 0).any():
        raise ValueError("AHP judgment matrix entries must be finite and positive")
    if not np.allclose(np.diag(matrix), 1.0, rtol=0.0, atol=tolerance):
        raise ValueError("AHP judgment matrix diagonal must be 1")
    if not np.allclose(matrix * matrix.T, 1.0, rtol=tolerance, atol=tolerance):
        raise ValueError("AHP judgment matrix must be reciprocal: a_ij * a_ji = 1")


def calculate(matrix: np.ndarray) -> dict[str, object]:
    matrix = np.asarray(matrix, dtype=float)
    _validate_matrix(matrix)
    values, vectors = np.linalg.eig(matrix)
    index = int(np.argmax(values.real))
    lambda_max = float(values[index].real)
    vector = np.abs(vectors[:, index].real)
    if np.isclose(vector.sum(), 0.0):
        raise ValueError("AHP principal eigenvector is degenerate")
    weights = vector / vector.sum()
    n = matrix.shape[0]
    ci = float((lambda_max - n) / (n - 1)) if n > 1 else 0.0
    ri = RI_TABLE[n]
    cr = float(ci / ri) if ri > 0 else 0.0
    return {
        "weights": weights,
        "lambda_max": lambda_max,
        "ci": ci,
        "ri": ri,
        "cr": cr,
        "consistency_passed": bool(cr < 0.1),
    }


def sensitivity(matrix: np.ndarray, perturbation: float = 0.1) -> pd.DataFrame:
    if not 0 < perturbation < 1:
        raise ValueError("perturbation must be in (0, 1)")
    baseline = np.asarray(calculate(matrix)["weights"], dtype=float)
    records: list[dict[str, float | int | str]] = []
    for row in range(matrix.shape[0]):
        for column in range(row + 1, matrix.shape[1]):
            for direction, factor in (("down", 1.0 - perturbation), ("up", 1.0 + perturbation)):
                candidate = matrix.copy()
                candidate[row, column] *= factor
                candidate[column, row] = 1.0 / candidate[row, column]
                result = calculate(candidate)
                weights = np.asarray(result["weights"], dtype=float)
                records.append(
                    {
                        "row": row,
                        "column": column,
                        "direction": direction,
                        "cr": float(result["cr"]),
                        "max_weight_abs_delta": float(np.max(np.abs(weights - baseline))),
                        "consistency_passed": str(result["consistency_passed"]),
                    }
                )
    return pd.DataFrame.from_records(records)


def run(input_path: Path, output_dir: Path, perturbation: float = 0.1) -> dict:
    input_path = input_path.expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"input file not found: {input_path}")
    matrix = pd.read_csv(input_path, header=None).to_numpy(dtype=float)
    result = calculate(matrix)
    sensitivity_frame = sensitivity(matrix, perturbation)
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(matrix).to_csv(output_dir / "judgment_matrix.csv", index=False, header=False)
    pd.DataFrame(
        {"item": [f"item_{i + 1}" for i in range(len(result["weights"]))], "weight": result["weights"]}
    ).to_csv(output_dir / "ahp_weights.csv", index=False)
    sensitivity_frame.to_csv(output_dir / "sensitivity.csv", index=False)
    evidence = {
        "input": str(input_path),
        "input_sha256": _sha256(input_path),
        "order": int(matrix.shape[0]),
        "lambda_max": float(result["lambda_max"]),
        "ci": float(result["ci"]),
        "ri": float(result["ri"]),
        "cr": float(result["cr"]),
        "consistency_passed": bool(result["consistency_passed"]),
        "weights": np.asarray(result["weights"], dtype=float).tolist(),
        "perturbation": perturbation,
        "sensitivity_cases": len(sensitivity_frame),
        "outputs": ["judgment_matrix.csv", "ahp_weights.csv", "sensitivity.csv"],
    }
    (output_dir / "run.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--perturbation", type=float, default=0.1)
    args = parser.parse_args()
    try:
        run(args.input, args.output, args.perturbation)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

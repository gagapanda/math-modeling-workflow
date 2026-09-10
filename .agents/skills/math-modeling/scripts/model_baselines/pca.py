"""Run an auditable standardized PCA dimensionality-reduction baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
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


def _canonical_signs(components: np.ndarray) -> np.ndarray:
    signed = np.array(components, dtype=float, copy=True)
    for index, vector in enumerate(signed):
        anchor = int(np.argmax(np.abs(vector)))
        if vector[anchor] < 0:
            signed[index] *= -1
    return signed


def run(
    input_path: Path,
    output_dir: Path,
    features_arg: str,
    id_column: str | None = None,
    variance_threshold: float = 0.85,
    max_components: int | None = None,
) -> dict[str, Any]:
    input_path = input_path.expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"input file not found: {input_path}")
    if (
        isinstance(variance_threshold, bool)
        or not isinstance(variance_threshold, (int, float))
        or not math.isfinite(float(variance_threshold))
        or not 0 < float(variance_threshold) <= 1
    ):
        raise ValueError("variance_threshold must be finite and in (0, 1]")
    if max_components is not None and (
        isinstance(max_components, bool)
        or not isinstance(max_components, int)
        or max_components < 1
    ):
        raise ValueError("max_components must be a positive integer")

    frame = pd.read_csv(input_path)
    features = _csv_items(features_arg)
    if len(features) < 2:
        raise ValueError("PCA baseline requires at least two feature columns")
    if len(features) > 500:
        raise ValueError("PCA baseline supports at most 500 feature columns")
    required = features + ([id_column] if id_column else [])
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"missing columns: {', '.join(missing)}")
    if id_column in features:
        raise ValueError("id column cannot also be a feature")
    if id_column:
        if frame[id_column].isna().any():
            raise ValueError("id column must contain complete values")
        if frame[id_column].duplicated().any():
            raise ValueError("id column must contain unique values")
    if len(frame) < 3:
        raise ValueError("PCA baseline requires at least three rows")

    numeric = frame[features].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any():
        raise ValueError("features must contain complete numeric values")
    values = numeric.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("features must contain finite numeric values")
    if numeric.nunique().min() < 2:
        constant = numeric.columns[numeric.nunique() < 2].tolist()
        raise ValueError(f"constant feature columns are not allowed: {', '.join(constant)}")

    available_components = min(len(frame), len(features))
    if max_components is not None and max_components > available_components:
        raise ValueError(
            "max_components cannot exceed min(number of rows, number of features)"
        )

    scaler = StandardScaler()
    standardized = scaler.fit_transform(values)
    pca = PCA(n_components=available_components, svd_solver="full")
    raw_scores = pca.fit_transform(standardized)
    components = _canonical_signs(pca.components_)
    sign_multipliers = np.sum(components * pca.components_, axis=1)
    scores = raw_scores * sign_multipliers
    explained_ratio = np.asarray(pca.explained_variance_ratio_, dtype=float)
    cumulative_ratio = np.cumsum(explained_ratio)
    threshold_count = int(np.searchsorted(cumulative_ratio, variance_threshold, side="left") + 1)
    threshold_count = min(threshold_count, available_components)
    retained_count = (
        threshold_count
        if max_components is None
        else min(threshold_count, max_components)
    )
    threshold_achieved = bool(cumulative_ratio[retained_count - 1] + 1e-12 >= variance_threshold)

    retained_scores = scores[:, :retained_count]
    retained_components = components[:retained_count]
    reconstructed_standardized = retained_scores @ retained_components
    reconstructed_original = scaler.inverse_transform(reconstructed_standardized)
    residual_standardized = standardized - reconstructed_standardized
    residual_original = values - reconstructed_original
    row_squared_error = np.sum(residual_standardized**2, axis=1)
    baseline_row_squared_error = np.sum(standardized**2, axis=1)
    retained_error = float(np.sum(row_squared_error))
    baseline_error = float(np.sum(baseline_row_squared_error))
    reconstruction_improvement = float(1 - retained_error / baseline_error)

    score_frame = pd.DataFrame({"row": np.arange(len(frame), dtype=int)})
    if id_column:
        score_frame[id_column] = frame[id_column].to_numpy()
    for component_index in range(retained_count):
        score_frame[f"PC{component_index + 1}"] = retained_scores[:, component_index]
    score_frame["reconstruction_squared_error_standardized"] = row_squared_error

    component_rows = []
    for component_index in range(available_components):
        component_rows.append(
            {
                "component": f"PC{component_index + 1}",
                "retained": component_index < retained_count,
                "explained_variance": float(pca.explained_variance_[component_index]),
                "explained_variance_ratio": float(explained_ratio[component_index]),
                "cumulative_explained_variance_ratio": float(cumulative_ratio[component_index]),
                "singular_value": float(pca.singular_values_[component_index]),
                "sign_anchor_feature": features[
                    int(np.argmax(np.abs(components[component_index])))
                ],
            }
        )

    loading_rows = []
    standardized_sample_variance = len(frame) / (len(frame) - 1)
    for component_index in range(available_components):
        correlation_scale = math.sqrt(
            max(float(pca.explained_variance_[component_index]), 0.0)
            / standardized_sample_variance
        )
        for feature_index, feature in enumerate(features):
            coefficient = float(components[component_index, feature_index])
            loading_rows.append(
                {
                    "component": f"PC{component_index + 1}",
                    "feature": feature,
                    "retained": component_index < retained_count,
                    "eigenvector_coefficient": coefficient,
                    "correlation_loading": float(
                        coefficient * correlation_scale
                    ),
                    "squared_coefficient_share": coefficient**2,
                }
            )

    original_variances = np.var(values, axis=0, ddof=1)
    original_variance_share = original_variances / np.sum(original_variances)
    preprocessing = pd.DataFrame(
        {
            "feature": features,
            "mean": scaler.mean_,
            "scale_standard_deviation": scaler.scale_,
            "sample_standard_deviation": numeric.std(ddof=1).to_numpy(dtype=float),
            "minimum": numeric.min().to_numpy(dtype=float),
            "maximum": numeric.max().to_numpy(dtype=float),
            "original_scale_variance_share": original_variance_share,
            "standardized_scale_variance_share": np.full(
                len(features), 1 / len(features), dtype=float
            ),
        }
    )

    feature_reconstruction_rows = []
    for feature_index, feature in enumerate(features):
        standardized_sse = float(np.sum(residual_standardized[:, feature_index] ** 2))
        original_sse = float(np.sum(residual_original[:, feature_index] ** 2))
        baseline_standardized_sse = float(np.sum(standardized[:, feature_index] ** 2))
        feature_reconstruction_rows.append(
            {
                "feature": feature,
                "retained_standardized_sse": standardized_sse,
                "mean_baseline_standardized_sse": baseline_standardized_sse,
                "standardized_error_reduction": float(
                    1 - standardized_sse / baseline_standardized_sse
                ),
                "retained_original_sse": original_sse,
            }
        )

    correlation = numeric.corr(method="pearson")
    reconstructed_frame = pd.DataFrame(
        reconstructed_original,
        columns=[f"{feature}_reconstructed" for feature in features],
    )
    reconstructed_frame.insert(0, "row", np.arange(len(frame), dtype=int))
    if id_column:
        reconstructed_frame.insert(1, id_column, frame[id_column].to_numpy())
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    score_frame.to_csv(output_dir / "scores.csv", index=False)
    pd.DataFrame.from_records(component_rows).to_csv(
        output_dir / "explained_variance.csv", index=False
    )
    pd.DataFrame.from_records(loading_rows).to_csv(
        output_dir / "loadings.csv", index=False
    )
    preprocessing.to_csv(output_dir / "preprocessing.csv", index=False)
    correlation.to_csv(output_dir / "correlation_matrix.csv")
    reconstructed_frame.to_csv(output_dir / "reconstructed_data.csv", index=False)
    pd.DataFrame.from_records(feature_reconstruction_rows).to_csv(
        output_dir / "reconstruction_by_feature.csv", index=False
    )

    warnings = [
        "PCA components describe sample variance, not causal importance or decision preference",
        "component signs are canonicalized for reproducibility but remain mathematically arbitrary",
        "scores are coordinates in the fitted sample and are not absolute evaluation grades",
        "new data must use the recorded training means, scales, and loadings or trigger a refit decision",
    ]
    if not threshold_achieved:
        warnings.append(
            "max_components prevents the retained components from reaching the declared variance threshold"
        )
    if len(frame) <= len(features):
        warnings.append(
            "rows do not exceed features; the decomposition is rank-limited and loading interpretation is fragile"
        )
    if retained_count == available_components:
        warnings.append(
            "all available components are retained, so PCA provides no dimensionality reduction"
        )
    if float(np.max(original_variance_share)) > 0.9:
        warnings.append(
            "one feature contributes over 90% of raw-scale variance; standardized and unstandardized PCA would answer materially different questions"
        )

    evidence = {
        "input": str(input_path),
        "input_sha256": _sha256(input_path),
        "method": "z_score_pca_full_svd",
        "features": features,
        "id_column": id_column,
        "rows": len(frame),
        "feature_count": len(features),
        "available_components": available_components,
        "variance_threshold": float(variance_threshold),
        "max_components": max_components,
        "threshold_component_count": threshold_count,
        "retained_component_count": retained_count,
        "retained_explained_variance_ratio": float(cumulative_ratio[retained_count - 1]),
        "threshold_achieved": threshold_achieved,
        "component_sign_rule": "largest_absolute_eigenvector_coefficient_is_positive",
        "mean_reconstruction_baseline_standardized_sse": baseline_error,
        "retained_reconstruction_standardized_sse": retained_error,
        "reconstruction_error_reduction": reconstruction_improvement,
        "warnings": warnings,
        "outputs": [
            "scores.csv",
            "explained_variance.csv",
            "loadings.csv",
            "preprocessing.csv",
            "correlation_matrix.csv",
            "reconstructed_data.csv",
            "reconstruction_by_feature.csv",
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
    parser.add_argument("--features", required=True)
    parser.add_argument("--id-column")
    parser.add_argument("--variance-threshold", type=float, default=0.85)
    parser.add_argument("--max-components", type=int)
    args = parser.parse_args()
    try:
        run(
            args.input,
            args.output,
            args.features,
            args.id_column,
            args.variance_threshold,
            args.max_components,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

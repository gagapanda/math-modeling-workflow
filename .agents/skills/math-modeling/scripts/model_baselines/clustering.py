"""Select and fit an auditable standardized KMeans clustering baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# Avoid joblib's Windows-only physical-core probe when the legacy system query
# executable is unavailable; KMeans remains bounded by its own library settings.
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")

from sklearn.cluster import KMeans
from sklearn.metrics import (
    adjusted_rand_score,
    calinski_harabasz_score,
    davies_bouldin_score,
    silhouette_score,
)
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


def _canonicalize_labels(
    labels: np.ndarray, centers: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    order = sorted(range(len(centers)), key=lambda index: tuple(centers[index]))
    mapping = {old: new for new, old in enumerate(order)}
    canonical_labels = np.array([mapping[int(label)] for label in labels], dtype=int)
    return canonical_labels, centers[order]


def _pairwise_stability(label_sets: list[np.ndarray]) -> tuple[float, float, list[float]]:
    scores = [
        float(adjusted_rand_score(label_sets[left], label_sets[right]))
        for left, right in combinations(range(len(label_sets)), 2)
    ]
    return float(np.mean(scores)), float(np.min(scores)), scores


def _representative_index(label_sets: list[np.ndarray], silhouettes: list[float]) -> int:
    mean_ari = []
    for index, labels in enumerate(label_sets):
        comparisons = [
            adjusted_rand_score(labels, other)
            for other_index, other in enumerate(label_sets)
            if other_index != index
        ]
        mean_ari.append(float(np.mean(comparisons)))
    return min(
        range(len(label_sets)),
        key=lambda index: (-mean_ari[index], -silhouettes[index], index),
    )


def run(
    input_path: Path,
    output_dir: Path,
    features_arg: str,
    id_column: str | None = None,
    k_min: int = 2,
    k_max: int = 8,
    repeats: int = 10,
    seed: int = 42,
    n_init: int = 20,
    silhouette_sample_size: int = 5000,
) -> dict[str, Any]:
    input_path = input_path.expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"input file not found: {input_path}")
    for value, label in ((k_min, "k_min"), (k_max, "k_max")):
        if isinstance(value, bool) or not isinstance(value, int) or value < 2:
            raise ValueError(f"{label} must be an integer of at least 2")
    if k_min > k_max:
        raise ValueError("k_min cannot exceed k_max")
    if k_max > 50:
        raise ValueError("k_max cannot exceed 50 in the auditable baseline")
    if isinstance(repeats, bool) or not isinstance(repeats, int) or not 2 <= repeats <= 100:
        raise ValueError("repeats must be an integer from 2 to 100")
    if isinstance(n_init, bool) or not isinstance(n_init, int) or not 1 <= n_init <= 100:
        raise ValueError("n_init must be an integer from 1 to 100")
    if (k_max - k_min + 1) * repeats > 500:
        raise ValueError("candidate k count times repeats cannot exceed 500")
    if (
        isinstance(silhouette_sample_size, bool)
        or not isinstance(silhouette_sample_size, int)
        or silhouette_sample_size < 100
    ):
        raise ValueError("silhouette_sample_size must be an integer of at least 100")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**32 - 1:
        raise ValueError("seed must be an integer from 0 to 2^32-1")
    if seed + repeats - 1 > 2**32 - 1:
        raise ValueError("seed plus repeats exceeds the supported random-state range")

    frame = pd.read_csv(input_path)
    features = _csv_items(features_arg)
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

    numeric = frame[features].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any():
        raise ValueError("features must contain complete numeric values")
    values = numeric.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("features must contain finite numeric values")
    if numeric.nunique().min() < 2:
        constant = numeric.columns[numeric.nunique() < 2].tolist()
        raise ValueError(f"constant feature columns are not allowed: {', '.join(constant)}")
    if len(frame) < 6:
        raise ValueError("clustering baseline requires at least six rows")
    if k_max >= len(frame):
        raise ValueError("k_max must be smaller than the number of rows")
    if len(frame) < 3 * k_max:
        raise ValueError(
            "clustering baseline requires at least three rows per candidate cluster at k_max"
        )
    unique_rows = len(np.unique(values, axis=0))
    if k_max > unique_rows:
        raise ValueError(
            "k_max cannot exceed the number of distinct feature rows"
        )

    scaler = StandardScaler()
    standardized = scaler.fit_transform(values)
    baseline_inertia = float(np.sum(standardized**2))
    if baseline_inertia <= 0 or not math.isfinite(baseline_inertia):
        raise ValueError("standardized data have no usable total variation")
    sampled_rows = min(len(frame), silhouette_sample_size)
    sample_size = None if sampled_rows == len(frame) else sampled_rows

    run_rows: list[dict[str, Any]] = []
    pair_rows: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    candidate_models: dict[int, list[KMeans]] = {}
    candidate_labels: dict[int, list[np.ndarray]] = {}
    for k in range(k_min, k_max + 1):
        models = []
        label_sets = []
        silhouettes = []
        inertias = []
        davies_bouldin = []
        calinski_harabasz = []
        minimum_sizes = []
        for repeat in range(repeats):
            run_seed = seed + repeat
            model = KMeans(
                n_clusters=k,
                random_state=run_seed,
                n_init=n_init,
                algorithm="lloyd",
            ).fit(standardized)
            labels = np.asarray(model.labels_, dtype=int)
            counts = np.bincount(labels, minlength=k)
            silhouette = float(
                silhouette_score(
                    standardized,
                    labels,
                    sample_size=sample_size,
                    random_state=seed,
                )
            )
            db_score = float(davies_bouldin_score(standardized, labels))
            ch_score = float(calinski_harabasz_score(standardized, labels))
            models.append(model)
            label_sets.append(labels)
            silhouettes.append(silhouette)
            inertias.append(float(model.inertia_))
            davies_bouldin.append(db_score)
            calinski_harabasz.append(ch_score)
            minimum_sizes.append(int(np.min(counts)))
            run_rows.append(
                {
                    "k": k,
                    "repeat": repeat + 1,
                    "seed": run_seed,
                    "silhouette": silhouette,
                    "inertia": float(model.inertia_),
                    "davies_bouldin": db_score,
                    "calinski_harabasz": ch_score,
                    "minimum_cluster_size": int(np.min(counts)),
                    "maximum_cluster_size": int(np.max(counts)),
                }
            )
        mean_ari, minimum_ari, pair_scores = _pairwise_stability(label_sets)
        for (left, right), ari in zip(
            combinations(range(repeats), 2), pair_scores
        ):
            pair_rows.append(
                {
                    "k": k,
                    "left_repeat": left + 1,
                    "left_seed": seed + left,
                    "right_repeat": right + 1,
                    "right_seed": seed + right,
                    "adjusted_rand_index": ari,
                }
            )
        representative = _representative_index(label_sets, silhouettes)
        candidate_models[k] = models
        candidate_labels[k] = label_sets
        candidates.append(
            {
                "k": k,
                "mean_silhouette": float(np.mean(silhouettes)),
                "minimum_silhouette": float(np.min(silhouettes)),
                "maximum_silhouette": float(np.max(silhouettes)),
                "mean_pairwise_ari": mean_ari,
                "minimum_pairwise_ari": minimum_ari,
                "mean_inertia": float(np.mean(inertias)),
                "inertia_standard_deviation": float(np.std(inertias)),
                "mean_davies_bouldin": float(np.mean(davies_bouldin)),
                "mean_calinski_harabasz": float(np.mean(calinski_harabasz)),
                "minimum_cluster_size_across_runs": int(np.min(minimum_sizes)),
                "representative_repeat": representative + 1,
                "representative_seed": seed + representative,
            }
        )

    selected = min(
        candidates,
        key=lambda row: (
            -row["mean_silhouette"],
            -row["mean_pairwise_ari"],
            row["k"],
        ),
    )
    selected_k = int(selected["k"])
    representative_index = int(selected["representative_repeat"]) - 1
    final_model = candidate_models[selected_k][representative_index]
    labels, standardized_centers = _canonicalize_labels(
        candidate_labels[selected_k][representative_index],
        np.asarray(final_model.cluster_centers_, dtype=float),
    )
    original_centers = scaler.inverse_transform(standardized_centers)
    distances = np.linalg.norm(
        standardized - standardized_centers[labels], axis=1
    )
    selected_inertia = float(np.sum(distances**2))

    assignments = pd.DataFrame({"row": np.arange(len(frame), dtype=int)})
    if id_column:
        assignments[id_column] = frame[id_column].to_numpy()
    for feature in features:
        assignments[feature] = numeric[feature].to_numpy(dtype=float)
    assignments["cluster"] = labels
    assignments["distance_to_center_standardized"] = distances

    center_rows = []
    profile_rows = []
    for cluster in range(selected_k):
        selected_rows = labels == cluster
        center_row: dict[str, Any] = {
            "cluster": cluster,
            "size": int(np.sum(selected_rows)),
            "share": float(np.mean(selected_rows)),
        }
        for feature_index, feature in enumerate(features):
            center_row[f"{feature}_center"] = float(original_centers[cluster, feature_index])
            cluster_values = values[selected_rows, feature_index]
            profile_rows.append(
                {
                    "cluster": cluster,
                    "feature": feature,
                    "count": int(len(cluster_values)),
                    "mean_original": float(np.mean(cluster_values)),
                    "standard_deviation_original": float(np.std(cluster_values)),
                    "minimum_original": float(np.min(cluster_values)),
                    "maximum_original": float(np.max(cluster_values)),
                    "mean_standardized": float(standardized_centers[cluster, feature_index]),
                }
            )
        center_rows.append(center_row)

    preprocessing = pd.DataFrame(
        {
            "feature": features,
            "mean": scaler.mean_,
            "scale_standard_deviation": scaler.scale_,
            "minimum": numeric.min().to_numpy(dtype=float),
            "maximum": numeric.max().to_numpy(dtype=float),
        }
    )
    candidate_frame = pd.DataFrame.from_records(candidates)
    candidate_frame["selected"] = candidate_frame["k"] == selected_k
    stability_frame = pd.DataFrame.from_records(run_rows)
    stability_frame["selected_k"] = stability_frame["k"] == selected_k
    stability_frame["representative"] = (
        stability_frame["selected_k"]
        & (stability_frame["repeat"] == representative_index + 1)
    )
    pair_frame = pd.DataFrame.from_records(pair_rows)
    pair_frame["selected_k"] = pair_frame["k"] == selected_k

    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    assignments.to_csv(output_dir / "cluster_assignments.csv", index=False)
    pd.DataFrame.from_records(center_rows).to_csv(
        output_dir / "cluster_centers.csv", index=False
    )
    pd.DataFrame.from_records(profile_rows).to_csv(
        output_dir / "cluster_profiles.csv", index=False
    )
    candidate_frame.to_csv(output_dir / "candidate_k.csv", index=False)
    stability_frame.to_csv(output_dir / "stability_runs.csv", index=False)
    pair_frame.to_csv(output_dir / "stability_pairs.csv", index=False)
    preprocessing.to_csv(output_dir / "preprocessing.csv", index=False)

    warnings = [
        "cluster numbers are arbitrary identifiers, not observed classes or ordinal ranks",
        "the selected k maximizes mean silhouette only within the declared candidate range",
        "cluster interpretation depends on the declared features and z-score distance geometry",
    ]
    if selected["mean_pairwise_ari"] < 0.8:
        warnings.append(
            "repeat stability is below 0.8 mean pairwise ARI; treat the partition as unstable"
        )
    if selected["minimum_cluster_size_across_runs"] < 5:
        warnings.append(
            "at least one selected-k run contains a cluster with fewer than five rows"
        )
    if selected_k == k_max:
        warnings.append(
            "the selected k is on the upper candidate-range boundary; expand the range before claiming a preferred cluster count"
        )
    if selected_k == k_min:
        warnings.append(
            "the selected k is on the lower candidate-range boundary; compare a smaller k when possible and retain the one-cluster no-segmentation baseline"
        )
    if sample_size is not None:
        warnings.append(
            "silhouette metrics use a deterministic sample because the dataset exceeds the declared sample-size limit"
        )

    evidence = {
        "input": str(input_path),
        "input_sha256": _sha256(input_path),
        "method": "standardized_kmeans",
        "features": features,
        "id_column": id_column,
        "rows": len(frame),
        "feature_count": len(features),
        "preprocessing": "z_score_fit_on_all_rows_for_unsupervised_exploration",
        "k_min": k_min,
        "k_max": k_max,
        "repeats": repeats,
        "seed": seed,
        "n_init": n_init,
        "silhouette_rows": sampled_rows,
        "selection_rule": "maximum_mean_silhouette_then_stability_then_smaller_k",
        "selected_k": selected_k,
        "selected_candidate": selected,
        "representative_rule": "maximum_mean_ari_then_silhouette_then_earlier_repeat",
        "representative_repeat": representative_index + 1,
        "representative_seed": seed + representative_index,
        "single_cluster_baseline_inertia": baseline_inertia,
        "selected_inertia": selected_inertia,
        "inertia_reduction_from_single_cluster": float(
            1 - selected_inertia / baseline_inertia
        ),
        "cluster_sizes": {
            str(cluster): int(np.sum(labels == cluster))
            for cluster in range(selected_k)
        },
        "warnings": warnings,
        "outputs": [
            "cluster_assignments.csv",
            "cluster_centers.csv",
            "cluster_profiles.csv",
            "candidate_k.csv",
            "stability_runs.csv",
            "stability_pairs.csv",
            "preprocessing.csv",
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
    parser.add_argument("--k-min", type=int, default=2)
    parser.add_argument("--k-max", type=int, default=8)
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n-init", type=int, default=20)
    parser.add_argument("--silhouette-sample-size", type=int, default=5000)
    args = parser.parse_args()
    try:
        run(
            args.input,
            args.output,
            args.features,
            args.id_column,
            args.k_min,
            args.k_max,
            args.repeats,
            args.seed,
            args.n_init,
            args.silhouette_sample_size,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

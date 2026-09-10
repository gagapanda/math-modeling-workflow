"""Train an auditable binary logistic-classification baseline."""

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
from sklearn.calibration import CalibratedClassifierCV
from sklearn.dummy import DummyClassifier
from sklearn.frozen import FrozenEstimator
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)
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


def _class_counts(labels: np.ndarray) -> dict[str, int]:
    values, counts = np.unique(labels, return_counts=True)
    return {str(value): int(count) for value, count in zip(values, counts)}


def _contains_both(labels: np.ndarray) -> bool:
    return len(np.unique(labels)) == 2


def _group_split(
    indices: np.ndarray,
    labels: np.ndarray,
    groups: np.ndarray,
    test_size: float,
    seed: int,
    label: str,
) -> tuple[np.ndarray, np.ndarray]:
    if len(np.unique(groups)) < 3:
        raise ValueError(f"{label} group split requires at least three groups")
    splitter = GroupShuffleSplit(n_splits=100, test_size=test_size, random_state=seed)
    for train_position, test_position in splitter.split(indices, labels, groups):
        train = indices[train_position]
        test = indices[test_position]
        if _contains_both(labels[train_position]) and _contains_both(labels[test_position]):
            return np.sort(train), np.sort(test)
    raise ValueError(
        f"{label} group split could not place both classes in both partitions"
    )


def _split_indices(
    labels: np.ndarray,
    split: str,
    test_size: float,
    seed: int,
    groups: np.ndarray | None,
    label: str,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    indices = np.arange(len(labels), dtype=int)
    if split == "stratified":
        train, test = train_test_split(
            indices,
            test_size=test_size,
            random_state=seed,
            stratify=labels,
        )
        return np.sort(train), np.sort(test), {"stratified": True}
    if groups is None:
        raise ValueError("group split requires --group-column")
    train, test = _group_split(indices, labels, groups, test_size, seed, label)
    train_groups = sorted(str(value) for value in np.unique(groups[train]))
    test_groups = sorted(str(value) for value in np.unique(groups[test]))
    overlap = sorted(set(train_groups) & set(test_groups))
    if overlap:
        raise RuntimeError(f"group leakage detected in {label} split")
    return train, test, {
        "train_groups": train_groups,
        "test_groups": test_groups,
        "group_overlap": overlap,
    }


def _model(c_value: float, class_weight: str, seed: int):
    weight = None if class_weight == "none" else "balanced"
    return make_pipeline(
        StandardScaler(),
        LogisticRegression(
            C=c_value,
            class_weight=weight,
            max_iter=2000,
            random_state=seed,
            solver="lbfgs",
        ),
    )


def _positive_probabilities(model: Any, features: pd.DataFrame) -> np.ndarray:
    classes = list(model.classes_)
    if 1 not in classes:
        raise RuntimeError("fitted model is missing the positive class")
    return np.asarray(model.predict_proba(features)[:, classes.index(1)], dtype=float)


def _calibrate_sigmoid(
    fitted_model: Any,
    features: pd.DataFrame,
    labels: np.ndarray,
) -> CalibratedClassifierCV:
    # The estimator is already fitted on a disjoint partition. The explicit split
    # lets sklearn fit one sigmoid on all calibration rows without refitting it.
    calibration_indices = np.arange(len(labels), dtype=int)
    calibrator = CalibratedClassifierCV(
        FrozenEstimator(fitted_model),
        method="sigmoid",
        cv=[(np.array([], dtype=int), calibration_indices)],
        ensemble=False,
    )
    calibrator.fit(features, labels)
    return calibrator


def _threshold_score(
    actual: np.ndarray, probability: np.ndarray, threshold: float, strategy: str
) -> float:
    predicted = (probability >= threshold).astype(int)
    if strategy == "f1":
        return float(f1_score(actual, predicted, zero_division=0))
    return float(balanced_accuracy_score(actual, predicted))


def _select_threshold(
    actual: np.ndarray, probability: np.ndarray, strategy: str
) -> tuple[float, pd.DataFrame]:
    thresholds = np.linspace(0.05, 0.95, 181)
    rows = [
        {
            "threshold": float(threshold),
            "selection_metric": strategy,
            "selection_score": _threshold_score(
                actual, probability, float(threshold), strategy
            ),
        }
        for threshold in thresholds
    ]
    best_score = max(row["selection_score"] for row in rows)
    best = min(
        (row for row in rows if abs(row["selection_score"] - best_score) <= 1e-12),
        key=lambda row: (abs(row["threshold"] - 0.5), -row["threshold"]),
    )
    return float(best["threshold"]), pd.DataFrame.from_records(rows)


def _metrics(
    actual: np.ndarray, predicted: np.ndarray, probability: np.ndarray
) -> dict[str, float]:
    matrix = confusion_matrix(actual, predicted, labels=[0, 1])
    true_negative, false_positive, false_negative, true_positive = matrix.ravel()
    specificity = (
        true_negative / (true_negative + false_positive)
        if true_negative + false_positive
        else 0.0
    )
    clipped = np.clip(probability, 1e-15, 1 - 1e-15)
    return {
        "accuracy": float(accuracy_score(actual, predicted)),
        "balanced_accuracy": float(balanced_accuracy_score(actual, predicted)),
        "precision": float(precision_score(actual, predicted, zero_division=0)),
        "recall_sensitivity": float(recall_score(actual, predicted, zero_division=0)),
        "specificity": float(specificity),
        "f1": float(f1_score(actual, predicted, zero_division=0)),
        "roc_auc": float(roc_auc_score(actual, probability)),
        "average_precision": float(average_precision_score(actual, probability)),
        "brier_score": float(brier_score_loss(actual, probability)),
        "log_loss": float(log_loss(actual, clipped, labels=[0, 1])),
    }


def _calibration_table(actual: np.ndarray, probability: np.ndarray) -> pd.DataFrame:
    bins = np.linspace(0.0, 1.0, 11)
    bin_ids = np.minimum(np.digitize(probability, bins[1:-1], right=False), 9)
    rows = []
    for bin_id in range(10):
        selected = bin_ids == bin_id
        if not np.any(selected):
            continue
        rows.append(
            {
                "bin": bin_id + 1,
                "lower": float(bins[bin_id]),
                "upper": float(bins[bin_id + 1]),
                "count": int(np.sum(selected)),
                "mean_predicted_probability": float(np.mean(probability[selected])),
                "observed_positive_rate": float(np.mean(actual[selected])),
            }
        )
    return pd.DataFrame.from_records(rows)


def run(
    input_path: Path,
    output_dir: Path,
    target: str,
    features_arg: str,
    positive_label: str,
    split: str = "stratified",
    test_size: float = 0.25,
    seed: int = 42,
    group_column: str | None = None,
    class_weight: str = "none",
    calibration: str = "sigmoid",
    c_value: float = 1.0,
    threshold_strategy: str = "f1",
    threshold: float = 0.5,
    threshold_validation_size: float = 0.25,
) -> dict[str, Any]:
    input_path = input_path.expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"input file not found: {input_path}")
    if split not in {"stratified", "group"}:
        raise ValueError("split must be stratified or group")
    if class_weight not in {"none", "balanced"}:
        raise ValueError("class_weight must be none or balanced")
    if calibration not in {"none", "sigmoid"}:
        raise ValueError("calibration must be none or sigmoid")
    if threshold_strategy not in {"fixed", "f1", "balanced_accuracy"}:
        raise ValueError(
            "threshold_strategy must be fixed, f1, or balanced_accuracy"
        )
    for value, label in (
        (test_size, "test_size"),
        (threshold_validation_size, "threshold_validation_size"),
    ):
        if not 0 < value < 1 or not math.isfinite(value):
            raise ValueError(f"{label} must be finite and between 0 and 1")
    if not 0 < threshold < 1 or not math.isfinite(threshold):
        raise ValueError("threshold must be finite and between 0 and 1")
    if c_value <= 0 or not math.isfinite(c_value):
        raise ValueError("C must be finite and positive")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**32 - 1:
        raise ValueError("seed must be an integer from 0 to 2^32-1")

    frame = pd.read_csv(input_path)
    features = _csv_items(features_arg)
    required = features + [target]
    if split == "group" and group_column:
        required.append(group_column)
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"missing columns: {', '.join(missing)}")
    if target in features:
        raise ValueError("target cannot also be a feature")
    if group_column in features or group_column == target:
        raise ValueError("group column cannot be a feature or target")
    if frame[target].isna().any():
        raise ValueError("target must contain complete labels")
    numeric = frame[features].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any():
        raise ValueError("features must contain complete numeric values")
    if numeric.nunique().min() < 2:
        constant = numeric.columns[numeric.nunique() < 2].tolist()
        raise ValueError(f"constant feature columns are not allowed: {', '.join(constant)}")
    labels = frame[target].astype(str).to_numpy()
    classes = sorted(np.unique(labels).tolist())
    if len(classes) != 2:
        raise ValueError("classification baseline currently requires exactly two classes")
    if positive_label not in classes:
        raise ValueError(
            f"positive_label must match one of the observed labels: {', '.join(classes)}"
        )
    negative_label = next(label for label in classes if label != positive_label)
    encoded = (labels == positive_label).astype(int)
    if min(np.bincount(encoded)) < 8:
        raise ValueError("each class requires at least eight rows")
    groups = None
    if split == "group":
        if group_column is None:
            raise ValueError("group split requires --group-column")
        if frame[group_column].isna().any():
            raise ValueError("group column must contain complete values")
        groups = frame[group_column].astype(str).to_numpy()

    outer_train, test_index, outer_evidence = _split_indices(
        encoded, split, test_size, seed, groups, "outer"
    )
    if not _contains_both(encoded[outer_train]) or not _contains_both(encoded[test_index]):
        raise ValueError("outer split must contain both classes in train and test")

    threshold_table = pd.DataFrame(
        columns=["threshold", "selection_metric", "selection_score"]
    )
    threshold_evidence: dict[str, Any]
    selected_threshold = threshold
    needs_validation = calibration == "sigmoid" or threshold_strategy != "fixed"
    if not needs_validation:
        model = _model(c_value, class_weight, seed)
        model.fit(numeric.iloc[outer_train], encoded[outer_train])
        fitted_estimator = model[-1]
        threshold_evidence = {
            "source": "declared_fixed_threshold",
            "fit_rows": len(outer_train),
            "validation_rows": 0,
            "split_evidence": None,
        }
    else:
        outer_labels = encoded[outer_train]
        outer_groups = groups[outer_train] if groups is not None else None
        fit_position, validation_position, inner_evidence = _split_indices(
            outer_labels,
            split,
            threshold_validation_size,
            seed + 1,
            outer_groups,
            "threshold",
        )
        fit_index = outer_train[fit_position]
        validation_index = outer_train[validation_position]
        provisional = _model(c_value, class_weight, seed)
        provisional.fit(numeric.iloc[fit_index], encoded[fit_index])
        fitted_estimator = provisional[-1]
        if calibration == "sigmoid":
            model = _calibrate_sigmoid(
                provisional,
                numeric.iloc[validation_index],
                encoded[validation_index],
            )
        else:
            model = provisional
        if threshold_strategy != "fixed":
            validation_probability = _positive_probabilities(
                model, numeric.iloc[validation_index]
            )
            selected_threshold, threshold_table = _select_threshold(
                encoded[validation_index], validation_probability, threshold_strategy
            )
        threshold_evidence = {
            "source": "training_only_validation_partition",
            "fit_rows": len(fit_index),
            "validation_rows": len(validation_index),
            "fit_class_counts": _class_counts(encoded[fit_index]),
            "validation_class_counts": _class_counts(encoded[validation_index]),
            "split_evidence": inner_evidence,
        }

    probability = _positive_probabilities(model, numeric.iloc[test_index])
    predicted = (probability >= selected_threshold).astype(int)

    baseline = DummyClassifier(strategy="prior")
    baseline.fit(numeric.iloc[outer_train], encoded[outer_train])
    baseline_probability = _positive_probabilities(
        baseline, numeric.iloc[test_index]
    )
    baseline_predicted = baseline.predict(numeric.iloc[test_index]).astype(int)
    model_metrics = _metrics(encoded[test_index], predicted, probability)
    baseline_metrics = _metrics(
        encoded[test_index], baseline_predicted, baseline_probability
    )

    predictions = pd.DataFrame(
        {
            "row": test_index,
            "actual_label": labels[test_index],
            "actual_positive": encoded[test_index],
            "positive_probability": probability,
            "predicted_label": np.where(predicted == 1, positive_label, negative_label),
            "predicted_positive": predicted,
            "prior_baseline_probability": baseline_probability,
            "prior_baseline_label": np.where(
                baseline_predicted == 1, positive_label, negative_label
            ),
        }
    ).sort_values("row", ignore_index=True)
    matrix = confusion_matrix(encoded[test_index], predicted, labels=[0, 1])
    matrix_frame = pd.DataFrame(
        matrix,
        index=[f"actual:{negative_label}", f"actual:{positive_label}"],
        columns=[f"predicted:{negative_label}", f"predicted:{positive_label}"],
    )
    coefficients = pd.DataFrame(
        {
            "feature": features,
            "standardized_coefficient": fitted_estimator.coef_[0],
            "odds_ratio_per_standard_deviation": np.exp(
                fitted_estimator.coef_[0]
            ),
        }
    )
    calibration_table = _calibration_table(encoded[test_index], probability)

    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    predictions.to_csv(output_dir / "predictions.csv", index=False)
    matrix_frame.to_csv(output_dir / "confusion_matrix.csv")
    coefficients.to_csv(output_dir / "coefficients.csv", index=False)
    calibration_table.to_csv(output_dir / "calibration.csv", index=False)
    threshold_table.to_csv(output_dir / "threshold_selection.csv", index=False)

    test_positive_rate = float(np.mean(encoded[test_index]))
    warnings = [
        "holdout metrics describe this split and are not confidence bounds for future data",
        "coefficient signs are conditional associations, not causal effects",
    ]
    full_positive_rate = float(np.mean(encoded))
    if min(full_positive_rate, 1 - full_positive_rate) < 0.2:
        warnings.append(
            "the full dataset is imbalanced; prioritize balanced accuracy, PR-AUC, and class-specific errors"
        )
    if len(test_index) < 100:
        warnings.append(
            "the test set has fewer than 100 rows; calibration bins and rare-class metrics are uncertain"
        )
    evidence = {
        "input": str(input_path),
        "input_sha256": _sha256(input_path),
        "target": target,
        "positive_label": positive_label,
        "negative_label": negative_label,
        "features": features,
        "model": "standardized_logistic_regression",
        "C": c_value,
        "class_weight": class_weight,
        "calibration": calibration,
        "split": split,
        "test_size": test_size,
        "seed": seed,
        "group_column": group_column,
        "rows": len(frame),
        "full_class_counts": _class_counts(encoded),
        "train_rows": len(outer_train),
        "test_rows": len(test_index),
        "train_class_counts": _class_counts(encoded[outer_train]),
        "test_class_counts": _class_counts(encoded[test_index]),
        "test_positive_rate": test_positive_rate,
        "outer_split_evidence": outer_evidence,
        "threshold_strategy": threshold_strategy,
        "selected_threshold": selected_threshold,
        "threshold_evidence": threshold_evidence,
        "model_metrics": model_metrics,
        "prior_baseline_metrics": baseline_metrics,
        "beats_prior_baseline_balanced_accuracy": (
            model_metrics["balanced_accuracy"]
            > baseline_metrics["balanced_accuracy"]
        ),
        "beats_prior_baseline_log_loss": (
            model_metrics["log_loss"] < baseline_metrics["log_loss"]
        ),
        "probability_calibration_evidence": {
            "brier_score": model_metrics["brier_score"],
            "log_loss": model_metrics["log_loss"],
            "nonempty_bins": len(calibration_table),
            "calibration_method": (
                "sigmoid_on_training_only_validation_partition"
                if calibration == "sigmoid"
                else "none; test bins are diagnostic only"
            ),
        },
        "coefficient_scale": "standardized_features",
        "warnings": warnings,
        "outputs": [
            "predictions.csv",
            "confusion_matrix.csv",
            "coefficients.csv",
            "calibration.csv",
            "threshold_selection.csv",
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
    parser.add_argument("--target", required=True)
    parser.add_argument("--features", required=True)
    parser.add_argument("--positive-label", required=True)
    parser.add_argument("--split", choices=("stratified", "group"), default="stratified")
    parser.add_argument("--test-size", type=float, default=0.25)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--group-column")
    parser.add_argument("--class-weight", choices=("none", "balanced"), default="none")
    parser.add_argument("--calibration", choices=("none", "sigmoid"), default="sigmoid")
    parser.add_argument("--C", dest="c_value", type=float, default=1.0)
    parser.add_argument("--threshold-strategy", choices=("fixed", "f1", "balanced_accuracy"), default="f1")
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--threshold-validation-size", type=float, default=0.25)
    args = parser.parse_args()
    try:
        run(
            args.input,
            args.output,
            args.target,
            args.features,
            args.positive_label,
            args.split,
            args.test_size,
            args.seed,
            args.group_column,
            args.class_weight,
            args.calibration,
            args.c_value,
            args.threshold_strategy,
            args.threshold,
            args.threshold_validation_size,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

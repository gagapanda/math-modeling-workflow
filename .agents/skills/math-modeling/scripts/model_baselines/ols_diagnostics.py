"""Fit an auditable OLS inference baseline with explicit diagnostics."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import shutil
import sys
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy
from scipy import stats
import statsmodels
import statsmodels.api as sm
from statsmodels.stats.diagnostic import het_breuschpagan, linear_reset
from statsmodels.stats.outliers_influence import variance_inflation_factor
from statsmodels.stats.stattools import durbin_watson, jarque_bera


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _csv_items(value: str, name: str) -> list[str]:
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items:
        raise ValueError(f"{name} cannot be empty")
    if len(items) != len(set(items)):
        raise ValueError(f"{name} must be unique")
    return items


def _finite_or_none(value: float) -> float | None:
    number = float(value)
    return number if math.isfinite(number) else None


def _fit_with_covariance(
    y: np.ndarray,
    design: pd.DataFrame,
    covariance: str,
    groups: np.ndarray | None,
):
    base = sm.OLS(y, design.to_numpy(dtype=float)).fit()
    if covariance == "classic":
        return base, base
    if covariance == "hc3":
        return base, base.get_robustcov_results(cov_type="HC3", use_t=True)
    robust = base.get_robustcov_results(
        cov_type="cluster",
        groups=groups,
        use_correction=True,
        df_correction=True,
        use_t=True,
    )
    return base, robust


def _coefficient_frame(
    result,
    terms: list[str],
    feature_units: list[str],
    target_unit: str,
    feature_sd: np.ndarray,
    target_sd: float,
    confidence_level: float,
) -> pd.DataFrame:
    intervals = np.asarray(result.conf_int(alpha=1.0 - confidence_level), dtype=float)
    rows = []
    for index, term in enumerate(terms):
        is_intercept = index == 0
        standardized = None
        if not is_intercept:
            standardized = float(result.params[index] * feature_sd[index - 1] / target_sd)
        rows.append(
            {
                "term": term,
                "estimate": float(result.params[index]),
                "standard_error": float(result.bse[index]),
                "statistic": float(result.tvalues[index]),
                "p_value": float(result.pvalues[index]),
                "confidence_lower": float(intervals[index, 0]),
                "confidence_upper": float(intervals[index, 1]),
                "standardized_effect": standardized,
                "estimate_unit": target_unit
                if is_intercept
                else f"{target_unit}/{feature_units[index - 1]}",
            }
        )
    return pd.DataFrame(rows)


def _vif_frame(features: pd.DataFrame) -> pd.DataFrame:
    if features.shape[1] == 1:
        values = [1.0]
    else:
        matrix = np.column_stack(
            [np.ones(len(features)), features.to_numpy(dtype=float)]
        )
        values = [
            float(variance_inflation_factor(matrix, index))
            for index in range(1, matrix.shape[1])
        ]
    return pd.DataFrame(
        {
            "feature": list(features.columns),
            "vif": values,
            "moderate_or_worse": [value >= 5.0 for value in values],
            "severe": [value >= 10.0 for value in values],
        }
    )


def _diagnostic_frame(base, design: pd.DataFrame, alpha: float, condition_number: float) -> pd.DataFrame:
    residuals = np.asarray(base.resid, dtype=float)
    bp_lm, bp_p, bp_f, bp_f_p = het_breuschpagan(residuals, design.to_numpy(dtype=float))
    reset = linear_reset(base, power=2, use_f=True)
    jb_stat, jb_p, skewness, kurtosis = jarque_bera(residuals)
    rows = [
        {"diagnostic": "breusch_pagan_lm", "statistic": bp_lm, "p_value": bp_p, "flagged": bp_p < alpha, "null_hypothesis": "constant residual variance"},
        {"diagnostic": "breusch_pagan_f", "statistic": bp_f, "p_value": bp_f_p, "flagged": bp_f_p < alpha, "null_hypothesis": "constant residual variance"},
        {"diagnostic": "ramsey_reset_f", "statistic": float(reset.fvalue), "p_value": float(reset.pvalue), "flagged": float(reset.pvalue) < alpha, "null_hypothesis": "declared linear specification is adequate"},
        {"diagnostic": "jarque_bera", "statistic": jb_stat, "p_value": jb_p, "flagged": jb_p < alpha, "null_hypothesis": "residual normality"},
        {"diagnostic": "durbin_watson", "statistic": durbin_watson(residuals), "p_value": None, "flagged": None, "null_hypothesis": "descriptive only; exact independence decision requires the sampling design"},
        {"diagnostic": "residual_skewness", "statistic": skewness, "p_value": None, "flagged": None, "null_hypothesis": "descriptive only"},
        {"diagnostic": "residual_kurtosis", "statistic": kurtosis, "p_value": None, "flagged": None, "null_hypothesis": "descriptive only; normal reference is 3"},
        {"diagnostic": "standardized_design_condition_number", "statistic": condition_number, "p_value": None, "flagged": condition_number >= 30.0, "null_hypothesis": "threshold is a review heuristic, not a hypothesis test"},
    ]
    return pd.DataFrame(rows)


def _plot_diagnostics(
    fitted: np.ndarray,
    residuals: np.ndarray,
    studentized: np.ndarray,
    cooks: np.ndarray,
    cook_threshold: float,
    target: str,
    target_unit: str,
    destination: Path,
) -> None:
    figure, axes = plt.subplots(2, 2, figsize=(11, 8.5), constrained_layout=True)
    axes[0, 0].scatter(fitted, residuals, s=22, alpha=0.75, color="#2B6F6D")
    axes[0, 0].axhline(0.0, color="#B33A3A", linewidth=1.0)
    axes[0, 0].set_title("Residuals vs fitted")
    axes[0, 0].set_xlabel(f"Fitted {target} ({target_unit})")
    axes[0, 0].set_ylabel(f"Residual ({target_unit})")

    stats.probplot(residuals, dist="norm", plot=axes[0, 1])
    axes[0, 1].set_title("Normal Q-Q")

    axes[1, 0].scatter(fitted, np.sqrt(np.abs(studentized)), s=22, alpha=0.75, color="#805D93")
    axes[1, 0].set_title("Scale-location")
    axes[1, 0].set_xlabel(f"Fitted {target} ({target_unit})")
    axes[1, 0].set_ylabel("sqrt(|studentized residual|)")

    positions = np.arange(len(cooks), dtype=int)
    axes[1, 1].vlines(positions, 0.0, cooks, color="#4C6680", linewidth=0.8)
    axes[1, 1].scatter(positions, cooks, s=12, color="#4C6680")
    axes[1, 1].axhline(cook_threshold, color="#B33A3A", linewidth=1.0, label="4/n review threshold")
    axes[1, 1].set_title("Cook's distance")
    axes[1, 1].set_xlabel("Input row")
    axes[1, 1].set_ylabel("Cook's D")
    axes[1, 1].legend(frameon=False)

    figure.savefig(destination, dpi=160)
    plt.close(figure)


def run(
    input_path: Path,
    output_dir: Path,
    target: str,
    features_arg: str,
    target_unit: str,
    feature_units_arg: str,
    source_note: str,
    covariance: str = "hc3",
    group_column: str | None = None,
    confidence_level: float = 0.95,
    diagnostic_alpha: float = 0.05,
) -> dict:
    input_path = input_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"input file not found: {input_path}")
    if output_dir.exists():
        raise ValueError(f"output directory already exists: {output_dir}")
    if covariance not in {"classic", "hc3", "cluster"}:
        raise ValueError("covariance must be classic, hc3, or cluster")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence_level must be between 0 and 1")
    if not 0.0 < diagnostic_alpha < 1.0:
        raise ValueError("diagnostic_alpha must be between 0 and 1")
    if not target_unit.strip() or not source_note.strip():
        raise ValueError("target unit and source note are required")

    features = _csv_items(features_arg, "features")
    feature_units = _csv_items(feature_units_arg, "feature_units")
    if len(features) != len(feature_units):
        raise ValueError("feature_units must match features in order")
    if target in features:
        raise ValueError("target cannot also be a feature")
    if covariance == "cluster" and group_column is None:
        raise ValueError("cluster covariance requires --group-column")
    if covariance != "cluster" and group_column is not None:
        raise ValueError("group column is only valid with cluster covariance")
    if group_column in features or group_column == target:
        raise ValueError("group column must be separate from target and features")

    frame = pd.read_csv(input_path)
    required = [target, *features] + ([group_column] if group_column else [])
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"missing columns: {', '.join(missing)}")
    numeric = frame[[target, *features]].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any():
        raise ValueError("target and features must contain complete numeric values")
    values = numeric.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("target and features must contain finite values")
    if any(float(numeric[column].std(ddof=1)) == 0.0 for column in [target, *features]):
        raise ValueError("target and features must have non-zero sample variance")

    parameter_count = len(features) + 1
    if len(frame) < max(20, parameter_count + 5):
        raise ValueError("OLS diagnostics require at least 20 rows and five residual degrees of freedom")
    feature_matrix = numeric[features]
    design = pd.DataFrame(
        np.column_stack([np.ones(len(frame)), feature_matrix.to_numpy(dtype=float)]),
        columns=["intercept", *features],
    )
    if np.linalg.matrix_rank(design.to_numpy(dtype=float)) < parameter_count:
        raise ValueError("design matrix is rank deficient")

    groups = None
    group_count = None
    if group_column is not None:
        group_series = frame[group_column]
        if group_series.isna().any():
            raise ValueError("group column must not contain missing values")
        group_count = int(group_series.nunique())
        if group_count < 8:
            raise ValueError("cluster covariance requires at least eight groups")
        groups = group_series.astype(str).to_numpy()

    target_values = numeric[target].to_numpy(dtype=float)
    base, inference = _fit_with_covariance(target_values, design, covariance, groups)
    feature_sd = feature_matrix.std(ddof=1).to_numpy(dtype=float)
    target_sd = float(numeric[target].std(ddof=1))
    coefficients = _coefficient_frame(
        inference, list(design.columns), feature_units, target_unit, feature_sd,
        target_sd, confidence_level,
    )
    vifs = _vif_frame(feature_matrix)

    standardized_features = (feature_matrix - feature_matrix.mean()) / feature_matrix.std(ddof=1)
    condition_number = float(np.linalg.cond(standardized_features.to_numpy(dtype=float)))
    diagnostics = _diagnostic_frame(base, design, diagnostic_alpha, condition_number)

    influence = base.get_influence()
    leverage = np.asarray(influence.hat_matrix_diag, dtype=float)
    studentized = np.asarray(influence.resid_studentized_external, dtype=float)
    cooks = np.asarray(influence.cooks_distance[0], dtype=float)
    leverage_threshold = 2.0 * parameter_count / len(frame)
    cook_threshold = 4.0 / len(frame)
    influence_output = pd.DataFrame(
        {
            "row": np.arange(len(frame), dtype=int),
            "leverage": leverage,
            "studentized_residual": studentized,
            "cooks_distance": cooks,
            "high_leverage": leverage > leverage_threshold,
            "large_studentized_residual": np.abs(studentized) > 3.0,
            "high_cooks_distance": cooks > cook_threshold,
        }
    )
    influence_output["review_flag"] = influence_output[
        ["high_leverage", "large_studentized_residual", "high_cooks_distance"]
    ].any(axis=1)

    fitted_output = pd.DataFrame(
        {
            "row": np.arange(len(frame), dtype=int),
            "actual": target_values,
            "fitted": np.asarray(base.fittedvalues, dtype=float),
            "residual": np.asarray(base.resid, dtype=float),
            "studentized_residual": studentized,
        }
    )
    if group_column is not None:
        fitted_output.insert(1, group_column, frame[group_column].to_numpy())

    flagged = influence_output["review_flag"].to_numpy(dtype=bool)
    sensitivity_rows = []
    sensitivity_available = bool(flagged.any() and (~flagged).sum() >= parameter_count + 5)
    if sensitivity_available:
        sensitivity_groups = groups[~flagged] if groups is not None else None
        _, sensitivity_result = _fit_with_covariance(
            target_values[~flagged], design.loc[~flagged].reset_index(drop=True),
            covariance, sensitivity_groups,
        )
        for index, term in enumerate(design.columns):
            primary = float(inference.params[index])
            alternative = float(sensitivity_result.params[index])
            sensitivity_rows.append(
                {
                    "term": term,
                    "primary_estimate": primary,
                    "review_excluded_estimate": alternative,
                    "absolute_change": abs(alternative - primary),
                    "sign_changed": bool(np.sign(primary) != np.sign(alternative)),
                    "review_excluded_rows": int(flagged.sum()),
                }
            )
    sensitivity = pd.DataFrame(
        sensitivity_rows,
        columns=["term", "primary_estimate", "review_excluded_estimate", "absolute_change", "sign_changed", "review_excluded_rows"],
    )

    r_squared = float(base.rsquared)
    warnings = [
        "coefficient associations are conditional on the declared linear specification and do not establish causality",
        "diagnostic p-values and review thresholds do not authorize automatic deletion, transformation, or model switching",
        "out-of-sample prediction is not evaluated here; use the regression prediction baseline with an appropriate split",
    ]
    if covariance in {"classic", "hc3"}:
        warnings.append("classic and HC3 inference still require independent observational units")
    if covariance == "classic":
        warnings.append("classic covariance requires constant residual variance for its standard errors")
    if covariance == "cluster" and group_count is not None and group_count < 20:
        warnings.append("fewer than 20 clusters makes cluster-robust inference fragile; treat p-values and intervals cautiously")
    if flagged.any():
        warnings.append("influence flags require source review; the sensitivity refit is evidence, not the primary model")

    evidence = {
        "input": str(input_path),
        "input_sha256": _sha256(input_path),
        "runtime": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scipy": scipy.__version__,
            "statsmodels": statsmodels.__version__,
            "matplotlib": matplotlib.__version__,
        },
        "claim_scope": "continuous-response OLS association and diagnostics under the declared numeric design and covariance structure",
        "source_note": source_note,
        "target": {"column": target, "unit": target_unit},
        "features": [
            {"column": column, "unit": unit}
            for column, unit in zip(features, feature_units, strict=True)
        ],
        "rows": len(frame),
        "parameters": parameter_count,
        "residual_degrees_of_freedom": float(base.df_resid),
        "covariance": covariance,
        "group_column": group_column,
        "group_count": group_count,
        "confidence_level": confidence_level,
        "diagnostic_alpha": diagnostic_alpha,
        "model_effects": {
            "r_squared": r_squared,
            "adjusted_r_squared": float(base.rsquared_adj),
            "cohen_f_squared": r_squared / (1.0 - r_squared) if r_squared < 1.0 else None,
            "f_statistic": _finite_or_none(inference.fvalue),
            "f_p_value": _finite_or_none(inference.f_pvalue),
        },
        "diagnostic_summary": {
            "breusch_pagan_flagged": bool(diagnostics.loc[diagnostics["diagnostic"] == "breusch_pagan_lm", "flagged"].iloc[0]),
            "reset_flagged": bool(diagnostics.loc[diagnostics["diagnostic"] == "ramsey_reset_f", "flagged"].iloc[0]),
            "jarque_bera_flagged": bool(diagnostics.loc[diagnostics["diagnostic"] == "jarque_bera", "flagged"].iloc[0]),
            "durbin_watson": float(durbin_watson(base.resid)),
            "maximum_vif": _finite_or_none(vifs["vif"].max()),
            "standardized_design_condition_number": condition_number,
        },
        "influence_review": {
            "leverage_threshold": leverage_threshold,
            "studentized_residual_threshold": 3.0,
            "cooks_distance_threshold": cook_threshold,
            "flagged_rows": int(flagged.sum()),
            "sensitivity_available": sensitivity_available,
        },
        "warnings": warnings,
        "outputs": [
            "coefficients.csv", "diagnostics.csv", "vif.csv",
            "influence.csv", "fitted.csv", "influence_sensitivity.csv",
            "diagnostic_plots.png",
        ],
    }

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}-", dir=output_dir.parent))
    try:
        coefficients.to_csv(temporary / "coefficients.csv", index=False)
        diagnostics.to_csv(temporary / "diagnostics.csv", index=False)
        vifs.to_csv(temporary / "vif.csv", index=False)
        influence_output.to_csv(temporary / "influence.csv", index=False)
        fitted_output.to_csv(temporary / "fitted.csv", index=False)
        sensitivity.to_csv(temporary / "influence_sensitivity.csv", index=False)
        _plot_diagnostics(
            fitted_output["fitted"].to_numpy(), fitted_output["residual"].to_numpy(),
            studentized, cooks, cook_threshold, target, target_unit,
            temporary / "diagnostic_plots.png",
        )
        (temporary / "run.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, output_dir)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--target", required=True)
    parser.add_argument("--features", required=True)
    parser.add_argument("--target-unit", required=True)
    parser.add_argument("--feature-units", required=True)
    parser.add_argument("--source-note", required=True)
    parser.add_argument("--covariance", choices=("classic", "hc3", "cluster"), default="hc3")
    parser.add_argument("--group-column")
    parser.add_argument("--confidence-level", type=float, default=0.95)
    parser.add_argument("--diagnostic-alpha", type=float, default=0.05)
    args = parser.parse_args()
    try:
        run(
            args.input, args.output, args.target, args.features, args.target_unit,
            args.feature_units, args.source_note, args.covariance, args.group_column,
            args.confidence_level, args.diagnostic_alpha,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Generate a read-only, hash-bound data-quality audit for a CSV file."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SEVERITY_ORDER = {"blocker": 0, "warning": 1, "review": 2, "info": 3}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _csv_items(value: str | None, label: str) -> list[str]:
    if value is None:
        return []
    items = [item.strip() for item in value.split(",") if item.strip()]
    if len(set(items)) != len(items):
        raise ValueError(f"{label} must contain unique column names")
    return items


def _validate_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        try:
            header = next(csv.reader(stream))
        except StopIteration as exc:
            raise ValueError("input CSV is empty") from exc
    normalized = [name.strip() for name in header]
    if not normalized or all(not name for name in normalized):
        raise ValueError("input CSV must contain a header row")
    if any(not name for name in normalized):
        raise ValueError("column names must not be blank")
    if len(set(normalized)) != len(normalized):
        raise ValueError("column names must be unique after trimming whitespace")
    if normalized != header:
        raise ValueError("column names must not have leading or trailing whitespace")
    return header


def _finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _display_value(value: Any, limit: int = 160) -> str:
    if pd.isna(value):
        return "<missing>"
    text = str(value).replace("\r", " ").replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _row_digest(values: list[Any]) -> str:
    normalized = [None if pd.isna(value) else str(value) for value in values]
    payload = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _equivalent(left: pd.Series, right: pd.Series) -> bool:
    missing_match = left.isna().to_numpy() == right.isna().to_numpy()
    if not bool(np.all(missing_match)):
        return False
    present = ~(left.isna() | right.isna())
    if not bool(present.any()):
        return True
    left_numeric = pd.to_numeric(left[present], errors="coerce")
    right_numeric = pd.to_numeric(right[present], errors="coerce")
    if left_numeric.notna().all() and right_numeric.notna().all():
        return bool(
            np.allclose(
                left_numeric.to_numpy(dtype=float),
                right_numeric.to_numpy(dtype=float),
                rtol=0.0,
                atol=0.0,
            )
        )
    return bool(
        np.all(
            left[present].astype("string").to_numpy()
            == right[present].astype("string").to_numpy()
        )
    )


def run(
    input_path: Path,
    output_dir: Path,
    id_columns_arg: str | None = None,
    target_columns_arg: str | None = None,
    time_columns_arg: str | None = None,
    group_columns_arg: str | None = None,
    missing_warning_rate: float = 0.05,
    high_correlation_threshold: float = 0.95,
    leakage_correlation_threshold: float = 0.999,
    outlier_iqr_multiplier: float = 1.5,
) -> dict[str, Any]:
    input_path = input_path.expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"input file not found: {input_path}")
    if input_path.suffix.lower() != ".csv":
        raise ValueError("data audit currently supports CSV input only")
    for label, value in (
        ("missing_warning_rate", missing_warning_rate),
        ("high_correlation_threshold", high_correlation_threshold),
        ("leakage_correlation_threshold", leakage_correlation_threshold),
    ):
        if not math.isfinite(value) or not 0 < value <= 1:
            raise ValueError(f"{label} must be finite and in (0, 1]")
    if high_correlation_threshold > leakage_correlation_threshold:
        raise ValueError(
            "high_correlation_threshold cannot exceed leakage_correlation_threshold"
        )
    if not math.isfinite(outlier_iqr_multiplier) or outlier_iqr_multiplier <= 0:
        raise ValueError("outlier_iqr_multiplier must be finite and positive")

    header = _validate_header(input_path)
    input_sha256 = _sha256(input_path)
    frame = pd.read_csv(input_path)
    if frame.empty:
        raise ValueError("input CSV must contain at least one data row")
    if len(frame.columns) > 2000:
        raise ValueError("data audit supports at most 2000 columns")
    if len(frame) > 1_000_000:
        raise ValueError("data audit supports at most 1000000 rows")
    if frame.columns.tolist() != header:
        raise RuntimeError("parsed CSV columns do not match the validated header")

    roles = {
        "id": _csv_items(id_columns_arg, "id_columns"),
        "target": _csv_items(target_columns_arg, "target_columns"),
        "time": _csv_items(time_columns_arg, "time_columns"),
        "group": _csv_items(group_columns_arg, "group_columns"),
    }
    declared = [column for columns in roles.values() for column in columns]
    unknown = sorted(set(declared) - set(frame.columns))
    if unknown:
        raise ValueError(f"declared role columns are missing: {', '.join(unknown)}")
    overlaps = sorted(
        column for column in set(declared) if declared.count(column) > 1
    )
    if overlaps:
        raise ValueError(
            f"columns cannot have multiple declared roles: {', '.join(overlaps)}"
        )
    role_by_column = {
        column: role for role, columns in roles.items() for column in columns
    }

    issues: list[dict[str, Any]] = []

    def add_issue(
        code: str,
        severity: str,
        scope: str,
        column: str | None,
        count: int,
        detail: str,
        action: str,
    ) -> None:
        issues.append(
            {
                "code": code,
                "severity": severity,
                "scope": scope,
                "column": column or "",
                "count": int(count),
                "detail": detail,
                "action": action,
            }
        )

    duplicate_mask = frame.duplicated(keep=False)
    duplicate_rows = frame.loc[duplicate_mask]
    duplicate_records = []
    for row_index, row in duplicate_rows.iterrows():
        record: dict[str, Any] = {
            "row": int(row_index),
            "duplicate_key_sha256": _row_digest(row.tolist()),
        }
        for column in roles["id"]:
            record[column] = row[column]
        duplicate_records.append(record)
    duplicate_pair_excess = int(frame.duplicated(keep="first").sum())
    if duplicate_pair_excess:
        add_issue(
            "duplicate_rows",
            "review",
            "dataset",
            None,
            duplicate_pair_excess,
            "exact duplicate rows were found",
            "confirm the observational unit before removing or aggregating rows",
        )

    column_rows: list[dict[str, Any]] = []
    numeric_rows: list[dict[str, Any]] = []
    categorical_rows: list[dict[str, Any]] = []
    outlier_rows: list[dict[str, Any]] = []
    numeric_data: dict[str, pd.Series] = {}

    for column in frame.columns:
        series = frame[column]
        role = role_by_column.get(column, "feature_candidate")
        missing_count = int(series.isna().sum())
        non_missing_count = len(series) - missing_count
        unique_count = int(series.nunique(dropna=True))
        unique_rate = unique_count / non_missing_count if non_missing_count else 0.0
        numeric = pd.to_numeric(series, errors="coerce")
        numeric_convertible_count = int(numeric.notna().sum())
        is_numeric = pd.api.types.is_numeric_dtype(series)
        if is_numeric:
            semantic_type = "numeric"
        elif column in roles["time"]:
            semantic_type = "datetime_declared"
        elif unique_count <= min(100, max(20, int(len(frame) * 0.2))):
            semantic_type = "categorical"
        else:
            semantic_type = "text_or_identifier"
        column_rows.append(
            {
                "column": column,
                "role": role,
                "pandas_dtype": str(series.dtype),
                "semantic_type": semantic_type,
                "rows": len(frame),
                "missing_count": missing_count,
                "missing_rate": missing_count / len(frame),
                "non_missing_count": non_missing_count,
                "unique_count": unique_count,
                "unique_rate_non_missing": unique_rate,
                "numeric_convertible_count": numeric_convertible_count,
                "numeric_convertible_rate_non_missing": (
                    numeric_convertible_count / non_missing_count
                    if non_missing_count
                    else 0.0
                ),
            }
        )
        if missing_count:
            severity = (
                "blocker"
                if role in {"id", "target", "time"}
                else "warning"
                if missing_count / len(frame) >= missing_warning_rate
                else "review"
            )
            add_issue(
                "missing_values",
                severity,
                "column",
                column,
                missing_count,
                f"missing rate is {missing_count / len(frame):.6g}",
                "define a source-aware missingness policy; do not silently drop or impute",
            )
        if unique_count <= 1:
            add_issue(
                "constant_column",
                "blocker" if role == "target" else "warning",
                "column",
                column,
                non_missing_count,
                "column has at most one non-missing value",
                "exclude it from modeling or correct the upstream data definition",
            )
        if (
            not is_numeric
            and non_missing_count
            and numeric_convertible_count / non_missing_count >= 0.9
        ):
            add_issue(
                "numeric_values_stored_as_text",
                "review",
                "column",
                column,
                numeric_convertible_count,
                "most non-missing values can be parsed as numbers but the column is not numeric",
                "inspect unit marks, locale separators, and sentinel strings before conversion",
            )

        if is_numeric and role != "id":
            finite = numeric.replace([np.inf, -np.inf], np.nan)
            nonfinite_count = int(numeric.notna().sum() - finite.notna().sum())
            if nonfinite_count:
                add_issue(
                    "non_finite_numeric_values",
                    "blocker",
                    "column",
                    column,
                    nonfinite_count,
                    "numeric column contains positive or negative infinity",
                    "trace non-finite values to their generating calculation",
                )
            clean = finite.dropna().astype(float)
            numeric_data[column] = finite.astype(float)
            quantiles = clean.quantile([0.25, 0.5, 0.75]) if not clean.empty else None
            q1 = _finite_float(quantiles.loc[0.25]) if quantiles is not None else None
            median = _finite_float(quantiles.loc[0.5]) if quantiles is not None else None
            q3 = _finite_float(quantiles.loc[0.75]) if quantiles is not None else None
            numeric_rows.append(
                {
                    "column": column,
                    "role": role,
                    "finite_count": len(clean),
                    "mean": _finite_float(clean.mean()) if not clean.empty else None,
                    "sample_standard_deviation": (
                        _finite_float(clean.std(ddof=1)) if len(clean) > 1 else None
                    ),
                    "minimum": _finite_float(clean.min()) if not clean.empty else None,
                    "q1": q1,
                    "median": median,
                    "q3": q3,
                    "maximum": _finite_float(clean.max()) if not clean.empty else None,
                    "zero_count": int((clean == 0).sum()),
                    "negative_count": int((clean < 0).sum()),
                }
            )
            if q1 is not None and q3 is not None and q3 > q1:
                iqr = q3 - q1
                lower = q1 - outlier_iqr_multiplier * iqr
                upper = q3 + outlier_iqr_multiplier * iqr
                outlier_mask = (clean < lower) | (clean > upper)
                outlier_count = int(outlier_mask.sum())
                outlier_rows.append(
                    {
                        "column": column,
                        "role": role,
                        "iqr_multiplier": outlier_iqr_multiplier,
                        "lower_fence": lower,
                        "upper_fence": upper,
                        "outlier_count": outlier_count,
                        "outlier_rate_finite": outlier_count / len(clean),
                    }
                )
                if outlier_count:
                    add_issue(
                        "iqr_outlier_candidates",
                        "review",
                        "column",
                        column,
                        outlier_count,
                        "values fall outside the declared IQR fences",
                        "inspect provenance and model influence; an outlier is not automatically an error",
                    )
        elif role != "id" and semantic_type == "categorical":
            counts = series.value_counts(dropna=True).head(20)
            for rank, (value, count) in enumerate(counts.items(), start=1):
                categorical_rows.append(
                    {
                        "column": column,
                        "role": role,
                        "rank": rank,
                        "value": _display_value(value),
                        "count": int(count),
                        "share_non_missing": int(count) / non_missing_count,
                    }
                )

    if roles["id"]:
        complete_ids = frame[roles["id"]].notna().all(axis=1)
        duplicate_ids = frame.loc[complete_ids, roles["id"]].duplicated(keep=False)
        duplicate_id_count = int(duplicate_ids.sum())
        if duplicate_id_count:
            add_issue(
                "id_not_unique",
                "blocker",
                "column_set",
                "|".join(roles["id"]),
                duplicate_id_count,
                "declared ID column set does not uniquely identify rows",
                "confirm whether rows, entities, or repeated measurements are the unit",
            )

    correlation_rows: list[dict[str, Any]] = []
    numeric_columns = list(numeric_data)
    target_copy_pairs: set[tuple[str, str]] = set()
    for target in roles["target"]:
        for candidate in frame.columns:
            if candidate == target or candidate in roles["id"]:
                continue
            if _equivalent(frame[target], frame[candidate]):
                target_copy_pairs.add(tuple(sorted((target, candidate))))
                add_issue(
                    "target_exact_copy_candidate",
                    "blocker",
                    "column_pair",
                    candidate,
                    int((~frame[target].isna()).sum()),
                    f"{candidate} is an exact value copy of target {target}",
                    "remove post-outcome or duplicated target fields before any split or fit",
                )
    for left_index, left in enumerate(numeric_columns):
        for right in numeric_columns[left_index + 1 :]:
            pair = pd.concat([numeric_data[left], numeric_data[right]], axis=1).dropna()
            if len(pair) < 3 or pair.iloc[:, 0].nunique() < 2 or pair.iloc[:, 1].nunique() < 2:
                continue
            correlation = float(pair.iloc[:, 0].corr(pair.iloc[:, 1]))
            if not math.isfinite(correlation):
                continue
            includes_target = left in roles["target"] or right in roles["target"]
            correlation_rows.append(
                {
                    "left_column": left,
                    "right_column": right,
                    "complete_pairs": len(pair),
                    "pearson_correlation": correlation,
                    "absolute_correlation": abs(correlation),
                    "includes_target": includes_target,
                }
            )
            pair_key = tuple(sorted((left, right)))
            if (
                includes_target
                and abs(correlation) >= leakage_correlation_threshold
                and pair_key not in target_copy_pairs
            ):
                candidate = right if left in roles["target"] else left
                target = left if left in roles["target"] else right
                add_issue(
                    "target_near_perfect_correlation_candidate",
                    "warning",
                    "column_pair",
                    candidate,
                    len(pair),
                    f"absolute Pearson correlation with target {target} is {abs(correlation):.8g}",
                    "review chronology and field derivation; correlation alone does not prove leakage",
                )
            elif abs(correlation) >= high_correlation_threshold:
                add_issue(
                    "high_numeric_correlation",
                    "review",
                    "column_pair",
                    f"{left}|{right}",
                    len(pair),
                    f"absolute Pearson correlation is {abs(correlation):.8g}",
                    "check redundancy, collinearity, shared definitions, and unit conversions",
                )

    time_rows: list[dict[str, Any]] = []
    for column in roles["time"]:
        if pd.api.types.is_numeric_dtype(frame[column]):
            parsed = pd.to_numeric(frame[column], errors="coerce").replace(
                [np.inf, -np.inf], np.nan
            )
            time_kind = "numeric"
            minimum = str(float(parsed.min())) if parsed.notna().any() else ""
            maximum = str(float(parsed.max())) if parsed.notna().any() else ""
            zero = 0.0
        else:
            parsed = pd.to_datetime(frame[column], errors="coerce", utc=True)
            time_kind = "datetime_utc"
            minimum = parsed.min().isoformat() if parsed.notna().any() else ""
            maximum = parsed.max().isoformat() if parsed.notna().any() else ""
            zero = pd.Timedelta(0)
        parse_failures = int((frame[column].notna() & parsed.isna()).sum())
        if parse_failures:
            add_issue(
                "time_parse_failure",
                "blocker",
                "column",
                column,
                parse_failures,
                "declared time values could not be parsed consistently",
                "declare and normalize the timestamp format and timezone explicitly",
            )
        order_violations = 0
        group_count = 1
        if roles["group"]:
            grouped = frame.assign(__parsed_time=parsed).groupby(
                roles["group"], dropna=False, sort=False
            )
            group_count = grouped.ngroups
            for _, group in grouped:
                sequence = group["__parsed_time"].dropna()
                order_violations += int((sequence.diff().dropna() < zero).sum())
        else:
            order_violations = int((parsed.dropna().diff().dropna() < zero).sum())
        if order_violations:
            add_issue(
                "time_order_violation",
                "warning",
                "column",
                column,
                order_violations,
                "declared time values decrease in input order within the audit grouping",
                "sort explicitly only after confirming row order and repeated-time semantics",
            )
        valid = parsed.dropna()
        time_rows.append(
            {
                "column": column,
                "time_kind": time_kind,
                "valid_count": len(valid),
                "parse_failure_count": parse_failures,
                "minimum": minimum,
                "maximum": maximum,
                "group_columns": ",".join(roles["group"]),
                "group_count": group_count,
                "order_violation_count": order_violations,
            }
        )

    issues.sort(
        key=lambda row: (
            SEVERITY_ORDER[row["severity"]],
            row["code"],
            row["column"],
            row["detail"],
        )
    )
    for index, issue in enumerate(issues, start=1):
        issue["issue_id"] = f"DQ-{index:04d}"

    if _sha256(input_path) != input_sha256:
        raise RuntimeError("input file changed while the data audit was running")

    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame.from_records(column_rows).to_csv(output_dir / "columns.csv", index=False)
    pd.DataFrame.from_records(numeric_rows, columns=[
        "column", "role", "finite_count", "mean",
        "sample_standard_deviation", "minimum", "q1", "median",
        "q3", "maximum", "zero_count", "negative_count",
    ]).to_csv(output_dir / "numeric_summary.csv", index=False)
    pd.DataFrame.from_records(categorical_rows, columns=[
        "column", "role", "rank", "value", "count", "share_non_missing",
    ]).to_csv(output_dir / "categorical_summary.csv", index=False)
    pd.DataFrame.from_records(outlier_rows, columns=[
        "column", "role", "iqr_multiplier", "lower_fence", "upper_fence",
        "outlier_count", "outlier_rate_finite",
    ]).to_csv(output_dir / "outliers.csv", index=False)
    pd.DataFrame.from_records(correlation_rows, columns=[
        "left_column", "right_column", "complete_pairs",
        "pearson_correlation", "absolute_correlation", "includes_target",
    ]).to_csv(output_dir / "correlations.csv", index=False)
    pd.DataFrame.from_records(time_rows, columns=[
        "column", "time_kind", "valid_count", "parse_failure_count", "minimum",
        "maximum", "group_columns", "group_count", "order_violation_count",
    ]).to_csv(output_dir / "time_summary.csv", index=False)
    pd.DataFrame.from_records(duplicate_records, columns=[
        "row", "duplicate_key_sha256", *roles["id"],
    ]).to_csv(output_dir / "duplicate_rows.csv", index=False)
    issue_columns = [
        "issue_id", "code", "severity", "scope", "column",
        "count", "detail", "action",
    ]
    pd.DataFrame.from_records(issues, columns=issue_columns).to_csv(
        output_dir / "issues.csv", index=False
    )

    severity_counts = {severity: 0 for severity in SEVERITY_ORDER}
    for issue in issues:
        severity_counts[issue["severity"]] += 1
    evidence = {
        "input": str(input_path),
        "input_sha256": input_sha256,
        "method": "read_only_csv_data_quality_audit",
        "rows": len(frame),
        "columns": len(frame.columns),
        "roles": roles,
        "parameters": {
            "missing_warning_rate": missing_warning_rate,
            "high_correlation_threshold": high_correlation_threshold,
            "leakage_correlation_threshold": leakage_correlation_threshold,
            "outlier_iqr_multiplier": outlier_iqr_multiplier,
        },
        "duplicate_excess_row_count": duplicate_pair_excess,
        "issue_count": len(issues),
        "issue_counts_by_severity": severity_counts,
        "ready_for_modeling": severity_counts["blocker"] == 0,
        "interpretation_boundary": (
            "audit findings are candidates for source and modeling review; they do not authorize automatic cleaning, exclusion, imputation, or leakage claims"
        ),
        "outputs": [
            "columns.csv", "numeric_summary.csv", "categorical_summary.csv",
            "outliers.csv", "correlations.csv", "time_summary.csv",
            "duplicate_rows.csv", "issues.csv", "summary.md",
        ],
    }
    (output_dir / "run.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    summary = [
        "# Data Audit Summary",
        "",
        f"- Input SHA-256: {input_sha256}",
        f"- Shape: {len(frame)} rows x {len(frame.columns)} columns",
        f"- Ready for modeling: {str(evidence['ready_for_modeling']).lower()}",
        f"- Issues: {len(issues)} ({severity_counts['blocker']} blocker, {severity_counts['warning']} warning, {severity_counts['review']} review)",
        "",
        "Findings are review candidates, not authorization to alter the source data.",
    ]
    (output_dir / "summary.md").write_text(
        "\n".join(summary) + "\n", encoding="utf-8"
    )
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--id-columns")
    parser.add_argument("--target-columns")
    parser.add_argument("--time-columns")
    parser.add_argument("--group-columns")
    parser.add_argument("--missing-warning-rate", type=float, default=0.05)
    parser.add_argument("--high-correlation-threshold", type=float, default=0.95)
    parser.add_argument("--leakage-correlation-threshold", type=float, default=0.999)
    parser.add_argument("--outlier-iqr-multiplier", type=float, default=1.5)
    args = parser.parse_args()
    try:
        run(
            args.input, args.output, args.id_columns, args.target_columns,
            args.time_columns, args.group_columns, args.missing_warning_rate,
            args.high_correlation_threshold, args.leakage_correlation_threshold,
            args.outlier_iqr_multiplier,
        )
    except (OSError, RuntimeError, ValueError, pd.errors.ParserError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

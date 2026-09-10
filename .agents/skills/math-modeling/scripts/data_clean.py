"""Apply a hash-bound, declarative cleaning plan to a CSV file."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from _json_schema import load_and_validate


OUTPUTS = (
    "processed.csv", "changes.csv", "dropped_rows.csv",
    "schema_changes.csv", "rule_summary.csv", "plan.json",
    "run.json", "summary.md",
)
RULE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
OPERATIONS = {
    "trim_whitespace": {"columns"},
    "replace_values": {"columns", "replacements"},
    "convert_numeric": {"columns", "errors"},
    "fill_missing": {"columns", "value"},
    "clip_numeric": {"columns", "minimum", "maximum"},
    "unit_transform": {"columns", "factor", "offset"},
    "swap_columns_by_row_key": {"columns", "row_keys"},
    "drop_missing_rows": {"columns", "how"},
    "drop_duplicate_rows": {"subset", "keep"},
    "rename_columns": {"mapping"},
}
COMMON_FIELDS = {"id", "operation", "reason", "expected_changes"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        try:
            header = next(csv.reader(stream))
        except StopIteration as exc:
            raise ValueError("input CSV is empty") from exc
    normalized = [name.strip() for name in header]
    if not normalized or any(not name for name in normalized):
        raise ValueError("input CSV must have non-blank column names")
    if normalized != header:
        raise ValueError("column names must not have leading or trailing whitespace")
    if len(set(header)) != len(header):
        raise ValueError("column names must be unique")
    return header


def _is_missing(value: Any) -> bool:
    return value is None or value is pd.NA or (
        isinstance(value, float) and math.isnan(value)
    )


def _plain(value: Any) -> Any:
    if _is_missing(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("cleaned values must be finite")
    return value


def _scalar(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool, type(None))) and not (
        isinstance(value, float) and not math.isfinite(value)
    )


def _same(left: Any, right: Any) -> bool:
    if _is_missing(left) or _is_missing(right):
        return _is_missing(left) and _is_missing(right)
    return type(_plain(left)) is type(_plain(right)) and _plain(left) == _plain(right)


def _json_value(value: Any) -> str:
    return json.dumps(_plain(value), ensure_ascii=False, separators=(",", ":"))


def _columns(rule_id: str, value: Any, available: list[str], label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"rule {rule_id}: {label} must be a non-empty list")
    if any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"rule {rule_id}: {label} must contain non-empty strings")
    if len(set(value)) != len(value):
        raise ValueError(f"rule {rule_id}: {label} must contain unique columns")
    missing = sorted(set(value) - set(available))
    if missing:
        raise ValueError(f"rule {rule_id}: unknown columns: {', '.join(missing)}")
    return value


def _validate_plan(plan: Any, header: list[str], input_hash: str) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise ValueError("cleaning plan must be a JSON object")
    allowed = {"version", "input_sha256", "row_id_columns", "rules"}
    unknown = sorted(set(plan) - allowed)
    if unknown:
        raise ValueError(f"unknown cleaning plan fields: {', '.join(unknown)}")
    if plan.get("version") != 1:
        raise ValueError("cleaning plan version must be 1")
    declared_hash = plan.get("input_sha256")
    if not isinstance(declared_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", declared_hash):
        raise ValueError("input_sha256 must be a lowercase SHA-256 digest")
    if declared_hash != input_hash:
        raise ValueError("input_sha256 does not match the current input file")
    row_ids = plan.get("row_id_columns", [])
    if not isinstance(row_ids, list):
        raise ValueError("row_id_columns must be a list")
    if row_ids:
        _columns("plan", row_ids, header, "row_id_columns")
    rules = plan.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ValueError("rules must be a non-empty list")

    available = list(header)
    seen: set[str] = set()
    for position, rule in enumerate(rules, start=1):
        if not isinstance(rule, dict):
            raise ValueError(f"rule {position} must be a JSON object")
        rule_id = rule.get("id")
        if not isinstance(rule_id, str) or not RULE_ID.fullmatch(rule_id):
            raise ValueError(f"rule {position}: invalid id")
        if rule_id in seen:
            raise ValueError(f"duplicate rule id: {rule_id}")
        seen.add(rule_id)
        operation = rule.get("operation")
        if operation not in OPERATIONS:
            raise ValueError(f"rule {rule_id}: unsupported operation: {operation}")
        allowed_fields = COMMON_FIELDS | OPERATIONS[operation]
        unknown_fields = sorted(set(rule) - allowed_fields)
        missing_fields = sorted(COMMON_FIELDS - set(rule))
        if unknown_fields or missing_fields:
            raise ValueError(
                f"rule {rule_id}: invalid fields; unknown={unknown_fields}, missing={missing_fields}"
            )
        if not isinstance(rule["reason"], str) or not rule["reason"].strip():
            raise ValueError(f"rule {rule_id}: reason must be non-empty")
        expected = rule["expected_changes"]
        if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
            raise ValueError(f"rule {rule_id}: expected_changes must be non-negative integer")
        if operation == "rename_columns":
            mapping = rule.get("mapping")
            if not isinstance(mapping, dict) or not mapping:
                raise ValueError(f"rule {rule_id}: mapping must be a non-empty object")
            _columns(rule_id, list(mapping), available, "mapping keys")
            if any(not isinstance(value, str) or not value for value in mapping.values()):
                raise ValueError(f"rule {rule_id}: mapping values must be non-empty strings")
            renamed = [mapping.get(column, column) for column in available]
            if len(set(renamed)) != len(renamed):
                raise ValueError(f"rule {rule_id}: renamed columns would not be unique")
            available = renamed
            continue
        key = "subset" if operation == "drop_duplicate_rows" else "columns"
        _columns(rule_id, rule.get(key), available, key)
        if operation == "swap_columns_by_row_key":
            if not row_ids:
                raise ValueError(
                    f"rule {rule_id}: swap_columns_by_row_key requires non-empty row_id_columns"
                )
            if not set(row_ids).issubset(available):
                raise ValueError(
                    f"rule {rule_id}: row_id_columns are unavailable after prior rules"
                )
            if len(rule["columns"]) != 2:
                raise ValueError(
                    f"rule {rule_id}: swap_columns_by_row_key requires exactly two columns"
                )
            if set(rule["columns"]) & set(row_ids):
                raise ValueError(
                    f"rule {rule_id}: swap columns must not include row_id_columns"
                )
            row_key_values = rule.get("row_keys")
            if not isinstance(row_key_values, list) or not row_key_values:
                raise ValueError(f"rule {rule_id}: row_keys must be a non-empty list")
            seen_row_keys: set[str] = set()
            for row_key in row_key_values:
                if not isinstance(row_key, dict) or set(row_key) != set(row_ids):
                    raise ValueError(
                        f"rule {rule_id}: each row key must contain exactly the row_id_columns"
                    )
                if any(not _scalar(value) for value in row_key.values()):
                    raise ValueError(f"rule {rule_id}: row key values must be finite scalars")
                encoded_key = json.dumps(
                    row_key, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                if encoded_key in seen_row_keys:
                    raise ValueError(f"rule {rule_id}: row_keys must be unique")
                seen_row_keys.add(encoded_key)
        if operation == "replace_values":
            replacements = rule.get("replacements")
            if not isinstance(replacements, list) or not replacements:
                raise ValueError(f"rule {rule_id}: replacements must be a non-empty list")
            for item in replacements:
                if not isinstance(item, dict) or set(item) != {"from", "to"}:
                    raise ValueError(f"rule {rule_id}: each replacement needs only from and to")
                if not _scalar(item["from"]) or not _scalar(item["to"]):
                    raise ValueError(f"rule {rule_id}: replacement values must be finite scalars")
        if operation == "convert_numeric" and rule.get("errors") not in {"fail", "coerce"}:
            raise ValueError(f"rule {rule_id}: errors must be fail or coerce")
        if operation == "fill_missing" and not _scalar(rule.get("value")):
            raise ValueError(f"rule {rule_id}: value must be a finite scalar")
        if operation == "clip_numeric":
            minimum, maximum = rule.get("minimum"), rule.get("maximum")
            if minimum is None and maximum is None:
                raise ValueError(f"rule {rule_id}: minimum or maximum is required")
            for label, value in (("minimum", minimum), ("maximum", maximum)):
                if value is not None and (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                ):
                    raise ValueError(
                        f"rule {rule_id}: {label} must be finite numeric or null"
                    )
            if minimum is not None and maximum is not None and minimum > maximum:
                raise ValueError(f"rule {rule_id}: minimum cannot exceed maximum")
        if operation == "unit_transform":
            for label in ("factor", "offset"):
                value = rule.get(label)
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                ):
                    raise ValueError(f"rule {rule_id}: {label} must be finite numeric")
            if rule["factor"] == 0:
                raise ValueError(f"rule {rule_id}: factor must not be zero")
        if operation == "drop_missing_rows" and rule.get("how") not in {"any", "all"}:
            raise ValueError(f"rule {rule_id}: how must be any or all")
        if operation == "drop_duplicate_rows" and rule.get("keep") not in {"first", "last"}:
            raise ValueError(f"rule {rule_id}: keep must be first or last")
    return plan


def _row_json(row: pd.Series, columns: list[str]) -> str:
    payload = {column: _plain(row[column]) for column in columns}
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def run(input_path: Path, plan_path: Path, output_dir: Path) -> dict[str, Any]:
    input_path = input_path.expanduser().resolve()
    plan_path = plan_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"input file not found: {input_path}")
    if input_path.suffix.lower() != ".csv":
        raise ValueError("data cleaning currently supports CSV input only")
    if not plan_path.is_file():
        raise FileNotFoundError(f"plan file not found: {plan_path}")
    if input_path == output_dir / "processed.csv":
        raise ValueError("processed output must not overwrite the input file")
    existing = [name for name in OUTPUTS if (output_dir / name).exists()]
    if existing:
        raise FileExistsError(f"managed outputs already exist: {', '.join(existing)}")

    header = _validate_header(input_path)
    input_hash = _sha256(input_path)
    plan_hash = _sha256(plan_path)
    try:
        raw_plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid cleaning plan JSON: {exc.msg}") from exc
    plan = _validate_plan(raw_plan, header, input_hash)
    load_and_validate(
        plan,
        Path(__file__).resolve().parents[1]
        / "schemas"
        / "data-cleaning-plan.schema.json",
        "data cleaning plan",
    )
    frame = pd.read_csv(
        input_path, dtype=object, keep_default_na=False, na_filter=False
    )
    if frame.empty:
        raise ValueError("input CSV must contain at least one data row")
    if frame.columns.tolist() != header:
        raise RuntimeError("parsed CSV columns do not match the validated header")
    if len(frame) > 1_000_000 or len(frame.columns) > 2000:
        raise ValueError("data cleaning supports at most 1000000 rows and 2000 columns")

    source_rows = pd.Series(range(2, len(frame) + 2), index=frame.index)
    original_rows = {index: _row_json(frame.loc[index], header) for index in frame.index}
    row_ids = plan.get("row_id_columns", [])
    row_keys = {
        index: json.dumps(
            {column: _plain(frame.at[index, column]) for column in row_ids},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        for index in frame.index
    }
    changes: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    schema_changes: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []

    def assign(rule: dict[str, Any], index: Any, column: str, after: Any) -> int:
        before = frame.at[index, column]
        if _same(before, after):
            return 0
        changes.append({
            "rule_id": rule["id"],
            "operation": rule["operation"],
            "reason": rule["reason"],
            "source_row": int(source_rows.loc[index]),
            "row_key_json": row_keys[index],
            "column": column,
            "before_json": _json_value(before),
            "after_json": _json_value(after),
        })
        frame.at[index, column] = after
        return 1

    for order, rule in enumerate(plan["rules"], start=1):
        operation = rule["operation"]
        observed = 0
        if operation == "rename_columns":
            for before, after in rule["mapping"].items():
                if before != after:
                    schema_changes.append({
                        "rule_id": rule["id"],
                        "operation": operation,
                        "reason": rule["reason"],
                        "before_column": before,
                        "after_column": after,
                    })
                    observed += 1
            frame = frame.rename(columns=rule["mapping"])
        elif operation == "trim_whitespace":
            for column in rule["columns"]:
                for index in frame.index:
                    value = frame.at[index, column]
                    if isinstance(value, str):
                        observed += assign(rule, index, column, value.strip())
        elif operation == "replace_values":
            for column in rule["columns"]:
                for index in frame.index:
                    value = frame.at[index, column]
                    for replacement in rule["replacements"]:
                        if _same(value, replacement["from"]):
                            after = replacement["to"]
                            observed += assign(
                                rule, index, column, pd.NA if after is None else after
                            )
                            break
        elif operation == "swap_columns_by_row_key":
            left_column, right_column = rule["columns"]
            for row_key in rule["row_keys"]:
                matched = [
                    index for index in frame.index
                    if all(_same(frame.at[index, column], row_key[column]) for column in row_ids)
                ]
                if len(matched) != 1:
                    key_text = json.dumps(
                        row_key, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                    )
                    raise ValueError(
                        f"rule {rule['id']}: row key {key_text} matched {len(matched)} rows"
                    )
                index = matched[0]
                left, right = frame.at[index, left_column], frame.at[index, right_column]
                observed += assign(rule, index, left_column, right)
                observed += assign(rule, index, right_column, left)
        elif operation == "convert_numeric":
            for column in rule["columns"]:
                for index in frame.index:
                    value = frame.at[index, column]
                    if _is_missing(value):
                        continue
                    converted = pd.to_numeric(
                        pd.Series([value]), errors="coerce"
                    ).iloc[0]
                    if _is_missing(converted):
                        if rule["errors"] == "fail":
                            raise ValueError(
                                f"rule {rule['id']}: cannot convert {column} at source row "
                                f"{source_rows.loc[index]} to numeric"
                            )
                        converted = pd.NA
                    elif not math.isfinite(float(converted)):
                        raise ValueError(
                            f"rule {rule['id']}: non-finite numeric value at source row "
                            f"{source_rows.loc[index]}"
                        )
                    else:
                        converted = _plain(converted)
                    observed += assign(rule, index, column, converted)
        elif operation == "fill_missing":
            for column in rule["columns"]:
                for index in frame.index:
                    if _is_missing(frame.at[index, column]):
                        observed += assign(rule, index, column, rule["value"])
        elif operation in {"clip_numeric", "unit_transform"}:
            for column in rule["columns"]:
                for index in frame.index:
                    value = frame.at[index, column]
                    if _is_missing(value):
                        continue
                    if (
                        isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or not math.isfinite(float(value))
                    ):
                        raise ValueError(
                            f"rule {rule['id']}: {column} at source row "
                            f"{source_rows.loc[index]} is not finite numeric"
                        )
                    if operation == "clip_numeric":
                        after = value
                        if rule["minimum"] is not None:
                            after = max(after, rule["minimum"])
                        if rule["maximum"] is not None:
                            after = min(after, rule["maximum"])
                    else:
                        after = float(value) * rule["factor"] + rule["offset"]
                        if not math.isfinite(after):
                            raise ValueError(
                                f"rule {rule['id']}: unit transform produced non-finite value"
                            )
                    observed += assign(rule, index, column, after)
        elif operation in {"drop_missing_rows", "drop_duplicate_rows"}:
            if operation == "drop_missing_rows":
                missing = frame[rule["columns"]].map(_is_missing)
                mask = (
                    missing.any(axis=1)
                    if rule["how"] == "any"
                    else missing.all(axis=1)
                )
            else:
                mask = frame.duplicated(
                    subset=rule["subset"], keep=rule["keep"]
                )
            indices = frame.index[mask].tolist()
            for index in indices:
                row_json = _row_json(frame.loc[index], frame.columns.tolist())
                dropped.append({
                    "rule_id": rule["id"],
                    "operation": operation,
                    "reason": rule["reason"],
                    "source_row": int(source_rows.loc[index]),
                    "row_key_json": row_keys[index],
                    "original_row_sha256": hashlib.sha256(
                        original_rows[index].encode("utf-8")
                    ).hexdigest(),
                    "row_before_drop_json": row_json,
                })
            frame = frame.drop(index=indices)
            observed = len(indices)

        if observed != rule["expected_changes"]:
            raise ValueError(
                f"rule {rule['id']}: expected {rule['expected_changes']} changes "
                f"but observed {observed}"
            )
        summaries.append({
            "order": order,
            "rule_id": rule["id"],
            "operation": operation,
            "reason": rule["reason"],
            "expected_changes": rule["expected_changes"],
            "observed_changes": observed,
            "rows_after": len(frame),
            "columns_after": len(frame.columns),
        })

    if _sha256(input_path) != input_hash:
        raise RuntimeError("input file changed while data cleaning was running")
    if _sha256(plan_path) != plan_hash:
        raise RuntimeError("cleaning plan changed while data cleaning was running")

    output_dir.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_dir / "processed.csv", index=False, lineterminator="\n")
    pd.DataFrame.from_records(changes, columns=[
        "rule_id", "operation", "reason", "source_row", "row_key_json",
        "column", "before_json", "after_json",
    ]).to_csv(output_dir / "changes.csv", index=False, lineterminator="\n")
    pd.DataFrame.from_records(dropped, columns=[
        "rule_id", "operation", "reason", "source_row", "row_key_json",
        "original_row_sha256", "row_before_drop_json",
    ]).to_csv(output_dir / "dropped_rows.csv", index=False, lineterminator="\n")
    pd.DataFrame.from_records(schema_changes, columns=[
        "rule_id", "operation", "reason", "before_column", "after_column",
    ]).to_csv(output_dir / "schema_changes.csv", index=False, lineterminator="\n")
    pd.DataFrame.from_records(summaries).to_csv(
        output_dir / "rule_summary.csv", index=False, lineterminator="\n"
    )
    (output_dir / "plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    hashed_outputs = OUTPUTS[:6]
    evidence = {
        "method": "declarative_hash_bound_csv_cleaning",
        "input": str(input_path),
        "input_sha256": input_hash,
        "plan": str(plan_path),
        "plan_sha256": plan_hash,
        "plan_version": 1,
        "input_rows": len(original_rows),
        "output_rows": len(frame),
        "input_columns": len(header),
        "output_columns": len(frame.columns),
        "cell_changes": len(changes),
        "dropped_rows": len(dropped),
        "schema_changes": len(schema_changes),
        "rules_applied": len(summaries),
        "input_unchanged": True,
        "plan_unchanged": True,
        "output_sha256": {name: _sha256(output_dir / name) for name in hashed_outputs},
        "interpretation_boundary": (
            "the ledger proves which declared mechanical transformations ran; "
            "it does not prove that the cleaning decisions are scientifically justified"
        ),
        "outputs": list(OUTPUTS[:-2]) + ["summary.md"],
    }
    (output_dir / "run.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    summary = [
        "# Data Cleaning Summary", "",
        f"- Input SHA-256: {input_hash}",
        f"- Plan SHA-256: {plan_hash}",
        f"- Shape: {len(original_rows)} x {len(header)} -> {len(frame)} x {len(frame.columns)}",
        f"- Rules applied: {len(summaries)}",
        f"- Cell changes: {len(changes)}",
        f"- Dropped rows: {len(dropped)}",
        f"- Schema changes: {len(schema_changes)}", "",
        "The ledger records execution, not scientific authorization for each rule.",
    ]
    (output_dir / "summary.md").write_text(
        "\n".join(summary) + "\n", encoding="utf-8"
    )
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        run(args.input, args.plan, args.output)
    except (OSError, RuntimeError, ValueError, pd.errors.ParserError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

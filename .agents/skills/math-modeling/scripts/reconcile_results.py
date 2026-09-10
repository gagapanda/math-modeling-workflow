#!/usr/bin/env python
"""Reconcile canonical result values with generated JSON and final papers."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

from _workflow_common import extract_docx_text, extract_pdf_text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--register", type=Path)
    parser.add_argument("--docx", type=Path)
    parser.add_argument("--pdf", type=Path)
    parser.add_argument(
        "--skip-paper",
        action="store_true",
        help="Validate the register and generated source values without requiring paper artifacts",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    return parser.parse_args()


def load_json(path: Path):
    def reject_constant(value: str):
        raise ValueError(f"non-finite JSON constant {value} is not allowed")

    try:
        return json.loads(
            path.read_text(encoding="utf-8"), parse_constant=reject_constant
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"cannot read JSON {path}: {exc}") from exc


def resolve_source(case_dir: Path, relative: str) -> Path:
    source = (case_dir / relative).resolve()
    try:
        source.relative_to(case_dir)
    except ValueError as exc:
        raise ValueError(f"source_file escapes case directory: {relative}") from exc
    return source


def get_key(data, key: str):
    current = data
    if not key:
        return current
    for part in key.split("."):
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(part)
            current = current[part]
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index]
        else:
            raise KeyError(part)
    return current


def values_match(expected, actual, absolute_tolerance: float, relative_tolerance: float) -> bool:
    if isinstance(expected, bool) or isinstance(actual, bool):
        return expected == actual
    if isinstance(expected, str) and isinstance(actual, str):
        return expected == actual
    try:
        expected_number = float(expected)
        actual_number = float(actual)
    except (TypeError, ValueError):
        return str(expected) == str(actual)
    if not math.isfinite(expected_number) or not math.isfinite(actual_number):
        return expected_number == actual_number
    return math.isclose(
        expected_number,
        actual_number,
        abs_tol=absolute_tolerance,
        rel_tol=relative_tolerance,
    )


def count_paper_occurrences(text: str, needle: str) -> int:
    numeric = re.fullmatch(
        r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", needle
    )
    if numeric:
        # Unicode \w includes Chinese characters, which commonly appear
        # directly beside values (for example, "降至35.663米"). Only block
        # adjacency that can make the match part of another numeric or ASCII
        # identifier token.
        pattern = rf"(?<![A-Za-z0-9_.+-]){re.escape(needle)}(?![A-Za-z0-9_.])"
        return len(re.findall(pattern, text))
    return text.count(needle)


def run_reconciliation(args: argparse.Namespace) -> dict:
    case_dir = args.case_dir.expanduser().resolve()
    register_path = (
        args.register.expanduser().resolve()
        if args.register
        else case_dir / "results" / "result-register.json"
    )
    report = {
        "reconciled": False,
        "case_dir": str(case_dir),
        "register": str(register_path),
        "results": [],
        "errors": [],
        "warnings": [],
    }
    if not case_dir.is_dir():
        report["errors"].append(f"case directory does not exist: {case_dir}")
        return report

    try:
        register = load_json(register_path)
    except ValueError as exc:
        report["errors"].append(str(exc))
        return report
    if not isinstance(register, dict):
        report["errors"].append("result register must be a JSON object")
        return report
    if register.get("schema_version") != 1:
        report["errors"].append("result register schema_version must be 1")
        return report
    entries = register.get("results")
    if not isinstance(entries, list):
        report["errors"].append("result register results must be an array")
        return report
    if not entries:
        report["errors"].append("result register contains no results")

    paper_texts = {}
    for label, path, loader in (
        ("docx", args.docx, extract_docx_text),
        ("pdf", args.pdf, extract_pdf_text),
    ):
        if path is None:
            continue
        resolved = path.expanduser().resolve()
        if not resolved.is_file():
            report["errors"].append(f"{label} paper does not exist: {resolved}")
            continue
        try:
            paper_texts[label] = loader(resolved)
        except ValueError as exc:
            report["errors"].append(str(exc))

    seen_ids = set()
    for index, entry in enumerate(entries):
        item = {"index": index, "ok": False, "errors": []}
        report["results"].append(item)
        if not isinstance(entry, dict):
            item["errors"].append("entry must be an object")
            continue
        result_id = entry.get("id")
        item["id"] = result_id
        required = ("id", "value", "source_file", "source_key", "paper_required")
        missing = [name for name in required if name not in entry]
        if missing:
            item["errors"].append(f"missing fields: {', '.join(missing)}")
            continue
        if not isinstance(result_id, str) or not result_id.strip():
            item["errors"].append("id must be a non-empty string")
            continue
        if result_id in seen_ids:
            item["errors"].append("duplicate id")
            continue
        seen_ids.add(result_id)
        if not isinstance(entry["paper_required"], bool):
            item["errors"].append("paper_required must be boolean")
            continue
        if not isinstance(entry["value"], (str, int, float, bool)):
            item["errors"].append("value must be a scalar string, number, or boolean")
            continue
        if "paper_text" in entry and not isinstance(entry["paper_text"], str):
            item["errors"].append("paper_text must be a string")
            continue
        paper_text = str(entry.get("paper_text", entry["value"]))
        if entry["paper_required"] and not paper_text.strip():
            item["errors"].append(
                "paper_text must be non-empty when paper_required is true"
            )
            continue
        if isinstance(entry["value"], float) and not math.isfinite(entry["value"]):
            item["errors"].append("registered numeric value must be finite")
            continue
        if not isinstance(entry["source_file"], str) or not entry["source_file"].strip():
            item["errors"].append("source_file must be a non-empty string")
            continue
        if not isinstance(entry["source_key"], str):
            item["errors"].append("source_key must be a string")
            continue

        try:
            absolute_tolerance = float(entry.get("absolute_tolerance", 0.0))
            relative_tolerance = float(entry.get("relative_tolerance", 0.0))
        except (TypeError, ValueError):
            item["errors"].append("tolerances must be numeric")
            continue
        if (
            not math.isfinite(absolute_tolerance)
            or not math.isfinite(relative_tolerance)
            or absolute_tolerance < 0
            or relative_tolerance < 0
        ):
            item["errors"].append("tolerances must be finite and non-negative")
            continue

        try:
            source_path = resolve_source(case_dir, entry["source_file"])
            source_data = load_json(source_path)
            actual = get_key(source_data, entry["source_key"])
        except (ValueError, KeyError, IndexError) as exc:
            item["errors"].append(f"cannot resolve source value: {exc}")
            continue
        if not isinstance(actual, (str, int, float, bool)):
            item["errors"].append(
                "generated source value must be a scalar string, number, or boolean"
            )
            continue
        if isinstance(actual, float) and not math.isfinite(actual):
            item["errors"].append("generated numeric source value must be finite")
            continue
        item["source_file"] = str(source_path)
        item["expected"] = entry["value"]
        item["actual"] = actual
        if not values_match(
            entry["value"], actual, absolute_tolerance, relative_tolerance
        ):
            item["errors"].append("registered value does not match generated value")

        if entry["paper_required"] and not args.skip_paper:
            if not paper_texts:
                item["errors"].append("paper_required is true but no readable paper was supplied")
            item["paper_text"] = paper_text
            item["paper_occurrences"] = {
                label: count_paper_occurrences(text, paper_text)
                for label, text in paper_texts.items()
            }
            for label, text in paper_texts.items():
                if count_paper_occurrences(text, paper_text) == 0:
                    item["errors"].append(
                        f"required paper text {paper_text!r} is missing from {label}"
                    )
        item["ok"] = not item["errors"]

    for item in report["results"]:
        for error in item["errors"]:
            report["errors"].append(f"{item.get('id', item['index'])}: {error}")
    report["reconciled"] = not report["errors"]
    return report


def print_human(report: dict) -> None:
    print(f"reconciled={str(report['reconciled']).lower()}")
    print(f"register={report['register']}")
    print(f"result_count={len(report['results'])}")
    for item in report["results"]:
        print(f"result.{item.get('id', item['index'])}={'ok' if item['ok'] else 'failed'}")
    for warning in report["warnings"]:
        print(f"warning: {warning}")
    for error in report["errors"]:
        print(f"error: {error}")


def main() -> int:
    args = parse_args()
    report = run_reconciliation(args)
    if args.json:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        print_human(report)
    return 0 if report["reconciled"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""Score hash-bound selected-page OCR output against reviewed text and formula features."""

from __future__ import annotations

import argparse
import json
import unicodedata
from datetime import datetime
from pathlib import Path

from _json_schema import load_and_validate
from _workflow_common import atomic_write_json, sha256_file


SKILL_DIR = Path(__file__).resolve().parents[1]
BENCHMARK_SCHEMA = SKILL_DIR / "schemas" / "ocr-benchmark.schema.json"
REVIEW_SCHEMA = SKILL_DIR / "schemas" / "ocr-benchmark-review.schema.json"
REPORT_SCHEMA = SKILL_DIR / "schemas" / "ocr-benchmark-report.schema.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--ocr-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scored-at", help="Explicit timezone-aware audit timestamp")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def load_json(path: Path, schema: Path, label: str) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    load_and_validate(payload, schema, label)
    return payload


def resolve_relative(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def require_hash(path: Path, expected: str, label: str) -> None:
    if not path.is_file():
        raise ValueError(f"{label} does not exist: {path}")
    if sha256_file(path) != expected:
        raise ValueError(f"{label} SHA-256 does not match the benchmark binding")


def normalize_retrieval_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def best_substring_levenshtein(reference: str, candidate: str) -> int:
    if not reference:
        raise ValueError("normalized body-text reference is empty")
    previous = [0] * (len(candidate) + 1)
    for row, expected in enumerate(reference, start=1):
        current = [row]
        for column, observed in enumerate(candidate, start=1):
            current.append(
                min(
                    previous[column] + 1,
                    current[column - 1] + 1,
                    previous[column - 1] + (expected != observed),
                )
            )
        previous = current
    return min(previous)


def _unique_by_id(items: list[dict], label: str) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for item in items:
        identifier = item["id"]
        if identifier in result:
            raise ValueError(f"duplicate {label} id: {identifier}")
        result[identifier] = item
    return result


def score(
    benchmark_path: Path,
    review_path: Path,
    ocr_dir: Path,
    scored_at: str | None = None,
) -> dict:
    benchmark_path = benchmark_path.expanduser().resolve()
    review_path = review_path.expanduser().resolve()
    ocr_dir = ocr_dir.expanduser().resolve()
    benchmark = load_json(benchmark_path, BENCHMARK_SCHEMA, "OCR benchmark")
    review = load_json(review_path, REVIEW_SCHEMA, "OCR benchmark review")
    if review["benchmark_sha256"] != sha256_file(benchmark_path):
        raise ValueError("OCR review is not bound to the current benchmark")

    manifest_binding = benchmark["prepared_manifest"]
    manifest_path = resolve_relative(benchmark_path.parent, manifest_binding["path"])
    require_hash(manifest_path, manifest_binding["sha256"], "prepared manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_pages = {item["page"]: item for item in manifest["pages"]}

    evidence_binding = benchmark["evidence_card"]
    evidence_path = resolve_relative(benchmark_path.parent, evidence_binding["path"])
    require_hash(evidence_path, evidence_binding["sha256"], "PDF evidence card")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence_formulas = _unique_by_id(evidence["verified_formulas"], "evidence formula")

    body_truth = benchmark["body_text"]
    body_page = body_truth["page"]
    if body_page not in manifest_pages:
        raise ValueError("body-text page is not present in the prepared manifest")
    if manifest_pages[body_page]["image_sha256"] != body_truth["image_sha256"]:
        raise ValueError("body-text image hash does not match the prepared manifest")

    benchmark_formulas = _unique_by_id(benchmark["formulas"], "benchmark formula")
    for identifier, truth in benchmark_formulas.items():
        if identifier not in evidence_formulas:
            raise ValueError(f"formula truth is absent from the evidence card: {identifier}")
        if evidence_formulas[identifier]["verified_transcription"] != truth["verified_transcription"]:
            raise ValueError(f"formula truth changed from the evidence card: {identifier}")
        page = truth["page"]
        if page not in manifest_pages:
            raise ValueError(f"formula page is not present in the prepared manifest: {page}")

    for page in {body_page, *[item["page"] for item in benchmark_formulas.values()]}:
        page_record = manifest_pages[page]
        image_path = resolve_relative(manifest_path.parent, page_record["image"])
        require_hash(image_path, page_record["image_sha256"], f"prepared page image {page}")

    if not ocr_dir.is_dir():
        raise ValueError(f"OCR output directory does not exist: {ocr_dir}")
    ocr_files: dict[int, tuple[Path, str]] = {}
    for item in review["ocr_files"]:
        page = item["page"]
        if page in ocr_files:
            raise ValueError(f"duplicate OCR output page: {page}")
        path = resolve_relative(ocr_dir, item["path"])
        require_hash(path, item["sha256"], f"OCR output page {page}")
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ValueError(f"cannot read OCR output page {page}: {exc}") from exc
        ocr_files[page] = (path, content)
    if body_page not in ocr_files:
        raise ValueError("OCR review does not include the body-text page")

    reference = normalize_retrieval_text(body_truth["reference_text"])
    candidate = normalize_retrieval_text(ocr_files[body_page][1])
    distance = best_substring_levenshtein(reference, candidate)
    cer = distance / len(reference)
    cjk_characters = sum("\u3400" <= character <= "\u9fff" for character in ocr_files[body_page][1])

    reviewed_formulas = _unique_by_id(review["formula_results"], "review formula")
    if set(reviewed_formulas) != set(benchmark_formulas):
        raise ValueError("formula review ids must exactly match the benchmark formula ids")
    detected = 0
    usable = 0
    feature_total = 0
    feature_correct = 0
    high_risk_total = 0
    high_risk_correct = 0
    formula_details = []
    for identifier, truth in benchmark_formulas.items():
        observed = reviewed_formulas[identifier]
        expected_features = _unique_by_id(truth["features"], f"feature for {identifier}")
        observed_features = _unique_by_id(observed["features"], f"review feature for {identifier}")
        if set(expected_features) != set(observed_features):
            raise ValueError(f"review features do not match the benchmark for {identifier}")
        detected += int(observed["detected"])
        usable += int(observed["usable_without_correction"])
        correct_for_formula = 0
        for feature_id, feature in expected_features.items():
            feature_total += 1
            correct = observed_features[feature_id]["status"] == "correct"
            feature_correct += int(correct)
            correct_for_formula += int(correct)
            if feature["risk"] == "high":
                high_risk_total += 1
                high_risk_correct += int(correct)
        formula_details.append(
            {
                "id": identifier,
                "detected": observed["detected"],
                "usable_without_correction": observed["usable_without_correction"],
                "features_correct": correct_for_formula,
                "features_total": len(expected_features),
            }
        )

    formula_count = len(benchmark_formulas)
    detection_recall = detected / formula_count
    feature_recall = feature_correct / feature_total
    high_risk_recall = high_risk_correct / high_risk_total if high_risk_total else 1.0
    thresholds = benchmark["thresholds"]
    body_passed = cer <= thresholds["max_body_text_cer"]
    detection_passed = detection_recall >= thresholds["min_formula_detection_recall"]
    features_passed = feature_recall >= thresholds["min_formula_feature_recall"]
    high_risk_passed = (
        high_risk_correct == high_risk_total
        if thresholds["require_all_high_risk_features"]
        else True
    )
    current_passed = body_passed and detection_passed and features_passed and high_risk_passed
    formula_passed = detection_passed and features_passed and high_risk_passed
    provisional = benchmark["status"] != "confirmed"
    if scored_at is None:
        scored_at = datetime.now().astimezone().isoformat()
    else:
        try:
            parsed_time = datetime.fromisoformat(scored_at)
        except ValueError as exc:
            raise ValueError("scored_at must be an ISO 8601 timestamp") from exc
        if parsed_time.tzinfo is None:
            raise ValueError("scored_at must include a timezone offset")
        scored_at = parsed_time.isoformat()

    report = {
        "schema_version": 1,
        "status": "provisional" if provisional else "final",
        "scored_at": scored_at,
        "bindings": {
            "benchmark_sha256": sha256_file(benchmark_path),
            "review_sha256": sha256_file(review_path),
            "prepared_manifest_sha256": manifest_binding["sha256"],
            "evidence_card_sha256": evidence_binding["sha256"],
            "ocr_files": {
                str(page): {"path": str(path), "sha256": sha256_file(path)}
                for page, (path, _) in sorted(ocr_files.items())
            },
        },
        "configuration": {
            "backend": review["backend"],
            "model": review["model"],
            "layout_analysis": review["layout_analysis"],
        },
        "body_text": {
            "page": body_page,
            "reference_characters_normalized": len(reference),
            "candidate_characters_normalized": len(candidate),
            "candidate_cjk_characters_raw": cjk_characters,
            "best_substring_edit_distance": distance,
            "normalized_cer": cer,
            "passed": body_passed,
        },
        "formulas": {
            "total": formula_count,
            "detected": detected,
            "detection_recall": detection_recall,
            "usable_without_correction": usable,
            "feature_correct": feature_correct,
            "feature_total": feature_total,
            "feature_recall": feature_recall,
            "high_risk_correct": high_risk_correct,
            "high_risk_total": high_risk_total,
            "high_risk_recall": high_risk_recall,
            "detection_passed": detection_passed,
            "features_passed": features_passed,
            "high_risk_passed": high_risk_passed,
            "details": formula_details,
        },
        "thresholds": thresholds,
        "decisions": {
            "current_configuration": "adopt" if current_passed else "reject",
            "body_text_retrieval": "adopt" if body_passed else "reject",
            "formula_retrieval": "adopt" if formula_passed else "reject",
            "production_default": (
                "blocked_pending_named_human_confirmation"
                if provisional
                else ("adopt" if current_passed else "reject")
            ),
            "formula_truth": "forbidden_without_visual_human_review",
        },
        "limitations": [
            *benchmark["limitations"],
            "formula feature scoring records retrieval fidelity only and does not validate the mathematics",
            "OCR output must never replace visual formula verification",
        ],
    }
    load_and_validate(report, REPORT_SCHEMA, "OCR benchmark report")
    return report


def main() -> int:
    args = parse_args()
    result = {"scored": False, "errors": []}
    try:
        output = args.output.expanduser().resolve()
        if output.exists():
            raise ValueError(f"output already exists: {output}")
        if not output.parent.is_dir():
            raise ValueError(f"output parent does not exist: {output.parent}")
        report = score(args.benchmark, args.review, args.ocr_dir, args.scored_at)
        atomic_write_json(output, report)
        result.update({"scored": True, "path": str(output), "report": report})
    except (OSError, ValueError) as exc:
        result["errors"].append(str(exc))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"scored={str(result['scored']).lower()}")
        if result.get("path"):
            print(f"path={result['path']}")
        for error in result["errors"]:
            print(f"error: {error}")
    return 0 if result["scored"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

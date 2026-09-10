#!/usr/bin/env python
"""Analyze a workflow v1 manifest for a conservative, read-only v2 migration."""

from __future__ import annotations

import argparse
import ast
import copy
import json
import re
import sys
from pathlib import Path, PurePosixPath

sys.dont_write_bytecode = True

from _diagnostics import attach_diagnostics, diagnostic
from _json_schema import load_and_validate
from run_pipeline import WORKFLOW_SCHEMA, load_manifest


REPORT_SCHEMA = (
    Path(__file__).resolve().parent.parent
    / "schemas"
    / "workflow-migration-analysis.schema.json"
)
READ_METHODS = {
    "read_bytes", "read_csv", "read_excel",
    "read_feather", "read_json", "read_parquet", "read_pickle",
    "read_table", "read_text",
}
WRITE_METHODS = {
    "savefig", "savetxt", "to_csv", "to_excel",
    "to_feather", "to_json", "to_parquet", "to_pickle",
    "write_bytes", "write_text",
}
PATH_LOAD_RECEIVERS = {"joblib", "np", "numpy", "pickle"}
PATH_SAVE_RECEIVERS = {"joblib", "np", "numpy"}
PATH_SUFFIXES = {
    ".csv", ".docx", ".json", ".mat", ".npy", ".npz", ".parquet",
    ".pdf", ".pickle", ".pkl", ".png", ".svg", ".tex", ".txt",
    ".xls", ".xlsx",
}
ROOT_NAMES = {"base", "case_dir", "project_dir", "project_root", "root"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    return parser.parse_args()


def relative_manifest_path(case_dir: Path, manifest: Path | None) -> Path:
    selected = manifest.expanduser() if manifest else case_dir / "workflow.json"
    if not selected.is_absolute():
        selected = case_dir / selected
    selected = selected.resolve()
    selected.relative_to(case_dir)
    return selected


def normalized_literal(value: str) -> str | None:
    value = value.strip().replace("\\", "/")
    if not value or value.startswith(("http://", "https://")):
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.suffix.casefold() not in PATH_SUFFIXES:
        return None
    while path.parts and path.parts[0] in {".", ""}:
        path = PurePosixPath(*path.parts[1:])
    return path.as_posix() if path.parts else None


def path_expression(node: ast.AST, symbols: dict[str, str] | None = None) -> str | None:
    symbols = symbols or {}
    if isinstance(node, ast.Name):
        return symbols.get(node.id)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return normalized_literal(node.value)
    if isinstance(node, ast.Call) and node.args:
        name = call_name(node.func)
        if name in {"Path", "PurePath", "PurePosixPath", "PureWindowsPath"}:
            return path_expression(node.args[0], symbols)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        right = node.right.value if isinstance(node.right, ast.Constant) else None
        if not isinstance(right, str):
            return None
        left = path_expression(node.left, symbols)
        if left:
            return normalized_literal(f"{left}/{right}")
        if isinstance(node.left, ast.Name) and node.left.id.casefold() in ROOT_NAMES:
            return normalized_literal(right)
        if isinstance(node.left, ast.BinOp):
            segments = division_segments(node, symbols)
            return normalized_literal("/".join(segments)) if segments is not None else None
    return None


def division_segments(node: ast.AST, symbols: dict[str, str]) -> list[str] | None:
    if isinstance(node, ast.Name) and node.id in symbols:
        return list(PurePosixPath(symbols[node.id]).parts)
    if isinstance(node, ast.Name) and node.id.casefold() in ROOT_NAMES:
        return []
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = division_segments(node.left, symbols)
        if left is not None and isinstance(node.right, ast.Constant) and isinstance(node.right.value, str):
            return [*left, node.right.value]
    return None


def call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def call_receiver(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return node.value.id
    return ""


def open_access(call: ast.Call) -> str:
    mode = None
    if len(call.args) > 1 and isinstance(call.args[1], ast.Constant):
        mode = call.args[1].value
    for keyword in call.keywords:
        if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
            mode = keyword.value.value
    return "output" if isinstance(mode, str) and any(char in mode for char in "wax+") else "input"


def static_path_hints(script: Path) -> tuple[list[dict], bool]:
    try:
        tree = ast.parse(script.read_text(encoding="utf-8"), filename=str(script))
    except (OSError, UnicodeError, SyntaxError):
        return [], False
    symbols: dict[str, str] = {}
    assignments = [node for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.AnnAssign))]
    for _ in range(len(assignments) + 1):
        changed = False
        for node in assignments:
            value = path_expression(node.value, symbols) if node.value is not None else None
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if value is not None:
                for target in targets:
                    if isinstance(target, ast.Name) and symbols.get(target.id) != value:
                        symbols[target.id] = value
                        changed = True
        if not changed:
            break

    hints: dict[tuple[str, str], dict] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = call_name(node.func)
        receiver = call_receiver(node.func)
        access = None
        candidate = None
        if name == "open" and node.args:
            access = open_access(node)
            candidate = path_expression(node.args[0], symbols)
        elif name in READ_METHODS | WRITE_METHODS:
            access = "input" if name in READ_METHODS else "output"
            if node.args:
                candidate = path_expression(node.args[0], symbols)
            if candidate is None and isinstance(node.func, ast.Attribute):
                candidate = path_expression(node.func.value, symbols)
        elif name == "load" and receiver in PATH_LOAD_RECEIVERS and node.args:
            access = "input"
            candidate = path_expression(node.args[0], symbols)
        elif name == "save" and receiver in PATH_SAVE_RECEIVERS and node.args:
            access = "output"
            candidate = path_expression(node.args[0], symbols)
        if candidate and access:
            hints.setdefault(
                (candidate, access),
                {
                    "path": candidate,
                    "access": access,
                    "line": node.lineno,
                    "evidence": f"literal path used by {name}()",
                    "confidence": "static_literal_hint",
                },
            )
    return sorted(hints.values(), key=lambda item: (item["path"], item["access"])), True


def safe_v2_candidate(raw: dict) -> dict:
    candidate = copy.deepcopy(raw)
    candidate["schema_version"] = 2
    candidate["profile"] = "practice"
    for step in candidate["steps"]:
        if step.get("type", "python") == "python":
            step.update(
                {
                    "inputs": [],
                    "outputs": [],
                    "timeout_seconds": 300,
                    "cache": False,
                }
            )
    return candidate


def analyze(case_dir: Path, manifest_path: Path) -> dict:
    load_manifest(case_dir, manifest_path)
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_version = raw["schema_version"]
    applicable = source_version == 1
    candidate = safe_v2_candidate(raw) if applicable else None
    if candidate is not None:
        load_and_validate(candidate, WORKFLOW_SCHEMA, "migration candidate")

    steps = []
    review_required = []
    input_hints = 0
    output_hints = 0
    for raw_step in raw["steps"]:
        step_type = raw_step.get("type", "python")
        hints = []
        reasons = []
        defaults = {}
        action = "unchanged"
        if step_type == "python" and applicable:
            action = "add_safe_python_defaults"
            defaults = {"inputs": [], "outputs": [], "timeout_seconds": 300, "cache": False}
            script = case_dir / raw_step["script"]
            hints, parsed = static_path_hints(script)
            input_hints += sum(item["access"] == "input" for item in hints)
            output_hints += sum(item["access"] == "output" for item in hints)
            reasons = ["declared_dependencies_require_review", "cache_requires_review"]
            if not parsed:
                reasons.append("source_analysis_unavailable")
            for code, message in (
                ("declared_dependencies_require_review", "Confirm every input and output; static literal hints are incomplete by design."),
                ("cache_requires_review", "Enable cache only after dependency closure and deterministic-output review."),
            ):
                review_required.append({"step": raw_step["name"], "code": code, "message": message})
            if not parsed:
                review_required.append(
                    {
                        "step": raw_step["name"],
                        "code": "source_analysis_unavailable",
                        "message": "The Python source could not be parsed; inspect it manually.",
                    }
                )
        steps.append(
            {
                "name": raw_step["name"],
                "type": step_type,
                "migration_action": action,
                "safe_defaults": defaults,
                "static_path_hints": hints,
                "review_reason_codes": reasons,
            }
        )

    warnings = []
    entries = []
    if applicable:
        warnings.append(
            "The candidate preserves v1 execution semantics; static path hints are not inserted into the manifest."
        )
        entries.append(
            diagnostic(
                "warning",
                "migration_human_review_required",
                "workflow_migration",
                f"{len(review_required)} migration decisions require human review",
                remediation=["Review declared inputs, outputs, timeouts, and determinism before enabling cache"],
            )
        )
    else:
        warnings.append("The manifest already uses workflow schema version 2; no candidate was generated.")

    report = {
        "schema_version": 1,
        "command": "analyze_workflow_migration",
        "mode": "passive_read_only",
        "files_written": False,
        "case_steps_executed": False,
        "case_dir": str(case_dir),
        "manifest_path": str(manifest_path),
        "source_schema_version": source_version,
        "target_schema_version": 2,
        "applicable": applicable,
        "candidate_manifest": candidate,
        "candidate_valid": candidate is not None,
        "steps": steps,
        "summary": {
            "python_steps": sum(step["type"] == "python" for step in steps),
            "matlab_steps": sum(step["type"] == "matlab" for step in steps),
            "static_input_hints": input_hints,
            "static_output_hints": output_hints,
            "cache_enable_recommended": 0,
            "human_review_items": len(review_required),
        },
        "review_required": review_required,
        "errors": [],
        "warnings": warnings,
    }
    report = attach_diagnostics(report, entries)
    load_and_validate(report, REPORT_SCHEMA, "workflow migration analysis")
    return report


def failure_report(case_dir: Path, manifest_path: Path, message: str) -> dict:
    return attach_diagnostics(
        {
            "schema_version": 1,
            "command": "analyze_workflow_migration",
            "mode": "passive_read_only",
            "files_written": False,
            "case_steps_executed": False,
            "case_dir": str(case_dir),
            "manifest_path": str(manifest_path),
            "source_schema_version": 1,
            "target_schema_version": 2,
            "applicable": False,
            "candidate_manifest": None,
            "candidate_valid": False,
            "steps": [],
            "summary": {"python_steps": 0, "matlab_steps": 0, "static_input_hints": 0, "static_output_hints": 0, "cache_enable_recommended": 0, "human_review_items": 0},
            "review_required": [],
            "errors": [message],
            "warnings": [],
        },
        [diagnostic("error", "migration_analysis_failed", "workflow_migration", message, remediation=["Repair the case path or manifest, then rerun the analyzer"])],
    )


def print_human(report: dict) -> None:
    print(f"applicable={str(report['applicable']).lower()}")
    print(f"candidate_valid={str(report['candidate_valid']).lower()}")
    for step in report["steps"]:
        print(f"step.{step['name']}={step['migration_action']} ({len(step['static_path_hints'])} hints)")
    for error in report["errors"]:
        print(f"error: {error}")


def main() -> int:
    args = parse_args()
    case_dir = args.case_dir.expanduser().resolve()
    manifest_path = case_dir / "workflow.json"
    try:
        if not case_dir.is_dir():
            raise ValueError(f"case directory does not exist: {case_dir}")
        manifest_path = relative_manifest_path(case_dir, args.manifest)
        report = analyze(case_dir, manifest_path)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        report = failure_report(case_dir, manifest_path, str(exc))
    if args.json:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        print_human(report)
    return 0 if not report["errors"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

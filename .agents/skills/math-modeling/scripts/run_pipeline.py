#!/usr/bin/env python
"""Run a manifest-driven modeling case pipeline up to or after visual review."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from _diagnostics import enrich_legacy_report
from _json_schema import load_and_validate
from _workflow_common import (
    append_failure_event,
    atomic_write_json,
    resolve_inside,
    sha256_file,
    sha256_path,
    verify_evidence_hashes,
)
from data_audit import run as run_data_audit
from data_clean import OUTPUTS as DATA_CLEAN_OUTPUTS, run as run_data_clean
from audit_paper import inspect_png


WORKFLOW_SCHEMA = Path(__file__).resolve().parent.parent / "schemas" / "workflow.schema.json"
PIPELINE_REPORT_SCHEMA = (
    Path(__file__).resolve().parent.parent / "schemas" / "pipeline-report.schema.json"
)
EXECUTION_PLAN_SCHEMA = (
    Path(__file__).resolve().parent.parent / "schemas" / "execution-plan.schema.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--phase", choices=("build", "finalize"), default="build")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Explain selected steps and cache decisions without executing or writing files",
    )
    parser.add_argument(
        "--from",
        dest="from_step",
        metavar="STEP",
        help="Start at STEP and continue through the remaining build steps",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="STEPS",
        help="Run only comma-separated build steps and skip paper post-processing",
    )
    parser.add_argument(
        "--force",
        action="append",
        default=[],
        metavar="STEPS",
        help="Ignore cached state for comma-separated build steps",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    return parser.parse_args()


def parse_step_names(values: list[str]) -> set[str]:
    names = {name.strip() for value in values for name in value.split(",") if name.strip()}
    return names


def select_steps(
    steps: list[dict], from_step: str | None = None, only: set[str] | None = None
) -> tuple[list[dict], bool]:
    names = [step["name"] for step in steps]
    selected_only = only or set()
    if from_step and selected_only:
        raise ValueError("--from and --only cannot be used together")
    unknown = selected_only - set(names)
    if unknown:
        raise ValueError(f"unknown --only step(s): {', '.join(sorted(unknown))}")
    if from_step:
        if from_step not in names:
            raise ValueError(f"unknown --from step: {from_step}")
        return steps[names.index(from_step) :], True
    if selected_only:
        return [step for step in steps if step["name"] in selected_only], False
    return steps, True


def load_workflow_state(path: Path) -> dict:
    return inspect_workflow_state(path)[0]


def inspect_workflow_state(path: Path) -> tuple[dict, str]:
    if not path.exists():
        return {"schema_version": 1, "steps": {}}, "missing"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"schema_version": 1, "steps": {}}, "invalid"
    if (
        not isinstance(data, dict)
        or data.get("schema_version") != 1
        or not isinstance(data.get("steps"), dict)
    ):
        return {"schema_version": 1, "steps": {}}, "invalid"
    return data, "loaded"


def python_step_fingerprint(step: dict, case_dir: Path) -> tuple[str | None, list[str]]:
    files = [step["script"], *step.get("inputs", [])]
    missing = [
        str(path.relative_to(case_dir)).replace("\\", "/")
        for path in files
        if not path.is_file() and not path.is_dir()
    ]
    if missing:
        return None, missing
    file_hashes = {
        str(path.relative_to(case_dir)).replace("\\", "/"): sha256_path(path)
        for path in files
    }
    payload = {
        "name": step["name"],
        "type": "python",
        "args": step["args"],
        "timeout_seconds": step.get("timeout_seconds", 300),
        "python_executable": str(Path(sys.executable).resolve()),
        "python_version": sys.version,
        "files": file_hashes,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), []


def output_hashes(step: dict, case_dir: Path) -> tuple[dict[str, str], list[str]]:
    hashes = {}
    missing = []
    for path in step.get("outputs", []):
        relative = str(path.relative_to(case_dir)).replace("\\", "/")
        if not path.is_file():
            missing.append(relative)
        else:
            hashes[relative] = sha256_file(path)
    return hashes, missing


def cached_python_step(
    step: dict, case_dir: Path, state: dict, fingerprint: str
) -> dict | None:
    if not step.get("cache"):
        return None
    entry = state["steps"].get(step["name"])
    if not isinstance(entry, dict) or entry.get("fingerprint") != fingerprint:
        return None
    hashes, missing = output_hashes(step, case_dir)
    if missing or entry.get("output_sha256") != hashes:
        return None
    return {
        "name": step["name"],
        "type": "python",
        "ok": True,
        "status": "cache-hit",
        "fingerprint": fingerprint,
        "output_sha256": hashes,
    }


DATA_AUDIT_OUTPUTS = (
    "columns.csv",
    "numeric_summary.csv",
    "categorical_summary.csv",
    "outliers.csv",
    "correlations.csv",
    "time_summary.csv",
    "duplicate_rows.csv",
    "issues.csv",
    "run.json",
    "summary.md",
)


def relative_path(path: Path, case_dir: Path) -> str:
    return str(path.relative_to(case_dir)).replace("\\", "/")


def paths_overlap(left: Path, right: Path) -> bool:
    try:
        left.relative_to(right)
        return True
    except ValueError:
        try:
            right.relative_to(left)
            return True
        except ValueError:
            return False


def hash_output_directory(
    directory: Path, names: tuple[str, ...], case_dir: Path
) -> tuple[dict[str, str], list[str]]:
    hashes: dict[str, str] = {}
    missing: list[str] = []
    for name in names:
        path = directory / name
        relative = relative_path(path, case_dir)
        if not path.is_file():
            missing.append(relative)
        else:
            hashes[relative] = sha256_file(path)
    return hashes, missing


def data_preparation_outputs(
    preparation: dict, case_dir: Path
) -> tuple[dict[str, str], list[str]]:
    groups: list[tuple[Path, tuple[str, ...]]] = [
        (preparation["raw_audit_output"], DATA_AUDIT_OUTPUTS)
    ]
    if preparation.get("cleaning_plan") is not None:
        groups.extend(
            [
                (preparation["cleaning_output"], tuple(DATA_CLEAN_OUTPUTS)),
                (preparation["processed_audit_output"], DATA_AUDIT_OUTPUTS),
            ]
        )
    hashes: dict[str, str] = {}
    missing: list[str] = []
    for directory, names in groups:
        group_hashes, group_missing = hash_output_directory(directory, names, case_dir)
        hashes.update(group_hashes)
        missing.extend(group_missing)
    return hashes, missing


def data_preparation_fingerprint(
    preparation: dict, case_dir: Path
) -> tuple[str | None, list[str]]:
    files = [preparation["input"], Path(__file__).resolve().parent / "data_audit.py"]
    if preparation.get("cleaning_plan") is not None:
        scripts_dir = Path(__file__).resolve().parent
        files.extend(
            [
                preparation["cleaning_plan"],
                scripts_dir / "data_clean.py",
                scripts_dir.parent / "schemas" / "data-cleaning-plan.schema.json",
            ]
        )
    missing = []
    for path in files:
        if not path.is_file():
            try:
                missing.append(relative_path(path, case_dir))
            except ValueError:
                missing.append(str(path))
    if missing:
        return None, missing
    payload = {
        "type": "data_preparation",
        "python_executable": str(Path(sys.executable).resolve()),
        "python_version": sys.version,
        "roles": preparation["roles"],
        "input": relative_path(preparation["input"], case_dir),
        "raw_audit_output": relative_path(preparation["raw_audit_output"], case_dir),
        "cleaning_plan": (
            relative_path(preparation["cleaning_plan"], case_dir)
            if preparation.get("cleaning_plan") is not None
            else None
        ),
        "cleaning_output": (
            relative_path(preparation["cleaning_output"], case_dir)
            if preparation.get("cleaning_output") is not None
            else None
        ),
        "processed_audit_output": (
            relative_path(preparation["processed_audit_output"], case_dir)
            if preparation.get("processed_audit_output") is not None
            else None
        ),
        "files": {
            str(path): sha256_file(path)
            for path in files
        },
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), []


def cached_data_preparation(
    preparation: dict, case_dir: Path, state: dict, fingerprint: str
) -> dict | None:
    entry = state.get("data_preparation")
    if not isinstance(entry, dict) or entry.get("fingerprint") != fingerprint:
        return None
    hashes, missing = data_preparation_outputs(preparation, case_dir)
    if missing or entry.get("output_sha256") != hashes:
        return None
    return {
        "name": "data-preparation",
        "type": "data_preparation",
        "status": "cache-hit",
        "ok": True,
        "fingerprint": fingerprint,
        "output_sha256": hashes,
    }


def read_json_object(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def reusable_cleaning_evidence(
    preparation: dict, case_dir: Path, state: dict
) -> dict | None:
    output_dir = preparation["cleaning_output"]
    evidence = read_json_object(output_dir / "run.json")
    if evidence is None:
        return None
    if evidence.get("input_sha256") != sha256_file(preparation["input"]):
        return None
    if evidence.get("plan_sha256") != sha256_file(preparation["cleaning_plan"]):
        return None
    expected = evidence.get("output_sha256")
    if not isinstance(expected, dict):
        return None
    actual = {}
    for name in DATA_CLEAN_OUTPUTS[:6]:
        path = output_dir / name
        if not path.is_file():
            return None
        actual[name] = sha256_file(path)
    if actual != expected or any(not (output_dir / name).is_file() for name in DATA_CLEAN_OUTPUTS):
        return None
    state_entry = state.get("data_preparation")
    if isinstance(state_entry, dict) and isinstance(state_entry.get("output_sha256"), dict):
        actual_full, missing = hash_output_directory(
            output_dir, tuple(DATA_CLEAN_OUTPUTS), case_dir
        )
        expected_full = {
            relative_path(output_dir / name, case_dir): state_entry["output_sha256"].get(
                relative_path(output_dir / name, case_dir)
            )
            for name in DATA_CLEAN_OUTPUTS
        }
        if missing or None in expected_full.values() or actual_full != expected_full:
            return None
    return evidence


def run_data_preparation(
    preparation: dict, case_dir: Path, state: dict
) -> dict:
    fingerprint, missing_inputs = data_preparation_fingerprint(preparation, case_dir)
    base = {
        "name": "data-preparation",
        "type": "data_preparation",
        "status": "executed",
        "fingerprint": fingerprint,
        "stages": [],
    }
    if missing_inputs:
        return {
            **base,
            "ok": False,
            "failed_stage": "inputs",
            "missing_inputs": missing_inputs,
            "stderr": "Data preparation input, plan, or bundled script is missing",
            "remediation": ["Restore every missing data-preparation input before rerunning."],
        }
    cached = cached_data_preparation(preparation, case_dir, state, fingerprint)
    if cached is not None:
        return cached

    roles = preparation["roles"]
    try:
        raw_audit = run_data_audit(
            preparation["input"],
            preparation["raw_audit_output"],
            ",".join(roles["id"]) or None,
            ",".join(roles["target"]) or None,
            ",".join(roles["time"]) or None,
            ",".join(roles["group"]) or None,
        )
    except Exception as exc:
        return {
            **base,
            "ok": False,
            "failed_stage": "raw_audit",
            "stderr": str(exc),
            "remediation": ["Repair the CSV or data-preparation roles, then rerun."],
        }
    base["stages"].append(
        {
            "name": "raw_audit",
            "status": "executed",
            "ready_for_modeling": raw_audit["ready_for_modeling"],
            "run": relative_path(preparation["raw_audit_output"] / "run.json", case_dir),
        }
    )

    if preparation.get("cleaning_plan") is None:
        final_audit = raw_audit
        final_stage = "raw_audit"
    else:
        cleaning = reusable_cleaning_evidence(preparation, case_dir, state)
        if cleaning is None:
            existing = [
                name for name in DATA_CLEAN_OUTPUTS
                if (preparation["cleaning_output"] / name).exists()
            ]
            if existing:
                return {
                    **base,
                    "ok": False,
                    "failed_stage": "cleaning_evidence",
                    "stderr": "Cleaning output already exists but its hash-bound ledger is not reusable",
                    "existing_outputs": existing,
                    "remediation": [
                        "Allocate a new cleaning_output directory; do not overwrite existing cleaning evidence."
                    ],
                }
            try:
                cleaning = run_data_clean(
                    preparation["input"],
                    preparation["cleaning_plan"],
                    preparation["cleaning_output"],
                )
                cleaning_status = "executed"
            except Exception as exc:
                return {
                    **base,
                    "ok": False,
                    "failed_stage": "cleaning",
                    "stderr": str(exc),
                    "remediation": [
                        "Repair the hash-bound cleaning plan or allocate a new cleaning_output directory."
                    ],
                }
        else:
            cleaning_status = "existing-evidence"
        base["stages"].append(
            {
                "name": "cleaning",
                "status": cleaning_status,
                "run": relative_path(preparation["cleaning_output"] / "run.json", case_dir),
                "processed": relative_path(preparation["cleaning_output"] / "processed.csv", case_dir),
            }
        )
        try:
            final_audit = run_data_audit(
                preparation["cleaning_output"] / "processed.csv",
                preparation["processed_audit_output"],
                ",".join(roles["id"]) or None,
                ",".join(roles["target"]) or None,
                ",".join(roles["time"]) or None,
                ",".join(roles["group"]) or None,
            )
        except Exception as exc:
            return {
                **base,
                "ok": False,
                "failed_stage": "processed_audit",
                "stderr": str(exc),
                "remediation": ["Repair the processed CSV or declared column roles, then rerun."],
            }
        final_stage = "processed_audit"
        base["stages"].append(
            {
                "name": "processed_audit",
                "status": "executed",
                "ready_for_modeling": final_audit["ready_for_modeling"],
                "run": relative_path(preparation["processed_audit_output"] / "run.json", case_dir),
            }
        )

    if not final_audit["ready_for_modeling"]:
        return {
            **base,
            "ok": False,
            "failed_stage": final_stage,
            "stderr": "Data audit reported blocker findings; ordinary modeling steps were not started",
            "remediation": [
                "Review the audit issues and either provide a justified hash-bound cleaning plan or correct the source data."
            ],
        }
    hashes, missing_outputs = data_preparation_outputs(preparation, case_dir)
    if missing_outputs:
        return {
            **base,
            "ok": False,
            "failed_stage": "outputs",
            "missing_outputs": missing_outputs,
            "stderr": "Data preparation did not produce every required evidence file",
            "remediation": ["Repair the data-preparation stage and rerun."],
        }
    state["data_preparation"] = {
        "fingerprint": fingerprint,
        "output_sha256": hashes,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    return {**base, "ok": True, "output_sha256": hashes}


def run_data_preparations(preparations: list[dict], case_dir: Path, state: dict) -> dict:
    stored = state.get("data_preparation")
    entries = dict(stored.get("entries", {})) if isinstance(stored, dict) and isinstance(stored.get("entries"), dict) else {}
    reports: list[dict] = []
    state_changed = False
    for preparation in preparations:
        name = preparation["name"]
        entry_view = {"data_preparation": entries.get(name)}
        report = run_data_preparation(preparation, case_dir, entry_view)
        report["name"] = name
        reports.append(report)
        updated_entry = entry_view.get("data_preparation")
        if report.get("ok") and isinstance(updated_entry, dict) and entries.get(name) != updated_entry:
            entries[name] = updated_entry
            state_changed = True
        if not report.get("ok"):
            if state_changed:
                state["data_preparation"] = {"entries": entries}
            return {
                "configured": True,
                "status": "failed",
                "ok": False,
                "datasets": reports,
                "failed_dataset": name,
                "failed_stage": report.get("failed_stage", "data_preparation_failed"),
                "stderr": report.get("stderr", "data preparation failed"),
                "remediation": report.get("remediation", []),
                "state_changed": state_changed,
            }
    state["data_preparation"] = {"entries": entries}
    return {
        "configured": True,
        "status": "cache-hit" if all(report["status"] == "cache-hit" for report in reports) else "executed",
        "ok": True,
        "datasets": reports,
        "state_changed": state_changed,
    }


def plan_data_preparation(preparation: dict | None, case_dir: Path, state: dict) -> dict:
    if preparation is None:
        return {"configured": False, "action": "not_configured"}
    fingerprint, missing_inputs = data_preparation_fingerprint(preparation, case_dir)
    planned = {"configured": True, "fingerprint": fingerprint}
    if missing_inputs:
        return {
            **planned,
            "action": "blocked",
            "reason_code": "input_missing",
            "missing_inputs": missing_inputs,
        }
    cached = cached_data_preparation(preparation, case_dir, state, fingerprint)
    if cached is not None:
        return {**planned, "action": "cache-hit", "reason_code": "cache_hit"}
    return {**planned, "action": "execute", "reason_code": "evidence_refresh_required"}


def plan_data_preparations(preparations: list[dict] | None, case_dir: Path, state: dict) -> dict:
    if preparations is None:
        return {"configured": False, "action": "not_configured"}
    stored = state.get("data_preparation")
    entries = stored.get("entries", {}) if isinstance(stored, dict) and isinstance(stored.get("entries"), dict) else {}
    datasets = []
    for preparation in preparations:
        planned = plan_data_preparation(preparation, case_dir, {"data_preparation": entries.get(preparation["name"])})
        datasets.append({"name": preparation["name"], **planned})
    actions = {item["action"] for item in datasets}
    if "blocked" in actions:
        action = "blocked"
    elif "execute" in actions:
        action = "execute"
    else:
        action = "cache-hit"
    reason_code = "cache_hit" if action == "cache-hit" else "mixed_dataset_actions"
    if len(actions) == 1:
        reason_code = datasets[0].get("reason_code", reason_code)
    return {
        "configured": True,
        "action": action,
        "reason_code": reason_code,
        "datasets": datasets,
    }


def normalize_data_preparation(case_dir: Path, value: object, schema_version: int) -> dict | None:
    if value is None:
        return None
    if schema_version != 2:
        raise ValueError("data_preparation requires schema_version 2")
    if not isinstance(value, dict):
        raise ValueError("data_preparation must be an object")
    input_path = resolve_inside(case_dir, value.get("input"), "data_preparation input")
    if input_path.suffix.casefold() != ".csv":
        raise ValueError("data_preparation input must end in .csv")
    raw_audit_output = resolve_inside(
        case_dir, value.get("raw_audit_output"), "data_preparation raw_audit_output"
    )
    roles: dict[str, list[str]] = {}
    for name in ("id", "target", "time", "group"):
        columns = value.get(f"{name}_columns", [])
        if not isinstance(columns, list) or not all(
            isinstance(column, str) and column.strip() for column in columns
        ):
            raise ValueError(f"data_preparation {name}_columns must be non-empty strings")
        roles[name] = columns
    declared = [column for columns in roles.values() for column in columns]
    if len(set(declared)) != len(declared):
        raise ValueError("data_preparation role columns cannot overlap")

    plan_value = value.get("cleaning_plan")
    companion_keys = ("cleaning_output", "processed_audit_output")
    if plan_value is None:
        if any(key in value for key in companion_keys):
            raise ValueError(
                "data_preparation cleaning_output and processed_audit_output require cleaning_plan"
            )
        preparation = {
            "input": input_path,
            "raw_audit_output": raw_audit_output,
            "roles": roles,
            "cleaning_plan": None,
        }
    else:
        if not all(key in value for key in companion_keys):
            raise ValueError(
                "data_preparation cleaning_plan requires cleaning_output and processed_audit_output"
            )
        cleaning_plan = resolve_inside(
            case_dir, plan_value, "data_preparation cleaning_plan"
        )
        if cleaning_plan.suffix.casefold() != ".json":
            raise ValueError("data_preparation cleaning_plan must end in .json")
        cleaning_output = resolve_inside(
            case_dir, value.get("cleaning_output"), "data_preparation cleaning_output"
        )
        processed_root = (case_dir / "data" / "processed").resolve()
        try:
            cleaning_output.relative_to(processed_root)
        except ValueError as exc:
            raise ValueError(
                "data_preparation cleaning_output must be inside data/processed"
            ) from exc
        if cleaning_output == processed_root:
            raise ValueError("data_preparation cleaning_output must name a subdirectory")
        preparation = {
            "input": input_path,
            "raw_audit_output": raw_audit_output,
            "roles": roles,
            "cleaning_plan": cleaning_plan,
            "cleaning_output": cleaning_output,
            "processed_audit_output": resolve_inside(
                case_dir,
                value.get("processed_audit_output"),
                "data_preparation processed_audit_output",
            ),
        }

    output_dirs = [preparation["raw_audit_output"]]
    if preparation["cleaning_plan"] is not None:
        output_dirs.extend(
            [preparation["cleaning_output"], preparation["processed_audit_output"]]
        )
    sources = [preparation["input"]]
    if preparation["cleaning_plan"] is not None:
        sources.append(preparation["cleaning_plan"])
    for output in output_dirs:
        if output.suffix:
            raise ValueError("data_preparation output paths must be directories without suffixes")
        if any(paths_overlap(output, source) for source in sources):
            raise ValueError("data_preparation output directories must not contain source files")
    for index, output in enumerate(output_dirs):
        if any(paths_overlap(output, other) for other in output_dirs[index + 1 :]):
            raise ValueError("data_preparation output directories must be distinct and non-overlapping")
    return preparation


def data_preparation_output_dirs(preparation: dict) -> list[Path]:
    outputs = [preparation["raw_audit_output"]]
    if preparation["cleaning_plan"] is not None:
        outputs.extend([preparation["cleaning_output"], preparation["processed_audit_output"]])
    return outputs


def data_preparation_sources(preparation: dict) -> list[Path]:
    sources = [preparation["input"]]
    if preparation["cleaning_plan"] is not None:
        sources.append(preparation["cleaning_plan"])
    return sources


def normalize_data_preparations(case_dir: Path, value: object, schema_version: int) -> list[dict] | None:
    if value is None:
        return None
    if schema_version != 2:
        raise ValueError("data_preparations requires schema_version 2")
    if not isinstance(value, list) or not value:
        raise ValueError("data_preparations must be a non-empty array")
    preparations: list[dict] = []
    names: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"data_preparations item {index} must be an object")
        name = item.get("name")
        if not isinstance(name, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name) is None:
            raise ValueError(
                f"data_preparations item {index} name must use only letters, digits, dot, underscore, and hyphen"
            )
        if name in names:
            raise ValueError(f"duplicate data_preparations name: {name}")
        names.add(name)
        preparation = normalize_data_preparation(case_dir, item, schema_version)
        if preparation is None:
            raise ValueError(f"data_preparations item {index} is missing")
        preparation["name"] = name
        preparations.append(preparation)
    for index, preparation in enumerate(preparations):
        for output in data_preparation_output_dirs(preparation):
            for other in preparations[index + 1 :]:
                if any(paths_overlap(output, candidate) for candidate in data_preparation_output_dirs(other)):
                    raise ValueError("data_preparations output directories must be distinct and non-overlapping")
                if any(paths_overlap(output, source) for source in data_preparation_sources(other)):
                    raise ValueError("data_preparations outputs must not contain another dataset source")
            for other in preparations[:index]:
                if any(paths_overlap(output, source) for source in data_preparation_sources(other)):
                    raise ValueError("data_preparations outputs must not contain another dataset source")
    return preparations


def load_manifest(case_dir: Path, path: Path) -> dict:
    case_dir = case_dir.expanduser().resolve()
    path = path.expanduser().resolve()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read pipeline manifest: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") not in {1, 2}:
        raise ValueError("pipeline manifest schema_version must be 1 or 2")
    schema_version = data["schema_version"]
    profile = data.get("profile", "practice")
    if profile not in {"explore", "practice", "submission"}:
        raise ValueError("pipeline manifest profile must be explore, practice, or submission")
    if schema_version == 1 and "profile" in data:
        raise ValueError("pipeline profile requires schema_version 2")
    if schema_version == 1 and "compliance" in data:
        raise ValueError("pipeline compliance requires schema_version 2")
    if schema_version == 1 and "paper_authority_plan" in data:
        raise ValueError("paper authority plan requires schema_version 2")
    if schema_version == 1 and "m6_compliance_plan" in data:
        raise ValueError("M6 compliance plan requires schema_version 2")
    if profile == "submission" and "compliance" not in data:
        raise ValueError("submission profile requires a compliance JSON path")
    raw_steps = data.get("steps")
    if isinstance(raw_steps, list):
        for index, raw_step in enumerate(raw_steps):
            if not isinstance(raw_step, dict):
                continue
            step_type = raw_step.get("type", "python")
            name = raw_step.get("name", index)
            if step_type not in {"python", "matlab"}:
                raise ValueError(f"step {name} type must be python or matlab")
            if step_type == "matlab" and raw_step.get("args"):
                raise ValueError(f"step {name} MATLAB scripts do not accept args")
            if schema_version == 1 and step_type == "python" and any(
                key in raw_step for key in ("inputs", "outputs", "timeout_seconds", "cache")
            ):
                raise ValueError(
                    f"step {name} Python execution metadata requires schema_version 2"
                )
    load_and_validate(data, WORKFLOW_SCHEMA, "pipeline manifest")
    if "data_preparation" in data and "data_preparations" in data:
        raise ValueError("data_preparation and data_preparations are mutually exclusive")
    data_preparation = normalize_data_preparation(
        case_dir, data.get("data_preparation"), schema_version
    )
    data_preparations = normalize_data_preparations(
        case_dir, data.get("data_preparations"), schema_version
    )
    compliance_value = data.get("compliance")
    compliance = (
        resolve_inside(case_dir, compliance_value, "submission compliance")
        if compliance_value is not None
        else None
    )
    m6_value = data.get("m6_compliance_plan")
    m6_compliance_plan = (
        resolve_inside(case_dir, m6_value, "M6 compliance plan")
        if m6_value is not None
        else None
    )
    m7_value = data.get("m7_f2_plan")
    m7_f2_plan = (
        resolve_inside(case_dir, m7_value, "M7/F2 plan")
        if m7_value is not None
        else None
    )
    paper_authority_value = data.get("paper_authority_plan")
    paper_authority_plan = (
        resolve_inside(case_dir, paper_authority_value, "paper authority plan")
        if paper_authority_value is not None
        else None
    )
    quality_gate_value = data.get("quality_gate_plan")
    quality_gate_plan = (
        resolve_inside(case_dir, quality_gate_value, "quality gate plan")
        if quality_gate_value is not None
        else None
    )
    if compliance is not None and compliance.suffix.casefold() != ".json":
        raise ValueError("submission compliance must end in .json")
    if profile == "submission" and compliance is None:
        raise ValueError("submission profile requires a compliance JSON path")
    if m6_compliance_plan is not None and m6_compliance_plan.suffix.casefold() != ".json":
        raise ValueError("M6 compliance plan must end in .json")
    if m7_f2_plan is not None and m7_f2_plan.suffix.casefold() != ".json":
        raise ValueError("M7/F2 plan must end in .json")
    if paper_authority_plan is not None and paper_authority_plan.suffix.casefold() != ".json":
        raise ValueError("paper authority plan must end in .json")
    if quality_gate_plan is not None and quality_gate_plan.suffix.casefold() != ".json":
        raise ValueError("quality gate plan must end in .json")

    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("pipeline manifest steps must be a non-empty array")
    names: set[str] = set()
    normalized_steps = []
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError(f"step {index} must be an object")
        name = step.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"step {index} name must be a non-empty string")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name) is None:
            raise ValueError(
                f"step {index} name must use only letters, digits, dot, underscore, and hyphen"
            )
        if name in names:
            raise ValueError(f"duplicate step name: {name}")
        names.add(name)
        step_type = step.get("type", "python")
        if step_type not in {"python", "matlab"}:
            raise ValueError(f"step {name} type must be python or matlab")
        script = resolve_inside(case_dir, step.get("script"), f"step {name} script")
        expected_suffix = ".py" if step_type == "python" else ".m"
        if script.suffix.casefold() != expected_suffix:
            raise ValueError(
                f"step {name} {step_type} script must end in {expected_suffix}"
            )
        arguments = step.get("args", [])
        if not isinstance(arguments, list) or not all(
            isinstance(argument, str) for argument in arguments
        ):
            raise ValueError(f"step {name} args must be an array of strings")
        if step_type == "matlab" and arguments:
            raise ValueError(f"step {name} MATLAB scripts do not accept args")
        normalized_step = {
            "name": name,
            "type": step_type,
            "script": script,
            "args": arguments,
        }
        if step_type == "python":
            input_values = step.get("inputs", [])
            output_values = step.get("outputs", [])
            if not isinstance(input_values, list) or not all(
                isinstance(value, str) and value.strip() for value in input_values
            ):
                raise ValueError(
                    f"step {name} inputs must be an array of non-empty relative paths"
                )
            if not isinstance(output_values, list) or not all(
                isinstance(value, str) and value.strip() for value in output_values
            ):
                raise ValueError(
                    f"step {name} outputs must be an array of non-empty relative paths"
                )
            inputs = [
                resolve_inside(case_dir, value, f"step {name} input")
                for value in input_values
            ]
            outputs = [
                resolve_inside(case_dir, value, f"step {name} output")
                for value in output_values
            ]
            if len(set(inputs)) != len(inputs):
                raise ValueError(f"step {name} inputs must be distinct")
            if len(set(outputs)) != len(outputs):
                raise ValueError(f"step {name} outputs must be distinct")
            if set(inputs) & set(outputs):
                raise ValueError(f"step {name} inputs and outputs must be distinct")
            if script in outputs:
                raise ValueError(f"step {name} output must not overwrite its script")
            timeout_seconds = step.get("timeout_seconds", 300)
            if (
                isinstance(timeout_seconds, bool)
                or not isinstance(timeout_seconds, int)
                or not 1 <= timeout_seconds <= 86400
            ):
                raise ValueError(
                    f"step {name} timeout_seconds must be an integer from 1 to 86400"
                )
            cache = step.get("cache", False)
            if not isinstance(cache, bool):
                raise ValueError(f"step {name} cache must be true or false")
            if schema_version == 1 and any(
                key in step for key in ("inputs", "outputs", "timeout_seconds", "cache")
            ):
                raise ValueError(
                    f"step {name} Python execution metadata requires schema_version 2"
                )
            if cache and not outputs:
                raise ValueError(f"step {name} cache requires at least one output")
            normalized_step.update(
                {
                    "inputs": inputs,
                    "outputs": outputs,
                    "timeout_seconds": timeout_seconds,
                    "cache": cache,
                }
            )
        if step_type == "matlab":
            runner = step.get("runner", "mcp-evidence")
            if runner not in {"mcp-evidence", "batch"}:
                raise ValueError(
                    f"step {name} MATLAB runner must be mcp-evidence or batch"
                )
            test_value = step.get("test")
            test = (
                resolve_inside(case_dir, test_value, f"step {name} test")
                if test_value is not None
                else None
            )
            if test is not None and test.suffix.casefold() != ".m":
                raise ValueError(f"step {name} MATLAB test must end in .m")
            dependency_values = step.get("dependencies", [])
            if not isinstance(dependency_values, list) or not all(
                isinstance(dependency, str) and dependency.strip()
                for dependency in dependency_values
            ):
                raise ValueError(
                    f"step {name} dependencies must be an array of non-empty relative paths"
                )
            normalized_step["dependencies"] = [
                resolve_inside(case_dir, dependency, f"step {name} dependency")
                for dependency in dependency_values
            ]
            if len(set(normalized_step["dependencies"])) != len(
                normalized_step["dependencies"]
            ):
                raise ValueError(f"step {name} MATLAB dependencies must be distinct")
            output_values = step.get("outputs", [])
            if not isinstance(output_values, list) or not all(
                isinstance(output, str) and output.strip() for output in output_values
            ):
                raise ValueError(
                    f"step {name} outputs must be an array of non-empty relative paths"
                )
            normalized_step["test"] = test
            normalized_step["outputs"] = [
                resolve_inside(case_dir, output, f"step {name} output")
                for output in output_values
            ]
            if len(set(normalized_step["outputs"])) != len(normalized_step["outputs"]):
                raise ValueError(f"step {name} MATLAB outputs must be distinct")
            normalized_step["runner"] = runner
            evidence_value = step.get(
                "evidence", f"results/matlab-validation-{name}.json"
            )
            normalized_step["evidence"] = resolve_inside(
                case_dir, evidence_value, f"step {name} evidence"
            )
            if normalized_step["evidence"].suffix.casefold() != ".json":
                raise ValueError(f"step {name} MATLAB evidence must end in .json")
            protected = {
                script,
                *normalized_step["dependencies"],
                *normalized_step["outputs"],
            }
            if test is not None:
                protected.add(test)
            expected_count = (
                1
                + (1 if test is not None else 0)
                + len(normalized_step["dependencies"])
                + len(normalized_step["outputs"])
            )
            if len(protected) != expected_count:
                raise ValueError(
                    f"step {name} script, test, dependencies, and outputs must be distinct"
                )
            if normalized_step["evidence"] in protected:
                raise ValueError(
                    f"step {name} MATLAB evidence must not overwrite a script, test, or output"
                )
        normalized_steps.append(normalized_step)

    artifacts = data.get("artifacts")
    if artifacts is None and profile == "explore":
        normalized_artifacts = {}
    else:
        if not isinstance(artifacts, dict):
            raise ValueError("pipeline manifest artifacts must be an object")
        normalized_artifacts = {
            key: resolve_inside(case_dir, artifacts.get(key), f"artifact {key}")
            for key in ("docx", "pdf", "render_dir", "visual_review")
        }
        if normalized_artifacts["docx"].suffix.casefold() != ".docx":
            raise ValueError("artifact docx must end in .docx")
        if normalized_artifacts["pdf"].suffix.casefold() != ".pdf":
            raise ValueError("artifact pdf must end in .pdf")
        if normalized_artifacts["visual_review"].suffix.casefold() != ".json":
            raise ValueError("artifact visual_review must end in .json")
        if len({path for path in normalized_artifacts.values()}) != 4:
            raise ValueError("artifact paths must be distinct")
    if compliance is not None and compliance in normalized_artifacts.values():
        raise ValueError("submission compliance must be distinct from artifact paths")
    if m6_compliance_plan is not None and m6_compliance_plan in normalized_artifacts.values():
        raise ValueError("M6 compliance plan must be distinct from artifact paths")
    if m7_f2_plan is not None and m7_f2_plan in normalized_artifacts.values():
        raise ValueError("M7/F2 plan must be distinct from artifact paths")
    if paper_authority_plan is not None and paper_authority_plan in normalized_artifacts.values():
        raise ValueError("paper authority plan must be distinct from artifact paths")
    if quality_gate_plan is not None and quality_gate_plan in normalized_artifacts.values():
        raise ValueError("quality gate plan must be distinct from artifact paths")

    audit = data.get("audit", {})
    if not isinstance(audit, dict):
        raise ValueError("pipeline manifest audit must be an object")
    page_size = audit.get("page_size", "a4")
    orientation = audit.get("orientation", "portrait")
    forbidden = audit.get("forbid", ["TODO"])
    dpi = audit.get("render_dpi", 150)
    if page_size not in {"any", "a4", "letter"}:
        raise ValueError("audit page_size must be any, a4, or letter")
    if orientation not in {"any", "portrait", "landscape"}:
        raise ValueError("audit orientation must be any, portrait, or landscape")
    if not isinstance(forbidden, list) or not all(
        isinstance(item, str) and item for item in forbidden
    ):
        raise ValueError("audit forbid must be an array of non-empty strings")
    if isinstance(dpi, bool) or not isinstance(dpi, int) or not 72 <= dpi <= 600:
        raise ValueError("audit render_dpi must be an integer from 72 to 600")

    claimed_outputs: dict[Path, str] = {}
    reserved_outputs = {
        (case_dir / ".workflow" / "state.json").resolve(),
        (case_dir / "paper" / "pipeline-report.json").resolve(),
        (case_dir / "paper" / "finalization-report.json").resolve(),
    }
    if compliance is not None:
        reserved_outputs.add(compliance)
    if m6_compliance_plan is not None:
        reserved_outputs.add(m6_compliance_plan)
    if m7_f2_plan is not None:
        reserved_outputs.add(m7_f2_plan)
    if paper_authority_plan is not None:
        reserved_outputs.add(paper_authority_plan)
    for step in normalized_steps:
        for output in step.get("outputs", []):
            if output in reserved_outputs:
                raise ValueError(
                    f"step {step['name']} output is reserved by the workflow: "
                    f"{output.relative_to(case_dir)}"
                )
            previous = claimed_outputs.get(output)
            if previous is not None:
                raise ValueError(
                    f"steps {previous} and {step['name']} declare the same output: "
                    f"{output.relative_to(case_dir)}"
                )
            claimed_outputs[output] = step["name"]

    configured_preparations = (
        [data_preparation] if data_preparation is not None else data_preparations or []
    )
    if configured_preparations:
        protected_paths = [
            *reserved_outputs,
            *claimed_outputs,
            *normalized_artifacts.values(),
        ]
        for preparation in configured_preparations:
            for output_dir in data_preparation_output_dirs(preparation):
                if any(paths_overlap(output_dir, protected) for protected in protected_paths):
                    raise ValueError(
                        "data_preparation output directories must not overlap workflow outputs"
                    )

    return {
        "schema_version": schema_version,
        "profile": profile,
        "compliance": compliance,
        "m6_compliance_plan": m6_compliance_plan,
        "m7_f2_plan": m7_f2_plan,
        "paper_authority_plan": paper_authority_plan,
        "quality_gate_plan": quality_gate_plan,
        "steps": normalized_steps,
        "artifacts": normalized_artifacts,
        "audit": {
            "page_size": page_size,
            "orientation": orientation,
            "forbid": forbidden,
            "render_dpi": dpi,
        },
        "data_preparation": data_preparation,
        "data_preparations": data_preparations,
    }


def run_command(command: list[str], cwd: Path, timeout: int = 300) -> dict:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        return {
            "ok": False,
            "exit_code": None,
            "stdout": stdout,
            "stderr": str(exc),
            "failed_stage": "timeout",
            "timeout_seconds": timeout,
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "ok": False,
            "exit_code": None,
            "stdout": "",
            "stderr": str(exc),
            "failed_stage": "launch",
        }
    return {
        "ok": completed.returncode == 0,
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        **({"failed_stage": "execution"} if completed.returncode != 0 else {}),
    }


def step_failure_remediation(result: dict) -> list[str]:
    cause = result.get("failed_stage", "step_failed")
    if cause == "timeout":
        return [
            "Inspect the step for a hang or unexpectedly slow work",
            "Optimize the step or increase timeout_seconds, then rerun from the failed step",
        ]
    if cause == "inputs":
        missing = ", ".join(result.get("missing_inputs", []))
        return [f"Restore the missing script or declared inputs: {missing}"]
    if cause == "outputs":
        missing = ", ".join(result.get("missing_outputs", []))
        return [f"Fix the step to create every declared output: {missing}"]
    if cause == "launch":
        return [
            "Inspect the launch error and confirm the configured interpreter and script are accessible"
        ]
    return [
        "Inspect the step exit code, stdout, and stderr; fix the error, then rerun from the failed step"
    ]


def run_json_script(script: Path, arguments: list[str], cwd: Path) -> tuple[dict, dict]:
    command = [sys.executable, str(script), *arguments, "--json"]
    result = run_command(command, cwd)
    try:
        payload = json.loads(result["stdout"])
    except json.JSONDecodeError:
        payload = {"errors": [f"{script.name} did not emit valid JSON"]}
    payload["exit_code"] = result["exit_code"]
    if result["stderr"]:
        payload["stderr"] = result["stderr"]
    return payload, result


def matlab_string(value: Path | str) -> str:
    return str(value).replace("'", "''")


def run_matlab_expression(
    executable: str, expression: str, cwd: Path, timeout: int = 600
) -> dict:
    return run_command([executable, "-batch", expression], cwd, timeout=timeout)


def run_matlab_step(step: dict, executable: str, case_dir: Path) -> dict:
    script = step["script"]
    analyzer_expression = (
        f"issues=checkcode('{matlab_string(script)}','-id');"
        "if ~isempty(issues),"
        "for k=1:numel(issues),"
        "fprintf(2,'MATLAB_ANALYZER %s:%d:%d %s\\n',"
        "issues(k).id,issues(k).line,issues(k).column,issues(k).message);"
        "end;error('mathmodel:CodeAnalyzer','MATLAB Code Analyzer found issues.');end"
    )
    analyzer = run_matlab_expression(executable, analyzer_expression, case_dir)
    report = {
        "name": step["name"],
        "type": "matlab",
        "script": str(script),
        "analyzer": analyzer,
        "ok": False,
    }
    if not analyzer["ok"]:
        report["failed_stage"] = "analyzer"
        return report

    execution_expression = (
        f"cd('{matlab_string(case_dir)}');"
        f"run('{matlab_string(script)}')"
    )
    execution = run_matlab_expression(executable, execution_expression, case_dir)
    report["execution"] = execution
    if not execution["ok"]:
        report["failed_stage"] = "execution"
        return report

    test = step.get("test")
    if test is not None:
        test_expression = (
            f"results=runtests('{matlab_string(test)}');"
            "disp(table(results));"
            "assertSuccess(results)"
        )
        test_result = run_matlab_expression(executable, test_expression, case_dir)
        report["test"] = {"path": str(test), **test_result}
        if not test_result["ok"]:
            report["failed_stage"] = "test"
            return report

    output_status = {
        str(output.relative_to(case_dir)): output.is_file()
        for output in step.get("outputs", [])
    }
    report["outputs"] = output_status
    if not all(output_status.values()):
        report["failed_stage"] = "outputs"
        report["stderr"] = "MATLAB step did not create every declared output"
        return report
    report["ok"] = True
    return report


def verify_matlab_evidence(step: dict, case_dir: Path) -> dict:
    evidence_path = step["evidence"]
    report = {
        "name": step["name"],
        "type": "matlab",
        "runner": "mcp-evidence",
        "evidence": str(evidence_path),
        "ok": False,
        "errors": [],
    }
    try:
        data = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        report["errors"].append(f"cannot read MATLAB evidence: {exc}")
        return report
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        report["errors"].append("MATLAB evidence schema_version must be 1")
        return report
    if data.get("status") != "passed" or data.get("runner") != "matlab-mcp":
        report["errors"].append("MATLAB evidence must record passed matlab-mcp validation")
    if data.get("step_name") != step["name"]:
        report["errors"].append("MATLAB evidence step_name does not match the manifest")
    expected_files = [step["script"]]
    if step.get("test") is not None:
        expected_files.append(step["test"])
    expected_files.extend(step.get("dependencies", []))
    expected_files.extend(step.get("outputs", []))
    expected_hashes = {}
    for path in expected_files:
        relative = str(path.relative_to(case_dir)).replace("\\", "/")
        if not path.is_file():
            report["errors"].append(f"MATLAB evidence input/output is missing: {relative}")
            continue
        expected_hashes[relative] = sha256_file(path)
    if data.get("file_sha256") != expected_hashes:
        report["errors"].append(
            "MATLAB evidence hashes do not match current scripts, tests, dependencies, and outputs"
        )
    checks = data.get("checks", {})
    for name in ("code_analyzer", "script_execution"):
        if checks.get(name) != "passed":
            report["errors"].append(f"MATLAB evidence check is not passed: {name}")
    if step.get("test") is not None and checks.get("unit_tests") != "passed":
        report["errors"].append("MATLAB evidence check is not passed: unit_tests")
    report["file_sha256"] = expected_hashes
    report["ok"] = not report["errors"]
    return report


def plan_python_step(
    step: dict,
    case_dir: Path,
    state: dict,
    state_status: str,
    schema_version: int,
    forced: bool,
) -> dict:
    fingerprint, missing_inputs = python_step_fingerprint(step, case_dir)
    planned = {
        "name": step["name"],
        "type": "python",
        "cache_enabled": bool(step.get("cache")),
        "forced": forced,
        "fingerprint": fingerprint,
    }
    if missing_inputs:
        return {
            **planned,
            "action": "blocked",
            "reason_code": "input_missing",
            "missing_inputs": missing_inputs,
        }
    if forced:
        return {**planned, "action": "execute", "reason_code": "forced"}
    if not step.get("cache"):
        reason = "manifest_v1_cache_unsupported" if schema_version == 1 else "cache_disabled"
        return {**planned, "action": "execute", "reason_code": reason}
    if state_status == "invalid":
        return {
            **planned,
            "action": "execute",
            "reason_code": "cache_state_invalid",
        }
    entry = state["steps"].get(step["name"])
    if not isinstance(entry, dict):
        return {
            **planned,
            "action": "execute",
            "reason_code": "cache_state_missing",
        }
    if entry.get("fingerprint") != fingerprint:
        return {
            **planned,
            "action": "execute",
            "reason_code": "fingerprint_changed",
        }
    hashes, missing_outputs = output_hashes(step, case_dir)
    if missing_outputs:
        return {
            **planned,
            "action": "execute",
            "reason_code": "output_missing",
            "missing_outputs": missing_outputs,
        }
    if entry.get("output_sha256") != hashes:
        return {
            **planned,
            "action": "execute",
            "reason_code": "output_hash_changed",
            "output_sha256": hashes,
        }
    return {
        **planned,
        "action": "cache-hit",
        "reason_code": "cache_hit",
        "output_sha256": hashes,
    }


def execution_plan(
    case_dir: Path,
    manifest: dict,
    *,
    from_step: str | None = None,
    only: set[str] | None = None,
    force: set[str] | None = None,
) -> dict:
    selected_steps, run_postprocessing = select_steps(
        manifest["steps"], from_step=from_step, only=only
    )
    if manifest.get("profile", "practice") == "explore":
        run_postprocessing = False
    force_steps = force or set()
    state_path = case_dir / ".workflow" / "state.json"
    state, state_status = inspect_workflow_state(state_path)
    data_preparation = (
        plan_data_preparations(manifest["data_preparations"], case_dir, state)
        if manifest.get("data_preparations") is not None
        else plan_data_preparation(manifest.get("data_preparation"), case_dir, state)
    )
    steps = []
    for step in selected_steps:
        if step["type"] == "python":
            planned = plan_python_step(
                step,
                case_dir,
                state,
                state_status,
                manifest["schema_version"],
                step["name"] in force_steps,
            )
        elif step["runner"] == "mcp-evidence":
            evidence = verify_matlab_evidence(step, case_dir)
            planned = {
                "name": step["name"],
                "type": "matlab",
                "runner": "mcp-evidence",
                "action": "verify-evidence" if evidence["ok"] else "blocked",
                "reason_code": (
                    "matlab_evidence_valid" if evidence["ok"] else "matlab_evidence_invalid"
                ),
                "evidence": str(step["evidence"]),
                "errors": evidence["errors"],
            }
        else:
            planned = {
                "name": step["name"],
                "type": "matlab",
                "runner": "batch",
                "action": "execute",
                "reason_code": "matlab_batch_required",
            }
        steps.append(planned)
    actions = {name: 0 for name in ("execute", "cache-hit", "verify-evidence", "blocked")}
    for step in steps:
        actions[step["action"]] += 1
    report = {
        "schema_version": 1,
        "phase": "plan",
        "mode": "passive_read_only",
        "case_steps_executed": False,
        "files_written": False,
        "active_preflight_performed": False,
        "case_dir": str(case_dir),
        "manifest_schema_version": manifest["schema_version"],
        "profile": manifest.get("profile", "practice"),
        "selection": {
            "from": from_step,
            "only": sorted(only or []),
            "force": sorted(force_steps),
        },
        "postprocessing_planned": run_postprocessing,
        "state": {"path": str(state_path), "status": state_status},
        "steps": steps,
        "data_preparation": data_preparation,
        "summary": actions,
        "errors": [],
    }
    enrich_pipeline_report(report, "execution_plan_failed")
    load_and_validate(report, EXECUTION_PLAN_SCHEMA, "execution plan")
    return report


def powershell_literal(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def export_with_word(docx: Path, pdf: Path, cwd: Path) -> dict:
    shell = shutil.which("powershell.exe") or shutil.which("powershell")
    if shell is None:
        return {"ok": False, "exit_code": None, "stderr": "PowerShell was not found"}
    script = (
        "$ErrorActionPreference='Stop';"
        f"$docx={powershell_literal(docx)};"
        f"$pdf={powershell_literal(pdf)};"
        "$word=New-Object -ComObject Word.Application;"
        "$word.Visible=$false;$word.DisplayAlerts=0;"
        "try{$doc=$word.Documents.Open($docx,$false,$true);"
        "$null=$doc.Fields.Update();"
        "foreach($toc in $doc.TablesOfContents){$toc.Update()};"
        "foreach($section in $doc.Sections){"
        "foreach($header in $section.Headers){$null=$header.Range.Fields.Update()};"
        "foreach($footer in $section.Footers){$null=$footer.Range.Fields.Update()}};"
        "$doc.Repaginate();"
        "$doc.ExportAsFixedFormat($pdf,17);$doc.Close($false)}"
        "finally{$word.Quit()}"
    )
    return run_command(
        [shell, "-NoProfile", "-NonInteractive", "-Command", script], cwd, timeout=180
    )


def export_with_libreoffice(executable: str, docx: Path, pdf: Path, cwd: Path) -> dict:
    pdf.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".libreoffice-profile-", dir=pdf.parent
    ) as profile:
        result = run_command(
            [
                executable,
                f"-env:UserInstallation={Path(profile).resolve().as_uri()}",
                "--headless",
                "--nologo",
                "--nodefault",
                "--nofirststartwizard",
                "--norestore",
                "--convert-to",
                "pdf",
                "--outdir",
                str(pdf.parent),
                str(docx),
            ],
            cwd,
            timeout=180,
        )
    generated = pdf.parent / f"{docx.stem}.pdf"
    if result["ok"] and generated != pdf:
        if not generated.is_file():
            return {**result, "ok": False, "stderr": "LibreOffice output PDF was not found"}
        generated.replace(pdf)
    return result


def validate_pdf_output(path: Path) -> str | None:
    if not path.is_file() or path.stat().st_size == 0:
        return "conversion did not create a nonempty PDF"
    try:
        with path.open("rb") as stream:
            if stream.read(5) != b"%PDF-":
                return "conversion created an unreadable PDF: invalid PDF signature"
    except OSError as exc:
        return f"conversion created an unreadable PDF: {exc}"
    try:
        from pypdf import PdfReader

        reader = PdfReader(path)
        if reader.is_encrypted:
            return "conversion created an encrypted PDF"
        if len(reader.pages) == 0:
            return "conversion created a PDF with no pages"
    except Exception as exc:
        return f"conversion created an unreadable PDF: {exc}"
    return None


def validate_rendered_pages(pages: list[Path]) -> str | None:
    if not pages:
        return "renderer created no pages"
    expected_names = [f"page-{index}.png" for index in range(1, len(pages) + 1)]
    if [page.name for page in pages] != expected_names:
        return "renderer page names must be continuous from page-1.png"
    for page in pages:
        try:
            inspect_png(page)
        except (OSError, ValueError) as exc:
            return f"renderer created invalid PNG {page.name}: {exc}"
    return None


def normalize_rendered_page_names(directory: Path) -> list[Path]:
    pages = list(directory.glob("page-*.png"))
    numbered: list[tuple[int, Path]] = []
    for page in pages:
        match = re.fullmatch(r"page-(\d+)\.png", page.name)
        if match is None:
            return sorted(pages)
        numbered.append((int(match.group(1)), page))
    numbered.sort(key=lambda item: item[0])
    indices = [index for index, _ in numbered]
    if indices != list(range(1, len(numbered) + 1)):
        return [page for _, page in numbered]
    expected_names = [f"page-{index}.png" for index in indices]
    if [page.name for _, page in numbered] == expected_names:
        return [page for _, page in numbered]

    staged: list[tuple[int, Path]] = []
    for sequence, (index, page) in enumerate(numbered, start=1):
        temporary = directory / f".page-normalize-{sequence}.png"
        page.replace(temporary)
        staged.append((index, temporary))
    normalized = []
    for index, temporary in staged:
        destination = directory / f"page-{index}.png"
        temporary.replace(destination)
        normalized.append(destination)
    return normalized


def replace_render_directory(staging: Path, destination: Path) -> None:
    commit = destination.parent / f".render-commit-{os.urandom(8).hex()}"
    # TemporaryDirectory uses a creator-only ACL on current Windows Python.
    # Create the committed directory normally so it inherits the paper directory ACL.
    commit.mkdir()
    try:
        shutil.copytree(staging, commit, dirs_exist_ok=True)
    except Exception:
        shutil.rmtree(commit, ignore_errors=True)
        raise

    backup = Path(tempfile.mkdtemp(prefix=".render-backup-", dir=destination.parent))
    backup.rmdir()
    moved_existing = False
    if destination.exists():
        destination.replace(backup)
        moved_existing = True
    try:
        commit.replace(destination)
    except OSError as commit_error:
        if moved_existing:
            try:
                backup.replace(destination)
            except OSError as restore_error:
                raise OSError(
                    f"render commit failed and the previous pages remain at {backup}: "
                    f"{restore_error}"
                ) from commit_error
        raise
    finally:
        if commit.exists():
            shutil.rmtree(commit, ignore_errors=True)
    if backup.exists():
        shutil.rmtree(backup)


def export_docx(docx: Path, pdf: Path, preflight: dict, cwd: Path) -> dict:
    if not docx.is_file():
        return {"ok": False, "backend": None, "stderr": f"DOCX does not exist: {docx}"}
    pdf.parent.mkdir(parents=True, exist_ok=True)
    backend_status = preflight.get("backends", {}).get("docx_to_pdf", {})
    candidates = [
        backend
        for backend in [backend_status.get("primary"), *backend_status.get("fallbacks", [])]
        if backend is not None and backend.get("usable", True)
    ]
    if not candidates:
        detected = backend_status.get("detected", [])
        attempts = [
            {
                "ok": False,
                "backend": backend.get("name"),
                "stage": "startup_probe",
                "exit_code": None,
                "stdout": "",
                "stderr": backend.get("probe_error") or "backend startup probe failed",
            }
            for backend in detected
            if not backend.get("usable", True)
        ]
        stderr = "; ".join(
            attempt["stderr"] for attempt in attempts if attempt.get("stderr")
        ) or "no DOCX-to-PDF backend"
        return {
            "ok": False,
            "backend": None,
            "stderr": stderr,
            "attempts": attempts,
        }
    attempts = []
    with tempfile.TemporaryDirectory(prefix=".export-", dir=pdf.parent) as temporary:
        temporary_pdf = Path(temporary) / pdf.name
        for backend in candidates:
            temporary_pdf.unlink(missing_ok=True)
            if backend["name"] == "Microsoft Word":
                result = export_with_word(docx, temporary_pdf, cwd)
            else:
                result = export_with_libreoffice(
                    backend["path"], docx, temporary_pdf, cwd
                )
            result["backend"] = backend["name"]
            output_error = validate_pdf_output(temporary_pdf) if result["ok"] else None
            if output_error:
                result["ok"] = False
                result["stderr"] = output_error
            attempts.append(result)
            if result["ok"]:
                temporary_pdf.replace(pdf)
                return {**result, "attempts": attempts}
    return {**attempts[-1], "attempts": attempts}


def render_pdf(pdf: Path, render_dir: Path, preflight: dict, dpi: int, cwd: Path) -> dict:
    if not pdf.is_file():
        return {"ok": False, "backend": None, "stderr": f"PDF does not exist: {pdf}"}
    backend_status = preflight.get("backends", {}).get("pdf_to_images", {})
    candidates = [
        backend
        for backend in [backend_status.get("primary"), *backend_status.get("fallbacks", [])]
        if backend is not None and backend.get("usable", True)
    ]
    if not candidates:
        return {"ok": False, "backend": None, "stderr": "no PDF renderer"}
    if render_dir.is_symlink():
        return {"ok": False, "backend": candidates[0]["name"], "stderr": "render directory is a symlink"}
    if render_dir.exists() and not render_dir.is_dir():
        return {"ok": False, "backend": candidates[0]["name"], "stderr": "render path is not a directory"}
    render_dir.parent.mkdir(parents=True, exist_ok=True)
    attempts = []
    for backend in candidates:
        with tempfile.TemporaryDirectory(prefix=".render-", dir=render_dir.parent) as temporary:
            temporary_dir = Path(temporary)
            prefix = temporary_dir / "page"
            command = [backend["path"], "-png", "-r", str(dpi), str(pdf), str(prefix)]
            result = run_command(command, cwd, timeout=180)
            pages = (
                normalize_rendered_page_names(temporary_dir)
                if result["ok"]
                else sorted(temporary_dir.glob("page-*.png"))
            )
            output_error = validate_rendered_pages(pages) if result["ok"] else None
            attempt = {
                **result,
                "ok": bool(result["ok"] and not output_error),
                "backend": backend["name"],
                "stderr": result["stderr"] or output_error,
            }
            attempts.append(attempt)
            if not attempt["ok"]:
                continue
            try:
                replace_render_directory(temporary_dir, render_dir)
            except OSError as exc:
                attempt["ok"] = False
                attempt["stderr"] = f"could not atomically replace rendered pages: {exc}"
                continue
            return {
                **attempt,
                "ok": True,
                "page_count": len(pages),
                "attempts": attempts,
            }
    final = attempts[-1]
    return {**final, "ok": False, "attempts": attempts}


def collect_build_preflight_targets(
    case_dir: Path,
    manifest: dict,
    selected_steps: list[dict],
    run_postprocessing: bool,
) -> tuple[list[Path], list[Path], list[Path]]:
    """Return bounded writable directories, exact files, and output trees."""
    profile = manifest.get("profile", "practice")
    report_dir = ".workflow" if profile == "explore" else "paper"
    writable_dirs = {
        (case_dir / ".workflow").resolve(),
        (case_dir / report_dir).resolve(),
    }
    exact_files = {
        (case_dir / ".workflow" / "state.json").resolve(),
        (case_dir / report_dir / "pipeline-report.json").resolve(),
    }
    output_roots: set[Path] = set()

    for step in selected_steps:
        for output in step.get("outputs", []):
            exact_files.add(output)
            writable_dirs.add(output.parent)
        if step["type"] == "matlab" and step.get("runner") == "batch":
            evidence = step.get("evidence")
            if evidence is not None:
                exact_files.add(evidence)
                writable_dirs.add(evidence.parent)

    if run_postprocessing and manifest.get("artifacts"):
        artifacts = manifest["artifacts"]
        for key in ("docx", "pdf"):
            exact_files.add(artifacts[key])
            writable_dirs.add(artifacts[key].parent)
        render_dir = artifacts["render_dir"]
        output_roots.add(render_dir)
        writable_dirs.add(render_dir.parent)

    preparations = manifest.get("data_preparations")
    if preparations is None and manifest.get("data_preparation") is not None:
        preparations = [manifest["data_preparation"]]
    for preparation in preparations or []:
        roots = [preparation["raw_audit_output"]]
        if preparation.get("cleaning_plan") is not None:
            roots.extend(
                [preparation["cleaning_output"], preparation["processed_audit_output"]]
            )
        output_roots.update(roots)
        writable_dirs.update(roots)

    sort_key = lambda path: os.path.normcase(str(path))
    return (
        sorted(writable_dirs, key=sort_key),
        sorted(exact_files, key=sort_key),
        sorted(output_roots, key=sort_key),
    )


def build_phase(
    case_dir: Path,
    manifest: dict,
    scripts_dir: Path,
    *,
    from_step: str | None = None,
    only: set[str] | None = None,
    force: set[str] | None = None,
) -> dict:
    report = {
        "report_schema_version": 1,
        "phase": "build",
        "profile": manifest.get("profile", "practice"),
        "ready_for_visual_review": False,
        "steps": [],
        "errors": [],
        "last_successful_step": None,
    }
    selected_steps, run_postprocessing = select_steps(
        manifest["steps"], from_step=from_step, only=only
    )
    if manifest.get("profile", "practice") == "explore":
        run_postprocessing = False
    force_steps = force or set()
    unknown_force = force_steps - {step["name"] for step in manifest["steps"]}
    if unknown_force:
        raise ValueError(f"unknown --force step(s): {', '.join(sorted(unknown_force))}")
    report["selection"] = {
        "from": from_step,
        "only": sorted(only or []),
        "force": sorted(force_steps),
        "postprocessing": run_postprocessing,
    }
    profile = manifest.get("profile", "practice")
    needs_batch_preflight = any(
        step["type"] == "matlab" and step.get("runner") == "batch"
        for step in selected_steps
    )
    if profile == "explore" and not needs_batch_preflight:
        preflight = {
            "ready": True,
            "skipped": True,
            "scope": "step-local",
            "reason": "explore profile defers dependency checks to configured steps",
            "tools": {},
            "matlab_batch": {},
        }
    else:
        preflight_args = [
            "--project-root", str(case_dir),
            "--output-dir", str(case_dir / (".workflow" if profile == "explore" else "paper")),
        ]
        writable_dirs, exact_files, output_roots = collect_build_preflight_targets(
            case_dir, manifest, selected_steps, run_postprocessing
        )
        for path in writable_dirs:
            preflight_args.extend(["--writable-dir", str(path)])
        for path in exact_files:
            preflight_args.extend(["--existing-file", str(path)])
        for path in output_roots:
            preflight_args.extend(["--existing-file-root", str(path)])
        if profile == "explore":
            preflight_args.extend(["--module", "json"])
        preflight, _ = run_json_script(
            scripts_dir / "preflight.py", preflight_args, case_dir
        )
    report["preflight"] = preflight
    if not preflight.get("ready"):
        report["errors"].append("environment preflight failed")
        report["failure"] = {
            "failed_stage": "preflight",
            "cause_code": "environment_not_ready",
            "retryable": True,
            "last_successful_step": None,
            "remediation": preflight.get("errors", []),
        }
        return report

    state_path = case_dir / ".workflow" / "state.json"
    state = load_workflow_state(state_path)
    if manifest.get("data_preparations") is not None:
        data_preparation = run_data_preparations(
            manifest["data_preparations"], case_dir, state
        )
    elif manifest.get("data_preparation") is not None:
        data_preparation = run_data_preparation(
            manifest["data_preparation"], case_dir, state
        )
    else:
        data_preparation = {"configured": False, "status": "not_configured", "ok": True}
    report["data_preparation"] = data_preparation
    if data_preparation.get("state_changed") or data_preparation["status"] == "executed":
        atomic_write_json(state_path, state)
    if not data_preparation["ok"]:
        report["errors"].append("data-preparation stage failed")
        report["failure"] = {
            "failed_stage": "data_preparation",
            "cause_code": data_preparation.get("failed_stage", "data_preparation_failed"),
            "retryable": True,
            "last_successful_step": None,
            "remediation": data_preparation.get(
                "remediation", ["Repair the data-preparation evidence and rerun."]
            ),
        }
        if data_preparation.get("failed_dataset") is not None:
            report["failure"]["failed_dataset"] = data_preparation["failed_dataset"]
        return report

    if profile == "explore":
        report["model_definition_audit"] = {
            "required": False,
            "passed": True,
            "reason": "explore profile does not claim a finalized model definition",
        }
    else:
        definition_audit, _ = run_json_script(
            scripts_dir / "audit_model_definitions.py",
            ["--case-dir", str(case_dir), "--structure-only"],
            case_dir,
        )
        report["model_definition_audit"] = definition_audit
        if not definition_audit.get("passed"):
            report["errors"].append("model-definition audit failed")
            report["failure"] = {
                "failed_stage": "model_definition_audit",
                "cause_code": "definition_gate_failed",
                "retryable": True,
                "last_successful_step": None,
                "remediation": definition_audit.get("errors", []),
            }
            return report

    state_path = case_dir / ".workflow" / "state.json"
    state = load_workflow_state(state_path)
    for step in selected_steps:
        if step["type"] == "matlab":
            if step["runner"] == "mcp-evidence":
                result = verify_matlab_evidence(step, case_dir)
            else:
                matlab = preflight.get("tools", {}).get("matlab")
                batch_status = preflight.get("matlab_batch", {})
                if matlab is None or not batch_status.get("safe_to_start", False):
                    result = {
                        "name": step["name"],
                        "type": "matlab",
                        "runner": "batch",
                        "ok": False,
                        "stderr": batch_status.get("reason")
                        or "MATLAB batch was not cleared by preflight",
                    }
                else:
                    result = run_matlab_step(step, matlab, case_dir)
                    result["runner"] = "batch"
        else:
            fingerprint, missing_inputs = python_step_fingerprint(step, case_dir)
            if missing_inputs:
                result = {
                    "name": step["name"],
                    "type": "python",
                    "ok": False,
                    "status": "blocked",
                    "failed_stage": "inputs",
                    "missing_inputs": missing_inputs,
                    "stderr": "Python step script or declared inputs are missing",
                }
            else:
                result = None
                if step["name"] not in force_steps:
                    result = cached_python_step(step, case_dir, state, fingerprint)
                if result is None:
                    command = [sys.executable, str(step["script"]), *step["args"]]
                    raw_result = run_command(
                        command, case_dir, timeout=step.get("timeout_seconds", 300)
                    )
                    result = {
                        "name": step["name"],
                        "type": "python",
                        "command": command,
                        "status": "executed",
                        "fingerprint": fingerprint,
                        **raw_result,
                    }
                    if result["ok"]:
                        hashes, missing_outputs = output_hashes(step, case_dir)
                        result["output_sha256"] = hashes
                        if missing_outputs:
                            result["ok"] = False
                            result["failed_stage"] = "outputs"
                            result["missing_outputs"] = missing_outputs
                            result["stderr"] = (
                                result.get("stderr", "")
                                + "\nPython step did not create every declared output"
                            ).strip()
                        elif step.get("cache"):
                            state["steps"][step["name"]] = {
                                "fingerprint": fingerprint,
                                "output_sha256": hashes,
                                "completed_at": datetime.now(timezone.utc).isoformat(),
                            }
                            atomic_write_json(state_path, state)
        for key in ("stdout", "stderr"):
            if key in result:
                result[key] = result[key][-8000:]
        for stage in ("analyzer", "execution", "test"):
            if stage in result:
                for key in ("stdout", "stderr"):
                    if key in result[stage]:
                        result[stage][key] = result[stage][key][-8000:]
        report["steps"].append(result)
        if not result["ok"]:
            report["errors"].append(f"pipeline step failed: {step['name']}")
            report["failure"] = {
                "failed_stage": "pipeline_step",
                "step": step["name"],
                "cause_code": result.get("failed_stage", "step_failed"),
                "retryable": True,
                "last_successful_step": report["last_successful_step"],
                "remediation": step_failure_remediation(result),
                "resume_command": (
                    f'python scripts/run_pipeline.py --case-dir "{case_dir}" '
                    f"--phase build --from {step['name']}"
                ),
            }
            return report
        report["last_successful_step"] = step["name"]

    report["steps_completed"] = True
    if not run_postprocessing:
        report["postprocessing_skipped"] = True
        report["completion_scope"] = "configured_steps_only"
        return report

    # Fail before export when the canonical result register is missing or stale.
    # This keeps paper generation from hiding an upstream accounting failure.
    result_register_precheck, _ = run_json_script(
        scripts_dir / "reconcile_results.py",
        ["--case-dir", str(case_dir), "--skip-paper"],
        case_dir,
    )
    report["result_register_precheck"] = result_register_precheck
    if not result_register_precheck.get("reconciled"):
        report["errors"].append("result-register precheck failed")
        report["failure"] = {
            "failed_stage": "result_register_precheck",
            "cause_code": "result_register_invalid",
            "retryable": True,
            "last_successful_step": report["last_successful_step"],
            "remediation": result_register_precheck.get("errors", []),
        }
        return report

    artifacts = manifest["artifacts"]
    export = export_docx(artifacts["docx"], artifacts["pdf"], preflight, case_dir)
    report["docx_to_pdf"] = export
    if not export["ok"]:
        report["errors"].append("DOCX-to-PDF export failed")
        stderr = "\n".join(
            attempt.get("stderr", "") for attempt in export.get("attempts", [export])
        )
        word_session_error = "80070520" in stderr or "logon session" in stderr.casefold()
        report["failure"] = {
            "failed_stage": "docx_to_pdf",
            "cause_code": (
                "word_com_logon_session" if word_session_error else "all_backends_failed"
            ),
            "retryable": True,
            "last_successful_step": report["last_successful_step"],
            "remediation": (
                [
                    "Re-establish an interactive Microsoft Word logon session",
                    "Install or configure LibreOffice as a fallback backend",
                ]
                if word_session_error
                else ["Inspect docx_to_pdf.attempts and configure a working export backend"]
            ),
            "resume_command": (
                f"python scripts/run_pipeline.py --case-dir {case_dir} --phase build "
                f"--from {report['last_successful_step']}"
                if report["last_successful_step"]
                else None
            ),
        }
        return report
    rendered = render_pdf(
        artifacts["pdf"],
        artifacts["render_dir"],
        preflight,
        manifest["audit"]["render_dpi"],
        case_dir,
    )
    report["pdf_to_images"] = rendered
    if not rendered["ok"]:
        report["errors"].append("PDF rendering failed")
        report["failure"] = {
            "failed_stage": "pdf_to_images",
            "cause_code": "renderer_failed",
            "retryable": True,
            "last_successful_step": report["last_successful_step"],
            "remediation": [rendered.get("stderr") or "Configure a working PDF renderer"],
        }
        return report

    common = [
        "--docx", str(artifacts["docx"]),
        "--pdf", str(artifacts["pdf"]),
        "--render-dir", str(artifacts["render_dir"]),
    ]
    audit_args = [
        *common,
        "--page-size", manifest["audit"]["page_size"],
        "--orientation", manifest["audit"]["orientation"],
    ]
    for item in manifest["audit"]["forbid"]:
        audit_args.extend(["--forbid", item])
    audit, _ = run_json_script(scripts_dir / "audit_paper.py", audit_args, case_dir)
    reconciliation, _ = run_json_script(
        scripts_dir / "reconcile_results.py",
        ["--case-dir", str(case_dir), "--docx", str(artifacts["docx"]), "--pdf", str(artifacts["pdf"])],
        case_dir,
    )
    report["paper_audit"] = audit
    report["reconciliation"] = reconciliation
    definition_audit, _ = run_json_script(
        scripts_dir / "audit_model_definitions.py",
        [
            "--case-dir", str(case_dir),
            "--docx", str(artifacts["docx"]),
            "--pdf", str(artifacts["pdf"]),
        ],
        case_dir,
    )
    report["model_definition_audit"] = definition_audit
    if not audit.get("structural_ok"):
        report["errors"].append("paper structural audit failed")
    if not reconciliation.get("reconciled"):
        report["errors"].append("headline result reconciliation failed")
    if not definition_audit.get("passed"):
        report["errors"].append("model-definition audit failed")
    if manifest.get("profile") == "submission":
        if manifest.get("m6_compliance_plan") is not None:
            compliance_script = scripts_dir / "audit_m6_compliance.py"
            compliance_args = [
                "technical", "--case-dir", str(case_dir),
                "--plan", str(manifest["m6_compliance_plan"]),
                "--docx", str(artifacts["docx"]),
                "--pdf", str(artifacts["pdf"]),
            ]
        else:
            compliance_script = scripts_dir / "audit_submission_compliance.py"
            compliance_args = [
                "--case-dir", str(case_dir),
                "--compliance", str(manifest["compliance"]),
                "--docx", str(artifacts["docx"]),
                "--pdf", str(artifacts["pdf"]),
            ]
        compliance_audit, _ = run_json_script(
            compliance_script, compliance_args, case_dir
        )
        report["submission_compliance"] = compliance_audit
        evidence_errors = verify_evidence_hashes(
            compliance_audit.get("evidence_sha256")
        )
        if evidence_errors:
            compliance_audit["passed"] = False
            compliance_audit.setdefault("errors", []).extend(evidence_errors)
        compliance_passed = (
            compliance_audit.get("technical_passed")
            if manifest.get("m6_compliance_plan") is not None
            else compliance_audit.get("passed")
        )
        if not compliance_passed:
            report["errors"].append("submission compliance audit failed")
            report["failure"] = {
                "failed_stage": "submission_compliance",
                "cause_code": "rules_or_ai_compliance_failed",
                "retryable": True,
                "last_successful_step": report["last_successful_step"],
                "remediation": compliance_audit.get("errors", []),
            }
    report["ready_for_visual_review"] = not report["errors"]
    return report


def finalize_phase(case_dir: Path, manifest: dict, scripts_dir: Path) -> dict:
    if manifest.get("profile", "practice") == "explore":
        return {
            "phase": "finalize",
            "profile": "explore",
            "ready_for_submission": False,
            "errors": ["explore profile cannot be finalized"],
        }
    artifacts = manifest["artifacts"]
    arguments = [
        "--case-dir", str(case_dir),
        "--docx", str(artifacts["docx"]),
        "--pdf", str(artifacts["pdf"]),
        "--render-dir", str(artifacts["render_dir"]),
        "--visual-review-record", str(artifacts["visual_review"]),
        "--page-size", manifest["audit"]["page_size"],
        "--orientation", manifest["audit"]["orientation"],
    ]
    for item in manifest["audit"]["forbid"]:
        arguments.extend(["--forbid", item])
    if manifest.get("paper_authority_plan") is not None:
        arguments.extend(["--paper-authority-plan", str(manifest["paper_authority_plan"])])
    if manifest.get("quality_gate_plan") is not None:
        arguments.extend(["--quality-gate-plan", str(manifest["quality_gate_plan"])])
    if manifest.get("profile") == "submission":
        arguments.extend(["--submission-compliance", str(manifest["compliance"])])
        if manifest.get("m6_compliance_plan") is not None:
            arguments.extend(["--m6-compliance-plan", str(manifest["m6_compliance_plan"])])
    payload, _ = run_json_script(scripts_dir / "finalize_case.py", arguments, case_dir)
    return {"phase": "finalize", "profile": manifest.get("profile", "practice"), **payload}


def serialize_manifest(manifest: dict) -> dict:
    serialized = {
        "schema_version": manifest["schema_version"],
        "profile": manifest.get("profile", "practice"),
        "steps": [
            serialize_step(step, manifest["schema_version"])
            for step in manifest["steps"]
        ],
        "artifacts": {key: str(value) for key, value in manifest["artifacts"].items()},
        "audit": manifest["audit"],
    }
    preparation = manifest.get("data_preparation")
    preparations = manifest.get("data_preparations")
    if preparation is not None or preparations is not None:
        items = [preparation] if preparation is not None else preparations
        serialized_items = []
        for item in items:
            serialized_preparation = {
                "input": str(item["input"]),
                "raw_audit_output": str(item["raw_audit_output"]),
                "id_columns": item["roles"]["id"],
                "target_columns": item["roles"]["target"],
                "time_columns": item["roles"]["time"],
                "group_columns": item["roles"]["group"],
            }
            if item["cleaning_plan"] is not None:
                serialized_preparation.update(
                    {
                        "cleaning_plan": str(item["cleaning_plan"]),
                        "cleaning_output": str(item["cleaning_output"]),
                        "processed_audit_output": str(item["processed_audit_output"]),
                    }
                )
            if preparations is not None:
                serialized_preparation["name"] = item["name"]
            serialized_items.append(serialized_preparation)
        if preparation is not None:
            serialized["data_preparation"] = serialized_items[0]
        else:
            serialized["data_preparations"] = serialized_items
    if manifest.get("compliance") is not None:
        serialized["compliance"] = str(manifest["compliance"])
    if manifest.get("m6_compliance_plan") is not None:
        serialized["m6_compliance_plan"] = str(manifest["m6_compliance_plan"])
    if manifest.get("m7_f2_plan") is not None:
        serialized["m7_f2_plan"] = str(manifest["m7_f2_plan"])
    if manifest.get("paper_authority_plan") is not None:
        serialized["paper_authority_plan"] = str(manifest["paper_authority_plan"])
    if manifest.get("quality_gate_plan") is not None:
        serialized["quality_gate_plan"] = str(manifest["quality_gate_plan"])
    return serialized


def serialize_step(step: dict, schema_version: int = 1) -> dict:
    serialized = {
        "name": step["name"],
        "type": step["type"],
        "script": str(step["script"]),
        "args": step["args"],
    }
    if step["type"] == "matlab":
        serialized["test"] = str(step["test"]) if step["test"] else None
        serialized["dependencies"] = [
            str(dependency) for dependency in step["dependencies"]
        ]
        serialized["outputs"] = [str(output) for output in step["outputs"]]
        serialized["runner"] = step["runner"]
        serialized["evidence"] = str(step["evidence"])
    elif schema_version >= 2:
        serialized["inputs"] = [str(path) for path in step.get("inputs", [])]
        serialized["outputs"] = [str(path) for path in step.get("outputs", [])]
        serialized["timeout_seconds"] = step.get("timeout_seconds", 300)
        serialized["cache"] = step.get("cache", False)
    return serialized


def print_human(report: dict) -> None:
    print(f"phase={report.get('phase', 'validation')}")
    if report.get("phase") == "plan":
        print(f"mode={report['mode']}")
        for step in report["steps"]:
            print(f"step.{step['name']}={step['action']} ({step['reason_code']})")
    if "ready_for_visual_review" in report:
        print(f"ready_for_visual_review={str(report['ready_for_visual_review']).lower()}")
    if "ready_for_submission" in report:
        print(f"ready_for_submission={str(report['ready_for_submission']).lower()}")
    for error in report.get("errors", []):
        print(f"error: {error}")


def enrich_pipeline_report(report: dict, error_code: str = "pipeline_failed") -> dict:
    if report.get("diagnostics_schema_version") == 1:
        return report
    return enrich_legacy_report(
        report,
        stage=str(report.get("phase", "pipeline")).replace("-", "_"),
        error_code=error_code,
        warning_code="pipeline_advisory",
    )


def main() -> int:
    args = parse_args()
    case_dir = args.case_dir.expanduser().resolve()
    if not case_dir.is_dir():
        report = {"phase": args.phase, "errors": [f"case directory does not exist: {case_dir}"]}
        enrich_pipeline_report(report, "case_not_found")
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print_human(report)
        return 2
    manifest_path = (
        args.manifest.expanduser().resolve() if args.manifest else case_dir / "workflow.json"
    )
    try:
        manifest_path.relative_to(case_dir)
        manifest = load_manifest(case_dir, manifest_path)
        only_steps = parse_step_names(args.only)
        force_steps = parse_step_names(args.force)
        if args.phase != "build" and (args.from_step or only_steps or force_steps):
            raise ValueError("--from, --only, and --force are available only for build phase")
        if args.plan and args.phase != "build":
            raise ValueError("--plan is available only for build phase")
        if args.plan and args.validate_only:
            raise ValueError("--plan and --validate-only cannot be used together")
        if args.validate_only and (args.from_step or only_steps or force_steps):
            raise ValueError("step selection options cannot be used with --validate-only")
        select_steps(manifest["steps"], args.from_step, only_steps)
        unknown_force = force_steps - {step["name"] for step in manifest["steps"]}
        if unknown_force:
            raise ValueError(f"unknown --force step(s): {', '.join(sorted(unknown_force))}")
    except ValueError as exc:
        report = {
            "phase": args.phase,
            "errors": [str(exc)],
            "failure": {
                "failed_stage": "manifest_or_selection",
                "cause_code": "manifest_or_selection_invalid",
                "retryable": True,
                "remediation": [
                    "Repair the manifest or command selection, then rerun --validate-only."
                ],
            },
        }
        enrich_pipeline_report(report, "manifest_or_selection_invalid")
        append_failure_event(
            case_dir / "rehearsal" / "failure-events.jsonl",
            source="run_pipeline",
            report=report,
            command=sys.argv,
        )
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print_human(report)
        return 2

    if args.validate_only:
        report = {"phase": "validation", "valid": True, "manifest": serialize_manifest(manifest), "errors": []}
        enrich_pipeline_report(report)
    elif args.plan:
        report = execution_plan(
            case_dir,
            manifest,
            from_step=args.from_step,
            only=only_steps,
            force=force_steps,
        )
    elif args.phase == "build":
        report = build_phase(
            case_dir,
            manifest,
            Path(__file__).resolve().parent,
            from_step=args.from_step,
            only=only_steps,
            force=force_steps,
        )
        report["generated_at"] = datetime.now(timezone.utc).isoformat()
        enrich_pipeline_report(report)
        report_dir = ".workflow" if manifest.get("profile") == "explore" else "paper"
        report_path = case_dir / report_dir / "pipeline-report.json"
        try:
            load_and_validate(report, PIPELINE_REPORT_SCHEMA, "pipeline report")
            atomic_write_json(report_path, report)
        except ValueError as exc:
            report["ready_for_visual_review"] = False
            report["steps_completed"] = False
            report.setdefault("errors", []).append(str(exc))
            report["failure"] = {
                "failed_stage": "report_validation",
                "cause_code": "report_contract_invalid",
                "retryable": False,
                "remediation": [
                    "Repair the report generator or bundled report schema before retrying."
                ],
            }
            enrich_legacy_report(
                report,
                stage="report_validation",
                error_code="report_contract_invalid",
                warning_code="pipeline_advisory",
            )
        except OSError as exc:
            report["ready_for_visual_review"] = False
            report["steps_completed"] = False
            report.setdefault("errors", []).append(
                f"cannot write pipeline report atomically: {exc}"
            )
            report["failure"] = {
                "failed_stage": "report_write",
                "cause_code": "atomic_write_failed",
                "retryable": True,
                "remediation": [
                    f"Make the report path writable and remove path conflicts: {report_path}"
                ],
            }
            enrich_legacy_report(
                report,
                stage="report_write",
                error_code="atomic_write_failed",
                warning_code="pipeline_advisory",
            )
    else:
        report = finalize_phase(case_dir, manifest, Path(__file__).resolve().parent)
        enrich_pipeline_report(report)

    success = (
        report.get("valid")
        or (report.get("phase") == "plan" and not report.get("errors"))
        or report.get("ready_for_visual_review")
        or report.get("ready_for_submission")
        or (report.get("steps_completed") and report.get("postprocessing_skipped"))
    )
    if not success:
        event_log = case_dir / "rehearsal" / "failure-events.jsonl"
        if append_failure_event(
            event_log,
            source="run_pipeline",
            report=report,
            command=sys.argv,
        ):
            # Keep stdout and the on-disk pipeline report schema identical;
            # the event log is intentionally a separate diagnostic artifact.
            pass
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    else:
        print_human(report)
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())

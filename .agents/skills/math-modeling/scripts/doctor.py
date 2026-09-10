#!/usr/bin/env python
"""Passively diagnose a modeling case without executing steps or writing files."""

from __future__ import annotations

import argparse
import json
import os
import sys
from types import SimpleNamespace
from pathlib import Path

sys.dont_write_bytecode = True

from _diagnostics import attach_diagnostics, diagnostic, pointer_from_message
from _json_schema import load_and_validate
from _workflow_common import resolve_inside
from preflight import (
    DEFAULT_MODULES,
    find_executable,
    find_libreoffice,
    find_word,
    module_available,
    run_preflight,
)
from run_pipeline import load_manifest, serialize_manifest


COMPLIANCE_SCHEMA = (
    Path(__file__).resolve().parent.parent
    / "schemas"
    / "submission-compliance.schema.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--phase", choices=("build", "finalize"), default="build")
    parser.add_argument(
        "--active-probe",
        action="store_true",
        help="Start detected export/render backends and perform a real writability probe",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    return parser.parse_args()


def passive_tools() -> dict[str, str | None]:
    return {
        "word": find_word(),
        "libreoffice": find_libreoffice(),
        "pdftoppm": find_executable("pdftoppm"),
        "pdftocairo": find_executable("pdftocairo"),
        "matlab": find_executable("matlab"),
    }


def nearest_existing_parent(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def diagnose_submission_evidence(root: Path, compliance_path: Path, entries: list[dict]) -> None:
    if not compliance_path.is_file():
        entries.append(
            diagnostic(
                "error",
                "compliance_file_missing",
                "submission_compliance",
                f"submission compliance file is missing: {compliance_path}",
                remediation=["Complete compliance/submission.json before submission checks"],
                json_pointer="/compliance",
            )
        )
        return
    try:
        data = json.loads(compliance_path.read_text(encoding="utf-8"))
        load_and_validate(data, COMPLIANCE_SCHEMA, "submission compliance")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        message = str(exc)
        entries.append(
            diagnostic(
                "error",
                "compliance_invalid",
                "submission_compliance",
                message,
                remediation=["Correct the submission compliance JSON and rerun doctor"],
                json_pointer=pointer_from_message(message) or "/compliance",
            )
        )
        return
    evidence = [("usage_log", data["ai"]["usage_log"])]
    if data["ai"]["status"] == "used":
        evidence.append(("detail_pdf", data["ai"]["detail_pdf"]))
    for name, value in evidence:
        try:
            path = resolve_inside(root, value, f"AI {name}")
        except ValueError as exc:
            entries.append(
                diagnostic(
                    "error",
                    "compliance_evidence_invalid",
                    "submission_compliance",
                    str(exc),
                    remediation=[f"Use a case-relative path for AI {name}"],
                    json_pointer=f"/ai/{name}",
                )
            )
            continue
        if not path.is_file():
            entries.append(
                diagnostic(
                    "error",
                    "compliance_evidence_missing",
                    "submission_compliance",
                    f"AI {name} file is missing: {path}",
                    remediation=[f"Create or restore the declared AI {name} file"],
                    json_pointer=f"/ai/{name}",
                )
            )


def diagnose(
    case_dir: Path,
    manifest_path: Path | None,
    phase: str,
    *,
    active_probe: bool = False,
) -> dict:
    root = case_dir.expanduser().resolve()
    selected_manifest = manifest_path.expanduser() if manifest_path else root / "workflow.json"
    if not selected_manifest.is_absolute():
        selected_manifest = root / selected_manifest
    selected_manifest = selected_manifest.resolve()
    entries = []
    report = {
        "schema_version": 1,
        "command": "doctor",
        "mode": "passive_read_only",
        "phase": phase,
        "case_dir": str(root),
        "manifest_path": str(selected_manifest),
        "manifest": None,
        "environment": {},
    }
    if not root.is_dir():
        entries.append(
            diagnostic(
                "error",
                "case_not_found",
                "case",
                f"case directory does not exist: {root}",
                remediation=["Supply an existing case directory"],
            )
        )
        report["healthy"] = False
        return attach_diagnostics(report, entries)
    try:
        selected_manifest.relative_to(root)
        manifest = load_manifest(root, selected_manifest)
    except ValueError as exc:
        message = str(exc)
        entries.append(
            diagnostic(
                "error",
                "manifest_invalid",
                "manifest",
                message,
                remediation=["Correct workflow.json and run doctor again"],
                retry_command=f'python scripts/doctor.py --case-dir "{root}" --phase {phase}',
                json_pointer=pointer_from_message(message),
            )
        )
        report["healthy"] = False
        return attach_diagnostics(report, entries)

    report["manifest"] = serialize_manifest(manifest)
    for index, step in enumerate(manifest["steps"]):
        required_files = [("script", step["script"])]
        if step["type"] == "python":
            required_files.extend(("input", path) for path in step.get("inputs", []))
        else:
            if step.get("test") is not None:
                required_files.append(("test", step["test"]))
            required_files.extend(("dependency", path) for path in step["dependencies"])
            if step["runner"] == "mcp-evidence":
                required_files.append(("evidence", step["evidence"]))
        for kind, path in required_files:
            if not path.is_file():
                entries.append(
                    diagnostic(
                        "error",
                        f"step_{kind}_missing",
                        "inputs",
                        f"step {step['name']} {kind} is missing: {path}",
                        remediation=[f"Create or restore the declared {kind} file"],
                        json_pointer=f"/steps/{index}",
                    )
                )

    profile = manifest["profile"]
    if profile != "explore":
        definition_register = root / "problem" / "model-definition-register.json"
        if not definition_register.is_file():
            entries.append(
                diagnostic(
                    "error",
                    "model_definition_register_missing",
                    "model_definition_audit",
                    f"model-definition register is missing: {definition_register}",
                    remediation=["Complete problem/model-definition-register.json"],
                )
            )
    if profile == "submission":
        diagnose_submission_evidence(root, manifest["compliance"], entries)
    modules = ("json",) if profile == "explore" else DEFAULT_MODULES
    module_status = {name: module_available(name) for name in modules}
    tools = passive_tools()
    report["environment"] = {
        "python_executable": sys.executable,
        "modules": module_status,
        "tools": tools,
        "active_probes_performed": False,
    }
    if active_probe:
        probe_args = SimpleNamespace(
            project_root=root,
            output_dir=(root / "paper") if profile != "explore" else None,
            modules=list(modules),
        )
        active_report = run_preflight(probe_args)
        report["environment"]["active_probes_performed"] = True
        report["environment"]["active_probe_report"] = active_report
        for message in active_report.get("errors", []):
            entries.append(
                diagnostic(
                    "error",
                    "active_probe_failed",
                    "environment",
                    message,
                    remediation=["Fix the reported backend, dependency, or output-directory issue and rerun doctor"],
                )
            )
        for message in active_report.get("warnings", []):
            entries.append(
                diagnostic(
                    "warning",
                    "active_probe_advisory",
                    "environment",
                    message,
                    remediation=["Review the active probe details before relying on the affected backend"],
                )
            )
    for name, present in module_status.items():
        if not present:
            entries.append(
                diagnostic(
                    "error",
                    "python_module_missing",
                    "environment",
                    f"required Python module is missing: {name}",
                    remediation=[f"Install {name} into {sys.executable}"],
                )
            )
    needs_batch = any(
        step["type"] == "matlab" and step["runner"] == "batch"
        for step in manifest["steps"]
    )
    if needs_batch and tools["matlab"] is None:
        entries.append(
            diagnostic(
                "error",
                "matlab_not_found",
                "environment",
                "MATLAB batch runner is configured but no matlab executable was found",
                remediation=["Install MATLAB or change the step runner to mcp-evidence"],
            )
        )
    if profile != "explore":
        if tools["word"] is None and tools["libreoffice"] is None:
            entries.append(
                diagnostic(
                    "warning",
                    "docx_backend_not_found",
                    "environment",
                    "no DOCX-to-PDF backend was passively detected",
                    remediation=["Install Microsoft Word or LibreOffice"],
                )
            )
        if tools["pdftoppm"] is None and tools["pdftocairo"] is None:
            entries.append(
                diagnostic(
                    "warning",
                    "pdf_renderer_not_found",
                    "environment",
                    "no PDF renderer was passively detected",
                    remediation=["Install pdftoppm or pdftocairo"],
                )
            )
        output_parent = nearest_existing_parent(root / "paper")
        if not output_parent.is_dir() or not os.access(output_parent, os.W_OK):
            entries.append(
                diagnostic(
                    "error",
                    "output_parent_not_writable",
                    "filesystem",
                    f"nearest existing paper output parent is not writable: {output_parent}",
                    remediation=["Grant write access to the case output directory"],
                )
            )

    if phase == "finalize" and profile != "explore":
        finalize_inputs = {**manifest["artifacts"]}
        if manifest.get("compliance") is not None:
            finalize_inputs["compliance"] = manifest["compliance"]
        for name, path in finalize_inputs.items():
            exists = path.is_dir() if name == "render_dir" else path.is_file()
            if not exists:
                entries.append(
                    diagnostic(
                        "error",
                        "finalization_input_missing",
                        "finalize",
                        f"finalization input {name} is missing: {path}",
                        remediation=["Complete the build and visual review before finalization"],
                    )
                )
    report["healthy"] = not any(entry["severity"] == "error" for entry in entries)
    return attach_diagnostics(report, entries)


def print_human(report: dict) -> None:
    print(f"healthy={str(report['healthy']).lower()}")
    print(f"mode={report['mode']}")
    for entry in report["diagnostics"]:
        print(f"{entry['severity']}.{entry['code']}: {entry['message']}")


def main() -> int:
    args = parse_args()
    report = diagnose(
        args.case_dir,
        args.manifest,
        args.phase,
        active_probe=args.active_probe,
    )
    if args.json:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        print_human(report)
    return 0 if report["healthy"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""Passively audit the case authority pointer and candidate lineage.

The heartbeat checks recorded state only. It never selects an artifact, edits a
case, signs a human gate, or treats modification time as authority.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

sys.dont_write_bytecode = True

from _diagnostics import attach_diagnostics, diagnostic
from _json_schema import load_and_validate
from manage_candidates import validate_semantics as validate_candidate_registry_semantics


SKILL_DIR = Path(__file__).resolve().parent.parent
REPORT_SCHEMA = SKILL_DIR / "schemas" / "authority-heartbeat-report.schema.json"
CANDIDATE_REGISTRY_SCHEMA = SKILL_DIR / "schemas" / "candidate-registry.schema.json"

REQUIRED_FIELDS = (
    "Pointer status",
    "Last updated at",
    "Last updated by",
    "Candidate registry",
    "Canonical result register",
    "Current result candidate",
    "F1 status",
    "F1 candidate",
    "F1 accepted manifest",
    "F1 verification",
    "Paper authoritative",
    "Authoritative paper source",
    "Current generated paper",
    "Selected delivery candidate",
    "M7 precheck status",
    "M7 candidate",
    "M7 accepted manifest",
    "M7 verification",
    "Selected package report",
    "Selected packaged paper",
    "Selected support ZIP",
    "F2 manifest",
    "Official receipt",
    "Official submission status",
    "Human approval",
)

PATH_FIELDS = (
    "Candidate registry",
    "Canonical result register",
    "Current result candidate",
    "F1 candidate",
    "F1 accepted manifest",
    "Authoritative paper source",
    "Current generated paper",
    "Selected delivery candidate",
    "M7 candidate",
    "M7 accepted manifest",
    "Selected package report",
    "Selected packaged paper",
    "Selected support ZIP",
    "F2 manifest",
    "Official receipt",
)

DEFAULT_CANDIDATE_ROOTS = (
    "paper/candidates",
    "results/candidates",
    "delivery/candidates",
    "submission/candidates",
)

DEFAULT_CONTROL_FILES = (
    "START-HERE.md",
    "PLAN.md",
    "decisions.md",
    "validation.md",
)

SENTINEL_PREFIXES = (
    "NOT_",
    "NONE_",
    "RESPONSIBLE_HUMAN_",
)

UNRESOLVED_MARKER = re.compile(r"\b(TODO|TBD|FIXME|PENDING)\b", re.IGNORECASE)


def clean_cell(value: str) -> str:
    value = value.strip()
    if value.startswith("`") and value.endswith("`") and len(value) >= 2:
        value = value[1:-1].strip()
    return value


def section(text: str, heading: str) -> str:
    pattern = re.compile(
        rf"(?ms)^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s+|\Z)"
    )
    match = pattern.search(text)
    return match.group(1) if match else ""


def parse_authority(text: str) -> tuple[dict[str, str], list[str]]:
    body = section(text, "Authority")
    fields: dict[str, str] = {}
    duplicates: list[str] = []
    for line in body.splitlines():
        match = re.fullmatch(r"\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", line)
        if not match:
            continue
        field = clean_cell(match.group(1))
        value = clean_cell(match.group(2))
        if field == "Field" or not field or set(field) == {"-"}:
            continue
        if field in fields:
            duplicates.append(field)
        fields[field] = value
    return fields, sorted(set(duplicates))


def is_sentinel(value: str) -> bool:
    normalized = value.strip().upper()
    return (
        not normalized
        or normalized in {"FALSE", "TRUE", "N/A", "NONE", "-"}
        or normalized.startswith(SENTINEL_PREFIXES)
    )


def resolve_relative(root: Path, value: str, label: str) -> tuple[Path, str]:
    supplied = Path(value).expanduser()
    if supplied.is_absolute():
        raise ValueError(f"{label} must be case-relative, found absolute path: {value}")
    raw = PurePosixPath(value.replace("\\", "/"))
    if raw.is_absolute() or ".." in raw.parts:
        raise ValueError(f"{label} escapes the case directory: {value}")
    path = (root / Path(*raw.parts)).resolve()
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"{label} escapes the case directory: {value}") from exc
    current = root
    for part in raw.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{label} must not traverse a symlink: {value}")
    return path, relative


def add_consistency_checks(fields: dict[str, str], entries: list[dict]) -> None:
    pointer = fields.get("Pointer status", "")
    f1_status = fields.get("F1 status", "")
    f1_verification = fields.get("F1 verification", "")
    paper_authoritative = fields.get("Paper authoritative", "").lower()
    human_approval = fields.get("Human approval", "")
    accepted_manifest = fields.get("F1 accepted manifest", "")
    m7_precheck = fields.get("M7 precheck status", "")
    m7_verification = fields.get("M7 verification", "")
    official_status = fields.get("Official submission status", "")

    if paper_authoritative == "true":
        expected = {
            "Pointer status": "ACTIVE",
            "F1 verification": "PASSED",
            "Human approval": "SIGNED",
        }
        for field, required in expected.items():
            if fields.get(field) != required:
                entries.append(
                    diagnostic(
                        "error",
                        "paper_authority_state_mismatch",
                        "authority_heartbeat",
                        f"Paper authoritative=true requires {field}={required}, found {fields.get(field)!r}",
                        remediation=["Reconcile CURRENT-STATE with verified F1 evidence or set Paper authoritative=false"],
                    )
                )
        if is_sentinel(accepted_manifest):
            entries.append(
                diagnostic(
                    "error",
                    "paper_authority_manifest_missing",
                    "authority_heartbeat",
                    "Paper authoritative=true requires one selected F1 accepted manifest",
                    remediation=["Select the exact verified accepted manifest or revoke paper authority"],
                )
            )

    if f1_verification == "PASSED" and is_sentinel(accepted_manifest):
        entries.append(
            diagnostic(
                "error",
                "f1_verification_without_manifest",
                "authority_heartbeat",
                "F1 verification=PASSED but no accepted manifest is selected",
                remediation=["Record the exact accepted manifest used by freeze_results.py verify"],
            )
        )
    if f1_status in {"F1_ACCEPTED", "F1_ACCEPTED_WITH_LIMITATIONS"} and human_approval != "SIGNED":
        entries.append(
            diagnostic(
                "error",
                "f1_acceptance_without_human_signature",
                "authority_heartbeat",
                f"{f1_status} requires Human approval=SIGNED",
                remediation=["Record the real responsible-human decision; Codex cannot sign it"],
            )
        )
    if m7_verification == "PASSED":
        for field in (
            "M7 accepted manifest",
            "Selected package report",
            "Selected packaged paper",
            "Selected support ZIP",
        ):
            if is_sentinel(fields.get(field, "")):
                entries.append(
                    diagnostic(
                        "error",
                        "m7_evidence_selection_missing",
                        "authority_heartbeat",
                        f"M7 verification=PASSED requires {field}",
                        remediation=["Select the exact verified M7 evidence or change M7 verification to its actual state"],
                    )
                )
    if m7_precheck == "M7-PRECHECK-PASS" and is_sentinel(fields.get("Selected delivery candidate", "")):
        entries.append(
            diagnostic(
                "error",
                "m7_precheck_without_delivery_candidate",
                "authority_heartbeat",
                "M7-PRECHECK-PASS requires one selected delivery candidate",
                remediation=["Record the prechecked delivery candidate path"],
            )
        )
    if official_status == "F2_COMPLETE":
        requirements = {
            "M7 verification": "PASSED",
            "F2 manifest": None,
            "Official receipt": None,
        }
        for field, required in requirements.items():
            value = fields.get(field, "")
            invalid = value != required if required is not None else is_sentinel(value)
            if invalid:
                entries.append(
                    diagnostic(
                        "error",
                        "f2_evidence_missing",
                        "authority_heartbeat",
                        f"F2_COMPLETE requires {field}{'=' + required if required else ''}",
                        remediation=["Preserve the real upload evidence or revert Official submission status to NOT_FORMAL_F2"],
                    )
                )
    if pointer == "AUTHORITY_UNRESOLVED" and paper_authoritative == "true":
        entries.append(
            diagnostic(
                "error",
                "unresolved_pointer_claims_authority",
                "authority_heartbeat",
                "AUTHORITY_UNRESOLVED cannot coexist with Paper authoritative=true",
                remediation=["Resolve the candidate lineage before restoring paper authority"],
            )
        )


def audit(
    case_dir: Path,
    current_state_value: str = "CURRENT-STATE.md",
    candidate_roots: list[str] | None = None,
    control_files: list[str] | None = None,
) -> dict:
    root = case_dir.expanduser().resolve()
    entries: list[dict] = []
    if not root.is_dir():
        raise ValueError(f"case directory does not exist: {root}")
    current_state_path, current_state_relative = resolve_relative(
        root, current_state_value, "current state"
    )
    if not current_state_path.is_file():
        raise ValueError(f"current state file does not exist: {current_state_path}")
    text = current_state_path.read_text(encoding="utf-8-sig")
    fields, duplicates = parse_authority(text)

    if not section(text, "Authority"):
        entries.append(
            diagnostic(
                "error",
                "authority_table_missing",
                "authority_heartbeat",
                "CURRENT-STATE has no structured '## Authority' section",
                remediation=["Migrate the case pointer to the current CURRENT-STATE template"],
            )
        )
    missing_fields = [field for field in REQUIRED_FIELDS if field not in fields]
    if missing_fields:
        entries.append(
            diagnostic(
                "error",
                "authority_fields_missing",
                "authority_heartbeat",
                "CURRENT-STATE is missing required authority fields: " + ", ".join(missing_fields),
                remediation=["Add the missing fields from templates/CURRENT-STATE.md without inventing gate evidence"],
            )
        )
    if duplicates:
        entries.append(
            diagnostic(
                "error",
                "authority_fields_duplicated",
                "authority_heartbeat",
                "CURRENT-STATE repeats authority fields: " + ", ".join(duplicates),
                remediation=["Keep exactly one current value for every authority field"],
            )
        )

    for field in ("Last updated at", "Last updated by"):
        if field in fields and is_sentinel(fields[field]):
            entries.append(
                diagnostic(
                    "warning",
                    "authority_update_not_recorded",
                    "authority_heartbeat",
                    f"{field} is not recorded",
                    remediation=["Record the real update metadata on the next authority transition"],
                )
            )

    path_checks: list[dict] = []
    selected_paths: list[str] = []
    selected_paths_by_field: dict[str, str] = {}
    for field in PATH_FIELDS:
        value = fields.get(field, "")
        if is_sentinel(value):
            path_checks.append({"field": field, "value": value, "status": "not_selected"})
            continue
        try:
            path, relative = resolve_relative(root, value, field)
        except ValueError as exc:
            path_checks.append({"field": field, "value": value, "status": "invalid"})
            entries.append(
                diagnostic(
                    "error",
                    "authority_path_invalid",
                    "authority_heartbeat",
                    str(exc),
                    remediation=["Use a case-relative path that does not traverse a symlink"],
                )
            )
            continue
        selected_paths.append(relative)
        selected_paths_by_field[field] = relative
        status = "exists" if path.exists() else "missing"
        path_checks.append(
            {"field": field, "value": value, "relative_path": relative, "status": status}
        )
        if status == "missing":
            entries.append(
                diagnostic(
                    "error",
                    "selected_authority_path_missing",
                    "authority_heartbeat",
                    f"{field} selects a missing path: {relative}",
                    remediation=["Restore the selected artifact or update the pointer to the actual current artifact"],
                )
            )

    add_consistency_checks(fields, entries)

    registry_record = {
        "path": fields.get("Candidate registry", ""),
        "present": False,
        "valid": False,
        "revision": None,
        "current": {kind: [] for kind in ("result", "paper", "support")},
        "errors": [],
    }
    registry_entries: list[dict] = []
    registry_value = fields.get("Candidate registry", "")
    if not is_sentinel(registry_value):
        try:
            registry_path, registry_relative = resolve_relative(
                root, registry_value, "Candidate registry"
            )
            registry_record["path"] = registry_relative
            registry_record["present"] = registry_path.is_file()
            if registry_path.is_file():
                payload = json.loads(registry_path.read_text(encoding="utf-8-sig"))
                load_and_validate(payload, CANDIDATE_REGISTRY_SCHEMA, "candidate registry")
                registry_errors = validate_candidate_registry_semantics(payload)
                if registry_errors:
                    raise ValueError("; ".join(registry_errors))
                registry_entries = payload["candidates"]
                registry_record["valid"] = True
                registry_record["revision"] = payload["revision"]
                registry_record["current"] = {
                    kind: [
                        item["path"]
                        for item in registry_entries
                        if item["kind"] == kind and item["status"] == "current"
                    ]
                    for kind in ("result", "paper", "support")
                }
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            registry_record["errors"].append(str(exc))
            entries.append(
                diagnostic(
                    "error",
                    "candidate_registry_invalid",
                    "authority_heartbeat",
                    f"Candidate registry is invalid: {exc}",
                    remediation=["Repair the registry with manage_candidates.py evidence; do not hand-invent candidate status"],
                )
            )

    pointer_fields_by_kind = {
        "result": ("Current result candidate",),
        "paper": ("Current generated paper",),
        "support": ("Selected delivery candidate", "Selected support ZIP"),
    }
    for kind, current_paths in registry_record["current"].items():
        pointer_paths = [
            selected_paths_by_field[field]
            for field in pointer_fields_by_kind[kind]
            if field in selected_paths_by_field
        ]
        for current_path in current_paths:
            matches = any(
                pointer == current_path
                or pointer.startswith(current_path + "/")
                or current_path.startswith(pointer + "/")
                for pointer in pointer_paths
            )
            if not matches:
                entries.append(
                    diagnostic(
                        "error",
                        "candidate_registry_pointer_mismatch",
                        "authority_heartbeat",
                        f"Registry current {kind} candidate is not selected by CURRENT-STATE: {current_path}",
                        remediation=[f"Update {pointer_fields_by_kind[kind][0]} or correct the registry selection"],
                    )
                )
            try:
                current_candidate_path, _ = resolve_relative(
                    root, current_path, f"registry current {kind} candidate"
                )
                if not current_candidate_path.exists():
                    raise ValueError(f"registered current path is missing: {current_path}")
            except ValueError as exc:
                entries.append(
                    diagnostic(
                        "error",
                        "candidate_registry_current_missing",
                        "authority_heartbeat",
                        str(exc),
                        remediation=["Restore the registered artifact or select an existing registered candidate"],
                    )
                )

    superseded_body = section(text, "Superseded Candidates")
    superseded_references = {
        match.group(1).strip().replace("\\", "/")
        for match in re.finditer(r"`([^`]+)`", superseded_body)
    }
    root_values = candidate_roots if candidate_roots is not None else list(DEFAULT_CANDIDATE_ROOTS)
    candidate_root_records: list[dict] = []
    candidates: list[str] = []
    for value in root_values:
        candidate_root, relative_root = resolve_relative(root, value, "candidate root")
        present = candidate_root.is_dir()
        candidate_root_records.append({"path": relative_root, "present": present})
        if present:
            candidates.extend(
                child.relative_to(root).as_posix()
                for child in sorted(candidate_root.iterdir(), key=lambda item: item.name.lower())
                if not child.is_symlink()
            )
    candidates = sorted(set(candidates))
    selected_candidates: list[str] = []
    superseded_candidates: list[str] = []
    retained_candidates: list[str] = []
    unresolved_candidates: list[str] = []
    for candidate in candidates:
        matching_registry = [
            item
            for item in registry_entries
            if item["path"] == candidate or item["path"].startswith(candidate + "/")
        ]
        selected = any(
            selected == candidate or selected.startswith(candidate + "/")
            for selected in selected_paths
        ) or any(item["status"] == "current" for item in matching_registry)
        superseded = any(
            reference == candidate or reference.startswith(candidate + "/")
            for reference in superseded_references
        ) or any(item["status"] == "superseded" for item in matching_registry)
        registered_unselected = any(
            item["status"] == "candidate" for item in matching_registry
        )
        retained = any(item["status"] == "retained" for item in matching_registry)
        if selected:
            selected_candidates.append(candidate)
        elif superseded:
            superseded_candidates.append(candidate)
        elif retained:
            retained_candidates.append(candidate)
        elif registered_unselected or not matching_registry:
            unresolved_candidates.append(candidate)

    if len(unresolved_candidates) > 1:
        entries.append(
            diagnostic(
                "error",
                "candidate_lineage_unresolved",
                "authority_heartbeat",
                f"{len(unresolved_candidates)} candidate entries are neither selected, superseded, nor retained as evidence",
                remediation=["Record the selected candidate and classify every other entry as superseded or retained evidence"],
            )
        )
        if fields.get("Pointer status") != "AUTHORITY_UNRESOLVED":
            entries.append(
                diagnostic(
                    "error",
                    "pointer_status_not_unresolved",
                    "authority_heartbeat",
                    "Multiple unresolved candidates require Pointer status=AUTHORITY_UNRESOLVED",
                    remediation=["Set the honest unresolved status until candidate lineage is reconciled"],
                )
            )
    elif len(unresolved_candidates) == 1:
        entries.append(
            diagnostic(
                "warning",
                "candidate_not_classified",
                "authority_heartbeat",
                f"Candidate is neither selected, superseded, nor retained: {unresolved_candidates[0]}",
                remediation=["Select it, supersede it, or retain it as non-current evidence"],
            )
        )

    controls: list[dict] = []
    control_values = control_files if control_files is not None else list(DEFAULT_CONTROL_FILES)
    for value in control_values:
        control_path, relative = resolve_relative(root, value, "control file")
        if not control_path.exists():
            controls.append({"path": relative, "status": "absent", "markers": []})
            continue
        if not control_path.is_file():
            entries.append(
                diagnostic(
                    "error",
                    "control_path_not_file",
                    "authority_heartbeat",
                    f"Active control path is not a regular file: {relative}",
                    remediation=["Select a regular case-local control file"],
                )
            )
            controls.append({"path": relative, "status": "invalid", "markers": []})
            continue
        markers = []
        for number, line in enumerate(
            control_path.read_text(encoding="utf-8-sig").splitlines(), start=1
        ):
            if UNRESOLVED_MARKER.search(line):
                markers.append({"line": number, "text": line.strip()[:240]})
            if len(markers) >= 20:
                break
        status = "unresolved_markers" if markers else "clear"
        controls.append({"path": relative, "status": status, "markers": markers})
        if markers:
            entries.append(
                diagnostic(
                    "warning",
                    "stale_control_file_marker",
                    "authority_heartbeat",
                    f"Active control file contains unresolved markers: {relative}",
                    remediation=["Complete the item or explicitly mark the control file superseded"],
                )
            )

    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "command": "authority-heartbeat",
        "mode": "passive_read_only",
        "case_dir": str(root),
        "current_state": current_state_relative,
        "healthy": not any(item["severity"] == "error" for item in entries),
        "fields": fields,
        "missing_fields": missing_fields,
        "duplicate_fields": duplicates,
        "path_checks": path_checks,
        "control_files": controls,
        "candidate_lineage": {
            "registry": registry_record,
            "roots": candidate_root_records,
            "found": candidates,
            "selected": selected_candidates,
            "superseded": superseded_candidates,
            "retained": retained_candidates,
            "unresolved": unresolved_candidates,
        },
    }
    attach_diagnostics(report, entries)
    load_and_validate(report, REPORT_SCHEMA, "authority heartbeat report")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--current-state", default="CURRENT-STATE.md")
    parser.add_argument(
        "--candidate-root",
        action="append",
        help="Case-relative candidate directory; repeat to replace the default set",
    )
    parser.add_argument(
        "--control-file",
        action="append",
        help="Case-relative active control file; repeat to replace the default set",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = audit(
            args.case_dir,
            args.current_state,
            args.candidate_root,
            args.control_file,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        report = {
            "schema_version": 1,
            "command": "authority-heartbeat",
            "mode": "passive_read_only",
            "healthy": False,
        }
        attach_diagnostics(
            report,
            [
                diagnostic(
                    "error",
                    "authority_heartbeat_invalid",
                    "authority_heartbeat",
                    str(exc),
                    remediation=["Correct the case path or authority pointer and rerun the heartbeat"],
                )
            ],
        )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"authority_heartbeat_healthy={str(report.get('healthy', False)).lower()}")
        for item in report.get("diagnostics", []):
            print(f"{item['severity']}: {item['code']}: {item['message']}")
    return 0 if report.get("healthy") else 2


if __name__ == "__main__":
    raise SystemExit(main())

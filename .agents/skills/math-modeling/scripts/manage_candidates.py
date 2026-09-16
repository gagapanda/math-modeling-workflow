#!/usr/bin/env python
"""Register and classify result, paper, and support candidates without deleting them."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

sys.dont_write_bytecode = True

from _json_schema import load_and_validate
from _workflow_common import atomic_write_json, sha256_file


SKILL_DIR = Path(__file__).resolve().parent.parent
REGISTRY_SCHEMA = SKILL_DIR / "schemas" / "candidate-registry.schema.json"
IMPORT_PLAN_SCHEMA = SKILL_DIR / "schemas" / "candidate-classification-plan.schema.json"
DEFAULT_REGISTRY = "authority/candidate-registry.json"
KINDS = ("result", "paper", "support")
FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def timestamp(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    validate_timestamp(value, "timestamp")
    return value


def validate_timestamp(value: str, label: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be ISO 8601: {value}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone offset: {value}")


def is_reparse(path: Path) -> bool:
    try:
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT)
    except OSError:
        return False


def resolve_relative(root: Path, value: str, label: str) -> tuple[Path, str]:
    supplied = Path(value).expanduser()
    if supplied.is_absolute():
        raise ValueError(f"{label} must be case-relative: {value}")
    raw = PurePosixPath(value.replace("\\", "/"))
    if raw.is_absolute() or ".." in raw.parts or not raw.parts:
        raise ValueError(f"{label} must stay inside the case directory: {value}")
    path = (root / Path(*raw.parts)).resolve()
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"{label} escapes the case directory: {value}") from exc
    current = root
    for part in raw.parts:
        current = current / part
        if current.exists() and (current.is_symlink() or is_reparse(current)):
            raise ValueError(f"{label} must not traverse a symlink or reparse point: {value}")
    return path, relative


def registry_location(root: Path, value: str) -> tuple[Path, str]:
    path, relative = resolve_relative(root, value, "candidate registry")
    if path.exists() and not path.is_file():
        raise ValueError(f"candidate registry is not a regular file: {relative}")
    return path, relative


def empty_registry() -> dict:
    return {"schema_version": 1, "revision": 0, "updated_at": None, "candidates": []}


def load_registry(path: Path) -> tuple[dict, bool]:
    if not path.exists():
        return empty_registry(), False
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read candidate registry: {path}: {exc}") from exc
    load_and_validate(payload, REGISTRY_SCHEMA, "candidate registry")
    semantic_errors = validate_semantics(payload)
    if semantic_errors:
        raise ValueError("candidate registry semantics are invalid: " + "; ".join(semantic_errors))
    return payload, True


def validate_semantics(payload: dict) -> list[str]:
    errors: list[str] = []
    ids: set[str] = set()
    paths: set[str] = set()
    entries_by_id = {entry["id"]: entry for entry in payload.get("candidates", [])}
    currents = {kind: 0 for kind in KINDS}
    if payload["revision"] == 0 and payload["candidates"]:
        errors.append("revision=0 cannot contain registered candidates")
    if payload["updated_at"] is not None:
        try:
            validate_timestamp(payload["updated_at"], "updated_at")
        except ValueError as exc:
            errors.append(str(exc))
    for entry in payload.get("candidates", []):
        identifier = entry["id"]
        normalized_path = entry["path"].replace("\\", "/").casefold()
        if identifier in ids:
            errors.append(f"duplicate candidate id: {identifier}")
        ids.add(identifier)
        if not entry["source"].strip():
            errors.append(f"candidate source is blank: {identifier}")
        for field in ("registered_at", "selected_at", "superseded_at"):
            if entry[field] is not None:
                try:
                    validate_timestamp(entry[field], f"{identifier}.{field}")
                except ValueError as exc:
                    errors.append(str(exc))
        if normalized_path in paths:
            errors.append(f"duplicate candidate path: {entry['path']}")
        paths.add(normalized_path)
        status = entry["status"]
        if status == "current":
            currents[entry["kind"]] += 1
            if entry["selected_at"] is None:
                errors.append(f"current candidate lacks selected_at: {identifier}")
            if any(entry[field] is not None for field in ("superseded_at", "superseded_by")):
                errors.append(f"current candidate has superseded metadata: {identifier}")
        elif status == "superseded":
            if any(entry[field] is None for field in ("superseded_at", "superseded_by", "reason")):
                errors.append(f"superseded candidate lacks replacement metadata: {identifier}")
            elif not entry["reason"].strip():
                errors.append(f"superseded candidate reason is blank: {identifier}")
            replacement = entries_by_id.get(entry["superseded_by"])
            if replacement is None:
                errors.append(f"superseded_by does not exist: {identifier}")
            elif replacement["kind"] != entry["kind"]:
                errors.append(f"superseded_by kind mismatch: {identifier}")
            elif replacement["id"] == identifier:
                errors.append(f"candidate cannot supersede itself: {identifier}")
        elif status == "retained":
            if not entry["reason"] or not entry["reason"].strip():
                errors.append(f"retained evidence lacks a reason: {identifier}")
            if any(entry[field] is not None for field in ("selected_at", "superseded_at", "superseded_by")):
                errors.append(f"retained evidence has transition metadata: {identifier}")
        else:
            if any(entry[field] is not None for field in ("selected_at", "superseded_at", "superseded_by", "reason")):
                errors.append(f"unselected candidate has transition metadata: {identifier}")
    for kind, count in currents.items():
        if count > 1:
            errors.append(f"multiple current {kind} candidates: {count}")
    return errors


def snapshot(root: Path, registry_path: Path, value: str) -> dict:
    path, relative = resolve_relative(root, value, "candidate path")
    if not path.exists():
        raise ValueError(f"candidate path does not exist: {relative}")
    if path == root:
        raise ValueError("the case root cannot be registered as a candidate")
    if path.is_dir():
        try:
            registry_path.relative_to(path)
        except ValueError:
            pass
        else:
            raise ValueError("candidate directory must not contain its own registry")
        digest = hashlib.sha256()
        file_count = 0
        byte_count = 0
        for current, directories, files in os.walk(path, followlinks=False):
            current_path = Path(current)
            directories.sort(key=str.casefold)
            for name in directories:
                child = current_path / name
                if child.is_symlink() or is_reparse(child):
                    raise ValueError(f"candidate directory contains a symlink or reparse point: {child}")
            for name in sorted(files):
                child = current_path / name
                if child.is_symlink() or is_reparse(child):
                    raise ValueError(f"candidate directory contains a symlink or reparse point: {child}")
                child_relative = child.relative_to(path).as_posix()
                child_hash = sha256_file(child)
                child_bytes = child.stat().st_size
                encoded = child_relative.encode("utf-8")
                digest.update(len(encoded).to_bytes(8, "big"))
                digest.update(encoded)
                digest.update(bytes.fromhex(child_hash))
                digest.update(child_bytes.to_bytes(8, "big"))
                file_count += 1
                byte_count += child_bytes
        if file_count == 0:
            raise ValueError(f"candidate directory contains no files: {relative}")
        return {
            "path": relative,
            "artifact_type": "directory",
            "sha256": digest.hexdigest(),
            "bytes": byte_count,
            "file_count": file_count,
        }
    if not path.is_file():
        raise ValueError(f"candidate path is not a regular file or directory: {relative}")
    return {
        "path": relative,
        "artifact_type": "file",
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "file_count": 1,
    }


def candidate_id(kind: str, path: str) -> str:
    suffix = hashlib.sha256(f"{kind}\0{path.casefold()}".encode("utf-8")).hexdigest()[:12]
    return f"candidate-{kind}-{suffix}"


def find_entry(payload: dict, kind: str, path: str) -> dict:
    normalized = path.replace("\\", "/").casefold()
    for entry in payload["candidates"]:
        if entry["kind"] == kind and entry["path"].casefold() == normalized:
            return entry
    raise ValueError(f"candidate is not registered for kind={kind}: {path}")


def verify_entry(root: Path, registry_path: Path, entry: dict) -> list[str]:
    try:
        actual = snapshot(root, registry_path, entry["path"])
    except (OSError, ValueError) as exc:
        return [str(exc)]
    errors = []
    for field in ("artifact_type", "sha256", "bytes", "file_count"):
        if actual[field] != entry[field]:
            errors.append(
                f"candidate drift for {entry['id']}: {field} recorded={entry[field]!r} actual={actual[field]!r}"
            )
    return errors


def save_registry(path: Path, payload: dict, at: str) -> None:
    payload["revision"] += 1
    payload["updated_at"] = at
    load_and_validate(payload, REGISTRY_SCHEMA, "candidate registry")
    errors = validate_semantics(payload)
    if errors:
        raise ValueError("refusing to write invalid candidate registry: " + "; ".join(errors))
    atomic_write_json(path, payload)


def summary(payload: dict, *, verify_errors: list[str] | None = None) -> dict:
    current = {
        kind: [entry["path"] for entry in payload["candidates"] if entry["kind"] == kind and entry["status"] == "current"]
        for kind in KINDS
    }
    counts = {
        status: sum(entry["status"] == status for entry in payload["candidates"])
        for status in ("candidate", "current", "superseded", "retained")
    }
    return {
        "revision": payload["revision"],
        "updated_at": payload["updated_at"],
        "counts": counts,
        "current": current,
        "candidates": payload["candidates"],
        "verification_errors": verify_errors or [],
    }


def execute(args: argparse.Namespace) -> dict:
    root = args.case_dir.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"case directory does not exist: {root}")
    registry_path, registry_relative = registry_location(root, args.registry)
    payload, existed = load_registry(registry_path)
    action = args.candidate_action
    changed = False
    pointer_update_required = False
    at = timestamp(getattr(args, "at", None)) if action not in {"list", "import-plan"} else None

    if action == "register":
        recorded = snapshot(root, registry_path, args.path)
        for existing in payload["candidates"]:
            if existing["path"].casefold() == recorded["path"].casefold():
                if existing["kind"] != args.kind:
                    raise ValueError(
                        f"path is already registered as kind={existing['kind']}: {recorded['path']}"
                    )
                drift = verify_entry(root, registry_path, existing)
                if drift:
                    raise ValueError("; ".join(drift))
                return {
                    "schema_version": 1,
                    "command": "candidate register",
                    "passed": True,
                    "changed": False,
                    "registry": registry_relative,
                    "registry_existed": existed,
                    "candidate": existing,
                    "pointer_update_required": False,
                    "summary": summary(payload),
                    "claim_scope": "Registration records a candidate; it does not select authority or pass a gate.",
                    "errors": [],
                }
        entry = {
            "id": candidate_id(args.kind, recorded["path"]),
            "kind": args.kind,
            **recorded,
            "status": "candidate",
            "registered_at": at,
            "source": args.source,
            "selected_at": None,
            "superseded_at": None,
            "superseded_by": None,
            "reason": None,
        }
        payload["candidates"].append(entry)
        payload["candidates"].sort(key=lambda item: (item["kind"], item["path"].casefold()))
        save_registry(registry_path, payload, at)
        changed = True
        selected_entry = entry
        claim_scope = "Registration records a candidate; it does not select authority or pass a gate."
    elif action == "select":
        _, relative = resolve_relative(root, args.path, "candidate path")
        selected_entry = find_entry(payload, args.kind, relative)
        if selected_entry["status"] == "superseded":
            raise ValueError("a superseded candidate cannot be reselected; register a new candidate path")
        drift = verify_entry(root, registry_path, selected_entry)
        if drift:
            raise ValueError("; ".join(drift))
        current = [
            entry
            for entry in payload["candidates"]
            if entry["kind"] == args.kind
            and entry["status"] == "current"
            and entry["id"] != selected_entry["id"]
        ]
        if current and not args.supersede_current:
            raise ValueError(
                "a current candidate already exists; rerun with --supersede-current and --reason: "
                + ", ".join(entry["path"] for entry in current)
            )
        if current and not args.reason.strip():
            raise ValueError("--reason is required when --supersede-current is used")
        for entry in current:
            entry.update(
                status="superseded",
                superseded_at=at,
                superseded_by=selected_entry["id"],
                reason=args.reason.strip(),
            )
        if selected_entry["status"] != "current":
            selected_entry.update(
                status="current",
                selected_at=at,
                superseded_at=None,
                superseded_by=None,
                reason=None,
            )
            changed = True
        if current:
            changed = True
        if changed:
            save_registry(registry_path, payload, at)
        pointer_update_required = changed
        claim_scope = "Selection changes candidate lineage only; CURRENT-STATE and all human gates remain separate."
    elif action == "supersede":
        _, relative = resolve_relative(root, args.path, "candidate path")
        _, replacement_relative = resolve_relative(root, args.by, "replacement candidate path")
        selected_entry = find_entry(payload, args.kind, relative)
        replacement = find_entry(payload, args.kind, replacement_relative)
        if selected_entry["id"] == replacement["id"]:
            raise ValueError("a candidate cannot supersede itself")
        if not args.reason.strip():
            raise ValueError("--reason must be non-empty")
        drift = verify_entry(root, registry_path, selected_entry) + verify_entry(
            root, registry_path, replacement
        )
        if drift:
            raise ValueError("; ".join(drift))
        selected_entry.update(
            status="superseded",
            superseded_at=at,
            superseded_by=replacement["id"],
            reason=args.reason.strip(),
        )
        save_registry(registry_path, payload, at)
        changed = True
        pointer_update_required = True
        claim_scope = "Superseding records lineage only; it does not delete files or pass a gate."
    elif action == "retain":
        _, relative = resolve_relative(root, args.path, "candidate path")
        selected_entry = find_entry(payload, args.kind, relative)
        if selected_entry["status"] == "current":
            raise ValueError("a current candidate cannot be retained; select another current candidate first")
        if not args.reason.strip():
            raise ValueError("--reason must be non-empty")
        drift = verify_entry(root, registry_path, selected_entry)
        if drift:
            raise ValueError("; ".join(drift))
        selected_entry.update(
            status="retained",
            selected_at=None,
            superseded_at=None,
            superseded_by=None,
            reason=args.reason.strip(),
        )
        save_registry(registry_path, payload, at)
        changed = True
        claim_scope = "Retaining records non-current evidence without deleting it or passing a gate."
    elif action == "import-plan":
        if existed or payload["revision"] != 0 or payload["candidates"]:
            raise ValueError("import-plan requires an absent, empty candidate registry")
        plan_path, _ = resolve_relative(root, args.plan, "candidate classification plan")
        if not plan_path.is_file():
            raise ValueError(f"candidate classification plan does not exist: {args.plan}")
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read candidate classification plan: {exc}") from exc
        load_and_validate(plan, IMPORT_PLAN_SCHEMA, "candidate classification plan")
        at = timestamp(plan["recorded_at"])
        source = plan["source"].strip()
        if not source:
            raise ValueError("candidate classification plan source must be non-empty")
        planned: list[tuple[dict, dict]] = []
        normalized_paths: set[str] = set()
        currents = {kind: 0 for kind in KINDS}
        for item in plan["entries"]:
            recorded = snapshot(root, registry_path, item["path"])
            normalized = recorded["path"].casefold()
            if normalized in normalized_paths:
                raise ValueError(f"duplicate path in candidate classification plan: {recorded['path']}")
            normalized_paths.add(normalized)
            status = item["status"]
            reason = item["reason"]
            replacement_path = item["superseded_by"]
            if status == "current":
                currents[item["kind"]] += 1
                if reason is not None or replacement_path is not None:
                    raise ValueError(f"current entry must not have reason or superseded_by: {recorded['path']}")
            elif status == "superseded":
                if not reason or not reason.strip() or not replacement_path:
                    raise ValueError(f"superseded entry requires reason and superseded_by: {recorded['path']}")
            elif status == "retained":
                if not reason or not reason.strip() or replacement_path is not None:
                    raise ValueError(f"retained entry requires reason and no superseded_by: {recorded['path']}")
            elif reason is not None or replacement_path is not None:
                raise ValueError(f"candidate entry must not have transition metadata: {recorded['path']}")
            planned.append((item, recorded))
        for kind, count in currents.items():
            if count > 1:
                raise ValueError(f"classification plan has multiple current {kind} candidates: {count}")
        ids_by_path = {
            recorded["path"].casefold(): candidate_id(item["kind"], recorded["path"])
            for item, recorded in planned
        }
        for item, recorded in planned:
            replacement_id = None
            if item["status"] == "superseded":
                _, replacement_relative = resolve_relative(root, item["superseded_by"], "superseded_by")
                replacement_id = ids_by_path.get(replacement_relative.casefold())
                if replacement_id is None:
                    raise ValueError(f"superseded_by is not in the classification plan: {replacement_relative}")
                replacement_item = next(
                    candidate_item
                    for candidate_item, candidate_recorded in planned
                    if candidate_recorded["path"].casefold() == replacement_relative.casefold()
                )
                if replacement_item["kind"] != item["kind"]:
                    raise ValueError(f"superseded_by kind mismatch: {recorded['path']}")
            status = item["status"]
            payload["candidates"].append(
                {
                    "id": candidate_id(item["kind"], recorded["path"]),
                    "kind": item["kind"],
                    **recorded,
                    "status": status,
                    "registered_at": at,
                    "source": source,
                    "selected_at": at if status == "current" else None,
                    "superseded_at": at if status == "superseded" else None,
                    "superseded_by": replacement_id,
                    "reason": item["reason"].strip() if item["reason"] else None,
                }
            )
        payload["candidates"].sort(key=lambda item: (item["kind"], item["path"].casefold()))
        save_registry(registry_path, payload, at)
        changed = True
        pointer_update_required = True
        selected_entry = None
        claim_scope = "Importing records candidate lineage only; it does not delete files, select authority, or pass a gate."
    else:
        verification_errors = []
        if not args.skip_content_verification:
            for entry in payload["candidates"]:
                verification_errors.extend(verify_entry(root, registry_path, entry))
        return {
            "schema_version": 1,
            "command": "candidate list",
            "passed": not verification_errors,
            "changed": False,
            "registry": registry_relative,
            "registry_existed": existed,
            "pointer_update_required": False,
            "summary": summary(payload, verify_errors=verification_errors),
            "claim_scope": "Listing verifies registry structure and recorded content only; it does not select authority or pass a gate.",
            "errors": verification_errors,
        }

    return {
        "schema_version": 1,
        "command": f"candidate {action}",
        "passed": True,
        "changed": changed,
        "registry": registry_relative,
        "registry_existed": existed,
        "candidate": selected_entry,
        "pointer_update_required": pointer_update_required,
        "summary": summary(payload),
        "claim_scope": claim_scope,
        "errors": [],
    }


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("case_dir", type=Path)
    parser.add_argument("--registry", default=DEFAULT_REGISTRY)
    parser.add_argument("--json", action="store_true")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    actions = root.add_subparsers(dest="candidate_action", required=True)
    listing = actions.add_parser("list", help="List and verify registered candidates")
    add_common(listing)
    listing.add_argument("--skip-content-verification", action="store_true")
    register = actions.add_parser("register", help="Register a hash-bound candidate")
    add_common(register)
    register.add_argument("--kind", choices=KINDS, required=True)
    register.add_argument("--path", required=True)
    register.add_argument("--source", default="registered via manage_candidates.py")
    register.add_argument("--at")
    select = actions.add_parser("select", help="Select one current candidate by kind")
    add_common(select)
    select.add_argument("--kind", choices=KINDS, required=True)
    select.add_argument("--path", required=True)
    select.add_argument("--at")
    select.add_argument("--supersede-current", action="store_true")
    select.add_argument("--reason", default="")
    supersede = actions.add_parser("supersede", help="Mark one candidate superseded by another")
    add_common(supersede)
    supersede.add_argument("--kind", choices=KINDS, required=True)
    supersede.add_argument("--path", required=True)
    supersede.add_argument("--by", required=True)
    supersede.add_argument("--reason", required=True)
    supersede.add_argument("--at")
    retain = actions.add_parser("retain", help="Classify a registered item as retained non-current evidence")
    add_common(retain)
    retain.add_argument("--kind", choices=KINDS, required=True)
    retain.add_argument("--path", required=True)
    retain.add_argument("--reason", required=True)
    retain.add_argument("--at")
    importing = actions.add_parser("import-plan", help="Atomically initialize a registry from a classification plan")
    add_common(importing)
    importing.add_argument("--plan", required=True)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        report = execute(args)
    except (OSError, UnicodeError, ValueError) as exc:
        report = {
            "schema_version": 1,
            "command": f"candidate {getattr(args, 'candidate_action', 'invalid')}",
            "passed": False,
            "changed": False,
            "pointer_update_required": False,
            "errors": [str(exc)],
            "claim_scope": "No candidate transition was accepted.",
        }
    if getattr(args, "json", False):
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"candidate_command_passed={str(report.get('passed', False)).lower()}")
        if "registry" in report:
            print(f"registry={report['registry']}")
        summary_value = report.get("summary", {})
        if summary_value:
            print(f"revision={summary_value.get('revision')}")
            for kind, values in summary_value.get("current", {}).items():
                print(f"current_{kind}={','.join(values) if values else 'NONE'}")
        for error in report.get("errors", []):
            print(f"error: {error}")
    return 0 if report.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())

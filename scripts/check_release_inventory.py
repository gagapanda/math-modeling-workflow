#!/usr/bin/env python
"""Check candidate source inventory coverage/integrity; fail closed for release authorization."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

MANIFEST = "docs/source-inventory.json"
LOCAL_DIRS = {".git", "local-work", ".venv", "__pycache__"}
BINARY_SUFFIXES = {".exe", ".dll", ".whl", ".zip", ".pdf", ".docx", ".ttf", ".ttc", ".otf", ".pyc"}


def candidate_files(root):
    result = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part in LOCAL_DIRS for part in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError("symlinks are not allowed in the source inventory")
        if path.is_file():
            # The documented synthetic figure is generated locally, not release source.
            if relative.as_posix() == "examples/paper-export/toy-figure.png":
                continue
            result[relative.as_posix()] = path
    return result


def verify(root):
    root = Path(root).resolve()
    data = json.loads((root / MANIFEST).read_text(encoding="utf-8-sig"))
    if data.get("schema_version") != 1 or not isinstance(data.get("files"), list):
        raise ValueError("unsupported source inventory")
    actual = candidate_files(root)
    records = {}
    problems = []
    pending = []
    for row in data["files"]:
        name = row.get("path")
        if not isinstance(name, str) or "\\" in name or Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError("invalid inventory path")
        if name in records:
            raise ValueError("duplicate inventory path")
        records[name] = row
        if not row.get("source_class") or not row.get("source_reference"):
            problems.append("missing provenance: " + name)
        if not isinstance(row.get("license_expression"), str) or not row["license_expression"].strip():
            problems.append("missing license status: " + name)
        if row.get("authorization_status") != "confirmed" or row.get("license_expression") == "NOASSERTION":
            pending.append(name)
        elif not isinstance(row.get("authorization_evidence"), str) or not row["authorization_evidence"].strip():
            problems.append("confirmed status without evidence: " + name)
        if name not in actual:
            continue
        if Path(name).suffix.lower() in BINARY_SUFFIXES:
            problems.append("binary distribution not approved by this source-only policy: " + name)
        if name == MANIFEST:
            if row.get("sha256") is not None:
                problems.append("self-manifest hash must be null; recursive hashing is undefined")
        else:
            digest = hashlib.sha256(actual[name].read_bytes()).hexdigest()
            if row.get("sha256") != digest:
                problems.append("hash mismatch: " + name)
    problems += ["unregistered file: " + name for name in sorted(set(actual) - set(records))]
    problems += ["registered file missing: " + name for name in sorted(set(records) - set(actual))]
    license_path = root / "LICENSE"
    license_text = license_path.read_text(encoding="utf-8-sig") if license_path.is_file() else ""
    root_authorized = data.get("project_license_status") == "confirmed" and bool(license_text.strip()) and "许可证将在" not in license_text
    blockers = []
    if not root_authorized:
        blockers.append("Project license is still pending or a placeholder")
    if pending:
        blockers.append(f"{len(pending)} source files still require rights/license confirmation")
    if data.get("dependency_distribution_review") != "confirmed_source_only":
        blockers.append("Dependency distribution policy has not been confirmed")
    if problems:
        blockers.append("Source inventory integrity/coverage failed")
    return {"schema_version": 1, "command": "check_release_inventory", "inventory_valid": not problems,
            "file_count": len(actual), "pending_authorization_count": len(pending), "problems": problems,
            "release_ready": not blockers, "release_blockers": blockers,
            "limits": ["Checks declarations and hashes, not legal ownership or actual human identity", "Local ignored directories and generated toy image are not approved for publication", "No Git history, vulnerability or clean-OS clearance"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--require-release", action="store_true", help="Fail while any release authorization is pending")
    args = parser.parse_args()
    try:
        report = verify(args.root)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f"release inventory rejected: {exc}\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["inventory_valid"] and (not args.require_release or report["release_ready"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())

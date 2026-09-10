#!/usr/bin/env python
"""Smoke-test anonymous support-material ZIP packages in a temporary directory."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from _json_schema import load_and_validate

SKILL_DIR = Path(__file__).resolve().parent.parent
PLAN_SCHEMA = SKILL_DIR / "schemas" / "support-smoke-plan.schema.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_absolute_name(name: str) -> bool:
    path = PurePosixPath(name)
    return path.is_absolute() or name.startswith(("/", "\\")) or (len(name) >= 2 and name[1] == ":")


def validate_relative_path(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty relative path")
    candidate = value.replace("\\", "/")
    if _is_absolute_name(candidate):
        raise ValueError(f"{label} must not be absolute: {value}")
    path = PurePosixPath(candidate)
    if path == PurePosixPath("."):
        return "."
    if any(part in {"", "."} for part in path.parts) or ".." in path.parts:
        raise ValueError(f"{label} must not contain empty, dot, or traversal components: {value}")
    return "/".join(path.parts)


def validate_archive_member(name: str) -> str:
    if not isinstance(name, str) or not name:
        raise ValueError("archive member has an empty name")
    directory = name.endswith("/")
    normalized = validate_relative_path(name.rstrip("/"), "archive member")
    return normalized + ("/" if directory else "")


def is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return (mode & 0o170000) == 0o120000


def safe_extract(archive: zipfile.ZipFile, destination: Path) -> list[str]:
    members: list[str] = []
    root = destination.resolve()
    for info in archive.infolist():
        normalized = validate_archive_member(info.filename)
        if is_symlink(info):
            raise ValueError(f"archive member is a symlink: {info.filename}")
        target = (destination / normalized.rstrip("/").replace("/", os.sep)).resolve()
        if target != root and root not in target.parents:
            raise ValueError(f"archive member escapes extraction directory: {info.filename}")
        if info.is_dir() or normalized.endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info, "r") as source, target.open("wb") as output:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
        members.append(normalized)
    return members


def validate_command(command: list[str], test_name: str) -> list[str]:
    if not command or any(not isinstance(item, str) or not item for item in command):
        raise ValueError(f"test {test_name} command must contain non-empty strings")
    entry = command[0]
    if Path(entry).is_absolute() or _is_absolute_name(entry):
        raise ValueError(f"test {test_name} command entry must not be absolute: {entry}")
    if ".." in PurePosixPath(entry.replace("\\", "/")).parts:
        raise ValueError(f"test {test_name} command entry must not contain traversal: {entry}")
    resolved = list(command)
    if entry.casefold() in {"python", "python.exe"}:
        resolved[0] = sys.executable
    return resolved


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_plan(plan_path: Path) -> dict[str, Any]:
    try:
        data = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read smoke plan: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("smoke plan must be a JSON object")
    load_and_validate(data, PLAN_SCHEMA, "support smoke plan")
    return data


def _base_report(package_path: Path, plan_path: Path) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at": utc_now(),
        "package": str(package_path),
        "plan": str(plan_path),
        "package_sha256": None,
        "package_bytes": None,
        "archive_members": [],
        "tests": [],
        "errors": [],
        "passed": False,
    }


def audit_support_package(package_path: Path, plan_path: Path) -> dict[str, Any]:
    """Run all declared smoke tests and return a stable JSON-compatible report."""
    package_path = Path(package_path).resolve()
    plan_path = Path(plan_path).resolve()
    report = _base_report(package_path, plan_path)
    try:
        plan = _load_plan(plan_path)
        if not package_path.is_file():
            raise ValueError(f"support package does not exist: {package_path}")
        report["package_sha256"] = sha256_file(package_path)
        report["package_bytes"] = package_path.stat().st_size
        declared_package = plan["package"]
        if Path(declared_package).is_absolute() or _is_absolute_name(declared_package):
            raise ValueError("smoke plan package must be relative")
        if Path(declared_package).name != package_path.name:
            report["errors"].append(
                f"smoke plan package name {declared_package!r} does not match supplied package {package_path.name!r}"
            )
    except (OSError, ValueError) as exc:
        report["errors"].append(str(exc))
        return report

    try:
        archive = zipfile.ZipFile(package_path)
    except (OSError, zipfile.BadZipFile) as exc:
        report["errors"].append(f"cannot open support ZIP: {exc}")
        return report

    try:
        with archive:
            for info in archive.infolist():
                report["archive_members"].append(validate_archive_member(info.filename))
                if is_symlink(info):
                    raise ValueError(f"archive member is a symlink: {info.filename}")
            with tempfile.TemporaryDirectory(prefix="math-modeling-support-smoke-") as temporary:
                extraction_root = Path(temporary).resolve()
                safe_extract(archive, extraction_root)
                for declaration in plan["tests"]:
                    record: dict[str, Any] = {
                        "name": declaration["name"],
                        "command": declaration["command"],
                        "cwd": declaration["cwd"],
                        "expected_outputs": declaration["expected_outputs"],
                        "timeout_seconds": declaration["timeout_seconds"],
                        "exit_code": None,
                        "timed_out": False,
                        "stdout_bytes": 0,
                        "stderr_bytes": 0,
                        "stdout_sha256": None,
                        "stderr_sha256": None,
                        "missing_outputs": [],
                        "elapsed_seconds": None,
                        "errors": [],
                    }
                    report["tests"].append(record)
                    started = time.monotonic()
                    try:
                        cwd_relative = validate_relative_path(declaration["cwd"], f"test {record['name']} cwd")
                        cwd = (extraction_root / cwd_relative.replace("/", os.sep)).resolve()
                        if cwd != extraction_root and extraction_root not in cwd.parents:
                            raise ValueError("cwd escapes extraction directory")
                        if not cwd.is_dir():
                            raise ValueError(f"cwd does not exist in package: {declaration['cwd']}")
                        output_paths = []
                        for output in declaration["expected_outputs"]:
                            output_relative = validate_relative_path(output, f"test {record['name']} expected output")
                            output_path = (cwd / output_relative.replace("/", os.sep)).resolve()
                            if output_path != extraction_root and extraction_root not in output_path.parents:
                                raise ValueError("expected output escapes extraction directory")
                            output_paths.append((output, output_path))
                        command = validate_command(declaration["command"], record["name"])
                        try:
                            completed = subprocess.run(
                                command,
                                cwd=cwd,
                                shell=False,
                                capture_output=True,
                                timeout=declaration["timeout_seconds"],
                                check=False,
                            )
                            stdout = completed.stdout or b""
                            stderr = completed.stderr or b""
                            record["exit_code"] = completed.returncode
                        except subprocess.TimeoutExpired as exc:
                            stdout = exc.stdout or b""
                            stderr = exc.stderr or b""
                            record["timed_out"] = True
                            record["errors"].append("command timed out")
                        record["stdout_bytes"] = len(stdout)
                        record["stderr_bytes"] = len(stderr)
                        record["stdout_sha256"] = _hash_bytes(stdout)
                        record["stderr_sha256"] = _hash_bytes(stderr)
                        record["elapsed_seconds"] = round(time.monotonic() - started, 6)
                        if record["timed_out"]:
                            continue
                        if record["exit_code"] != 0:
                            record["errors"].append(f"command exited with code {record['exit_code']}")
                        for output, output_path in output_paths:
                            if not output_path.exists():
                                record["missing_outputs"].append(output)
                        if record["missing_outputs"]:
                            record["errors"].append("expected outputs are missing")
                    except (OSError, ValueError, subprocess.SubprocessError) as exc:
                        record["errors"].append(str(exc))
                        record["elapsed_seconds"] = round(time.monotonic() - started, 6)
                    for error in record["errors"]:
                        report["errors"].append(f"test {record['name']}: {error}")
                report["passed"] = not report["errors"] and all(
                    not item["errors"] for item in report["tests"]
                )
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        report["errors"].append(str(exc))
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = audit_support_package(args.package, args.plan)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.json or not args.output:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

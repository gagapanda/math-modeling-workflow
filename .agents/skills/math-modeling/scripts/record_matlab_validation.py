#!/usr/bin/env python
"""Record hash-bound evidence after MATLAB MCP analysis, execution, and tests pass."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from _json_schema import load_and_validate
from _workflow_common import (
    atomic_write_json as atomic_write,
    resolve_path_inside as resolve_inside,
    sha256_file,
)


MATLAB_VALIDATION_SCHEMA = (
    Path(__file__).resolve().parent.parent / "schemas" / "matlab-validation.schema.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--step-name", required=True)
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument("--test", type=Path)
    parser.add_argument("--dependency", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, action="append", default=[])
    parser.add_argument("--notes", default="Validated through MATLAB MCP.")
    parser.add_argument("--confirm-code-analyzer-passed", action="store_true")
    parser.add_argument("--confirm-script-execution-passed", action="store_true")
    parser.add_argument("--confirm-unit-tests-passed", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = {"recorded": False, "errors": []}
    try:
        case_dir = args.case_dir.expanduser().resolve()
        if not case_dir.is_dir():
            raise ValueError(f"case directory does not exist: {case_dir}")
        step_name = args.step_name.strip()
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", step_name) is None:
            raise ValueError(
                "step-name must use only letters, digits, dot, underscore, and hyphen"
            )
        if not args.confirm_code_analyzer_passed:
            raise ValueError("--confirm-code-analyzer-passed is required")
        if not args.confirm_script_execution_passed:
            raise ValueError("--confirm-script-execution-passed is required")
        if args.test is not None and not args.confirm_unit_tests_passed:
            raise ValueError("--confirm-unit-tests-passed is required when --test is supplied")
        script = resolve_inside(case_dir, args.script, "script")
        test = resolve_inside(case_dir, args.test, "test") if args.test else None
        dependencies = [
            resolve_inside(case_dir, dependency, "dependency")
            for dependency in args.dependency
        ]
        outputs = [resolve_inside(case_dir, output, "output") for output in args.output]
        files = [script, *([test] if test else []), *dependencies, *outputs]
        if len(set(files)) != len(files):
            raise ValueError("script, test, dependencies, and outputs must be distinct")
        for path in files:
            if not path.is_file():
                raise ValueError(f"validated file does not exist: {path}")
        hashes = {
            str(path.relative_to(case_dir)).replace("\\", "/"): sha256_file(path)
            for path in files
        }
        checks = {
            "code_analyzer": "passed",
            "script_execution": "passed",
            "unit_tests": "passed" if test else "not_applicable",
        }
        evidence = {
            "schema_version": 1,
            "status": "passed",
            "runner": "matlab-mcp",
            "step_name": step_name,
            "validated_at": datetime.now().astimezone().isoformat(),
            "checks": checks,
            "file_sha256": hashes,
            "notes": args.notes.strip(),
        }
        path = case_dir / "results" / f"matlab-validation-{step_name}.json"
        load_and_validate(evidence, MATLAB_VALIDATION_SCHEMA, "MATLAB validation evidence")
        atomic_write(path, evidence)
        report.update({"recorded": True, "path": str(path), "evidence": evidence})
    except (OSError, ValueError) as exc:
        report["errors"].append(str(exc))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"recorded={str(report['recorded']).lower()}")
        if report.get("path"):
            print(f"path={report['path']}")
        for error in report["errors"]:
            print(f"error: {error}")
    return 0 if report["recorded"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

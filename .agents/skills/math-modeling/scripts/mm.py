#!/usr/bin/env python
"""Unified thin CLI for the mathematical-modeling workflow.

This command delegates to existing workflow tools. It does not reimplement
their checks, select artifacts, or sign human gates.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent


def invoke(script: str, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, str(SCRIPT_DIR / script), *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
    )


def print_passthrough(completed: subprocess.CompletedProcess[str]) -> int:
    if completed.stdout:
        print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
    if completed.stderr:
        print(
            completed.stderr,
            end="" if completed.stderr.endswith("\n") else "\n",
            file=sys.stderr,
        )
    return completed.returncode


def parse_json_output(
    name: str, completed: subprocess.CompletedProcess[str]
) -> tuple[dict | None, dict]:
    try:
        payload = json.loads(completed.stdout)
        if not isinstance(payload, dict):
            raise ValueError("JSON root is not an object")
    except (json.JSONDecodeError, ValueError) as exc:
        return None, {
            "name": name,
            "returncode": completed.returncode,
            "passed": False,
            "error": f"invalid JSON from delegated tool: {exc}",
            "stderr": completed.stderr.strip(),
        }
    return payload, {
        "name": name,
        "returncode": completed.returncode,
        "passed": completed.returncode == 0,
        "report": payload,
        "stderr": completed.stderr.strip(),
    }


def start_command(args: argparse.Namespace) -> int:
    delegated = [args.case_name, "--root", str(args.root), "--profile", args.profile]
    completed = invoke("scaffold_case.py", delegated)
    if not args.json:
        return print_passthrough(completed)
    values: dict[str, str | int] = {}
    for line in completed.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = int(value) if key in {"created", "preserved"} and value.isdigit() else value
    report = {
        "schema_version": 1,
        "command": "mm start",
        "passed": completed.returncode == 0,
        "profile": args.profile,
        "case": values,
        "errors": [completed.stderr.strip()] if completed.stderr.strip() else [],
        "claim_scope": "Scaffolding creates or preserves files only; it does not complete a modeling or submission gate.",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return completed.returncode


def heartbeat_arguments(args: argparse.Namespace) -> list[str]:
    delegated = [
        "--case-dir",
        str(args.case_dir),
        "--current-state",
        args.current_state,
        "--json",
    ]
    for value in args.candidate_root or []:
        delegated.extend(["--candidate-root", value])
    for value in args.control_file or []:
        delegated.extend(["--control-file", value])
    return delegated


def status_command(args: argparse.Namespace) -> int:
    completed = invoke("audit_authority_heartbeat.py", heartbeat_arguments(args))
    if args.json:
        return print_passthrough(completed)
    payload, component = parse_json_output("authority_heartbeat", completed)
    if payload is None:
        print(f"status_healthy=false\nerror: {component['error']}")
        if component.get("stderr"):
            print(component["stderr"], file=sys.stderr)
        return completed.returncode or 2
    print(f"status_healthy={str(payload.get('healthy', False)).lower()}")
    summary = payload.get("diagnostic_summary", {})
    print(
        "diagnostics="
        f"error:{summary.get('error', 0)} "
        f"warning:{summary.get('warning', 0)} "
        f"info:{summary.get('info', 0)}"
    )
    for item in payload.get("diagnostics", []):
        print(f"{item['severity']}: {item['code']}: {item['message']}")
    return completed.returncode


def check_command(args: argparse.Namespace) -> int:
    case_dir = args.case_dir.expanduser().resolve()
    heartbeat = invoke("audit_authority_heartbeat.py", heartbeat_arguments(args))
    doctor_args = ["--case-dir", str(case_dir), "--phase", args.phase, "--json"]
    pipeline_args = ["--case-dir", str(case_dir), "--validate-only", "--json"]
    if args.manifest:
        doctor_args.extend(["--manifest", str(args.manifest)])
        pipeline_args.extend(["--manifest", str(args.manifest)])
    if args.active_probe:
        doctor_args.append("--active-probe")
    doctor = invoke("doctor.py", doctor_args)
    pipeline = invoke("run_pipeline.py", pipeline_args)
    components = []
    for name, completed in (
        ("authority_heartbeat", heartbeat),
        ("doctor", doctor),
        ("manifest_validation", pipeline),
    ):
        _, component = parse_json_output(name, completed)
        components.append(component)
    passed = all(component["passed"] for component in components)
    report = {
        "schema_version": 1,
        "command": "mm check",
        "mode": "active_environment_probe" if args.active_probe else "passive_read_only",
        "case_dir": str(case_dir),
        "phase": args.phase,
        "passed": passed,
        "components": components,
        "claim_scope": (
            "This aggregates pointer consistency, manifest validation, and environment diagnostics. "
            "It does not execute modeling steps or prove model validity, paper quality, human acceptance, "
            "compliance, upload, or receipt authenticity."
        ),
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"check_passed={str(passed).lower()}")
        for component in components:
            print(
                f"{component['name']}={'passed' if component['passed'] else 'failed'} "
                f"(exit={component['returncode']})"
            )
            nested = component.get("report", {}).get("diagnostic_summary")
            if nested:
                print(
                    "  diagnostics="
                    f"error:{nested.get('error', 0)} "
                    f"warning:{nested.get('warning', 0)} "
                    f"info:{nested.get('info', 0)}"
                )
            if component.get("error"):
                print(f"  error: {component['error']}")
    return 0 if passed else 2


def freeze_command(args: argparse.Namespace) -> int:
    delegated = [args.freeze_action, "--case-dir", str(args.case_dir)]
    if args.freeze_action == "prepare":
        delegated.extend(
            [
                "--plan",
                args.plan,
                "--output",
                args.output,
                "--generated-at",
                args.generated_at,
            ]
        )
    elif args.freeze_action == "verify":
        delegated.extend(["--manifest", args.manifest])
    else:
        delegated.extend(
            [
                "--candidate",
                args.candidate,
                "--output",
                args.output,
                "--decision",
                args.decision,
                "--reviewer",
                args.reviewer,
                "--review-start",
                args.review_start,
                "--review-end",
                args.review_end,
                "--signed-at",
                args.signed_at,
                "--generated-at",
                args.generated_at,
                "--objections",
                args.objections,
                "--resolution",
                args.resolution,
            ]
        )
        if args.confirm_human_reviewed:
            delegated.append("--confirm-human-reviewed")
    return print_passthrough(invoke("freeze_results.py", delegated))


def package_command(args: argparse.Namespace) -> int:
    delegated = ["--case-dir", str(args.case_dir), "--plan", args.plan]
    if args.output_dir:
        delegated.extend(["--output-dir", str(args.output_dir)])
    if args.generated_at:
        delegated.extend(["--generated-at", args.generated_at])
    if args.replace:
        delegated.append("--replace")
    if args.json:
        delegated.append("--json")
    return print_passthrough(invoke("package_submission.py", delegated))


def candidate_command(args: argparse.Namespace) -> int:
    delegated = ["--help"] if args.candidate_help else (args.candidate_arguments or ["--help"])
    return print_passthrough(invoke("manage_candidates.py", delegated))


def add_heartbeat_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("case_dir", type=Path)
    parser.add_argument("--current-state", default="CURRENT-STATE.md")
    parser.add_argument("--candidate-root", action="append")
    parser.add_argument("--control-file", action="append")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    subcommands = root.add_subparsers(dest="command", required=True)

    start = subcommands.add_parser("start", help="Create or preserve a case scaffold")
    start.add_argument("case_name")
    start.add_argument("--root", type=Path, default=Path.cwd())
    start.add_argument(
        "--profile", choices=("explore", "practice", "submission"), default="practice"
    )
    start.add_argument("--json", action="store_true")
    start.set_defaults(handler=start_command)

    status = subcommands.add_parser("status", help="Run the read-only authority heartbeat")
    add_heartbeat_options(status)
    status.add_argument("--json", action="store_true")
    status.set_defaults(handler=status_command)

    check = subcommands.add_parser(
        "check", help="Aggregate heartbeat, doctor, and manifest validation"
    )
    add_heartbeat_options(check)
    check.add_argument("--manifest", type=Path)
    check.add_argument("--phase", choices=("build", "finalize"), default="build")
    check.add_argument("--active-probe", action="store_true")
    check.add_argument("--json", action="store_true")
    check.set_defaults(handler=check_command)

    freeze = subcommands.add_parser("freeze", help="Delegate to the F1 freeze tool")
    freeze_actions = freeze.add_subparsers(dest="freeze_action", required=True)
    prepare = freeze_actions.add_parser("prepare")
    prepare.add_argument("case_dir", type=Path)
    prepare.add_argument("--plan", required=True)
    prepare.add_argument("--output", required=True)
    prepare.add_argument("--generated-at", required=True)
    prepare.set_defaults(handler=freeze_command)
    verify = freeze_actions.add_parser("verify")
    verify.add_argument("case_dir", type=Path)
    verify.add_argument("--manifest", required=True)
    verify.set_defaults(handler=freeze_command)
    finalize = freeze_actions.add_parser("finalize")
    finalize.add_argument("case_dir", type=Path)
    finalize.add_argument("--candidate", required=True)
    finalize.add_argument("--output", required=True)
    finalize.add_argument(
        "--decision",
        choices=("accepted", "accepted_with_limitations", "rejected"),
        required=True,
    )
    finalize.add_argument("--reviewer", required=True)
    finalize.add_argument("--review-start", required=True)
    finalize.add_argument("--review-end", required=True)
    finalize.add_argument("--signed-at", required=True)
    finalize.add_argument("--generated-at", required=True)
    finalize.add_argument("--objections", default="NONE")
    finalize.add_argument("--resolution", default="NONE")
    finalize.add_argument("--confirm-human-reviewed", action="store_true")
    finalize.set_defaults(handler=freeze_command)

    package = subcommands.add_parser("package", help="Delegate to submission packaging")
    package.add_argument("case_dir", type=Path)
    package.add_argument("--plan", required=True)
    package.add_argument("--output-dir", type=Path)
    package.add_argument("--generated-at")
    package.add_argument("--replace", action="store_true")
    package.add_argument("--json", action="store_true")
    package.set_defaults(handler=package_command)

    candidate = subcommands.add_parser(
        "candidate",
        help="Delegate candidate registration and selection",
        add_help=False,
    )
    candidate.add_argument("--help", action="store_true", dest="candidate_help")
    candidate.add_argument("candidate_arguments", nargs=argparse.REMAINDER)
    candidate.set_defaults(handler=candidate_command)
    return root


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())

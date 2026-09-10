#!/usr/bin/env python
"""Render a passive workflow migration review package as Markdown on stdout."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from analyze_workflow_migration import relative_manifest_path
from prepare_workflow_migration_review_package import prepare


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--expected-source-sha256")
    parser.add_argument("--expected-candidate-sha256")
    args = parser.parse_args()
    for name in ("expected_source_sha256", "expected_candidate_sha256"):
        value = getattr(args, name)
        if value is not None and (
            len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
        ):
            parser.error(f"--{name.replace('_', '-')} must be a lowercase SHA-256 digest")
    return args


def code(value: object) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ")
    fence = "`"
    while fence in text:
        fence += "`"
    return f"{fence}{text}{fence}"


def text(value: object) -> str:
    return (
        str(value)
        .replace("\r", " ")
        .replace("\n", " ")
        .replace("\\", "\\\\")
        .replace("*", "\\*")
        .replace("_", "\\_")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def bullets(values: list[str], empty: str) -> list[str]:
    if not values:
        return [f"- {empty}"]
    return [f"- {code(value)}" for value in values]


def render_markdown(report: dict) -> str:
    bindings = report["bindings"]
    summary = report["summary"]
    lines = [
        "# Workflow Migration Human Review Work Package",
        "",
        f"> Status: {code(report['status'])}",
        "> This is a read-only evidence view, not a completed review record or migration approval.",
        "",
        "## Provenance",
        "",
        f"- Case: {code(report['case_dir'])}",
        f"- Source manifest: {code(bindings['source_manifest']['path'])}",
        f"- Source SHA-256: {code(bindings['source_manifest']['sha256'])}",
        f"- Base candidate SHA-256: {code(bindings['base_candidate_sha256'] or 'not applicable')}",
        f"- Source unchanged: {code(str(report['source_unchanged']).lower())}",
        "",
        "## Safety",
        "",
        f"- Files written: {code(str(report['files_written']).lower())}",
        f"- Case steps executed: {code(str(report['case_steps_executed']).lower())}",
        f"- External tools started: {code(str(report['external_tools_started']).lower())}",
        f"- Review record created: {code(str(report['review_record_created']).lower())}",
        f"- Candidate exported: {code(str(report['candidate_exported']).lower())}",
        f"- Cache enabled: {code(str(report['cache_enabled']).lower())}",
        "",
        "## Summary",
        "",
        f"- Python steps: {summary['python_steps']}",
        f"- Path candidates: {summary['path_candidates']}",
        f"- Candidate inputs: {summary['candidate_inputs']}",
        f"- Candidate outputs: {summary['candidate_outputs']}",
        f"- Exact relationship candidates: {summary['relationships']}",
        f"- Evidence gaps: {summary['evidence_gaps']}",
        f"- Pending human-review items: {summary['pending_checklist_items']}",
        f"- Cache-enable recommendations: {summary['cache_enable_recommended']}",
        f"- Provenance chains: {summary['provenance_chains']}",
        f"- Direct provenance chains: {summary['direct_provenance_chains']}",
        f"- Local-helper provenance chains: {summary['local_helper_provenance_chains']}",
        f"- Imported-helper provenance chains: {summary['imported_helper_provenance_chains']}",
        f"- Trace limitation occurrences: {summary['trace_limitation_occurrences']}",
        f"- Unique trace limitations: {summary['unique_trace_limitations']}",
        f"- Trace limitations: {summary['trace_limitations']}",
        f"- Trace limitation groups: {summary['trace_limitation_groups']}",
    ]

    if report["status"] == "ready_for_human_review":
        lines.extend(["", "## Script Bindings", ""])
        for binding in bindings["python_scripts"]:
            lines.append(
                f"- {code(binding['step'])}: {code(binding['path'])} ({code(binding['sha256'])})"
            )
        if bindings["support_modules"]:
            lines.extend(["", "### Traced Support Modules", ""])
            for binding in bindings["support_modules"]:
                lines.append(f"- {code(binding['path'])} ({code(binding['sha256'])})")

        lines.extend(["", "## Relationship Candidates", ""])
        if report["relationships"]:
            for item in report["relationships"]:
                lines.append(
                    f"- {code(item['producer_step'])} -> {code(item['consumer_step'])} via "
                    f"{code(item['path'])}; confidence {code(item['confidence'])}; "
                    f"evidence: {text(item['evidence'])}"
                )
        else:
            lines.append("- None discovered.")

        lines.extend(["", "## Evidence Gaps", ""])
        if report["gaps"]:
            for item in report["gaps"]:
                lines.append(
                    f"- {code(item['step'])} / {code(item['code'])}: {text(item['message'])}"
                )
        else:
            lines.append("- None reported by static analysis.")

        lines.extend(["", "## Trace Limitations", ""])
        limitation_steps = [step for step in report["steps"] if step["trace_limitations"]]
        if limitation_steps:
            for step in limitation_steps:
                lines.extend([f"### {code(step['name'])}", ""])
                reason_codes = sorted(
                    {item["code"] for item in step["trace_limitations"]}
                )
                for reason_code in reason_codes:
                    lines.extend([f"#### {code(reason_code)}", ""])
                    groups = [
                        group
                        for group in step["trace_limitation_groups"]
                        if group["code"] == reason_code
                    ]
                    for group in groups:
                        stop = (
                            f"{group['module']}:{group['function']}:"
                            f"{group['line']}:{group['callee']}"
                        )
                        lines.extend(
                            [
                                f"##### Stop {code(stop)}",
                                "",
                                f"- Occurrences: {group['occurrences']}",
                                f"- Unique call chains: {group['unique_call_chains']}",
                                f"- Status: {code(group['status'])}",
                                f"- Message: {text(group['message'])}",
                                "",
                            ]
                        )
                        for item in step["trace_limitations"]:
                            if (
                                item["code"],
                                item["module"],
                                item["function"],
                                item["line"],
                                item["callee"],
                            ) != (
                                group["code"],
                                group["module"],
                                group["function"],
                                group["line"],
                                group["callee"],
                            ):
                                continue
                            chain = " -> ".join(
                                f"{frame['module']}:{frame['function']}:"
                                f"{frame['line']}:{frame['callee']}"
                                for frame in item["call_chain"]
                            )
                            lines.append(f"- {code(chain)}")
                        lines.append("")
                    if lines[-1] == "":
                        lines.pop()
                    lines.append("")
                if lines[-1] == "":
                    lines.pop()
        else:
            lines.append("- None reported by the bounded static tracer.")

        lines.extend(["", "## Step Review", ""])
        for step in report["steps"]:
            lines.extend(
                [
                    f"### {step['order']}. {code(step['name'])}",
                    "",
                    f"- Script: {code(step['script'])}",
                    f"- Script SHA-256: {code(step['script_sha256'])}",
                    "",
                    "#### Candidate Inputs",
                    "",
                    *bullets(step["candidate_inputs"], "None discovered."),
                    "",
                    "#### Candidate Outputs",
                    "",
                    *bullets(step["candidate_outputs"], "None discovered."),
                    "",
                    "#### Unclassified Paths",
                    "",
                    *bullets(step["unclassified_paths"], "None discovered."),
                    "",
                    "#### Path Evidence",
                    "",
                ]
            )
            if step["path_evidence"]:
                for item in step["path_evidence"]:
                    lines.append(
                        f"- {code(item['access'])} {code(item['path'])} at line {item['line']}; "
                        f"confidence {code(item['confidence'])}; evidence: {text(item['evidence'])}"
                    )
                    for provenance in item["provenance"]:
                        chain = " -> ".join(
                            f"{frame['module']}:{frame['function']}:{frame['line']}:{frame['callee']}"
                            for frame in provenance["call_chain"]
                        )
                        lines.append(
                            f"  - Provenance {code(provenance['kind'])}: {code(chain)}"
                        )
            else:
                lines.append("- None discovered.")
            lines.extend(["", "#### Pending Human Review", ""])
            for item in step["checklist"]:
                lines.append(
                    f"- [ ] {code(item['code'])} ({code(item['status'])}): {text(item['prompt'])}"
                )
            lines.append("")

    if report["warnings"]:
        lines.extend(["## Warnings", ""] + [f"- {text(item)}" for item in report["warnings"]] + [""])
    if report["errors"]:
        lines.extend(["## Errors", ""] + [f"- {text(item)}" for item in report["errors"]] + [""])
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    args = parse_args()
    case_dir = args.case_dir.expanduser().resolve()
    manifest_path = case_dir / "workflow.json"
    try:
        if not case_dir.is_dir():
            raise ValueError(f"case directory does not exist: {case_dir}")
        manifest_path = relative_manifest_path(case_dir, args.manifest)
        report = prepare(
            case_dir,
            manifest_path,
            args.expected_source_sha256,
            args.expected_candidate_sha256,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print("# Workflow Migration Human Review Work Package")
        print()
        print("> Status: `failed`")
        print()
        print("## Errors")
        print()
        print(f"- {text(exc)}")
        return 2
    sys.stdout.write(render_markdown(report))
    return 0 if report["status"] in {"ready_for_human_review", "not_applicable"} else 2


if __name__ == "__main__":
    raise SystemExit(main())

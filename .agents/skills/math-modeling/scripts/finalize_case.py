#!/usr/bin/env python
"""Run final machine gates and verify recorded visual review for a case."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from audit_paper_closeout import audit_closeout
from _diagnostics import enrich_legacy_report
from _json_schema import load_and_validate
from _workflow_common import atomic_write_text, sha256_file, verify_evidence_hashes


START_MARKER = "<!-- math-modeling-finalize:start -->"
END_MARKER = "<!-- math-modeling-finalize:end -->"
FINALIZATION_REPORT_SCHEMA = (
    Path(__file__).resolve().parent.parent / "schemas" / "finalization-report.schema.json"
)


def write_finalization_report(path: Path, report: dict) -> None:
    """Validate the public report contract before replacing the prior report."""
    load_and_validate(report, FINALIZATION_REPORT_SCHEMA, "finalization report")
    atomic_write_text(path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--docx", type=Path, required=True)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--render-dir", type=Path, required=True)
    parser.add_argument("--register", type=Path)
    parser.add_argument("--visual-review-record", type=Path)
    parser.add_argument(
        "--submission-compliance",
        type=Path,
        help="Enable submission-profile rules and AI compliance audit",
    )
    parser.add_argument(
        "--m6-compliance-plan",
        type=Path,
        help="Require the complete M6 technical scope and accepted human decision",
    )
    parser.add_argument(
        "--paper-authority-plan",
        type=Path,
        help="Require an accepted F1 manifest and CURRENT-STATE agreement before finalization",
    )
    parser.add_argument(
        "--quality-gate-plan",
        type=Path,
        help="Enable declaration-driven paper quality gates",
    )
    parser.add_argument("--qa-register", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--page-size", choices=("any", "a4", "letter"), default="any")
    parser.add_argument(
        "--orientation", choices=("any", "portrait", "landscape"), default="any"
    )
    parser.add_argument("--forbid", action="append", default=[])
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    return parser.parse_args()


def run_json(script: Path, arguments: list[str]) -> tuple[dict, list[str]]:
    command = [sys.executable, str(script), *arguments, "--json"]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        payload = {
            "errors": [
                f"{script.name} did not emit valid JSON: {exc}",
                completed.stderr.strip(),
            ]
        }
    payload["exit_code"] = completed.returncode
    return payload, command


def render_manifest(path: Path) -> dict[str, str]:
    if not path.is_dir():
        return {}
    return {
        page.name: sha256_file(page)
        for page in sorted(path.glob("*.png"))
        if page.is_file()
    }


def validate_output_paths(
    case_dir: Path,
    report_path: Path,
    qa_register: Path,
    protected_paths: set[Path],
) -> None:
    paper_dir = (case_dir / "paper").resolve()
    for label, path, filename in (
        ("report", report_path, "finalization-report.json"),
        ("qa register", qa_register, "qa-register.md"),
    ):
        if path.parent != paper_dir or path.name.casefold() != filename.casefold():
            raise ValueError(f"{label} must be {paper_dir / filename}")
        if path in protected_paths:
            raise ValueError(f"{label} conflicts with an input artifact: {path}")
        for protected in protected_paths:
            if path.exists() and protected.exists() and path.samefile(protected):
                raise ValueError(f"{label} aliases an input artifact: {protected}")
        if path.exists() and not path.is_file():
            raise ValueError(f"{label} path is not a file: {path}")
    if report_path == qa_register:
        raise ValueError("report and QA register paths must be different")
    if report_path.exists() and qa_register.exists() and report_path.samefile(qa_register):
        raise ValueError("report and QA register paths alias the same file")


def check_visual_review(
    path: Path | None,
    pdf: Path,
    page_count: int | None,
    rendered_page_hashes: dict[str, str],
) -> dict:
    report = {
        "status": "not_performed",
        "record": str(path.resolve()) if path else None,
        "errors": [],
    }
    if path is None:
        report["errors"].append("visual review record was not supplied")
        return report
    resolved = path.expanduser().resolve()
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        report["status"] = "invalid"
        report["errors"].append(f"cannot read visual review record: {exc}")
        return report

    report["data"] = data
    if not isinstance(data, dict):
        report["status"] = "invalid"
        report["errors"].append("visual review record must be a JSON object")
        return report
    if data.get("schema_version") != 1:
        report["errors"].append("visual review schema_version must be 1")
    if data.get("status") != "passed":
        report["errors"].append("visual review status must be passed")
    for field in (
        "reviewed_at",
        "reviewer",
        "pdf_sha256",
        "page_count",
        "reviewed_pages",
        "rendered_pages_sha256",
    ):
        if field not in data:
            report["errors"].append(f"visual review record is missing {field}")

    if data.get("inspection_scope") in {"contact_sheet_only", "thumbnail_only", "sample_only"}:
        report["errors"].append("Full-page review cannot be established by contact sheets, thumbnails or samples")

    expected_hash = sha256_file(pdf) if pdf.is_file() else None
    report["pdf_sha256"] = expected_hash
    if expected_hash and data.get("pdf_sha256") != expected_hash:
        report["errors"].append("visual review PDF hash does not match the final PDF")
    if page_count is not None and data.get("page_count") != page_count:
        report["errors"].append("visual review page_count does not match the final PDF")
    if page_count is not None and data.get("reviewed_pages") != list(range(1, page_count + 1)):
        report["errors"].append("reviewed_pages must list every final PDF page in order")
    if data.get("rendered_pages_sha256") != rendered_page_hashes:
        report["errors"].append(
            "visual review rendered page hashes do not match the final rendered images"
        )
    if "reviewer" in data and not str(data["reviewer"]).strip():
        report["errors"].append("visual review reviewer must be non-empty")
    if "reviewed_at" in data and not str(data["reviewed_at"]).strip():
        report["errors"].append("visual review reviewed_at must be non-empty")
    elif "reviewed_at" in data:
        try:
            reviewed_at = datetime.fromisoformat(str(data["reviewed_at"]).replace("Z", "+00:00"))
        except ValueError:
            report["errors"].append("visual review reviewed_at must be ISO 8601")
        else:
            if reviewed_at.tzinfo is None:
                report["errors"].append("visual review reviewed_at must include a timezone")
    if "page_count" in data and (
        isinstance(data["page_count"], bool) or not isinstance(data["page_count"], int)
    ):
        report["errors"].append("visual review page_count must be an integer")

    report["status"] = "passed" if not report["errors"] else "invalid"
    return report


def update_qa_register(path: Path, report: dict, report_path: Path) -> None:
    if path.exists():
        content = path.read_text(encoding="utf-8")
    else:
        content = "# Paper QA Register\n"
    if START_MARKER in content and END_MARKER in content:
        before, remainder = content.split(START_MARKER, 1)
        _, after = remainder.split(END_MARKER, 1)
        content = before.rstrip() + "\n\n" + after.lstrip()

    preflight_status = "passed" if report["preflight"].get("ready") else "failed"
    reconcile_status = "passed" if report["reconciliation"].get("reconciled") else "failed"
    definition_status = "passed" if report["model_definition_audit"].get("passed") else "failed"
    audit_status = "passed" if report["paper_audit"].get("structural_ok") else "failed"
    rendered = report["paper_audit"].get("rendered_pages", {})
    render_status = (
        "passed"
        if rendered.get("png_count") == report["paper_audit"].get("pdf", {}).get("pages")
        else "failed"
    )
    visual_status = report["visual_review"]["status"]
    relative_report = report_path
    try:
        relative_report = report_path.relative_to(path.parent)
    except ValueError:
        pass
    compliance = report["submission_compliance"]
    paper_authority = report.get("paper_authority", {"required": False, "passed": True})
    quality_gates = report.get("quality_gates", {"required": False, "passed": True})
    compliance_row = ""
    paper_authority_row = ""
    quality_gate_row = ""
    closeout_row = ""
    if report.get("paper_closeout", {}).get("required"):
        closeout_status = "passed" if report["paper_closeout"].get("passed") else "failed"
        closeout_row = f"| Evaluator-facing closeout evidence | `{relative_report}` | {closeout_status} |\n"
    if paper_authority.get("required"):
        paper_authority_status = "passed" if paper_authority.get("passed") else "failed"
        paper_authority_row = (
            f"| F1-to-M5 paper authority | `{relative_report}` | "
            f"{paper_authority_status} |\n"
        )
    if quality_gates.get("required"):
        quality_gate_status = "passed" if quality_gates.get("passed") else "failed"
        quality_gate_row = (
            f"| Declaration-driven paper quality gates | `{relative_report}` | "
            f"{quality_gate_status} |\n"
        )
    if compliance.get("required"):
        compliance_status = "passed" if compliance.get("passed") else "failed"
        compliance_row = (
            f"| Rules freshness and AI disclosure | `{relative_report}` | "
            f"{compliance_status} |\n"
        )
    submission_status = "passed" if report["ready_for_submission"] else "failed"
    section = (
        f"{START_MARKER}\n"
        "## Automated Finalization\n\n"
        f"Generated: {report['generated_at']}\n\n"
        "| Gate | Evidence | Status |\n"
        "| --- | --- | --- |\n"
        f"| Environment preflight | `{relative_report}` | {preflight_status} |\n"
        f"| Headline values reconciled | `{relative_report}` | {reconcile_status} |\n"
        f"| Model-definition risks closed | `{relative_report}` | {definition_status} |\n"
        f"| DOCX/PDF structural audit | `{relative_report}` | {audit_status} |\n"
        f"| Rendered page count | `{relative_report}` | {render_status} |\n"
        f"| Every final page inspected | `{report['visual_review'].get('record') or 'not supplied'}` | {visual_status} |\n"
        f"{paper_authority_row}"
        f"{quality_gate_row}"
        f"{closeout_row}"
        f"{compliance_row}"
        f"| Submission gate | `{relative_report}` | {submission_status} |\n"
        f"{END_MARKER}\n"
    )
    atomic_write_text(path, content.rstrip() + "\n\n" + section)


def run_finalization(args: argparse.Namespace) -> tuple[dict, Path, Path]:
    script_dir = Path(__file__).resolve().parent
    case_dir = args.case_dir.expanduser().resolve()
    docx = args.docx.expanduser().resolve()
    pdf = args.pdf.expanduser().resolve()
    render_dir = args.render_dir.expanduser().resolve()
    qa_register = (
        args.qa_register.expanduser().resolve()
        if args.qa_register
        else case_dir / "paper" / "qa-register.md"
    )
    report_path = (
        args.report.expanduser().resolve()
        if args.report
        else case_dir / "paper" / "finalization-report.json"
    )
    register_path = (
        args.register.expanduser().resolve()
        if args.register
        else (case_dir / "results" / "result-register.json").resolve()
    )
    default_visual_record = (case_dir / "paper" / "visual-review.json").resolve()
    visual_record = (
        args.visual_review_record.expanduser().resolve()
        if args.visual_review_record
        else default_visual_record if default_visual_record.is_file() else None
    )
    paper_authority_plan = None
    paper_authority_plan_arg = getattr(args, "paper_authority_plan", None)
    if paper_authority_plan_arg:
        paper_authority_plan = paper_authority_plan_arg.expanduser().resolve()
        try:
            paper_authority_plan.relative_to(case_dir)
        except ValueError as exc:
            raise ValueError("paper authority plan escapes the case directory") from exc
        if paper_authority_plan.suffix.casefold() != ".json":
            raise ValueError("paper authority plan must end in .json")
    quality_gate_plan = None
    quality_gate_plan_arg = getattr(args, "quality_gate_plan", None)
    if quality_gate_plan_arg:
        quality_gate_plan = quality_gate_plan_arg.expanduser().resolve()
        try:
            quality_gate_plan.relative_to(case_dir)
        except ValueError as exc:
            raise ValueError("quality gate plan escapes the case directory") from exc
        if quality_gate_plan.suffix.casefold() != ".json":
            raise ValueError("quality gate plan must end in .json")
    m6_compliance_plan = None
    m6_plan_arg = getattr(args, "m6_compliance_plan", None)
    if m6_plan_arg:
        m6_compliance_plan = m6_plan_arg.expanduser().resolve()
        try:
            m6_compliance_plan.relative_to(case_dir)
        except ValueError as exc:
            raise ValueError("M6 compliance plan escapes the case directory") from exc
        if m6_compliance_plan.suffix.casefold() != ".json":
            raise ValueError("M6 compliance plan must end in .json")
    compliance_path = None
    if args.submission_compliance:
        compliance_path = args.submission_compliance.expanduser().resolve()
        try:
            compliance_path.relative_to(case_dir)
        except ValueError as exc:
            raise ValueError(
                "submission compliance escapes the case directory"
            ) from exc
        if compliance_path.suffix.casefold() != ".json":
            raise ValueError("submission compliance must end in .json")
    rendered_pages = {page.resolve() for page in render_dir.glob("*.png") if page.is_file()}
    protected_paths = {docx, pdf, register_path, *rendered_pages}
    if visual_record is not None:
        protected_paths.add(visual_record)
    if compliance_path is not None:
        protected_paths.add(compliance_path)
    if m6_compliance_plan is not None:
        protected_paths.add(m6_compliance_plan)
    if paper_authority_plan is not None:
        protected_paths.add(paper_authority_plan)
    if quality_gate_plan is not None:
        protected_paths.add(quality_gate_plan)
    validate_output_paths(
        case_dir,
        report_path,
        qa_register,
        protected_paths,
    )
    artifact_hashes_before = {
        "docx": sha256_file(docx) if docx.is_file() else None,
        "pdf": sha256_file(pdf) if pdf.is_file() else None,
        "rendered_pages": render_manifest(render_dir),
    }

    preflight_args = [
        "--project-root",
        str(case_dir),
        "--output-dir",
        str(case_dir / "paper"),
        "--module",
        "pypdf",
    ]
    preflight, preflight_command = run_json(script_dir / "preflight.py", preflight_args)

    reconciliation_args = [
        "--case-dir",
        str(case_dir),
        "--docx",
        str(docx),
        "--pdf",
        str(pdf),
    ]
    if args.register:
        reconciliation_args.extend(["--register", str(register_path)])
    reconciliation, reconciliation_command = run_json(
        script_dir / "reconcile_results.py", reconciliation_args
    )

    definition_audit, definition_audit_command = run_json(
        script_dir / "audit_model_definitions.py",
        [
            "--case-dir", str(case_dir),
            "--docx", str(docx),
            "--pdf", str(pdf),
        ],
    )

    if paper_authority_plan is None:
        paper_authority = {
            "required": False,
            "passed": True,
            "paper_authoritative": None,
            "errors": [],
        }
        paper_authority_command = None
    else:
        paper_authority, paper_authority_command = run_json(
            script_dir / "audit_paper_authority.py",
            [
                "--case-dir", str(case_dir),
                "--plan", str(paper_authority_plan),
                "--docx", str(docx),
                "--pdf", str(pdf),
            ],
        )
        paper_authority["required"] = True

    audit_args = [
        "--docx",
        str(docx),
        "--pdf",
        str(pdf),
        "--render-dir",
        str(render_dir),
        "--page-size",
        args.page_size,
        "--orientation",
        args.orientation,
    ]
    for value in args.forbid:
        audit_args.extend(["--forbid", value])
    paper_audit, audit_command = run_json(script_dir / "audit_paper.py", audit_args)

    visual_review = check_visual_review(
        visual_record,
        pdf,
        paper_audit.get("pdf", {}).get("pages"),
        render_manifest(render_dir),
    )
    if quality_gate_plan is None:
        quality_gates = {
            "required": False,
            "passed": True,
            "errors": [],
        }
        quality_gates_command = None
    else:
        quality_gates, quality_gates_command = run_json(
            script_dir / "audit_paper_quality_gates.py",
            ["--case-dir", str(case_dir), "--plan", str(quality_gate_plan)],
        )
        quality_gates["required"] = True
    if m6_compliance_plan is not None:
        submission_compliance, compliance_command = run_json(
            script_dir / "audit_m6_compliance.py",
            [
                "audit", "--case-dir", str(case_dir),
                "--plan", str(m6_compliance_plan),
                "--docx", str(docx),
                "--pdf", str(pdf),
            ],
        )
        submission_compliance["required"] = True
    elif compliance_path is None:
        submission_compliance = {
            "required": False,
            "passed": True,
            "scope": "not_run_or_not_required",
            "full_m6_proven": False,
            "errors": [],
        }
        compliance_command = None
    else:
        submission_compliance, compliance_command = run_json(
            script_dir / "audit_submission_compliance.py",
            [
                "--case-dir", str(case_dir),
                "--compliance", str(compliance_path),
                "--docx", str(docx),
                "--pdf", str(pdf),
            ],
        )
        submission_compliance["required"] = True
        submission_compliance["scope"] = "rules_and_ai_technical_only"
        submission_compliance["full_m6_proven"] = False
    if submission_compliance.get("required"):
        evidence_errors = verify_evidence_hashes(
            submission_compliance.get("evidence_sha256")
        )
        if evidence_errors:
            submission_compliance["passed"] = False
            submission_compliance.setdefault("errors", []).extend(evidence_errors)
    closeout_path = case_dir / "paper" / "closeout-review.json"
    try:
        metadata_path = case_dir / "case.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig")) if metadata_path.exists() else {}
        closeout = (audit_closeout(case_dir, closeout_path, docx, pdf)
                    if closeout_path.exists() or metadata.get("paper_closeout_required") else
                    {"required": False, "passed": True, "scope": "not_run_or_not_required", "errors": []})
    except (OSError, ValueError, AttributeError) as exc:
        closeout = {"required": True, "passed": False, "errors": [str(exc)]}
    ready = bool(
        preflight.get("ready")
        and reconciliation.get("reconciled")
        and definition_audit.get("passed")
        and paper_authority.get("passed")
        and paper_authority.get("paper_authoritative") is not False
        and paper_audit.get("structural_ok")
        and visual_review["status"] == "passed"
        and quality_gates.get("passed")
        and submission_compliance.get("passed")
        and closeout.get("passed")
    )
    errors = []
    for name, child in (
        ("preflight", preflight),
        ("reconciliation", reconciliation),
        ("model-definition audit", definition_audit),
        ("paper authority", paper_authority),
        ("paper audit", paper_audit),
        ("visual review", visual_review),
        ("paper quality gates", quality_gates),
        ("submission compliance", submission_compliance),
        ("paper closeout", closeout),
    ):
        errors.extend(f"{name}: {error}" for error in child.get("errors", []) if error)
    report = {
        "schema_version": 1,
        "paper_closeout": closeout,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ready_for_submission": ready,
        "gate_scopes": {
            "paper_quality": "declaration-driven structural audit",
            "visual_review": "finalization-only gate; not duplicated in paper-quality audit",
            "submission_compliance": submission_compliance.get("scope", "legacy_or_not_run"),
        },
        "case_dir": str(case_dir),
        "artifacts": {
            "docx": str(docx),
            "pdf": str(pdf),
            "render_dir": str(render_dir),
            "qa_register": str(qa_register),
            "report": str(report_path),
        },
        "artifact_hashes": {
            "before": artifact_hashes_before,
            "after": None,
        },
        "commands": {
            "preflight": preflight_command,
            "reconciliation": reconciliation_command,
            "model_definition_audit": definition_audit_command,
            "paper_authority": paper_authority_command,
            "paper_audit": audit_command,
            "quality_gates": quality_gates_command,
            "submission_compliance": compliance_command,
        },
        "preflight": preflight,
        "reconciliation": reconciliation,
        "model_definition_audit": definition_audit,
        "paper_authority": paper_authority,
        "paper_audit": paper_audit,
        "visual_review": visual_review,
        "quality_gates": quality_gates,
        "submission_compliance": submission_compliance,
        "errors": errors,
    }
    enrich_legacy_report(
        report,
        stage="finalize",
        error_code="finalization_gate_failed",
    )
    artifact_hashes_after = {
        "docx": sha256_file(docx) if docx.is_file() else None,
        "pdf": sha256_file(pdf) if pdf.is_file() else None,
        "rendered_pages": render_manifest(render_dir),
    }
    report["artifact_hashes"]["after"] = artifact_hashes_after
    if artifact_hashes_after != artifact_hashes_before:
        report["ready_for_submission"] = False
        report["errors"].append(
            "final DOCX, PDF, or rendered page changed during finalization"
        )
        enrich_legacy_report(
            report, stage="finalize", error_code="artifact_changed_during_finalization"
        )
    write_finalization_report(report_path, report)
    update_qa_register(qa_register, report, report_path)
    evidence_errors = (
        verify_evidence_hashes(submission_compliance.get("evidence_sha256"))
        if submission_compliance.get("required")
        else []
    )
    if evidence_errors:
        report["ready_for_submission"] = False
        report["errors"].extend(
            f"submission compliance: {error}" for error in evidence_errors
        )
        enrich_legacy_report(
            report, stage="finalize", error_code="compliance_evidence_changed"
        )
        write_finalization_report(report_path, report)
        update_qa_register(qa_register, report, report_path)
    artifact_hashes_final = {
        "docx": sha256_file(docx) if docx.is_file() else None,
        "pdf": sha256_file(pdf) if pdf.is_file() else None,
        "rendered_pages": render_manifest(render_dir),
    }
    if artifact_hashes_final != artifact_hashes_after:
        report["ready_for_submission"] = False
        report["artifact_hashes"]["after"] = artifact_hashes_final
        report["errors"].append(
            "final DOCX, PDF, or rendered page changed while reports were written"
        )
        enrich_legacy_report(
            report, stage="finalize", error_code="artifact_changed_during_report_write"
        )
        write_finalization_report(report_path, report)
        update_qa_register(qa_register, report, report_path)
    # Report/QA writes can invalidate bound review evidence. Never leave a PASS
    # based on the pre-write version (or silently accept a replacement review).
    if closeout.get("required") and closeout.get("passed"):
        refreshed = audit_closeout(case_dir, closeout_path, docx, pdf)
        if (not refreshed.get("passed")
                or refreshed.get("review_sha256") != closeout.get("review_sha256")):
            refreshed["passed"] = False
            refreshed.setdefault("errors", []).append(
                "Closeout review or its evidence changed while finalization reports were written"
            )
            report["paper_closeout"] = refreshed
            report["ready_for_submission"] = False
            report["errors"].extend(
                f"paper closeout: {error}" for error in refreshed["errors"]
            )
            enrich_legacy_report(
                report, stage="finalize", error_code="closeout_evidence_changed"
            )
            write_finalization_report(report_path, report)
            update_qa_register(qa_register, report, report_path)
    return report, report_path, qa_register


def print_human(report: dict, report_path: Path, qa_register: Path) -> None:
    print(f"ready_for_submission={str(report['ready_for_submission']).lower()}")
    print(f"preflight={'passed' if report['preflight'].get('ready') else 'failed'}")
    print(
        "reconciliation="
        f"{'passed' if report['reconciliation'].get('reconciled') else 'failed'}"
    )
    print(
        "structural_audit="
        f"{'passed' if report['paper_audit'].get('structural_ok') else 'failed'}"
    )
    print(f"visual_review={report['visual_review']['status']}")
    if report.get("paper_authority", {}).get("required"):
        print(
            "paper_authority="
            f"{'passed' if report['paper_authority'].get('passed') else 'failed'}"
        )
    if report.get("quality_gates", {}).get("required"):
        print(
            "quality_gates="
            f"{'passed' if report['quality_gates'].get('passed') else 'failed'}"
        )
    if report["submission_compliance"].get("required"):
        print(
            "submission_compliance="
            f"{'passed' if report['submission_compliance'].get('passed') else 'failed'}"
        )
    print(f"report={report_path}")
    print(f"qa_register={qa_register}")
    for error in report["errors"]:
        print(f"error: {error}")


def main() -> int:
    args = parse_args()
    try:
        report, report_path, qa_register = run_finalization(args)
    except (OSError, ValueError) as exc:
        failure = {"ready_for_submission": False, "errors": [str(exc)]}
        enrich_legacy_report(
            failure, stage="finalize", error_code="finalization_setup_invalid"
        )
        if args.json:
            json.dump(failure, sys.stdout, ensure_ascii=False, indent=2)
            print()
        else:
            print("ready_for_submission=false")
            print(f"error: {exc}")
        return 2
    if args.json:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        print_human(report, report_path, qa_register)
    return 0 if report["ready_for_submission"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

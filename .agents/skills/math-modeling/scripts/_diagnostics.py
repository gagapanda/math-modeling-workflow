"""Shared machine-readable diagnostics for modeling workflow CLIs."""

from __future__ import annotations

import re
from collections.abc import Iterable


DIAGNOSTICS_SCHEMA_VERSION = 1
POINTER_IN_MESSAGE = re.compile(r"(?:at|schema at) (/[^: ]*)")


def diagnostic(
    severity: str,
    code: str,
    stage: str,
    message: str,
    *,
    remediation: Iterable[str] = (),
    retry_command: str | None = None,
    json_pointer: str | None = None,
) -> dict:
    """Build one stable diagnostic entry."""
    entry = {
        "severity": severity,
        "code": code,
        "stage": stage,
        "message": message,
        "remediation": [item for item in remediation if item],
    }
    if retry_command:
        entry["retry_command"] = retry_command
    if json_pointer:
        entry["json_pointer"] = json_pointer
    return entry


def pointer_from_message(message: str) -> str | None:
    match = POINTER_IN_MESSAGE.search(message)
    return match.group(1) if match else None


def attach_diagnostics(report: dict, entries: Iterable[dict]) -> dict:
    """Attach a diagnostics envelope and severity counts to a report."""
    diagnostics = list(entries)
    counts = {severity: 0 for severity in ("error", "warning", "info")}
    for entry in diagnostics:
        counts[entry["severity"]] += 1
    report["diagnostics_schema_version"] = DIAGNOSTICS_SCHEMA_VERSION
    report["diagnostics"] = diagnostics
    report["diagnostic_summary"] = counts
    return report


def enrich_legacy_report(
    report: dict,
    *,
    stage: str,
    error_code: str,
    warning_code: str = "advisory",
) -> dict:
    """Add diagnostics without changing established errors/warnings fields."""
    failure = report.get("failure") if isinstance(report.get("failure"), dict) else {}
    failure_stage = failure.get("failed_stage", stage)
    failure_code = failure.get("cause_code", error_code)
    remediation = failure.get("remediation", [])
    if not isinstance(remediation, list):
        remediation = [str(remediation)]
    retry_command = failure.get("resume_command")
    entries = [
        diagnostic(
            "error",
            failure_code,
            failure_stage,
            str(message),
            remediation=remediation,
            retry_command=retry_command,
            json_pointer=pointer_from_message(str(message)),
        )
        for message in report.get("errors", [])
        if message
    ]
    entries.extend(
        diagnostic("warning", warning_code, stage, str(message))
        for message in report.get("warnings", [])
        if message
    )
    return attach_diagnostics(report, entries)

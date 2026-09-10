#!/usr/bin/env python
"""Create, append to, and close hash-bound timed-rehearsal records."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from _json_schema import load_and_validate
from _workflow_common import atomic_write_json, resolve_inside, resolve_path_inside, sha256_file


SKILL_DIR = Path(__file__).resolve().parent.parent
PLAN_SCHEMA = SKILL_DIR / "schemas" / "timed-rehearsal-plan.schema.json"
LOG_SCHEMA = SKILL_DIR / "schemas" / "timed-rehearsal-log.schema.json"
REVIEW_SCHEMA = SKILL_DIR / "schemas" / "timed-rehearsal-review.schema.json"
PHASE_IDS = (
    "problem-selection",
    "baseline",
    "primary-model",
    "synchronized-writing",
    "independent-review",
    "packaging",
)
EVENT_TYPES = (
    "milestone",
    "failure",
    "rework",
    "decision",
    "fault-injection",
    "recovery",
)
SCORECARD_IDS = (
    "rule-anonymity-risk",
    "unanswered-subproblems",
    "unproven-headline-values",
    "leakage-unit-definition-constraint",
    "unjustified-complex-model",
    "clean-input-rerun",
    "paper-result-support-consistency",
    "late-change-rework",
    "pdf-packaging",
)
RECORD_SCOPE = "Record closure does not validate the model, paper, or submission package."
MAX_LATE_EVENT = timedelta(days=7)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create an empty log bound to a plan")
    add_common_paths(init_parser)
    add_json_option(init_parser)

    record_parser = subparsers.add_parser("record", help="Append one verified event")
    add_common_paths(record_parser)
    add_json_option(record_parser)
    record_parser.add_argument("--occurred-at", required=True)
    record_parser.add_argument("--phase", choices=PHASE_IDS, required=True)
    record_parser.add_argument("--type", choices=EVENT_TYPES, required=True)
    record_parser.add_argument("--summary", required=True)
    record_parser.add_argument("--category")
    record_parser.add_argument("--fault-id")
    record_parser.add_argument("--related-event", type=int)
    record_parser.add_argument("--evidence", action="append", required=True)

    close_parser = subparsers.add_parser("close", help="Validate and close a rehearsal record")
    add_common_paths(close_parser)
    add_json_option(close_parser)
    close_parser.add_argument("--review-input", type=Path, required=True)
    close_parser.add_argument("--output", type=Path, required=True)
    close_parser.add_argument("--replace", action="store_true")

    parser.add_argument("--json", action="store_true", help="Emit JSON")
    return parser.parse_args()


def add_common_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)


def add_json_option(parser: argparse.ArgumentParser) -> None:
    """Accept the output-format switch before or after the subcommand."""
    parser.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Emit JSON",
    )

def load_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def parse_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty ISO 8601 timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone offset")
    return parsed


def load_plan(case_dir: Path, plan_path: Path) -> tuple[Path, dict]:
    resolved = resolve_path_inside(case_dir, plan_path, "rehearsal plan")
    if not resolved.is_file():
        raise ValueError(f"rehearsal plan is missing: {resolved}")
    plan = load_json(resolved, "rehearsal plan")
    load_and_validate(plan, PLAN_SCHEMA, "timed rehearsal plan")
    validate_plan_semantics(plan)
    return resolved, plan


def validate_plan_semantics(plan: dict) -> None:
    started = parse_timestamp(plan["started_at"], "started_at")
    deadline = parse_timestamp(plan["deadline_at"], "deadline_at")
    if deadline <= started:
        raise ValueError("deadline_at must be later than started_at")

    member_ids = [entry["member_id"].casefold() for entry in plan["team"]]
    if len(member_ids) != len(set(member_ids)):
        raise ValueError("team member_id values must be case-insensitively unique")
    phase_ids = [entry["id"] for entry in plan["phases"]]
    if len(phase_ids) != len(set(phase_ids)) or set(phase_ids) != set(PHASE_IDS):
        raise ValueError("phases must contain each required competition phase exactly once")
    fault_ids = [entry["id"].casefold() for entry in plan["fault_injections"]]
    if len(fault_ids) != len(set(fault_ids)):
        raise ValueError("fault injection IDs must be case-insensitively unique")
    if plan["mode"] == "full-simulation" and len(fault_ids) < 2:
        raise ValueError("full-simulation plans require at least two fault injections")
    for index, fault in enumerate(plan["fault_injections"]):
        planned = parse_timestamp(fault["planned_at"], f"fault_injections[{index}].planned_at")
        if not started <= planned <= deadline:
            raise ValueError(f"fault injection {fault['id']} falls outside the rehearsal window")


def event_digest(event: dict) -> str:
    unsigned = {key: value for key, value in event.items() if key != "event_sha256"}
    encoded = json.dumps(
        unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_event_semantics(case_dir: Path, plan: dict, events: list[dict]) -> None:
    started = parse_timestamp(plan["started_at"], "started_at")
    deadline = parse_timestamp(plan["deadline_at"], "deadline_at")
    phase_ids = {entry["id"] for entry in plan["phases"]}
    fault_ids = {entry["id"].casefold(): entry["id"] for entry in plan["fault_injections"]}
    seen_faults: set[str] = set()
    previous_time: datetime | None = None
    previous_hash: str | None = None

    for index, event in enumerate(events):
        sequence = index + 1
        if event["sequence"] != sequence:
            raise ValueError(f"event sequences must be continuous; expected {sequence}")
        occurred = parse_timestamp(event["occurred_at"], f"event {sequence} occurred_at")
        if occurred < started or occurred > deadline + MAX_LATE_EVENT:
            raise ValueError(f"event {sequence} falls outside the allowed rehearsal window")
        if previous_time is not None and occurred < previous_time:
            raise ValueError(f"event {sequence} timestamp precedes the prior event")
        if event["phase"] not in phase_ids:
            raise ValueError(f"event {sequence} uses a phase absent from the plan")
        if event["previous_event_sha256"] != previous_hash:
            raise ValueError(f"event {sequence} has an invalid previous-event hash")
        if event_digest(event) != event["event_sha256"]:
            raise ValueError(f"event {sequence} hash does not match its content")

        for evidence_index, evidence in enumerate(event["evidence"]):
            path = resolve_inside(
                case_dir, evidence["path"], f"event {sequence} evidence {evidence_index}"
            )
            if not path.is_file():
                raise ValueError(f"event {sequence} evidence is missing: {path}")
            if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
                raise ValueError(f"event {sequence} evidence must not be a link: {path}")
            if sha256_file(path) != evidence["sha256"]:
                raise ValueError(f"event {sequence} evidence changed after recording: {path}")

        related = event["related_event"]
        if related is not None and not 1 <= related < sequence:
            raise ValueError(f"event {sequence} must reference an earlier event")
        if event["type"] == "rework":
            if related is None or events[related - 1]["type"] not in {"failure", "decision", "milestone"}:
                raise ValueError(f"rework event {sequence} must reference its earlier trigger")
            if not event["category"]:
                raise ValueError(f"rework event {sequence} requires a root-cause category")
        if event["type"] == "recovery":
            if related is None or events[related - 1]["type"] not in {"failure", "fault-injection"}:
                raise ValueError(f"recovery event {sequence} must reference a failure or fault injection")
        if event["type"] == "failure" and not event["category"]:
            raise ValueError(f"failure event {sequence} requires a category")
        if event["type"] == "fault-injection":
            if not event["fault_id"] or event["fault_id"].casefold() not in fault_ids:
                raise ValueError(f"fault-injection event {sequence} must name a planned fault")
            folded = event["fault_id"].casefold()
            if folded in seen_faults:
                raise ValueError(f"planned fault {event['fault_id']} was injected more than once")
            seen_faults.add(folded)
        elif event["fault_id"] is not None and event["fault_id"].casefold() not in fault_ids:
            raise ValueError(f"event {sequence} names an unknown planned fault")

        previous_time = occurred
        previous_hash = event["event_sha256"]


def load_log(case_dir: Path, log_path: Path, plan_path: Path, plan: dict) -> tuple[Path, dict]:
    resolved = resolve_path_inside(case_dir, log_path, "rehearsal log")
    if not resolved.is_file():
        raise ValueError(f"rehearsal log is missing: {resolved}")
    log = load_json(resolved, "rehearsal log")
    load_and_validate(log, LOG_SCHEMA, "timed rehearsal log")
    if log["rehearsal_id"] != plan["rehearsal_id"]:
        raise ValueError("log rehearsal_id differs from the plan")
    if log["plan_sha256"] != sha256_file(plan_path):
        raise ValueError("rehearsal plan changed after the log was initialized")
    validate_event_semantics(case_dir, plan, log["events"])
    return resolved, log


def initialize_log(case_dir: Path, plan_path: Path, log_path: Path) -> dict:
    case_dir = case_dir.expanduser().resolve()
    resolved_plan, plan = load_plan(case_dir, plan_path)
    resolved_log = resolve_path_inside(case_dir, log_path, "rehearsal log")
    if resolved_log.exists():
        raise ValueError(f"refusing to overwrite existing rehearsal log: {resolved_log}")
    payload = {
        "schema_version": 1,
        "rehearsal_id": plan["rehearsal_id"],
        "plan_sha256": sha256_file(resolved_plan),
        "events": [],
    }
    load_and_validate(payload, LOG_SCHEMA, "timed rehearsal log")
    atomic_write_json(resolved_log, payload)
    return payload


def build_evidence(case_dir: Path, values: list[str]) -> list[dict]:
    evidence = []
    seen: set[str] = set()
    for index, value in enumerate(values):
        path = resolve_inside(case_dir, value, f"evidence {index}")
        if not path.is_file():
            raise ValueError(f"evidence is missing: {path}")
        normalized = path.relative_to(case_dir).as_posix()
        if normalized.casefold() in seen:
            raise ValueError(f"duplicate evidence path: {normalized}")
        seen.add(normalized.casefold())
        evidence.append({"path": normalized, "sha256": sha256_file(path)})
    return evidence


def append_event(
    case_dir: Path,
    plan_path: Path,
    log_path: Path,
    *,
    occurred_at: str,
    phase: str,
    event_type: str,
    summary: str,
    evidence_paths: list[str],
    category: str | None = None,
    fault_id: str | None = None,
    related_event: int | None = None,
) -> dict:
    case_dir = case_dir.expanduser().resolve()
    resolved_plan, plan = load_plan(case_dir, plan_path)
    resolved_log, log = load_log(case_dir, log_path, resolved_plan, plan)
    previous = log["events"][-1]["event_sha256"] if log["events"] else None
    event = {
        "sequence": len(log["events"]) + 1,
        "occurred_at": occurred_at,
        "phase": phase,
        "type": event_type,
        "summary": summary.strip(),
        "category": category.strip() if category else None,
        "fault_id": fault_id.strip() if fault_id else None,
        "related_event": related_event,
        "evidence": build_evidence(case_dir, evidence_paths),
        "previous_event_sha256": previous,
        "event_sha256": "",
    }
    event["event_sha256"] = event_digest(event)
    candidate = {**log, "events": [*log["events"], event]}
    load_and_validate(candidate, LOG_SCHEMA, "timed rehearsal log")
    validate_event_semantics(case_dir, plan, candidate["events"])
    atomic_write_json(resolved_log, candidate)
    return event


def require_exact_ids(entries: list[dict], key: str, expected: tuple[str, ...], label: str) -> None:
    values = [entry.get(key) for entry in entries]
    if len(values) != len(set(values)) or set(values) != set(expected):
        raise ValueError(f"{label} must contain each required ID exactly once")


def validate_review_input(review: dict, plan: dict, events: list[dict]) -> None:
    required = {
        "closed_at", "actual_minutes", "result_assessment", "scorecard",
        "improvements", "no_durable_change", "unresolved_blockers", "closure_notes",
    }
    if set(review) != required:
        missing = sorted(required - set(review))
        extra = sorted(set(review) - required)
        raise ValueError(f"review input fields differ; missing={missing}, extra={extra}")
    closed = parse_timestamp(review["closed_at"], "closed_at")
    started = parse_timestamp(plan["started_at"], "started_at")
    if closed < started or closed > parse_timestamp(plan["deadline_at"], "deadline_at") + MAX_LATE_EVENT:
        raise ValueError("closed_at falls outside the allowed rehearsal window")
    if events and closed < parse_timestamp(events[-1]["occurred_at"], "last event occurred_at"):
        raise ValueError("closed_at precedes the last event")
    actual = review["actual_minutes"]
    if not isinstance(actual, dict) or set(actual) != set(PHASE_IDS):
        raise ValueError("actual_minutes must contain each required phase exactly once")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in actual.values()):
        raise ValueError("actual_minutes values must be nonnegative integers")
    if review["result_assessment"] not in {"not-assessed", "incomplete", "complete-unverified", "verified"}:
        raise ValueError("result_assessment is invalid")
    if not isinstance(review["closure_notes"], str) or not review["closure_notes"].strip():
        raise ValueError("closure_notes must be non-empty")
    if not isinstance(review["unresolved_blockers"], list) or not all(
        isinstance(item, str) and item.strip() for item in review["unresolved_blockers"]
    ):
        raise ValueError("unresolved_blockers must contain non-empty strings")

    if not isinstance(review["scorecard"], list):
        raise ValueError("scorecard must be an array")
    require_exact_ids(review["scorecard"], "id", SCORECARD_IDS, "scorecard")
    sequences = {event["sequence"] for event in events}
    for entry in review["scorecard"]:
        if entry.get("status") not in {"pass", "fail", "not-applicable"}:
            raise ValueError(f"scorecard {entry.get('id')} has an invalid status")
        refs = entry.get("event_sequences")
        if not isinstance(refs, list) or not refs or len(refs) != len(set(refs)) or not set(refs) <= sequences:
            raise ValueError(f"scorecard {entry.get('id')} must reference existing events")
        if not isinstance(entry.get("notes"), str) or not entry["notes"].strip():
            raise ValueError(f"scorecard {entry.get('id')} requires notes")

    if not isinstance(review["improvements"], list):
        raise ValueError("improvements must be an array")
    improvement_ids = [entry.get("id") for entry in review["improvements"]]
    if len(improvement_ids) != len(set(improvement_ids)):
        raise ValueError("improvement IDs must be unique")
    covered: set[int] = set()
    for entry in review["improvements"]:
        refs = entry.get("source_event_sequences")
        if not isinstance(refs, list) or not refs or len(refs) != len(set(refs)) or not set(refs) <= sequences:
            raise ValueError(f"improvement {entry.get('id')} must reference existing events")
        covered.update(refs)
        for field in ("id", "statement", "owner", "acceptance_criterion", "rationale"):
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                raise ValueError(f"improvement {entry.get('id')} requires {field}")
        decision = entry.get("decision")
        if decision == "adopt" and (entry.get("destination") == "none" or entry.get("priority") == "reject"):
            raise ValueError(f"adopted improvement {entry['id']} needs a real destination and priority")
        if decision in {"adopt", "defer"} and entry.get("status") == "open" and not entry.get("due_date"):
            raise ValueError(f"open improvement {entry['id']} requires a due_date")
        if decision == "reject" and (entry.get("destination") != "none" or entry.get("priority") != "reject"):
            raise ValueError(f"rejected improvement {entry['id']} must use destination none and priority reject")

    if not isinstance(review["no_durable_change"], list):
        raise ValueError("no_durable_change must be an array")
    no_change_sequences: set[int] = set()
    for entry in review["no_durable_change"]:
        sequence = entry.get("event_sequence") if isinstance(entry, dict) else None
        if sequence not in sequences or sequence in no_change_sequences:
            raise ValueError("no_durable_change entries must uniquely reference existing events")
        if not isinstance(entry.get("rationale"), str) or not entry["rationale"].strip():
            raise ValueError(f"no_durable_change event {sequence} requires a rationale")
        no_change_sequences.add(sequence)
    actionable = {event["sequence"] for event in events if event["type"] in {"failure", "rework"}}
    missing_coverage = sorted(actionable - covered - no_change_sequences)
    if missing_coverage:
        raise ValueError(f"failure/rework events lack an improvement decision: {missing_coverage}")


def build_fault_summary(plan: dict, events: list[dict]) -> list[dict]:
    by_sequence = {event["sequence"]: event for event in events}
    summaries = []
    for planned in plan["fault_injections"]:
        injections = [
            event for event in events
            if event["type"] == "fault-injection" and event["fault_id"].casefold() == planned["id"].casefold()
        ]
        if len(injections) != 1:
            raise ValueError(f"planned fault {planned['id']} must have exactly one injection event")
        injection = injections[0]
        recoveries = []
        for event in events:
            if event["type"] != "recovery":
                continue
            related = by_sequence[event["related_event"]]
            related_fault = related.get("fault_id")
            if event.get("fault_id") and event["fault_id"].casefold() == planned["id"].casefold():
                recoveries.append(event)
            elif related["sequence"] == injection["sequence"]:
                recoveries.append(event)
            elif related_fault and related_fault.casefold() == planned["id"].casefold():
                recoveries.append(event)
        if len(recoveries) != 1:
            raise ValueError(f"planned fault {planned['id']} must have exactly one recovery event")
        recovery = recoveries[0]
        minutes = int(
            (parse_timestamp(recovery["occurred_at"], "recovery occurred_at") -
             parse_timestamp(injection["occurred_at"], "injection occurred_at")).total_seconds() // 60
        )
        summaries.append({
            "id": planned["id"],
            "injection_event": injection["sequence"],
            "recovery_event": recovery["sequence"],
            "recovery_minutes": minutes,
        })
    return summaries


def close_rehearsal(
    case_dir: Path,
    plan_path: Path,
    log_path: Path,
    review_input_path: Path,
    output_path: Path,
    *,
    replace: bool = False,
) -> dict:
    case_dir = case_dir.expanduser().resolve()
    resolved_plan, plan = load_plan(case_dir, plan_path)
    resolved_log, log = load_log(case_dir, log_path, resolved_plan, plan)
    input_path = resolve_path_inside(case_dir, review_input_path, "review input")
    output = resolve_path_inside(case_dir, output_path, "rehearsal review output")
    if input_path == output:
        raise ValueError("review input and output must be different files")
    if output.exists() and not replace:
        raise ValueError(f"refusing to overwrite existing rehearsal review: {output}")
    review_input = load_json(input_path, "review input")
    validate_review_input(review_input, plan, log["events"])

    counts = Counter(event["type"] for event in log["events"])
    phase_summary = []
    planned_by_id = {entry["id"]: entry["planned_minutes"] for entry in plan["phases"]}
    for phase_id in PHASE_IDS:
        count = sum(event["phase"] == phase_id for event in log["events"])
        if count == 0:
            raise ValueError(f"required phase has no recorded event: {phase_id}")
        phase_summary.append({
            "id": phase_id,
            "planned_minutes": planned_by_id[phase_id],
            "actual_minutes": review_input["actual_minutes"][phase_id],
            "event_count": count,
        })
    fault_summary = build_fault_summary(plan, log["events"])
    started = parse_timestamp(plan["started_at"], "started_at")
    deadline = parse_timestamp(plan["deadline_at"], "deadline_at")
    closed = parse_timestamp(review_input["closed_at"], "closed_at")
    elapsed_minutes = int((closed - started).total_seconds() // 60)
    result = {
        "schema_version": 1,
        "rehearsal_id": plan["rehearsal_id"],
        "plan_sha256": sha256_file(resolved_plan),
        "log_sha256": sha256_file(resolved_log),
        "closed_at": review_input["closed_at"],
        "record_complete": True,
        "record_scope": RECORD_SCOPE,
        "deadline_met": closed <= deadline,
        "elapsed_minutes": elapsed_minutes,
        "result_assessment": review_input["result_assessment"],
        "phase_summary": phase_summary,
        "fault_summary": fault_summary,
        "event_counts": {event_type: counts[event_type] for event_type in EVENT_TYPES},
        "scorecard": review_input["scorecard"],
        "improvements": review_input["improvements"],
        "no_durable_change": review_input["no_durable_change"],
        "unresolved_blockers": review_input["unresolved_blockers"],
        "closure_notes": review_input["closure_notes"].strip(),
    }
    load_and_validate(result, REVIEW_SCHEMA, "timed rehearsal review")
    atomic_write_json(output, result)
    return result


def main() -> int:
    args = parse_args()
    try:
        if args.command == "init":
            result = initialize_log(args.case_dir, args.plan, args.log)
        elif args.command == "record":
            result = append_event(
                args.case_dir, args.plan, args.log, occurred_at=args.occurred_at,
                phase=args.phase, event_type=args.type, summary=args.summary,
                evidence_paths=args.evidence, category=args.category, fault_id=args.fault_id,
                related_event=args.related_event,
            )
        else:
            result = close_rehearsal(
                args.case_dir, args.plan, args.log, args.review_input, args.output,
                replace=args.replace,
            )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"{args.command} completed for rehearsal {result.get('rehearsal_id', 'event')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

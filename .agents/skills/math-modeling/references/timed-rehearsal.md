# Timed Rehearsal Records

Use `scripts/manage_timed_rehearsal.py` for a scheduled practice or full simulation. It records what happened, when it happened, what evidence existed at that time, which failures caused rework, and which improvements enter the maintained workflow. It is deliberately separate from `workflow.json`, finalization, and submission packaging.

A closed rehearsal record proves only that the recording contract is complete. It does not prove that a model is correct, a paper is complete, or a package is submission-ready. Those judgments remain with the modeling, validation, paper, compliance, finalization, and packaging gates.

## Files And Ownership

Keep three machine records in the case or rehearsal directory:

| File | Contract | Owner | Meaning |
| --- | --- | --- | --- |
| rehearsal plan | `schemas/timed-rehearsal-plan.schema.json` | responsible human operator before start | Fixed window, mode, actual participant list, six phases, and planned fault injections |
| event log | `schemas/timed-rehearsal-log.schema.json` | active recorder during the rehearsal | Append-only, hash-chained events with hash-bound evidence |
| closure review | `schemas/timed-rehearsal-review.schema.json` | responsible human closure review after the last event | Phase timing, fault recovery, scorecard, and durable improvement decisions |

Use timezone-aware ISO 8601 timestamps such as `2026-09-01T08:00:00+08:00`. Do not reconstruct an apparently precise timeline from memory after the rehearsal. Record an event when it occurs or mark the record incomplete.

Schema version 1 retains the field name `team` and the phase ID `independent-review` for compatibility. In a single-operator rehearsal, put only the one actual operator in `team`; do not invent additional members or reviewers. Treat `independent-review` as a temporally separated, delayed adversarial second pass by that same operator, and record explicitly that it is not independent-person review. Codex may prepare evidence and objections but cannot approve or sign the human closure.

The plan must contain each phase exactly once: `problem-selection`, `baseline`, `primary-model`, `synchronized-writing`, `independent-review`, and `packaging`. A `full-simulation` plan requires at least two fault injections. Faults should exercise realistic recovery paths such as network unavailability, backend loss, input-path changes, cache invalidation, or result mismatch.

## Start And Record

Create the plan and have the responsible human operator review it first, then freeze its hash by initializing the log:

```powershell
python scripts/manage_timed_rehearsal.py init `
  --case-dir <case-dir> `
  --plan rehearsal/rehearsal-plan.json `
  --log rehearsal/rehearsal-log.json
```

Append events through the command instead of editing the log. Every event needs at least one existing case-local evidence file:

```powershell
python scripts/manage_timed_rehearsal.py record `
  --case-dir <case-dir> `
  --plan rehearsal/rehearsal-plan.json `
  --log rehearsal/rehearsal-log.json `
  --occurred-at 2026-09-01T10:20:00+08:00 `
  --phase baseline --type failure `
  --category result-mismatch `
  --summary "Result workbook differs from the generated summary" `
  --evidence rehearsal/evidence/result-mismatch.json
```

Use stable evidence snapshots, command logs, reports, commits exported as patches, or immutable generated artifacts. Do not bind an event to a live source file that will keep changing; any later byte change correctly invalidates the log. Preserve raw evidence and never rewrite it to make the timeline cleaner.

`rework` must reference an earlier failure, decision, or milestone with `--related-event` and requires a root-cause category. `recovery` must reference an earlier failure or fault-injection. A `fault-injection` must name a planned `--fault-id`. Event timestamps must be nondecreasing, sequences must be continuous, and the hash chain must validate before any append.

## Close And Review

Prepare a separate review-input JSON containing these exact fields:

- `closed_at`, `actual_minutes`, `result_assessment`, and `closure_notes`;
- all nine required scorecard entries listed below;
- `improvements`, `no_durable_change`, and `unresolved_blockers`.

The required scorecard IDs are:

1. `rule-anonymity-risk`
2. `unanswered-subproblems`
3. `unproven-headline-values`
4. `leakage-unit-definition-constraint`
5. `unjustified-complex-model`
6. `clean-input-rerun`
7. `paper-result-support-consistency`
8. `late-change-rework`
9. `pdf-packaging`

Every score must be `pass`, `fail`, or `not-applicable`, cite at least one event, and explain the decision. `not-applicable` is a scoped judgment, not a way to hide missing work.

Every failure and rework event must be covered by an improvement or an explicit `no_durable_change` rationale. Each improvement records source events, statement, owner, priority, acceptance criterion, destination, adopt/defer/reject decision, rationale, due date when open, and status. An adopted improvement cannot use `destination=none` or `priority=reject`; a rejected item must use both.

Close only after all six phases have at least one event and every planned fault has exactly one injection and one recovery:

```powershell
python scripts/manage_timed_rehearsal.py close `
  --case-dir <case-dir> `
  --plan rehearsal/rehearsal-plan.json `
  --log rehearsal/rehearsal-log.json `
  --review-input rehearsal/review-input.json `
  --output rehearsal/rehearsal-review.json
```

The output binds the plan and log by SHA-256, calculates elapsed time and fault-recovery time, and always states: `Record closure does not validate the model, paper, or submission package.` A missed deadline does not prevent honest closure; it is recorded as `deadline_met=false`. Use `result_assessment=verified` only when separate model, paper, and package evidence actually supports that judgment.

## Verification

Run the focused regression suite on Windows with discovery, because passing a filesystem path directly to `unittest` may be interpreted as a module name:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m unittest discover `
  -s .agents/skills/math-modeling/tests `
  -p test_timed_rehearsal.py -v
```

Before releasing the Skill, also run the complete `scripts/check_skill.py` gate. A dry run validates the recorder only; it does not replace the scheduled data-intensive practice, optimization practice, or full timed simulation.

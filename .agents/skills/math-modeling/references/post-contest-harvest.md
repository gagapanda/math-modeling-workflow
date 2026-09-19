# Post-Contest Workflow Harvest

Use this reference after a competition or full rehearsal to convert local evidence into a smaller, faster, and more reliable future workflow. Harvesting is not retrospective gate completion: never invent a review time, F1/M6/M7 acceptance, official upload, receipt, participant, or decision that was not recorded when it occurred. Record such absences as `NO_RETROACTIVE_GATE_CLAIM`.

## Evidence Layers

Keep four layers separate in every postmortem:

1. **observed facts**: paths, hashes, timestamps, command outputs, candidate counts, reports, recorded decisions, and official-rule snapshots that can be reopened;
2. **human recollection**: pressure, confusion, manual work, and decisions remembered by the operator but not contemporaneously logged;
3. **inferred causes**: explanations that fit the evidence but were not directly observed;
4. **adopted controls**: specific future behavior with an owner, trigger, acceptance criterion, and durable destination.

Do not promote a lesson merely because it sounds sensible. A durable change needs at least one located failure or repeated cost, a causal hypothesis that is narrow enough to test, and an acceptance check that would have caught or reduced the observed problem.

## Harvest Sequence

1. **Freeze the observable record.** Inventory the final problem, current pointer, result sources, paper candidates, support archives, AI log, rule snapshots, gate records, package reports, and any upload receipt. Hash stable artifacts when they will be cited later. Do not rename or clean the evidence tree during discovery.
2. **Reconstruct the actual route.** Compare `CURRENT-STATE.md`, active control files, candidate lineage, command logs, and file timestamps. Mark disagreements explicitly. Modification time is supporting evidence, never authority.
3. **Separate technical success from submission authority.** Report model, validation, paper, compliance, package, human gate, upload, and receipt status independently. A strong paper or clean replay cannot fill a missing F1, M6, M7, or F2 record.
4. **Extract both strengths and friction.** Preserve practices that prevented errors, not only failures. Quantify avoidable candidate churn, repeated exports, stale controls, environment recovery, late compliance work, and unplanned model expansion where the evidence allows it.
5. **Classify each candidate lesson.** Use `adopt`, `defer`, `reject`, or `case_only`. `case_only` is required for model equations, parameter values, or domain claims that do not generalize beyond the problem.
6. **Choose the smallest durable destination.** Prefer, in order: an existing checklist or runbook line, an executable quality gate or test, a reusable template, then a new reference. Do not duplicate a control already enforced; improve its adoption trigger or ergonomics instead.
7. **Verify the change.** Run focused tests, then the Skill quality gate when feasible. State anything not run. Preserve before/after hashes or a patch when the workspace is not a Git repository.
8. **Close with a future drill.** Name one rehearsal or live trigger that will test the new control. A written rule without a future observable check remains provisional.

## Required Postmortem Shape

```text
scope and evidence cutoff
observed strengths
observed friction/failures
human recollection still requested
inferred causes
adopted/deferred/rejected/case-only decisions
modified durable assets
verification run and result
unresolved risks
next rehearsal trigger
```

## Promotion Tests

A workflow improvement is ready to adopt only when all are true:

- it would have changed an observable step before the failure or rework occurred;
- it does not require guessing a future contest rule;
- it preserves mathematical correctness, data integrity, anonymity, AI disclosure, and human authority;
- it has a bounded operating cost during competition;
- its acceptance criterion is executable or reviewable under time pressure;
- it does not turn one case's model choice into a universal answer.

If evidence is incomplete, keep the lesson in the case postmortem as `defer` rather than weakening a production gate. If the contest finished but no receipt was preserved, say only that the competition period ended or that the user reports completion; do not claim `F2_COMPLETE`.

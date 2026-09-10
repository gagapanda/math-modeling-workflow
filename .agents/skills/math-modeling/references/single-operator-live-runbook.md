# Single-Operator Live Runbook

Use this reference when one responsible human operates Codex Desktop and maintains the only canonical competition workspace. It is a compact execution layer over the main modeling, validation, paper, compliance, and packaging references; it does not replace current official rules or the full competition protocol.

The runbook incorporates only reusable controls supported by the D4, stage F, and G4 rehearsals. Those rehearsals are calibration evidence, not a promise that every problem can be finished in the same elapsed time.

## Authority And Workspace Ownership

- The responsible human operator owns every human gate and final Go/No-Go decision.
- Codex may inspect, implement, execute, reconcile, draft, and challenge, but it must not sign a human gate, invent a reviewer, or silently convert an AI judgment into human approval.
- Maintain one canonical workspace. If other people provide comments, treat them as advisory inputs; they do not edit the canonical workspace directly unless the operator explicitly changes this rule.
- In a one-person run, state that review is single-operator review. Never claim independent-person, team, or dual review that did not occur.
- Reduce single-person confirmation bias with a separated second pass: close the first execution pass, reopen the evidence after a short context break, and perform an adversarial review focused on definitions, leakage, unsupported claims, frozen-number drift, anonymity, and package replay. Label it `single_operator_second_pass`, not `independent_reviewer`.

## Resume And Authority Check

Before executing or resuming an existing case:

1. Open exactly one case-local authority pointer. New scaffolds use case-root `CURRENT-STATE.md`; a legacy case may use one documented equivalent. The pointer must identify the current result register, current F1 manifest or the absence of one, authoritative paper source, selected delivery candidate, gate statuses, blockers, and superseded candidates by path and preferably SHA-256. Do not select an artifact merely because its filename or modification time looks newest. Multiple unresolved candidates require `AUTHORITY_UNRESOLVED`.
2. Treat `CURRENT-STATE.md` as a resume and authority summary, not as gate proof. Update it whenever authority changes: result-register selection, F1 freeze/thaw, paper-source replacement, package selection, or gate reversal. `.workflow/state.json`, a finalization report, a delivery checklist, or a package manifest remains supporting evidence and cannot silently replace the pointer.
3. Inspect active control files such as `START-HERE.md`, `decisions.md`, `validation.md`, manifests, checklists, and review cards for `TODO`, `pending`, contradictory status, or obsolete paths. Complete them or explicitly mark them superseded with the replacement path and reason. An unresolved active placeholder is `STALE_CONTROL_FILE` and blocks F1, M5, and M7 claims.
4. Interpret a machine gate from its complete status tuple: `required`, `scope`, `status`, `passed`, `errors`, and bound evidence. `required=false` with `passed=true` means `NOT_RUN_OR_NOT_REQUIRED`; it is not proof that the gate executed and passed.
5. Verify that an alleged F1 manifest directly binds the current result register and affected model/validation/figure evidence. A delivery freeze or package checklist is not automatically an F1 result freeze.
6. Before M7 precheck, compare the declared core-script set with the clean-extraction replay set. A successful subset smoke test proves only that subset.

The Markdown pointer is intentionally lightweight. Do not infer a machine-enforced transition or human approval from its text, and do not add a parallel pointer unless the existing authority record is explicitly superseded.

## Fast State Card

| State | Minimum acceptance evidence | If not satisfied |
| --- | --- | --- |
| M0 problem gate | Every subproblem has objective, inputs, outputs, evaluation target, and material assumptions | Stop decomposition; the human operator resolves the interpretation |
| M1 data gate | Shape, fields, types, units, missingness, duplicates, target, grouping, time/order, and lineage are known | Do not guess fields or start irreversible cleaning |
| M2 baseline gate | At least one transparent runnable baseline with a fair metric and declared scope | Return to the baseline before adding complexity |
| M3 validation gate | Leakage unit and the repeated-measure, group, temporal, or spatial structure determine the split | Reject row-random validation when it does not match the claim |
| M4 run gate | Definition closure, interpreter/dependency smoke, and current-input/current-code provenance pass | Record `DO_NOT_FREEZE` or `UNRESOLVED` |
| F1 result freeze | Results, validation, figures, register, two core replays, freeze manifest, and human decision agree | Keep every draft non-authoritative; use `F1_THAW` for frozen-scope changes |
| M5 paper gate | Every subproblem is answered; current F1 values, limitations, scope, figures, and claims reconcile; P0 defects are zero | Return to paper and evidence audit |
| M6 compliance gate | Current official rules, anonymity, AI record, citations, and external-data status are reviewed | Do not package as a submission candidate |
| M7/F2 submission gate | Final PDF/package, manifest, hashes, clean extraction replay, human final review, upload, and receipt are complete | Do not claim `F2_COMPLETE` |

Do not merge gate semantics. `M7-PRECHECK-PASS` is a technical candidate-package status, not formal submission completion. Historical or practice work must also state `NOT_FORMAL_F2`.

## M4 Definition Closure

Before bulk-generating an official workbook, headline figure, or paper containing formal numbers, close this five-way chain for every material term:

```text
problem-statement term
-> mathematical definition
-> code variable
-> output field / result ID
-> paper wording
```

Record alternatives, units, denominator, aggregation level, sign convention, boundary treatment, and inclusion/exclusion rules when they can change a conclusion. Any unresolved material term requires `DO_NOT_FREEZE`. A successful rerun or matching hash cannot prove that the chosen definition is correct.

## Environment And First Full Run

Before the first full-data run, and again before the M7 clean-extraction replay, record:

1. the absolute path of the actual interpreter or runtime;
2. its version;
3. import/startup smoke results for the already approved core dependencies;
4. the workspace or extraction root used for the run.

A failed smoke test enters recovery. Do not install or upgrade dependencies during the live route merely to preserve an ambitious model; fall back to an already available baseline or approved implementation.

## Canonical Results And Freeze

The scaffolded `results/f1-freeze-plan.json` declares the result register, every frozen file, at least two distinct replay-evidence files, limitations, and unresolved items. Use new output names for every attempt; the tool refuses to overwrite an existing candidate or final manifest.

```powershell
python .agents\skills\math-modeling\scripts\freeze_results.py prepare `
  --case-dir <case-dir> `
  --plan results/f1-freeze-plan.json `
  --output results/f1-candidate-<freeze-id>.json `
  --generated-at <ISO-8601-with-offset>
```

`prepare` produces only `F1_PENDING_HUMAN` with `paper_authoritative=false`. Codex may prepare the evidence and draft `results/F1-review-card.md`, but it cannot run an accepted finalization as its own decision. After the responsible human has actually reviewed the listed hashes and recorded a decision, record that decision in a new immutable manifest:

```powershell
python .agents\skills\math-modeling\scripts\freeze_results.py finalize `
  --case-dir <case-dir> `
  --candidate results/f1-candidate-<freeze-id>.json `
  --output results/f1-manifest-<freeze-id>.json `
  --decision accepted `
  --reviewer "<actual responsible human operator>" `
  --review-start <ISO-8601-with-offset> `
  --review-end <ISO-8601-with-offset> `
  --signed-at <ISO-8601-with-offset> `
  --generated-at <ISO-8601-with-offset> `
  --confirm-human-reviewed
```

Then recheck current hashes, candidate provenance, replay bindings, timestamp order, decision semantics, and paper authority:

```powershell
python .agents\skills\math-modeling\scripts\freeze_results.py verify `
  --case-dir <case-dir> `
  --manifest results/f1-manifest-<freeze-id>.json
```

A successful `verify` does not prove that a human review occurred; it only verifies the recorded, hash-bound evidence. Current numerical authority requires all three to agree: the verified accepted manifest, its bound current result register, and the case-root `CURRENT-STATE.md` pointer. Until then, preserve `paper_authoritative=false`.


## M5 Paper-Authority Entry

Write the paper early if useful, but before F1 acceptance keep the source and generated DOCX/PDF visibly marked `NON_AUTHORITATIVE REVIEW DRAFT`. A draft is reviewable evidence, not an authoritative result carrier and not a submission candidate.

New practice and submission scaffolds declare `paper/paper-authority-plan.json`. M5 passes only after all of the following agree:

- `freeze_results.py verify` passes the exact accepted F1 manifest;
- that manifest binds the declared current result register and has `paper_authoritative=true`;
- `CURRENT-STATE.md` selects the same register, manifest, accepted status, authoritative paper source, and records `F1 verification = PASSED`, `Paper authoritative = true`, and `Human approval = SIGNED`;
- the draft marker has been removed from the Markdown source and final DOCX/PDF.

After those facts are true, the responsible operator changes the plan from `draft` to `authoritative` and records the accepted manifest path. `audit_paper_authority.py` verifies the chain but cannot create or sign the human decision. Changes to frozen data, code, models, validation, results, or bound figures require `F1_THAW`. Pure wording or layout edits may leave numerical F1 intact, but they invalidate the paper hashes, visual review, finalization report, and package evidence and therefore require those downstream gates again.

- The current result register plus the current verified accepted F1 manifest are the only authoritative numerical source after freeze.
- Workbooks, figures, tables, and paper generators read those sources; they must fail closed on unknown result IDs, schema drift, definition drift, or stale hashes.
- Before human F1 approval, any generated paper or package must carry `NON_AUTHORITATIVE REVIEW DRAFT` and machine-readable `paper_authoritative=false`. It must not enter the final-submission directory.
- A change to frozen data, preprocessing, definition, code, model, validation, result, or bound figure requires:

```text
F1_THAW
-> identify affected chain
-> rerun affected steps
-> revalidate and reconcile
-> preserve the old accepted manifest as superseded history
-> create a new freeze ID and candidate
-> obtain a new human decision
-> verify the new immutable manifest and update CURRENT-STATE.md
```

- A wording-only or layout-only change outside the frozen scope does not thaw results, but it still invalidates affected paper hashes, rendered-page review, and final package evidence.

## M6 Compliance Entry

M6 is a human gate over a machine-prepared evidence set. New submission cases use `compliance/m6-plan.json`; the build phase may run its `technical` audit before human review, but finalization requires a verified accepted human manifest.

Minimum evidence:

1. reviewed current official-rules snapshot, source list, verification time, impact notes, and matching SHA-256;
2. anonymity precheck for DOCX/PDF metadata, text, filenames, support paths, and configured identity terms;
3. `compliance/source-register.json` at `complete` or justified `not_applicable`, never `pending`;
4. reviewed AI-use log and paper declaration; when required, a content-complete AI detail PDF present in the support allowlist;
5. exact `submission-package-plan.json` allowlist;
6. `M6_PENDING_HUMAN` candidate followed by the actual operator's decision.

Codex may run `technical`, `prepare`, `verify`, and `audit`. It must not execute `finalize --confirm-human-reviewed` or name itself as reviewer. The responsible operator performs a separated review and records `single_operator_review`. If accepted with limitations, record substantive objections and their resolution; unresolved compliance means reject/No-Go.

A legacy rules/AI audit is explicitly `rules_and_ai_technical_only`, not complete M6. Machine `verify` confirms the recorded hashes and semantics, not that the human truly reviewed them.

## Validation And Claim Boundaries

- Do not write correlation as causation without a defensible identification design.
- Do not write a conditional scenario forecast as a training, policy, or real-world performance guarantee.
- Row-random cross-validation does not establish generalization to a new individual, athlete, device, site, or future period when rows are dependent.
- For time series, repeated measurements, multiple trials from one subject, and grouped or spatial data, choose validation units that match the deployment claim.
- Register a non-reproduction honestly: source, evidence, status, numerical difference, limitations, and the stronger conclusions that are prohibited.

## Paper And Packaging Order

Paper structure, symbols, methods, and clearly marked placeholders may be drafted before F1. Formal numbers, abstract conclusions, and final claims enter the authoritative paper only from the current F1 sources.

Before claiming `M7-PRECHECK-PASS`, require at least:

1. two deterministic package builds or an explained allowlisted difference;
2. archive entry and CRC checks;
3. safe extraction into a fresh directory;
4. execution of every declared core script with the recorded runtime;
5. comparison of key outputs with the current F1 manifest;
6. post-run anonymity and absolute-path scans;
7. a readable PDF reopened from the candidate package.

Keep scanning rules and reports outside the scanned deliverable when their own forbidden patterns would create self-matches. This technical precheck cannot bypass M6, F1, human final review, official upload, or receipt capture.

## M7/F2 Authority Entry

Treat M7 as final local delivery acceptance and F2 as the separate official-upload fact. The authority chain is:

```text
ready_for_submission=true
-> selected package report and outputs
-> support smoke report for the same ZIP
-> M7-PRECHECK-PASS / NOT_FORMAL_F2
-> M7_PENDING_HUMAN
-> actual single_operator_review
-> verified accepted M7 / still NOT_FORMAL_F2
-> actual official upload of the unchanged package
-> real non-empty official receipt
-> explicit human upload confirmation
-> verified immutable F2 manifest
-> F2_COMPLETE
```

Codex may run `audit_m7_f2.py precheck`, `prepare-m7`, `verify-m7`, and `verify-f2`. It must stop before `finalize-m7 --confirm-human-reviewed` and `record-f2 --confirm-official-upload`; prior blanket consent does not prove that the future review or upload occurred. Do not use an attempted upload, a browser success-looking screen without preserved receipt evidence, or an accepted M7 manifest as `F2_COMPLETE`.

Update `CURRENT-STATE.md` with the exact selected package report, packaged paper, support ZIP, M7 candidate/final manifest, M7 verification, F2 manifest, and receipt paths/hashes. The Markdown pointer remains a resume aid; the verified manifests are the gate evidence.
## Deadline Degradation Card

These are stop rules, not target completion times:

- **120 minutes remaining:** stop introducing new model families, new external data, dependency changes, and nonessential figures. Select the defensible route and reserve time for F1, paper, compliance, and packaging.
- **60 minutes remaining:** freeze analysis scope. Work only on unresolved P0/P1 paper defects, result reconciliation, rule/anonymity/AI checks, deterministic packaging, and clean replay. Use the transparent baseline if the primary model is not stable.
- **30 minutes remaining:** no model or data changes unless an identified P0 error makes submission invalid. Reopen final artifacts, check names and hashes, complete upload/receipt actions, and preserve evidence. An unresolved P0 produces No-Go or an explicitly downgraded claim, never silent concealment.

## Recovery Card

1. Stop the failed gate; do not infer success from partial artifacts.
2. Preserve the command, error, input hashes, current outputs, and last valid state.
3. Classify the failure: definition, data, environment, dependency, code, numerical, validation, paper, compliance, packaging, upload, or recording.
4. Apply the smallest reversible repair and rerun the same gate.
5. If the repair changes frozen scope, execute `F1_THAW` before reuse.
6. If recovery exceeds the remaining budget, fall back to the last validated baseline and narrow the claim.
7. Record what remains unverified and what stronger conclusion is prohibited.

## AI Use Record

Keep a case-local chronological record of AI-assisted actions sufficient for the current official disclosure rule: timestamp, purpose, material inputs or file references, generated or changed artifacts, commands executed, evidence produced, human decision, and unresolved limitation. Do not fabricate interaction history after the fact. The responsible human operator reviews the record before M6 and remains accountable for the submission.

## Minimal Human Decision Card

```text
gate:
evidence_ready_time:
human_review_start:
human_review_end:
human_decision: approve | reject | conditional | not_reviewed
reviewer: <actual responsible human operator>
objections:
resolution:
finalization_time:
limitations:
```

Store this card in a case-local evidence location. Until a required human gate says `approve`, Codex must preserve the pending state rather than substituting its own judgment.

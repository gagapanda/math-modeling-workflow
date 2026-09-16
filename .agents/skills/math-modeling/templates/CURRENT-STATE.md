# Current State

> This is the only case-local resume pointer. It selects the artifacts and statuses to inspect next; it does not by itself prove that any model, human, compliance, freeze, or submission gate passed.

## Authority

| Field | Current value |
| --- | --- |
| Pointer status | `INITIALIZING` |
| Last updated at | `NOT_RECORDED` |
| Last updated by | `RESPONSIBLE_HUMAN_NOT_RECORDED` |
| Workflow profile | Read from `workflow.json` |
| Candidate registry | `authority/candidate-registry.json` |
| Canonical result register | `results/result-register.json` |
| Current result candidate | `NOT_SELECTED` |
| F1 status | `NOT_FROZEN` |
| F1 candidate | `NOT_CREATED` |
| F1 accepted manifest | `NOT_CREATED` |
| F1 verification | `NOT_RUN` |
| Paper authoritative | `false` |
| Authoritative paper source | `paper/full-paper.md` |
| Current generated paper | `NOT_BUILT` |
| Selected delivery candidate | `NOT_CREATED` |
| M7 precheck status | `NOT_RUN` |
| M7 candidate | `NOT_CREATED` |
| M7 accepted manifest | `NOT_CREATED` |
| M7 verification | `NOT_RUN` |
| Selected package report | `NOT_SELECTED` |
| Selected packaged paper | `NOT_SELECTED` |
| Selected support ZIP | `NOT_SELECTED` |
| F2 manifest | `NOT_CREATED` |
| Official receipt | `NOT_CAPTURED` |
| Official submission status | `NOT_FORMAL_F2` |
| Human gate owner | Responsible human operator |
| Human approval | `NOT_SIGNED` |

## Gate Snapshot

| Gate | Status | Bound evidence or next action |
| --- | --- | --- |
| M0 problem | `NOT_REACHED` | Close requirements, assumptions, and material definitions |
| M1 data | `NOT_REACHED` | Complete data profile and lineage |
| M2 baseline | `NOT_REACHED` | Run and register a transparent baseline |
| M3 validation | `NOT_REACHED` | Match validation to group/time/repeated/spatial structure |
| M4 run | `NOT_REACHED` | Close environment, definition, and provenance checks |
| F1 result freeze | `NOT_FROZEN` | Prepare a hash-bound candidate, obtain the real human decision, verify the accepted manifest, then update this pointer |
| M5 paper | `NOT_REACHED` | Reconcile the paper with the current accepted and verified F1 evidence |
| M6 compliance | `NOT_REACHED` | Review current official rules, anonymity, and AI use |
| M7 package | `NOT_REACHED` | Select and replay one package candidate |
| F2 official submission | `NOT_FORMAL_F2` | Requires actual upload and receipt evidence |

## Current Blockers

`NONE_RECORDED`

## Superseded Candidates

`NONE_RECORDED`

## Update Rules

- Update this file when authority changes: result-register selection, F1 candidate creation, F1 acceptance/rejection, F1 verification, thaw, authoritative paper-source change, generated-paper replacement, package selection, or gate reversal.
- Run `python scripts/audit_authority_heartbeat.py --case-dir <case-dir> --json` after each update. Its read-only report detects pointer, path, control-file, and candidate-lineage drift; it does not select artifacts or sign a gate.
- Record paths and SHA-256 when available. Never select an artifact only because its name or modification time looks newest.
- `prepare` creates only `F1_PENDING_HUMAN`; it does not freeze results and cannot make the paper authoritative.
- Set `Paper authoritative` to `true` only when the responsible human has recorded an accepted decision, `freeze_results.py verify` passes the immutable accepted manifest against current files, and this pointer names that exact manifest and current result register.
- If multiple candidates cannot be resolved, set pointer status to `AUTHORITY_UNRESOLVED`, list every candidate, and stop authority-dependent claims.
- If an active control file contains unresolved placeholders or obsolete paths, record `STALE_CONTROL_FILE` and block the affected gate until it is completed or explicitly superseded.
- Interpret `required`, `scope`, `status`, `passed`, `errors`, and bound evidence together. `required=false` with `passed=true` is `NOT_RUN_OR_NOT_REQUIRED`.
- Codex may draft updates, compute hashes, run `audit_m7_f2.py precheck`, and present evidence, but only the responsible human operator may sign M7 or confirm the official upload.
- `ready_for_submission=true`, package creation, `M7-PRECHECK-PASS`, and accepted M7 all remain `NOT_FORMAL_F2`. Record `F2_COMPLETE` only after the unchanged selected package is actually uploaded, a real non-empty official receipt is preserved, and the F2 manifest verifies.
- Keep one pointer only. A freeze manifest, finalization report, package checklist, or `.workflow/state.json` is supporting evidence, not a replacement for this authority summary.

## F1_THAW Rule

When frozen data, preprocessing, definition, code, model, validation, result, or a bound figure changes:

1. set `F1 status` to `F1_THAW` and `Paper authoritative` to `false` immediately;
2. record the thaw reason and affected chain under `Current Blockers`;
3. move the former accepted manifest into `Superseded Candidates` without editing or deleting it;
4. rerun and revalidate the affected chain;
5. create a new freeze ID, candidate, real human decision, and immutable final manifest;
6. run `freeze_results.py verify` and only then select the new manifest here.

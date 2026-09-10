# Versioning And Compatibility

The skill versions machine contracts independently. Do not infer one version from another.

## Current Contracts

| Contract | Current version | Compatibility policy |
| --- | --- | --- |
| `workflow.json` | 2 | Version 1 remains accepted and keeps its historical `practice` behavior. |
| Pipeline build report | 1 | Additive top-level and nested fields are allowed. Required fields and existing meanings remain stable. |
| Passive execution plan | 1 | Additive fields and new reason codes are allowed. Read-only guarantees and existing action meanings remain stable. |
| Workflow migration analysis | 1 | Additive fields and review codes are allowed. Read-only guarantees, conservative candidate semantics, and the prohibition on automatic cache enablement remain stable. |
| Workflow migration rehearsal | 1 | Additive review checks are allowed. Source immutability, temporary cleanup, no case execution, isolated candidate validation, and no automatic cache enablement remain stable. |
| Workflow migration review | 1 | Closed hash-bound human record. Unknown fields are rejected; manifest, base-candidate, and Python-script bindings remain mandatory. |
| Workflow migration review result | 1 | Additive fields are allowed. Rehearsal-before-validation, no case execution, stale-review rejection, and no-overwrite export semantics remain stable. |
| Workflow migration acceptance | 1 | Additive fields are allowed. Exact reviewed-candidate equality, hash bindings, plan-structure equivalence, source immutability, and no execution or installation remain stable. |
| Workflow migration readiness | 1 | Additive fields are allowed. Direct-child discovery, per-case failure isolation, source immutability, explicit ranking fields, and the non-approval meaning of recommendations remain stable. |
| Workflow migration review package | 1 | Additive fields are allowed. Hash-bound entry and traced support modules, candidate-only path/provenance/relationship evidence, located non-blocking trace limitations, explicit gaps, all-pending checklists, source immutability, and no review-record creation remain stable. |
| Finalization report | 1 | Additive top-level and nested fields are allowed. Required fields and existing meanings remain stable. |
| Visual-review evidence | 1 | Closed evidence record. Unknown fields are rejected so recorded approval stays explicit. |
| MATLAB validation evidence | 1 | Closed hash-bound evidence record. Unknown fields are rejected. |
| Diagnostic envelope | 1 | Diagnostic fields and severity meanings remain stable; producers may add new diagnostic codes. |
| Submission compliance | 1 | Closed human-reviewed evidence record. Unknown fields are rejected. |
| Submission package plan | 1 | Closed explicit allowlist. Unknown fields are rejected; recursive discovery is not part of the contract. |
| Submission package report | 1 | Closed hash-bound output record. Unknown fields are rejected; finalization binding, output hashes and validation meanings remain stable. |
| Timed rehearsal plan | 1 | Closed human-reviewed schedule. Unknown fields are rejected; the competition window, six required phases, team, mode, and planned faults remain stable after log initialization. |
| Timed rehearsal event log | 1 | Closed event shape with append-only semantics. Unknown fields are rejected; plan binding, continuous sequence, timestamp order, evidence hashes, relation rules, and the event hash chain remain stable. |
| Timed rehearsal review | 1 | Closed plan- and log-bound record. Unknown fields are rejected; required scorecard coverage, failure/rework disposition, improvement ownership, and the non-validation meaning of record closure remain stable. |

The authoritative Draft 2020-12 documents are under `schemas/`. Producers validate versioned output reports and evidence before atomic replacement. Passive execution plans, workflow migration analyses, migration rehearsal reports, migration review previews, migration acceptance reports, cross-case migration readiness reports, and human-review work packages are validated but never persisted in a case. The Markdown review view is a presentation of the validated work-package contract, not a new machine contract; it is emitted only to stdout and carries no approval state. Review templates and reviewed candidates are written only to explicit new paths and never replace an existing file. Consumers should select behavior from the report's own version field: `report_schema_version` for pipeline reports, `schema_version` for the other records, and `diagnostics_schema_version` for the embedded diagnostic envelope.

## Compatible Changes

The following may ship without a workflow schema increment:

- new optional manifest fields whose absence preserves current behavior;
- new diagnostic codes, execution-plan reason codes, warnings, backend metadata, or optional report fields;
- stricter runtime checks for corrupted files, escaped paths, stale hashes, or impossible states already forbidden by the documented contract;
- new profile-independent tools that do not alter manifest interpretation.

Existing version 1 workflows must continue to validate and execute with `practice` semantics. A new implementation must not silently add caching, submission compliance, or profile selection to them.
Timed-rehearsal contracts remain separate from workflow execution and submission readiness. A compatible recorder may add new event categories or optional report detail only when old records remain valid and `record_complete` continues to mean evidence closure rather than model, paper, or package approval. Changing required phase IDs, event hash canonicalization, relation meanings, scorecard IDs, or closure scope requires a new rehearsal contract version and migration fixtures.
Migration tooling may emit a version 2 candidate only when it preserves those semantics. Static dependency hints must remain clearly separated from declared inputs and outputs until a person confirms completeness; automatic cache enablement is incompatible with this policy.
Reviewed migration export may honor an explicit human cache decision only when the closed review record confirms dependency closure, outputs, timeout, determinism, and cache policy and all bound hashes are current. Export remains a new candidate file, not an in-place manifest migration.
Migration acceptance recomputes that reviewed candidate and requires exact object equality. The only authorized source-to-candidate changes are the version and `practice` profile plus reviewed Python dependency, timeout, and cache metadata. Passive plans must preserve step order, types, MATLAB runners, and post-processing intent; metadata-driven action or reason-code changes are compatible. `evidence_required` means no acceptance evidence was supplied and must never be interpreted as `accepted`.
Cross-case migration readiness may recommend an order for human review only from current passive diagnostic error counts and declared mechanical fields. It must expose the diagnostic codes, ranking fields and lexicographic policy, bind source and candidate hashes, preserve each case, and keep model correctness, paper quality, cache safety, and migration approval explicitly outside the recommendation's meaning. A readiness recommendation never suppresses case diagnostics or authorizes a migration.
A migration review package may expand static path candidates, attach multiple bounded provenance chains, report only exact candidate output/input matches, and add located `review_required` limitations with optional full call chains for conservatively unresolved branches. Additive raw-occurrence, unique-limitation, and group counts are compatible when the existing `trace_limitations` count continues to mean retained unique records. Optional limitation groups may index records only by step, reason code, and complete stop point; their occurrence and unique-chain totals must reconstruct the corresponding summary counts and must not replace the underlying call chains. Limitation deduplication may remove exact duplicates and shorter complete-chain suffixes only within one step and only for the same reason and stop point; different entries, stop points, reasons, and cycle directions remain review evidence. Case-local support modules reached through successful imported-helper chains must be hash-bound. Direct, local-helper, and imported-helper findings remain evidence for review and must never be inserted automatically into declared dependencies. Dynamic imports, star imports, runtime rebinding, transformed parameters, and other unresolved behavior remain outside path evidence; their limitation records and groups must not infer paths, bind support modules, block migration, assign priority, record approval, or enable caching. Every input, output, timeout, determinism, and cache checklist item remains pending; the package cannot be treated as a completed review record. Expected readiness hashes must fail closed when stale.
Resource limits may fail closed on structurally excessive or unreadable Python sources already outside the passive review contract. A step-local trace-event limit may add a located `trace_budget_exhausted` reason code while retaining earlier evidence; the limitation has the same non-error, non-approval, non-dependency, and non-cache meaning as every other conservative stop. Tightening a limit below ordinary historical-case requirements or changing exhaustion into inferred evidence would require an explicit compatibility review.
A human-readable renderer may reproduce that package only when it retains the source, candidate, entry-script, and traced support-module hashes; shows every pending item as unchecked; preserves provenance chains, limitation groups and full call chains, raw and unique counts, and explicit safety invariants; escapes untrusted Markdown text; and performs no case writes. Machine and Markdown views remain stdout-only, expose no output-path option, preserve UTF-8, normalize displayed paths to forward slashes, and produce identical bytes across repeated runs on one unchanged host. Adding presentation headings or conservatively removing redundant limitation-chain suffixes is compatible, but omitting bound evidence, adding persistent output, or introducing an approval control is not.
The frozen review-package meanings, producer/schema/renderer/gate ownership, supported version 1 document generations, and future change gate are summarized in `migration-review-package-stability.md`. Its measured thresholds, CLI states, historical headroom, and feedback-driven maintenance policy are recorded in `migration-review-package-release-baseline.md`. Current producers must validate cross-field limitation aggregation before returning a ready package; schema validation alone is not sufficient for those semantic relationships.

## Breaking Changes

A workflow schema version 3 is justified only when at least one of these is necessary:

- a currently valid version 2 manifest must become structurally invalid for reasons beyond an existing safety invariant;
- an existing field changes type or meaning;
- a default changes in a way that affects execution, caching, artifacts, or compliance;
- step ordering, dependency interpretation, or success semantics change incompatibly;
- a required profile or runner cannot be represented safely through an optional version 2 extension.

A report or evidence schema version increments when a required field is removed or renamed, a field type changes, a success state changes meaning, or a closed record gains a required field. New versions need migration notes, fixtures for old and new readers, and an explicit support window.

## Deprecation Process

1. Document the proposed replacement and migration in `CHANGELOG.md`.
2. Keep the old contract accepted for at least one normal release cycle unless a security or data-loss issue requires immediate rejection.
3. Emit a stable warning code while the old contract remains accepted.
4. Add compatibility tests before changing producers or consumers.
5. Remove support only in a declared breaking release.

Run `scripts/check_skill.py` before release. It validates bundled schemas and Python syntax, runs the full test suite, exercises temporary lifecycle fixtures, validates historical manifests, and invokes historical diagnostics, planning, rehearsal, review preview, acceptance preview, readiness ranking, the recommended all-pending review package, and its stdout-only Markdown rendering in passive read-only mode. Historical case findings are reported as warnings; malformed historical manifests, invalid migration previews, readiness reports, work packages or Markdown views, and skill regressions fail the gate.

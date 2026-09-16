# Changelog

## 2026-09-09 — Deterministic M6 test clock

- Scoped both audit clocks to the synthetic fixture date only around test prepare calls. Added exact-expiry, stale/future-date and backdated-generated-at rejection regressions; production freshness policy and case evidence remain unchanged.

## 2026-09-09 — Evaluator-facing closeout evidence

- Added default pending closeout reviews for new practice/submission cases; finalization binds source/DOCX/PDF and four actual review evidence sets, failing closed on missing/pending/stale records. Legacy omitted records remain explicitly not-run, not a closeout pass.
- Added read-only exact ZIP inventory verification (source/hash/bytes, duplicate/unsafe paths and stale payload rejection), supplemental to existing package/M6/smoke gates, with no numerical replay or human sign-off.
- Clarified Markdown and LaTeX template cleanup, per-question reviewer reconstruction, reference verification, AI-use coverage and final-page review. Explicit contact-sheet/sample-only records cannot satisfy full-page review.
- Preserved the distinction between evidence freshness and semantic/human validation; no historical case was promoted or rewritten by this change.

## Unreleased

- Added a bounded diagnosis-to-model-disposition writing contract: every material diagnostic retained in the main text now identifies the checked object and expected relation or threshold, the observed evidence, and an explicit scoped disposition (accept within scope, retain with restrictions, revise, or reject). A revision must rerun affected validation and refreeze dependent numbers, tables, figures, and conclusions; diagnostics with no downstream action are removed or demoted. Promotion followed corpus prior-art screening, bounded visual review of C126/E032 with B226 as an overclaim boundary, and an isolated one-page A/B fixture that held model, validation, diagnostic result, final disposition, and layout fixed.

- Added a bounded data-evidence-to-modeling-action writing contract: distinguish usability audit from problem-driving evidence, state analysis unit, observed pattern, downstream model/transformation/validation/decision action and prohibited stronger inference, remove or demote non-actionable EDA, and allow mechanism, geometry, pure-optimization, or data-free problems to mark it not applicable. The rule was promoted only after prior-art screening, bounded visual review of C050/E030 with A127 as a negative control, and an isolated one-page A/B fixture that held data, figure, model, validation, result, and conclusion fixed.

- Aligned the 2026 live protocol and readiness roadmap with the actual single-operator authority model: the user is the only real human decision-maker and workspace owner; final review uses recorded single_operator_second_pass / single_operator_review; optional outside opinions are non-authoritative until adopted; and no F1, M6, M7, or F2 gate requires invented teammates or two-person review.

- Added a separate M7/F2 authority chain: selected package/finalization/source/support/smoke hash binding, required replay enforcement, immutable pending and accepted M7 manifests, explicit `single_operator_review`, non-AI reviewer/operator checks, real non-empty receipt binding, upload timestamp and identifier checks, immutable `F2_COMPLETE` verification, submission-only scaffolding, current-state fields, and regression coverage. Local readiness, packaging, M7 precheck, and M7 acceptance remain `NOT_FORMAL_F2`; Codex cannot sign the human review or confirm the official upload.

- Added a complete M6 compliance entry alongside the legacy rules-and-AI audit: hash-bound official-rules snapshots, anonymity and support-allowlist checks, citation/external-data/software/license registration, content-aware AI records, immutable human review manifests, single-operator/non-AI reviewer enforcement, pipeline/finalization/package scope propagation, submission-only scaffolds, and regression coverage. Technical pass remains non-approval; historical cases are not forced to migrate.

- Added an opt-in M5 paper-authority gate for legacy workflows and enabled it by default in new practice/submission scaffolds: drafts carry `NON_AUTHORITATIVE REVIEW DRAFT`, while authoritative finalization requires a verified accepted F1 manifest, agreeing `CURRENT-STATE.md`, the same result register and paper source, and marker-free Markdown/DOCX/PDF artifacts.

- Added a minimal F1 result-freeze machine contract: schema-validated plans and immutable manifests, two-replay and result-register binding, SHA-256 verification, explicit real-human finalization, timestamp ordering, non-destructive scaffold controls, and a `CURRENT-STATE.md` authority link. `prepare` and `verify` remain non-approval operations, historical cases are not migrated, and `F1_THAW` preserves old manifests as superseded evidence.
- Raised the release gate unittest timeout from 300 to 600 seconds after the unchanged 281-test suite completed successfully in about 318 seconds on the current competition workstation; the prior limit produced a false quality-gate execution failure.
- Added a scaffolded case-root `CURRENT-STATE.md` authority pointer after read-only cross-checks of the 2025 E data case and 2023 B optimization case confirmed the resume gap across problem types. The pointer is deliberately Markdown-only, non-destructive, and non-authoritative for machine or human gates; no new Schema or state machine was introduced.
- Added front-loaded resume-authority and stale-control checks to the single-operator runbook and scaffolded `START-HERE.md`; reports with `required=false` and `passed=true` are now explicitly `NOT_RUN_OR_NOT_REQUIRED`, legacy delivery freezes are not automatically F1 freezes, and subset smoke tests cannot stand for all declared core scripts.
- Added a compact single-operator live runbook covering canonical-workspace ownership, honest single-person second-pass review, M0--M7/F1 status semantics, definition closure, environment smoke, authoritative result/freeze handling, 120/60/30-minute degradation, recovery, packaging precheck, and AI-use records; clarified timed-rehearsal and generic reviewer wording without changing schema version 1.
- Fixed explicit body result-ID extraction to accept dot, hyphen, underscore, and mixed dot/hyphen/underscore identifiers while retaining the `结果 ID`/`result_id` prefix requirement. Unknown extracted IDs now enter `unknown` and fail the paper-quality audit; the 2023 B temporary replay verified eight hyphenated IDs in `references`. This gate still does not require every paper to contain at least one explicit result-ID reference.
- Added a declaration-driven paper quality-gate plan and audit covering abstract Q1--Q4 structure, per-subproblem method/result/limitation markers, page-region contracts, complete source-appendix entries, formula-to-code tokens, figure/result bindings, DOCX/PDF metadata and forbidden-path scans, and exact rendered-page PNG continuity.
- Added optional `quality_gate_plan` routing through `workflow.json`, `run_pipeline.py --phase finalize`, and `finalization-report.json` without changing legacy manifests that omit the plan.
- Added anonymous support-package smoke plans and reports with ZIP SHA-256 binding, safe extraction, `shell=False` execution, timeout/exit/output checks, and selected-interpreter mapping for `python` commands.
- Replayed the 2025 E delivery in a temporary copy: all paper quality gates, three packaged core-script smoke tests, and finalization integration passed; the frozen case was not modified.
- Closed paper-quality-gate scope gaps for abstract and per-subproblem section matching, explicit body result-ID references, complete body-figure registration, and anonymous identity metadata. Visual-review hash/page checks remain finalizer-only and are reported with an explicit gate scope.
- The modeling requirements file intentionally has no pytest dependency. When the project venv lacks pytest, run the quality-gate unittest files directly; this is a test-runner fallback and must not be reported as pytest success.

- Added a declaration-driven paper quality-gate plan and audit covering abstract Q1--Q4 structure, per-subproblem method/result/limitation markers, page-region contracts, complete source-appendix entries, formula-to-code tokens, figure/result bindings, DOCX/PDF metadata and forbidden-path scans, and exact rendered-page PNG continuity.
- Added optional `quality_gate_plan` routing through `workflow.json`, `run_pipeline.py --phase finalize`, and `finalization-report.json` without changing legacy manifests that omit the plan.
- Added anonymous support-package smoke plans and reports with ZIP SHA-256 binding, safe extraction, `shell=False` execution, timeout/exit/output checks, and selected-interpreter mapping for `python` commands.
- Replayed the 2025 E delivery in a temporary copy: all paper quality gates, three packaged core-script smoke tests, and finalization integration passed; the frozen case was not modified.
### Added

- Append-only structured failure-event logging for failed `run_pipeline.py` and `preflight.py` attempts, with bounded cause/remediation/command evidence and regression coverage that preserves the existing pipeline-report contract.

- Root-cause regression coverage for DOCX table-cell text boundaries, unresolved Word TOC placeholders, ordered multi-inline-formula injection, and a real Word/PDF export sample covering display math, long paths, commands, lists, and page rendering.

- Hash-bound Tesseract selected-page OCR with explicit engine, tessdata, language, OEM, and PSM inputs; pinned offline recovery assets; and split prose/formula retrieval decisions. The verified A196 sample adopts `tessdata_best` `chi_sim` only for bounded Chinese prose retrieval and rejects formula retrieval.
- A schema-valid Tesseract recovery verifier that checks every cached installer/model and benchmark binding by confined path, byte size, and SHA-256, plus a release-gate check that fails closed on cache drift.

### Changed

- DOCX text extraction now preserves paragraph, row, and cell boundaries and includes native equation text; paper audits fail closed on known unrefreshed-TOC placeholders in DOCX or PDF.
- Enhanced Markdown export now injects all inline formulas in a paragraph atomically and exports standalone PDFs through direct Word COM instead of the failing docx2pdf wrapper.

- Windows environment snapshots now discover XeLaTeX and latexmk from bounded TeX Live, MiKTeX, and TinyTeX installation roots when the current process has not inherited the user's updated `PATH`.
- Active environment smoke runs now require an explicit timezone-aware audit timestamp and normalize LibreOffice/XeLaTeX PDF Info, existing XMP creation/modification metadata, and existing `dc:date` values to that authoritative instant before XML and reopen verification.

- A generated `START-HERE.md` case card in `scaffold_case.py`, giving every new case a fixed source-to-finalization sequence and safe manifest/build commands without overwriting existing files.

- Deterministic canonical-result registration guidance: time-limited solver headlines must flow from a declared summary producer into a cached `register-results` step, with derived machine values and paper-display text bound as `build-paper` inputs instead of hand-maintained incumbent snapshots.

- Replay-safe schema v2 guidance for time-limited optimizers: solver steps with feasible-incumbent or timing-sensitive behavior stay non-cached, while only fully declared deterministic downstream steps may cache; workflow-external result-workbook generation remains an explicit non-cached validation boundary.

- Read-only CSV data audit with explicit ID/target/time/group roles, input SHA-256 stability checks, composite-key validation, structured missing/duplicate/non-finite/outlier/correlation/time findings, deterministic evidence files, and no automatic cleaning authority.
- Hash-bound declarative CSV cleaning with a version 1 plan schema, ordered finite operations, expected-change guards, input/plan stability checks, cell/row/schema ledgers, deterministic outputs, and post-cleaning re-audit guidance.
- Row-keyed two-column swaps for reviewed record-level order errors: every selector must exactly match one declared row key, row-key columns cannot be swapped, and each cell-level exchange remains hash-bound and ledgered.
- Manifest-driven data preparation for schema version 2: raw audit, optional reviewed hash-bound cleaning, processed-data audit, evidence-hash cache reuse, passive planning, and fail-closed protection for existing cleaning evidence before ordinary model steps run.
- Backward-compatible multi-CSV data preparation through named `data_preparations`: independent audit evidence and cache entries, aggregate plus per-dataset passive plans, name/output/source collision rejection, and partial-run state persistence.
- Hash-bound XLSX extraction guidance for schema version 2 cached `prepare-*` steps, including raw-workbook inputs, all generated outputs, source-layout rules, source-note text hashes, and row-level ledgers for note-authorized derived records; verified on the 2024 CUMCM C crop-planning practice case.
- Auditable evaluation and prediction baselines adapted from the downloaded package: TOPSIS, entropy weighting, GM(1,1), and regression with explicit random/time/group split semantics. Each runner writes input SHA-256 evidence, structured outputs, and validation summaries.
- GM(1,1) rolling-origin comparison against persistence, positivity and horizon guards, residual/posterior checks, and a model card that treats point forecasts as short-horizon evidence rather than uncertainty intervals.
- Regression model card and baseline with train-only preprocessing, mean baseline comparison, group leakage detection, and a real 2021 CUMCM B attachment-1 group-holdout verification.
- AHP baseline with reciprocal/diagonal validation, RI/CI/CR evidence through order 15, and local pairwise-judgment perturbation records.
- Grey relational analysis with normalization and resolution-coefficient sensitivity, Pearson/Spearman baselines, constant-sequence rejection, and a real 2021 CUMCM B attachment-2 verification.
- Univariate time-series baselines with strict time ordering, expanding one-step validation, persistence comparison, zero-aware MAPE evidence, future point forecasts, and a mechanical verification on the 2025 CUMCM A recovered trajectory.
- Continuous linear programming with named/unit-bearing JSON inputs, HiGHS status handling, original-constraint and bound recomputation, feasible-baseline comparison, RHS sensitivity, and a textbook MATLAB example cross-check.
- Integer and mixed-integer linear programming with continuous/integer/binary variables, incumbent-aware limit handling, recomputed feasibility and integrality, LP-relaxation bounds, MIP gap evidence, feasible-baseline comparison, and a 2024 CUMCM C data cross-check.
- Independent-input Monte Carlo propagation with source-bound distributions, safe arithmetic expressions, fixed-seed repeatability, convergence and replication evidence, separate output quantiles and estimator confidence intervals, Wilson event-probability intervals, and an analytical benchmark.
- Auditable steady-state M/M/1 FCFS simulation with stability rejection, warm-up and run-length evidence, event-time integration, independent-replication confidence intervals, waiting-time tail metrics, Little-law residuals, and analytical cross-checks.
- Auditable bounded continuous nonlinear optimization with safe expressions, fixed-seed multi-start SLSQP, original-constraint recomputation, feasible-baseline comparison, analytical references, and explicit local-optimum claim limits.
- Auditable binary classification with stratified or group holdout, disjoint fit/calibration/test partitions, training-only sigmoid calibration and threshold selection, class-aware and probability metrics, prior-baseline comparison, and leakage evidence.
- Auditable standardized KMeans clustering with candidate-count selection, repeated-seed ARI stability, a one-cluster baseline, deterministic representative labels, cluster profiles, and explicit exploratory claim limits.
- Auditable standardized PCA with deterministic full SVD, cumulative-variance component selection, canonical component signs, scale-risk evidence, mean-reconstruction comparison, detailed reconstruction errors, and no implicit evaluation ranking.

- Workflow schema version 2 with `explore`, `practice`, and `submission` profiles while retaining version 1 compatibility.
- Declared Python inputs and outputs, timeouts, SHA-256 caching, selective resume controls, and forced step execution.
- Rules-freshness and AI-use compliance gates for submission workflows.
- Atomic PDF, rendered-page, report, visual-review, and MATLAB-evidence writes with rollback-oriented fault coverage.
- Draft 2020-12 schemas for workflow manifests, submission compliance, diagnostics, pipeline reports, finalization reports, visual-review records, and MATLAB validation evidence.
- Dependency-free local JSON Schema validation with JSON Pointer errors.
- Passive read-only `doctor.py` diagnostics and a shared version 1 diagnostic envelope.
- Explicit `doctor.py --active-probe` checks for real backend startup and output-directory writability without running case steps.
- Scaffolded `build-paper` steps now receive the same `--case-dir .` argument as analysis steps.
- Practice and submission scaffolds now include a non-destructive Markdown paper source and case-local enhanced DOCX adapter with project-local virtual-environment discovery, confined export-spec resolution, native formulas, TOC, page numbers, and saved Word fields.
- All profiles now scaffold a non-destructive, fail-closed `src/analyze.py` starter so passive plans have a complete entry point while real builds reject unimplemented analysis explicitly.
- Windows LibreOffice discovery now prefers `soffice.com`, and each headless export uses an isolated temporary user profile to avoid GUI-launcher hangs and profile-lock conflicts.
- Added a backend-isolated practice-build lifecycle regression covering result precheck, export, render, and paper-audit ordering.
- `check_skill.py` release gate covering schemas, Python syntax, unit tests, lifecycle smoke tests, historical manifest validation, and passive historical diagnostics.
- End-to-end lifecycle smoke coverage for `explore`, `practice`, and both submission AI statuses.
- Passive `--plan` execution previews with stable cache, evidence, selection, and recovery reason codes.
- Historical quality-gate planning with before/after file-tree metadata checks to enforce read-only behavior.
- Passive workflow v1-to-v2 migration analysis with a validated behavior-preserving candidate, conservative static path hints, explicit human-review decisions, and no automatic edits or cache enablement.
- Historical quality-gate coverage for migration-report validity under the same before/after metadata guard.
- Isolated v1-to-v2 migration rehearsal with minimal explicit-file copying, passive candidate planning, temporary-workspace cleanup, source metadata verification, and per-step human review checklists.
- Historical quality-gate coverage for rehearsal validity, zero blocked candidate steps, and temporary cleanup.
- Closed, hash-bound workflow migration review records covering Python inputs, outputs, timeout, determinism, cache decisions, explicit confirmations, and decision notes.
- Controlled v2 candidate export that reruns isolated rehearsal, rejects stale manifest or script evidence, validates output ownership, writes only explicit new paths, and never replaces `workflow.json`.
- Historical quality-gate coverage for passive migration-review previews and source immutability.
- Hash-bound migration-candidate acceptance reports with exact reviewed-candidate comparison, JSON Pointer diagnostics for unauthorized changes, and passive version 1/version 2 plan-structure equivalence checks.
- Historical quality-gate coverage for migration-acceptance previews, including explicit `evidence_required` versus `not_applicable` states under the source immutability guard.
- Passive cross-case migration readiness reports with source and conservative-candidate hashes, retained diagnostic codes, per-step review evidence, explicit diagnostic-first review-workload ordering, and non-approval semantics.
- Release-gate coverage for readiness ranking, malformed-case isolation, recommendation consistency, and per-case source immutability.
- Hash-bound single-case migration review work packages with enhanced case-relative path candidates, exact output/input relationship candidates, explicit evidence gaps, and all-pending human checklists.
- Release-gate coverage binding the readiness recommendation to its review package while prohibiting review-record creation, candidate export, cache enablement, case execution, and source writes.
- Stdout-only Markdown rendering of the hash-bound migration review work package, including provenance, safety invariants, script bindings, exact relationships, evidence gaps, path evidence, and unchecked human-review items.
- Release-gate coverage requiring the recommended Markdown view to retain every bound hash and pending item while preserving the source case and exposing no approval or file-output behavior.
- Bounded path-provenance tracing through explicit local helpers and case-local imported helpers, with parameter-flow checks, cycle/depth guards, longest-chain deduplication, and direct/local/imported summary counts.
- SHA-256 bindings for support modules reached by imported-helper chains, plus machine and Markdown release-gate coverage that preserves candidate-only, all-pending, non-approval semantics.
- Conservative provenance boundary coverage for cyclic and over-depth helper chains, dynamic and star imports, transformed path parameters, and runtime helper-name rebinding; transformed or shadowed calls are excluded from helper evidence.
- Structured `review_required` trace limitations with stable reason codes and source locations for conservatively unresolved helper branches, kept separate from path candidates, support-module bindings, errors, approvals, and cache decisions.
- Markdown and release-gate coverage for limitation counts, allowed codes, source locations, candidate isolation, and preserved all-pending review semantics.
- Full entry-to-stop call chains for trace limitations, with raw-occurrence and unique-record summary counts plus same-step, same-reason, same-stop conservative suffix deduplication.
- Grouped Markdown limitation review and release-gate coverage that retain different entries, stop points, reason codes, and cycle directions without widening static tracing or changing migration and cache decisions.
- Structured per-step limitation groups keyed by reason code and complete stop point, with raw occurrence and retained unique-chain counts that reconcile exactly to package summaries.
- Stop-point-first Markdown review and release-gate coverage that expose concentrated static-analysis boundaries without assigning severity, priority, approval, dependencies, or cache policy.
- Producer-side semantic validation for limitation chains, step-local groups, raw and unique totals, compatibility counts, and group metadata, with an independent release-gate recheck.
- Schema-valid tampering tests covering altered counts, unmatched stops, duplicate groups, cross-step movement, and summary drift, plus three generations of additive version 1 compatibility.
- A migration review-package stability matrix freezing field meanings, component responsibilities, compatibility generations, and the gate for future contract expansion.
- Byte-repeatability and failure-recovery coverage for review-package JSON and Markdown, including deep Unicode and space-containing paths, stable forward-slash display paths, syntax failures, rejected output arguments, and zero partial artifacts.
- Bounded migration-review static analysis with 1 MiB source, 50,000-node AST, 64-module closure, and 10,000-call-event per-step limits; structural excess fails closed while event exhaustion emits a non-blocking `trace_budget_exhausted` limitation.
- Adversarial fixtures for invalid UTF-8, missing and escaped scripts, absolute and parent paths, optional symlink escape checks, resource exhaustion, machine-readable failure output, and unchanged case trees.
- Inclusive boundary tests for every review-package resource limit, platform-independent path-escape checks, and a fixed CLI status/stream/read-only matrix.
- A normalized release-candidate baseline covering six-case resource headroom, three generations of schema version 1 compatibility, the recommended-case limitation summary, the complete quality gate, and feedback-driven post-freeze maintenance.

### Compatibility

- Workflow schema version 1 remains supported with historical `practice` semantics and without opt-in version 2 caching behavior.
- Output and evidence contracts start at version 1. See `references/versioning-and-compatibility.md`.

### Fixed

- Submission rule freshness now compares date-only verification evidence with the audit host's local calendar date, preventing false future-date failures between local midnight and UTC midnight while preserving rejection of genuinely future dates.
# Unreleased

- Added a declaration-driven paper quality-gate plan and audit covering abstract Q1--Q4 structure, per-subproblem method/result/limitation markers, page-region contracts, complete source-appendix entries, formula-to-code tokens, figure/result bindings, DOCX/PDF metadata and forbidden-path scans, and exact rendered-page PNG continuity.
- Added optional `quality_gate_plan` routing through `workflow.json`, `run_pipeline.py --phase finalize`, and `finalization-report.json` without changing legacy manifests that omit the plan.
- Added anonymous support-package smoke plans and reports with ZIP SHA-256 binding, safe extraction, `shell=False` execution, timeout/exit/output checks, and selected-interpreter mapping for `python` commands.
- Replayed the 2025 E delivery in a temporary copy: all paper quality gates, three packaged core-script smoke tests, and finalization integration passed; the frozen case was not modified.
- Added `doctor.py --active-probe` for explicit, non-modeling startup checks of document/PDF backends and output writability.
- Scaffolded `build-paper` steps now receive `--case-dir .` consistently with analysis steps.
- Added a hash-bound declarative CSV cleaning stage with a version 1 plan schema, ordered finite operations, expected-change guards, input/plan stability checks, cell/row/schema ledgers, deterministic outputs, and post-cleaning re-audit guidance.

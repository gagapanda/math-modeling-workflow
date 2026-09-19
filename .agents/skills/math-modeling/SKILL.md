---
name: math-modeling
description: Run an evidence-driven mathematical-modeling workflow for CUMCM, the China Graduate Mathematical Modeling Contest, MCM/ICM, practice problems, and modeling papers. Use when Codex must interpret a modeling problem, audit supplied data, route the problem to suitable models, implement Python or MATLAB solutions, validate and compare results, produce figures, write or review a LaTeX/Word paper, search this project's modeling library, or prepare a compliant competition submission.
---

# Mathematical Modeling

## Public Staging Scope

This candidate distribution includes general workflow helpers, schemas and generic templates, not a complete verified paper-production environment. Read the repository `docs/migration-status.md` before executing build steps. The private Word exporter, downloaded LaTeX template/fonts, historical cases, private library and companion Skills are not bundled. Use only tools actually available; unavailable features must be reported as unavailable, not silently substituted or marked passed. Historical rule descriptions require fresh official verification during an actual contest. Public staging is not release authorization.

## Public Word/PDF Backend

For Markdown-to-Word/PDF work in this public candidate, read [paper-export.md](../../../docs/paper-export.md). Use the public build adapter and an explicitly selected document Python. Preserve native inline/table equations, the author-written symbol table and visible equation numbers; inspect every final PDF page, not just extracted text. Export manifests and AI page observations are supporting evidence only: never treat them as human M6 approval or submission readiness. The legacy exporter, downloaded templates/fonts and their authorization are not included. Existing whole-case PDF steps are not automatically replaced by this optional backend.

## Core Contract

Treat the deliverable as a traceable chain:

`problem -> assumptions -> data -> model -> algorithm -> result -> validation -> conclusion`

Do not optimize for impressive method names. Prefer the simplest defensible baseline, then add complexity only when evidence shows a material benefit. Keep every reported number reproducible from source data and code.

## Competition-First Improvement Loop

Treat this project as a continuously improving competition system. Historical practice, material review, model experiments, paper revisions, and postmortems should feed reusable improvements back into the live-competition workflow whenever the evidence supports them. Prefer durable changes to Skills, references, templates, scripts, tests, quality gates, and verified cases over one-off answers.

For every substantial task, ask whether it improves competition-time correctness, speed, reliability, reproducibility, compliance, or submission quality. At completion, identify any reusable lesson and integrate it when the benefit is clear and the change is within scope. Do not absorb downloaded methods, code, templates, or claims without provenance, execution or structural checks, and compatibility review.

Competition-first does not mean optimizing for superficial complexity, page count, or speed. Mathematical correctness, source fidelity, official rules, academic integrity, anonymity, AI disclosure, and reproducibility remain hard constraints. During a live competition, the current official rules override historical practice and downloaded guidance.

## Classify The Request

Determine the operating mode before substantive work:

- **Learning**: explain a model, compare methods, or recommend study material. Do not create case files unless asked.
- **Practice**: solve or review a historical problem. Permit experimentation, but preserve provenance and validation.
- **Live competition**: work on an active competition problem. Load current official rules, obey collaboration restrictions, and maintain an AI-use record before producing submission content.
- **Paper review**: inspect an existing solution for mathematical correctness, data flow, reproducibility, writing quality, and rule compliance. Lead with consequential defects.

Ask only for information that changes the modeling direction. Infer discoverable facts from the problem statement, attachments, workspace, and official sources.

For a first-pass route, emit the contract in `references/integration-routing.md`: classify the operating mode, extract structural signals, list missing information, name a transparent baseline, compare candidate model families, bind each candidate to a validation method, and state the next action. Routing is advisory; it must not execute a model or claim a result before the normal workflow has been established.

For manifest-driven case work, select the narrowest `workflow.json` profile that matches the deliverable:

- `explore`: run configured analysis steps only; paper artifacts, full environment preflight, model-definition closure, export, and finalization are not required.
- `practice`: run the reproducible paper workflow and normal quality gates. This is the schema v1 compatibility default.
- `submission`: add the complete M6 path for current official rules, anonymity, citations/external data/software licenses, AI disclosure, support allowlist, and an immutable real-human decision. Build may perform the technical precheck before human M6; finalization must wait for an accepted human M6 manifest.

Do not label a practice run as submission-ready merely to obtain a stronger-looking report.

## Load References Selectively

- Read [competition-readiness-roadmap-2026.md](references/competition-readiness-roadmap-2026.md) when planning pre-contest improvements, deciding whether downloaded material should enter the production workflow, auditing tool readiness, or scheduling rehearsals and the feature freeze.
- Read [failure-prevention.md](references/failure-prevention.md) after a blocked build, paper export, permission issue, or quality-gate failure; inspect the latest case-local `rehearsal/failure-events.jsonl`, record the incident, and promote verified fixes into scripts, tests, templates, or case runbooks.
- Read [local-library.md](references/local-library.md) when searching or choosing local material.
- Read [model-routing.md](references/model-routing.md) after extracting the problem structure and before selecting methods.
- Read [integration-routing.md](references/integration-routing.md) when the user needs a first-pass task classification, a beginner-friendly next step, or a mapping from problem structure to model families.
- Read [integration-asset-inventory.md](references/integration-asset-inventory.md) only when evaluating or extending the downloaded sales package; it is not required for ordinary case execution.
- Read [integration-validation.md](references/integration-validation.md) when checking what has already been integrated, installed, and verified from the downloaded package.
- Read [independent-validation.md](references/independent-validation.md) when calibration evidence is narrow and new measurements, a holdout protocol, or prediction claims must be handled without leakage.
- Read [data-audit.md](references/data-audit.md) before cleaning supplied tabular data or routing it to a model.
- Read [data-cleaning.md](references/data-cleaning.md) when a reviewed audit finding requires a deterministic data change.
- Read [model-card-index.md](references/model-card-index.md) after routing to a supported model family, then load only the selected model card. Use [model-card-contract.md](references/model-card-contract.md) when creating or revising a card.
- Read [model-card-curve-analysis.md](references/model-card-curve-analysis.md) before using `scripts/model_baselines/curve_analysis.py` for a univariate interpolation-range curve comparison. Keep candidate selection on the development set, reserve the independent test set for final evaluation, and distinguish polynomial parameter intervals, mean-response intervals, and single-observation prediction intervals.
- Read [model-card-ols-diagnostics.md](references/model-card-ols-diagnostics.md) before using `scripts/model_baselines/ols_diagnostics.py` for continuous-response OLS association and inference. Declare covariance before inspecting results, keep HC3 and cluster boundaries explicit, review rather than auto-delete influence points, and route prediction claims to the separate prediction baseline.
- Read [competition-compliance.md](references/competition-compliance.md) for live competitions, official templates, AI use, eligibility questions, and the complete M6 evidence boundary. The legacy `audit_submission_compliance.py` proves only rules-and-AI technical checks, not full M6.
- Read [paper-production.md](references/paper-production.md) when generating or revising Word/PDF papers.
- Before a local DOCX formatting repair, use the base-hash-bound allowlist in `paper-production.md` and `scripts/audit_docx_local_format.py`; reject unrelated size/bold, formula or shared-style drift before candidate promotion. This read-only check does not replace re-export or final full-page review.
- Read [paper-abstract-writing.md](references/paper-abstract-writing.md) whenever drafting, compressing, or reviewing a competition-paper abstract. Complete the case-local `paper/abstract-evidence.md` from the current frozen result register and body evidence before finalizing the abstract; use the abstract-only reconstruction and cross-position reconciliation checks, but do not treat AI review as an independent evaluator or human gate.
- Read [paper-expression-quick-card.md](references/paper-expression-quick-card.md) when drafting or compressing competition-time question-by-question paper text; keep the detailed rules and evidence boundaries in [paper-production.md](references/paper-production.md).
- Read [paper-evidence-storyboard.md](references/paper-evidence-storyboard.md) before a full question-by-question draft when the answer, formulas, figures, validation, and limits need to be organized as one evidence chain; keep the detailed production rules in [paper-production.md](references/paper-production.md).
- Read [paper-claim-figure-innovation-card.md](references/paper-claim-figure-innovation-card.md) when promoting a core claim, figure/table, model choice, or innovation description into the abstract, body, conclusion, or recommendation; require claim-to-evidence mapping and distinguish algorithmic innovation from evidence-chain/application integration.
- Use downloaded LaTeX template (not bundled; see references/paper-production.md) only when the responsible human operator or team deliberately selects the controlled XeLaTeX path for a 2026 CUMCM practice or submission paper. Keep the case paper as the authoritative source; copy the template into the case rather than editing the Skill asset in place.
- Read [visual-review-context.md](references/visual-review-context.md) before loading rendered paper pages or other image batches into the conversation.
- Read [submission-checklist.md](references/submission-checklist.md) when drafting, reviewing, or finalizing a paper.
- Read [workflow-automation.md](references/workflow-automation.md) when starting a case, registering result values, or running final gates.
- Read [result-workbook-qa.md](references/result-workbook-qa.md) when a final `.xlsx` result template or support workbook must be checked against required sheets, critical cells, saved formula caches, number formats, and the canonical result register.
- Read [timed-rehearsal.md](references/timed-rehearsal.md) before a timed practice or full simulation and while recording its timeline, failures, rework, fault recovery, scorecard, and improvement decisions.
- Read [post-contest-harvest.md](references/post-contest-harvest.md) after a competition or full rehearsal when local evidence should be converted into durable workflow improvements. Keep observed facts, human recollection, inferred causes, and adopted controls separate; never backfill unrecorded gate approvals or upload facts.
- Read [single-operator-live-runbook.md](references/single-operator-live-runbook.md) when one responsible human operates Codex Desktop and the canonical workspace during a live route or rehearsal; use its compact gate, freeze, deadline-degradation, recovery, packaging, and honest single-person review rules.
- Run `scripts/audit_authority_heartbeat.py` after result, paper, or package authority changes and when resuming a case. Treat its errors as pointer-consistency blockers, while remembering that a clean heartbeat does not prove any modeling, human, compliance, or submission gate.
- Prefer `scripts/mm.py` as the human-facing entry point for `start`, `status`, `check`, `freeze`, and `package`; it remains a thin delegator, so the underlying tool contracts and real-human gates stay authoritative.
- Use `scripts/manage_candidates.py` through `mm candidate` to register and explicitly transition result, paper, and support candidates. Use `retained` for non-current component or audit evidence that is neither a displaced standalone candidate nor safe to discard. A post-contest inventory may initialize an empty registry atomically with `candidate import-plan`; it still does not move or delete artifacts. Never infer current status from filenames or modification times, and never treat registry selection as F1, M6, M7, or F2 approval.
- Read [environment-and-recovery.md](references/environment-and-recovery.md) when auditing, changing, freezing, rebuilding, or recovering the competition machine environment.
- Read [versioning-and-compatibility.md](references/versioning-and-compatibility.md) when changing manifests, generated reports, evidence records, diagnostics, or release policy.
- Read [migration-review-package-stability.md](references/migration-review-package-stability.md) before changing the workflow migration review package, limitation tracing, aggregation, renderer, or release checks.
- Read [migration-review-package-release-baseline.md](references/migration-review-package-release-baseline.md) when evaluating resource-limit changes or release-candidate drift.
- Read [matlab-integration.md](references/matlab-integration.md) when implementing or validating MATLAB code or adding MATLAB steps to `workflow.json`.

Never load textbooks or large paper collections wholesale. Search filenames first, then inspect only the relevant problem, matching papers, and method references.

For a scanned or otherwise non-searchable paper, create a bounded selected-page plan and run `scripts/prepare_pdf_evidence.py` rather than OCRing the whole document. Keep the source PDF read-only, bind it and every rendered page by SHA-256, and treat native text or OCR output only as retrieval candidates. The MATLAB helper `scripts/matlab/ocr_selected_pages.m` requires an explicit model; never rely on its English default for Chinese pages. Use `scripts/ocr_selected_pages_tesseract.py` for a hash-bound Tesseract run with an explicit executable, tessdata directory, language, OEM, and PSM. The pinned Tesseract 5.4.0 `tessdata_best` `chi_sim` configuration passed the A196 Chinese-prose sample but failed the formula-feature gate, so it may support bounded prose retrieval on visually comparable pages and must not transcribe formulas. Score every new backend, model, or layout with `scripts/score_ocr_benchmark.py`; require separate `body_text_retrieval` and `formula_retrieval` decisions rather than promoting an overall backend from prose accuracy alone. The actual responsible human reviewer/operator must visually confirm every selected page and every accepted formula in a schema-valid review before `scripts/release_pdf_evidence.py` may create an evidence card. A verified transcription proves only what the page states; mathematical correctness, applicability, and adoption still require problem-specific review.

Before executing an unfamiliar case, prefer the passive `scripts/doctor.py` check described in `workflow-automation.md`. It validates declared structure, inputs, modules, and backend discovery without running case steps or writing case files. Treat its backend findings as discovery only; the real build preflight performs active startup and writability probes.
Use `scripts/run_pipeline.py --plan` when deciding whether to build or resume. It explains the optional `data_preparation` gate, step selection, cache hits and invalidation, MATLAB evidence status, and post-processing intent without starting tools, executing case code, or writing case files.
For a schema version 1 case, run `scripts/analyze_workflow_migration.py` before considering version 2. It emits a conservative, read-only candidate that preserves `practice` behavior with caching disabled, plus separately labeled static path hints that require human review. It never edits the manifest or enables caching.
Use `scripts/rehearse_workflow_migration.py` to validate that candidate in an isolated temporary case. It copies only manifest-declared scripts and MATLAB evidence-chain files, produces a per-step human review checklist, runs validation and passive planning without case execution, removes the temporary case, and verifies the source case stayed unchanged.
Use `scripts/review_workflow_migration.py` after rehearsal to generate a hash-bound human-review template, validate completed Python dependency, timeout, determinism, and cache decisions, and export a new version 2 candidate. The tool reruns rehearsal, rejects stale manifest or script hashes, never executes case code, never overwrites an existing file, and does not replace `workflow.json`.
Use `scripts/audit_workflow_migration_candidate.py` to accept or reject an exported candidate against its completed review record. The passive auditor recomputes the unique reviewed candidate, reports unauthorized differences by JSON Pointer, and compares version 1 and version 2 plan structure without executing or installing either manifest. A preview status of `evidence_required` means that review and candidate evidence are missing; it is never migration acceptance.
Use `scripts/summarize_workflow_migration_readiness.py` to compare version 1 cases before choosing one for human migration review. It prioritizes cases without current passive diagnostic errors, then ranks mechanical review workload and static-analysis availability, preserves source hashes and expected candidate hashes, and isolates malformed cases. The ranking does not assess model correctness, paper quality, cache safety, or migration approval and never replaces existing case diagnostics.
Use `scripts/prepare_workflow_migration_review_package.py` for the selected version 1 case before creating a formal review record. It binds the source manifest, conservative candidate, entry scripts, and any traced case-local support modules; expands case-relative path candidates; and records direct, local-helper, and imported-helper provenance for a bounded set of static call chains. When that tracer stops at a conservative boundary, it records the full entry-to-stop chain in a located `review_required` limitation without guessing a path or dependency. Within each step it removes only identical limitations and shorter complete-chain suffixes with the same reason and stop point, while reporting both raw occurrences and unique limitations. It also groups those records by reason code and complete stop point so reviewers can compare raw occurrences with retained call chains without losing distinct entries. It reports exact output/input path matches and evidence gaps while leaving all dependency, timeout, determinism, and cache decisions pending. The package is review preparation only and never creates or completes the human review record.
Use `scripts/render_workflow_migration_review_package.py` with the same expected hashes when a person needs a readable review view. It regenerates and validates the package, renders every binding, support-module hash, provenance chain, limitation group and full call chain, path candidate, exact relationship, gap, and pending checklist item to stdout, and has no file-output option. The Markdown is still evidence preparation, not a completed review record or migration approval.

## Execute The Workflow

### 1. Establish The Contract

Extract and record:

- required outputs for every subproblem;
- decision variables, objectives, constraints, units, and time/space scales;
- supplied files and the role of each file;
- evaluation criteria, required result templates, and submission rules;
- ambiguities that materially affect the solution.

For a multi-subproblem task, also record a question-dependency table before model routing. For every subproblem, identify its inputs, decision variables, objective, constraints, required outputs, and any dependency on earlier results. Draw a relationship diagram only when it represents a real dependency and does not replace the formal definitions.

Complete `problem/model-definition-register.json` before optimization. For every
materially plausible interpretation, register a primary definition, an alternative,
same-strategy comparison evidence, and a materiality decision. If the difference is
material, optimize under the alternative definition and disclose the definition risk
in both final paper artifacts. Read [model-definition-gate.md](references/model-definition-gate.md).

Restate the problem operationally. Do not copy the prompt as analysis.

### 2. Audit Data Before Modeling

Inspect schema, units, types, ranges, missingness, duplicates, outliers, temporal order, identifiers, and leakage risks. Preserve raw inputs. Put deterministic cleaning in code and write processed data separately. When an official input arrives inside ZIP, RAR, or 7z, preserve and record the container path and SHA-256 separately from every extracted member path and SHA-256 used by code, together with the extraction method/time. Never bind an extracted member to the container hash or rely only on a temporary extraction path.

For CSV input, use `scripts/data_audit.py` to create a hash-bound, read-only first-pass audit after declaring ID, target, time, and group columns. Resolve every blocker before modeling and review all warnings; `ready_for_modeling=true` means only that the declared mechanical checks found no blocker. The audit never authorizes automatic deletion, imputation, clipping, type conversion, or a leakage conclusion. Read [data-audit.md](references/data-audit.md).

When a reviewed finding requires a data change, use `scripts/data_clean.py` with a version 1 plan that matches `schemas/data-cleaning-plan.schema.json`. Bind the source SHA-256, give every ordered rule a reason and an independently reviewed `expected_changes`, write to a new output directory, and retain the cell, row, and schema ledgers. Any hash, column, rule, or expected-count mismatch must fail before outputs are written. Re-run `data_audit.py` on `processed.csv` before model routing. The cleaning ledger proves execution, not scientific justification. Read [data-cleaning.md](references/data-cleaning.md).

For image, video, PDF, Word, or spreadsheet inputs, invoke the corresponding file skill and follow its verification requirements.

### 3. Route Models By Structure

Use [model-routing.md](references/model-routing.md). Produce a short candidate table containing assumptions, expected strengths, failure modes, data needs, and validation method.

Choose:

1. one transparent baseline;
2. one primary model justified by the problem structure;
3. an alternative only when it tests a meaningful modeling choice.

### 4. Derive Before Coding

Define symbols and units. Maintain an explicit assumption register and distinguish official facts, measured inputs, simplifying assumptions, and parameters requiring estimation. State the objective, constraints, dynamics, statistical assumptions, or loss function. Check dimensional consistency and boundary conditions. Identify parameters that must be estimated rather than silently chosen.

For spatial or dynamic models, lock the coordinate system, axis directions, time origin, units, object indices, initial states, and position/velocity conventions before deriving trajectories. Plot or tabulate the initial state as an input check, while keeping data audit and independent numerical recomputation as separate requirements. For lead-time, lagged-state, inventory-pipeline, or delayed-control models, write an information-availability table for every initialization value. A problem-statement exception for one lead time or one boundary period must not be generalized to other lead times. If any startup state uses future realized demand or another value unavailable at the decision time without explicit authorization, label all dependent results `DO_NOT_FREEZE`; for `L>=2`, replay the startup period separately after fixing the initial inventory, in-transit pipeline, and lag history.

### 5. Implement Reproducibly

Use established libraries for optimization, statistics, graph algorithms, machine learning, differential equations, and numerical methods. Fix random seeds when randomness is not itself the subject of study. Separate inputs, transformations, model code, and outputs.

Prefer Python for auditable data pipelines and broad library support. Use MATLAB when the supplied material, operator/team capability, or existing implementation makes it the clearer choice. Do not translate working code merely for uniformity.

For MATLAB work, use the MATLAB MCP to run Code Analyzer, execute the final script, and run `matlab.unittest` tests. Then create hash-bound evidence with `record_matlab_validation.py`; the local pipeline verifies that evidence before accepting MATLAB outputs. Use direct `matlab -batch` steps only after batch startup succeeds on the current machine.

### 6. Validate Before Interpreting

Match validation to the claim:

For models calibrated from a narrow historical source, read [independent-validation.md](references/independent-validation.md) before treating fit quality as predictive evidence. Preserve new source data, compare held-out observations with fixed calibration parameters, and state validation as pending when independent observations do not exist.

- optimization: feasibility, constraint residuals, bounds, optimality gap or multi-start consistency;
- multi-objective optimization: independently recomputed feasibility and nondominance, objective scaling, fixed-seed Pareto stability against a bound reference, and preference-sensitive compromise selection; use scripts/model_baselines/multi_objective_optimization.py only after loading its model card;
- prediction: held-out or rolling-origin evaluation against a naive baseline; when rows are repeated measurements, time-linked observations, or records nested within a person, device, site, route, or other deployment unit, define the prediction target, grouping unit, and deployment unit before splitting. Keep imputation, scaling, feature selection, and fitting inside each fold; use grouped or temporal validation that withholds the deployment unit rather than random row-level cross-validation. Report aggregate gain together with per-group failure structure, target-domain checks, interval construction and coverage semantics, and whether the gain materially changes the target decision. For a conditional scenario, disclose the source and sample size of the changed inputs, whether the model was refit, and an observable acceptance or stopping rule; do not restate the scenario as an intervention effect or training guarantee. Keep candidate-comparison evidence separate from any post-selection final fit: freeze the analysis/deployment unit, split or time window, fold-local preprocessing, metric and aggregation, candidate set, selection rule, and tuning budget; select only from the comparison evidence; if the selected structure is refit on all allowed training data, label its parameters or target outputs as final-fit outputs rather than unbiased validation performance, and reopen the freeze if any comparison or final-fit contract changes;
- univariate curve fitting/interpolation: load `references/model-card-curve-analysis.md` before using `scripts/model_baselines/curve_analysis.py`; compare only predeclared candidates including the linear baseline, select on development-set cross-validation with the one-standard-error rule, reserve the independent test set for final evaluation, inspect residuals, distinguish parameter/mean-response/prediction intervals, and restrict claims to the observed development range;
- continuous-response association and inference: load `references/model-card-ols-diagnostics.md` before using `scripts/model_baselines/ols_diagnostics.py`; declare classic, HC3, or cluster covariance in advance, inspect specification, heteroskedasticity, collinearity, residual and influence evidence, and never infer causality or out-of-sample prediction from the in-sample fit;
- classification: class-aware metrics, calibration, and leakage checks;
- simulation: conservation checks, limiting cases, convergence, and repeated runs;
- differential equations: load references/model-card-ode-system.md before using scripts/model_baselines/ode_system.py for an ODE initial-value system; verify initial conditions, units, independently derived invariants or closed-form references when available, and tolerance and maximum-step sensitivity; route PDEs, boundary-value, delay, stochastic, event-dense, and parameter-calibration problems elsewhere;
- evaluation/ranking: weight sensitivity, rank stability, and alternative normalization;
- graph/routing: path feasibility and recomputed cost from original edge data.
- graph/network: load references/model-card-graph-network.md before using scripts/model_baselines/graph_network.py; verify edge semantics, path continuity and recomputed cost for shortest paths, or edge capacities, node conservation, source/sink balance and max-flow/min-cut equality for maximum flow.

Run sensitivity or robustness analysis on assumptions that can change the conclusion. Report failure cases and uncertainty.
Treat definition sensitivity separately from numerical sensitivity. A converged solver
does not validate the meaning of the objective, target, boundary, coverage rule, time
window, aggregation rule, or uncertainty convention.
For any aggregate metric over heterogeneous groups, predeclare the atomic unit, denominator, and weighting rule. If defensible macro/unweighted and micro/volume-weighted definitions can change the model choice or conclusion, compute and register both, declare the paper's primary interpretation, and treat the difference as definition sensitivity rather than selecting the more favorable value after inspection.

#### Freeze Results Before Formal Claims

During a live route or full rehearsal, use the F1 contract in [single-operator-live-runbook.md](references/single-operator-live-runbook.md): complete `results/f1-freeze-plan.json`, prepare a hash-bound `F1_PENDING_HUMAN` candidate with `scripts/freeze_results.py`, obtain the actual responsible human decision, finalize to a new immutable manifest, run `verify`, and update `CURRENT-STATE.md`. `prepare` and `verify` never substitute for the human gate. Formal numbers and claims become paper-authoritative only when the accepted verified manifest, its bound current result register, and the current-state pointer agree. Any frozen-scope change requires `F1_THAW`, preservation of the old manifest as superseded evidence, and a new freeze ID.

### 7. Build The Paper From Evidence

Start writing once the first subproblem has a stable model. Keep each section connected to executable evidence. Put the direct answer to every subproblem near its result, not only in the conclusion.

Treat a requested full paper as a competition paper, not as a concise technical report. Before the substantive model sections, require a readable standalone Symbols and Units subsection for repeatedly used global indices, inputs, decision variables, state variables, parameters, and evaluation metrics; include units or domains and add index ranges or information timing when material. Define one-use local quantities at first use instead of bloating the table. For every substantive subproblem, produce the shortest defensible chain of problem transformation, definitions and assumptions, core derivation, transparent baseline, main model or justified improvement, algorithm, result, comparison or diagnostic, interpretation, validation and boundary, and direct answer. A step may be omitted only when genuinely inapplicable; never replace a missing derivation, baseline, or validation with a method name. Also include the cross-cutting data audit, assumptions with reasons, sensitivity or robustness analysis, limitations, references, support-file inventory, and complete runnable code appendix required by the current rules. Do not collapse these into a few summary paragraphs merely because the numerical result is already available.

## Evaluator-Facing Paper Narrative Contract

When an evidence-complete draft still reads like a checklist, use [paper-narrative-rewrite.md](references/paper-narrative-rewrite.md) for concrete prose transformations, without adding stages or inventing results.

A competition paper is written for a reviewer to understand and score, not only for an auditor to trace. Treat the following as a reusable acceptance contract for every future full paper; use the detailed compression and topic adapters in [paper-expression-quick-card.md](references/paper-expression-quick-card.md) rather than inventing a new style for each case.

For every substantive subproblem, the body must let a reviewer reconstruct this reasoning without opening the appendix:

```text
题目要求与现实对象
-> 问题转化与预测/决策对象
-> 数据结构、分析单位和信息时点
-> 假设与定义（说明为什么这样定义）
-> 符号、单位和核心公式推导
-> 透明基线与候选方法
-> 选择理由（证据、复杂度、适用边界）
-> 算法或求解步骤
-> 结果与表/图的直接解读
-> 验证、敏感性或失败结构
-> 结论边界与对下一问的承接
```

The chain is evidence-driven, not a demand for a fixed number of formulas, figures, pages, or models. Omit only a genuinely inapplicable step and state why. A method name, a result table, or a code reference cannot substitute for a missing definition, derivation, comparison, interpretation, or validation. For sparse data, increase explanatory and comparative depth—statistical-unit reasoning, individual/group heterogeneity, uncertainty, robustness, and limitation-specific decisions—without inventing observations, precision, or complexity.

Apply these writing rules:

- Put a standalone **Symbols and Units** subsection before substantive model sections. Define repeatedly used indices, inputs, decision/state variables, parameters, metrics, domains, units, and information timing; define one-use intermediates locally.
- Introduce every material equation with its purpose, define all new symbols, and explain what the equation makes observable or computable. After the equation, interpret the result and state its valid scope; do not paste formulas without a derivation or decision role.
- For clustered, repeated, temporal, or paired data, explain why the analysis unit, aggregation, split, and validation match the claim. Never present row-level sample size as independent evidence when the deployment unit is a person, device, site, or time block.
- Compare a transparent baseline with predeclared candidates when model choice is material. Explain the incremental information supplied by each candidate, the cost of added complexity, and why the selected model is adequate—not merely that it has the smallest score.
- Give every material table and figure one job. The caption identifies the object and unit; the surrounding prose states what question it answers, which evidence supports the claim, and what it cannot prove. Use tables for exact comparable values, figures for relationships/diagnostics, and equations for the model itself.
- Keep body prose reviewer-facing. Move hashes, field paths, generator commands, internal manifests, and exhaustive audit navigation to appendices or evidence records unless they are needed to understand the method. Do not let audit metadata replace technical narrative.
- Distinguish observation, association, prediction, conditional scenario, intervention, and causal effect. Do not turn a conditional prediction into a training guarantee, a random row split into new-person generalization, or a correlation into causality.
- End each subproblem with a direct answer, evidence level, limitation, and—when applicable—the exact input or frozen result passed to the next subproblem. Freeze results before writing formal numerical claims; if a material model/data/validation change occurs, thaw, recompute, and refreeze.

Before calling a full paper expressive enough, run the **reviewer reconstruction test**: from the main text alone, can a reviewer answer (1) what was modeled, (2) why the variables and statistical unit were chosen, (3) why this model beat or was preferred to alternatives, (4) what each table/figure proves, (5) what validation actually tested, and (6) where the conclusion stops? If any answer requires the appendix merely to recover the reasoning, revise the main text. This test does not authorize padding; it is a narrative completeness gate alongside mathematical, reproducibility, visual, and compliance gates.
For Markdown-to-Word production, do not assume inline LaTeX inside a symbol table renders as mathematics. Use export-safe notation unless table math has been verified, then inspect the final DOCX/PDF. For a mechanism- or geometry-heavy subproblem, close the local chain from real object and coordinates/time through geometry or physical mapping, state closure, event or constraint logic, numerical update order, mechanism evidence, result, and convergence or definition boundary. When a candidate paper receives a local expression-only repair after export, preserve the pre-repair authoritative source, classify the diff, rebind current source/DOCX/PDF hashes, and invalidate any old PDF-bound visual or delivery evidence; a diff limited to symbol rendering does not imply a model or result change, while any data/code/result/validation change requires thaw, recomputation, and refreeze. For a constrained optimization subproblem, make the local paper chain explicit enough to audit the decision variables and domains, objective and constraints, a transparent feasible baseline, search hierarchy and optimizer status, independent final-precision feasibility recomputation, active constraints, candidate comparison, robustness or sensitivity cost, and the optimality boundary. Reject a lower-objective candidate when recomputed margins are negative; never rewrite `success=false` or an iteration limit as convergence. For multi-objective work, recompute feasibility and nondominance at final precision, disclose scaling and the compromise-selection rule, and do not present a singleton final nondominated set as a continuous Pareto front. Add a local symbol table only for new or repeatedly used quantities, and keep it consistent with the global Symbols and Units section. Render structured display mathematics such as fractions, roots, integrals, sums, matrices, piecewise definitions, or nested scripts with native LaTeX mathematics, Word OMML, or another verified math engine; centered Cambria Math or other plain text is a degraded fallback, not professional equation completion. Any formula-rendering change is layout-sensitive and invalidates prior page-count and visual-review evidence. After any figure or table insertion, deletion, or movement, reconcile unique numbering, captions, body references, units, legends, and claim binding on the rendered pages. Figures and tables should explain model necessity, comparison, parameter effects, credibility, decision meaning, or failure boundaries rather than merely show that a step was run. A mechanism figure must expose a specific geometry-to-state mapping, event trigger, active constraint, computation relation, or mechanism-to-result check; a generic decorative flowchart does not satisfy this requirement.

Audit page accounting by section boundary rather than total PDF length. Record the abstract/front matter, main-text pages, references/declarations, and appendix pages separately. Page count is not a quality target: never pad prose, duplicate figures, enlarge spacing, or paste irrelevant code to imitate a long paper. Conversely, a multi-subproblem `practice` or `submission` paper with fewer than 15 main-text pages is a completeness warning that requires a section-by-section justification in `paper/qa-register.md`; it must not be called a full paper only because it exports successfully. For 2026 CUMCM, the current snapshot caps the main text after the abstract at 30 pages while appendix length is unrestricted; verify the live official rule before submission. As a planning calibration rather than a gate, evidence-rich full solutions commonly use roughly 18-28 main-text pages, with complete code and supporting material in appendices.

Use figures for relationships and diagnostics, tables for comparable records, and equations for the actual model. Avoid decorative diagrams and unexplained algorithm listings.

Maintain one authoritative paper source. Generate DOCX and PDF from that source, then apply [paper-production.md](references/paper-production.md). Never treat successful export as proof of correct layout: render every final page to images and inspect all pages after the last layout-sensitive change. Apply [visual-review-context.md](references/visual-review-context.md) so page inspection is batched and does not exhaust the conversation context.
For the CUMCM Markdown-to-Word route, omit the table of contents by default because the reviewed 2026 format snapshot says the main text has no directory; enable one only when another competition's current reviewed rules permit or require it. If DOCX-to-PDF export fails, use the bounded Word/LibreOffice fallback card in [environment-and-recovery.md](references/environment-and-recovery.md), then rerun every downstream PDF, metadata, reconciliation, render, visual-review, finalization, and package gate.

For an optional LaTeX path, use only a separately reviewed template permitted for the current contest. The private controlled class, fonts and derived template are not bundled. Preserve the required document order, keep the table of contents disabled when the rules require it, and repeat the complete page-region and visual review after every layout-sensitive change. Current official rules override every historical template or checklist.

### 8. Close The Loop

Re-run the complete pipeline from preserved inputs. Reconcile all headline values, figures, tables, and result-template files with generated outputs. Apply [submission-checklist.md](references/submission-checklist.md) and the current official rules.
Before packaging, scan paper and support filenames, archive paths, extractable text, and document metadata for configured identity terms and local absolute paths. Record non-extractable binary formats as a manual-review limitation; ZIP construction or CRC success is not an anonymity pass.
For every submitted `.xlsx`, run the hash-bound read-only audit in [result-workbook-qa.md](references/result-workbook-qa.md), then open that exact workbook in Excel or LibreOffice and inspect every worksheet visually. A passing mechanical report does not replace formula recalculation, visible-layout review, or model validation.

Keep finalization and upload packaging separate. After `paper/finalization-report.json` reports `ready_for_submission=true`, create a case-local plan matching `schemas/submission-package-plan.schema.json` and run `scripts/package_submission.py`. Declare every support file explicitly; never recursively archive a case directory. The packager binds the current paper to finalization, rechecks required compliance evidence, validates names, paths, aliases, size limits and configured anonymity terms, builds a deterministic ZIP with an internal SHA-256 manifest, reopens and extracts it in a temporary directory, and commits the paper, support ZIP and report as one managed transaction. Read [workflow-automation.md](references/workflow-automation.md) before using `--replace`.

For a timed practice or simulation, initialize `scripts/manage_timed_rehearsal.py` from a reviewed plan before starting substantive work, append events with stable case-local evidence as they occur, and close the record using the required nine-item scorecard and explicit improvement decisions. The plan, event log, and closure review are independently versioned and hash-bound. Record closure means only that the rehearsal evidence is complete; it never substitutes for model validation, paper review, finalization, or packaging. Read [timed-rehearsal.md](references/timed-rehearsal.md).

## Run Paper And Delivery Quality Gates

For a completed multi-subproblem paper, create a case-local declaration using
`schemas/paper-quality-gate-plan.schema.json`. It should bind the abstract Q1--Q4
markers, each subproblem's method/result/limitation markers, page regions, complete
source-appendix files and hashes, formula-to-code bindings, figure claims to result
IDs, and DOCX/PDF anonymity rules. Run:

```powershell
python scripts/audit_paper_quality_gates.py --case-dir <case-dir> `
  --plan paper/quality-gate-plan.json --json
```

Set `quality_gate_plan` in a schema-version-2 `workflow.json` to make
`run_pipeline.py --phase finalize` invoke this gate and bind its report into
`paper/finalization-report.json`. The plan is optional for compatibility, but when
present a failed quality gate keeps `ready_for_submission=false`.


For new practice and submission cases, keep `paper/paper-authority-plan.json` in `draft` mode and retain `NON_AUTHORITATIVE REVIEW DRAFT` in the paper source and generated artifacts until the responsible human has accepted F1. After `freeze_results.py verify` passes and `CURRENT-STATE.md` names the same accepted manifest, result register, and paper source, switch the plan to `authoritative`, remove the marker, rebuild, and finalize. `audit_paper_authority.py` enforces this M5 entry when the workflow declares `paper_authority_plan`; it never signs or substitutes for the human F1 decision. Legacy workflows that omit the plan remain compatible but do not thereby prove an F1-to-M5 authority chain.

For an anonymous support ZIP, declare core script smoke tests with
`schemas/support-smoke-plan.schema.json` and run:

```powershell
python scripts/audit_support_package.py --package <support.zip> `
  --plan support-smoke-plan.json --json
```

The smoke runner validates archive paths, extracts only to a temporary directory,
uses `shell=False`, maps the plan's `python` entry point to the selected interpreter,
checks exit codes/timeouts/expected outputs, records stdout/stderr hashes, and binds
the report to the ZIP SHA-256. It is complementary to `package_submission.py`: the
packager proves allowlist, anonymity, size, manifest and extraction integrity; the
smoke runner proves that declared core scripts execute from the packaged tree. For a
submission route this replay is mandatory after each selected package build: run the
case's main packaged entry point from the extraction root, declare its core outputs,
and keep every archive path required by case-relative input lookups. A package that
extracts cleanly but flattens or relocates an input is a failed package and cannot enter
M7 precheck.

## Handle Live Competition AI Use

For a live CUMCM case, treat AI disclosure as part of the deliverable:

1. Create or locate `ai/ai-usage.md` before substantive file-writing work.
2. Record the tool/model when known, purpose, task summary, adopted output, human modifications, and verification evidence for each material use.
3. Never invent missing interaction history or claim a verification that was not performed.
4. Before submission, convert the reviewed record into the officially required AI-use statement and support PDF, complete `compliance/submission.json`, and include the detail PDF in `submission-package-plan.json` when required.
5. For a submission scaffold, complete `compliance/m6-plan.json`, the official-rules snapshot/hash, and `compliance/source-register.json`; a machine technical pass is not the human M6 decision.

Do not communicate with prohibited external collaborators during a live event. Do not browse discussion platforms for active-problem solutions. Public factual sources may be researched only within the current competition rules and must be cited.

## Use Bundled Scripts

Create a case, configure its manifest, and run the build gate:

```powershell
python scripts/scaffold_case.py "2026-cumcm-a" --root <cases-directory> `
  --profile practice
python scripts/run_pipeline.py --case-dir <case-dir> --validate-only
python scripts/run_pipeline.py --case-dir <case-dir> --phase build
```

The build gate stops at `ready_for_visual_review=true`; it never claims that pages were inspected. After actually inspecting every rendered page using the context-safe batching rules in [visual-review-context.md](references/visual-review-context.md), record hash-bound evidence and finalize:

```powershell
python scripts/record_visual_review.py --case-dir <case-dir> `
  --pdf paper/paper.pdf --render-dir paper/rendered-pages `
  --reviewer "<reviewer>" --output paper/visual-review.json
  --confirm-all-pages-reviewed
python scripts/run_pipeline.py --case-dir <case-dir> --phase finalize
python scripts/package_submission.py --case-dir <case-dir> `
  --plan submission-package-plan.json --output-dir submission-package
```

For `submission`, scaffold with `--profile submission`. New scaffolds set `compliance`, `m6_compliance_plan`, and declarative `m7_f2_plan`; the pipeline does not perform or claim the official upload. During build, the complete M6 path runs only `audit_m6_compliance.py technical`; this can prove the rules snapshot/hash, anonymity precheck, source/license register, AI disclosure content, and support allowlist are technically consistent. It cannot approve M6. Use `prepare` to create `M6_PENDING_HUMAN`; after the responsible human actually reviews the evidence, that human—not Codex—may record `accepted`, `accepted_with_limitations`, or `rejected` with `finalize --confirm-human-reviewed`. Finalization runs the complete `audit` and requires the accepted hash-bound manifest. `verify` checks the recorded manifest and hashes but does not prove that the human review occurred.

The older `audit_submission_compliance.py` and a workflow containing only `compliance/submission.json` remain compatible, but their scope is `rules_and_ai_technical_only` and `full_m6_proven=false`. Do not report that legacy path as a complete M6 pass.
After packaging and support replay, use `audit_m7_f2.py precheck` to bind the selected package report, finalization report, source and packaged paper, support ZIP, smoke report, and every required smoke-test result. `ready_for_submission=true`, a created package, `M7-PRECHECK-PASS`, and an accepted M7 manifest all remain `NOT_FORMAL_F2`. Codex may run `precheck`, `prepare-m7`, `verify-m7`, and `verify-f2`, but must not execute `finalize-m7 --confirm-human-reviewed` or `record-f2 --confirm-official-upload` on the operator's behalf. Only a verified accepted `single_operator_review` M7 manifest, an unchanged selected package, an actual official upload, a real non-empty receipt, explicit human upload confirmation, and a verified immutable F2 manifest establish `F2_COMPLETE`.

Read [workflow-automation.md](references/workflow-automation.md) for manifest schemas, caching, resume controls, direct audit commands, compliance JSON, and final gate semantics. Use the project-selected interpreter.

Before releasing changes to this skill, run `python scripts/check_skill.py --workspace-root <MathModel-root>`. It runs the full quality gate and inspects historical cases only through manifest validation and passive read-only diagnostics. After an environment or external-tool change, also regenerate the passive environment snapshot; before a rehearsal or freeze, run its explicit active smoke mode as described in [environment-and-recovery.md](references/environment-and-recovery.md).

## Closeout Lessons Applied During Authoring

Use the existing [paper-expression-quick-card.md](references/paper-expression-quick-card.md), not a new stage chain. Its closeout delta requires the abstract, route diagram and body to agree on separate statistical pathways and denominators; symbol-table units and first-definition locations must be accurate; candidate-selection history requires dated evidence; continuous scenarios must not masquerade as discrete observations. Preserve the body derivation and selection reasons while removing template/repair narration. The scaffold carries these checks into new papers and QA registers; `audit_paper_closeout.py` catches scoped internal-language residue, not semantic correctness. Readable-page review, numerical reconciliation and real source verification remain separate gates; marker or hash matches alone never establish paper quality.

## Completion Standard

Finish only when:

- every requested subproblem has a direct answer;
- all reported values trace to code or explicit calculations;
- units, constraints, and assumptions are consistent;
- a baseline and appropriate validation exist;
- sensitivity or uncertainty is addressed where consequential;
- the model-definition register passes, including alternative reoptimization and paper disclosure for every material ambiguity;
- paper outputs match generated results;
- the structural paper audit passes and every final rendered page has been inspected;
- current competition formatting, citation, anonymity, support-material, and AI-use requirements pass; for a full-M6 submission route, the technical evidence and accepted real-human M6 manifest both verify;
- no local readiness or package status is reported as official submission; `F2_COMPLETE` is claimed only from a verified accepted M7 manifest, unchanged package evidence, actual official upload, non-empty receipt, and verified F2 manifest;
- unrun checks and residual risks are stated plainly.






## Evaluator-Facing Closeout Gate

For chapter-to-full-paper integration, use [paper-chapter-integration.md](templates/paper-chapter-integration.md) to reconstruct each answer from the body: actual substitution, same-basis comparison, choice reasons, figure interpretation and limits. New Markdown/Word practice/submission cases carry a pending [paper-integration-plan.json](templates/paper-integration-plan.json); the existing closeout/finalizer runs `audit_paper_integration.py` against current files. It checks native display structure/visible labels, body image bytes, source-appendix equality and declared support hashes, not mathematical meaning, inline-formula equivalence, readable pages or human acceptance. Keep symbol-table, result and page reviews; see the existing closeout reference for format scope.

Before final paper delivery, follow [paper-closeout.md](references/paper-closeout.md): remove internal operations prose without erasing scientific limitations, reconstruct each answer from the body, verify actual references and current AI-use coverage, inspect final pages at readable size, and then verify the selected ZIP contents against source hashes. Never replace a stale review by changing only its hash/date, treat an existing AI PDF or bibliography heading as a completed audit, or promote contact-sheet inspection to full-page review. New practice/submission scaffolds require hash-bound `paper/closeout-review.json`; `finalize_case.py` blocks pending, missing or stale review evidence. This is technical evidence binding, not semantic correctness or human acceptance. Run the existing M6, packaging, support replay, M7/F2 gates unchanged; a practice pass is not official submission.

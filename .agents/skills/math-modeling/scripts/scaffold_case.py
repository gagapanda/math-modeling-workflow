#!/usr/bin/env python
"""Create a non-destructive mathematical-modeling case workspace."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
TEMPLATES = SKILL_DIR / "templates"

OFFICIAL_RULES_SNAPSHOT_TEMPLATE = """# Official Rules Snapshot

Status: pending human verification
Verified at: TODO: YYYY-MM-DD
Official sources:
- TODO: current official HTTPS rules URL

## Submission impact

Record the current paper, anonymity, AI-use, support-material, naming, size, and upload requirements. Preserve the downloaded official file or a faithful local snapshot beside this note when available. Do not treat URL syntax as proof that a source is official.
"""

SUBMISSION_ONLY_FILES = {
    "compliance/m6-plan.json",
    "compliance/official-rules-snapshot.md",
    "compliance/source-register.json",
    "compliance/M6-review-card.md",
    "submission-package-plan.json",
    "support-smoke-plan.json",
    "m7-f2-plan.json",
    "submission/M7-review-card.md",
}


DIRECTORIES = (
    "problem",
    "data/raw",
    "data/cleaning",
    "data/processed",
    "src",
    "notebooks",
    "figures",
    "results",
    "authority",
    "paper",
    "ai",
    "compliance",
    "submission",
    "logs",
)

FILES = {
    "authority/candidate-registry.json": (
        "{\n"
        '  "schema_version": 1,\n'
        '  "revision": 0,\n'
        '  "updated_at": null,\n'
        '  "candidates": []\n'
        "}\n"
    ),
    "problem/statement.md": "# Problem Statement\n\nTODO: Preserve or link the official statement and attachments.\n",
    "problem/requirements.md": (
        "# Requirements\n\n"
        "## Required Outputs\n\nTODO\n\n"
        "## Variables And Constraints\n\nTODO\n\n"
        "## Ambiguities\n\nTODO\n"
    ),
    "START-HERE.md": (
        "# Start Here\n\n"
        "Use this card to turn a new modeling problem into a traceable case. Complete each gate before moving to the next one.\n\n"
        "## 0. Resume An Existing Case Safely\n\n"
        "Open the case-root `CURRENT-STATE.md` before trusting historical artifacts. It is the only current-state pointer and must identify the current result register, F1 manifest or its absence, authoritative paper source, selected delivery candidate, gate statuses, and superseded candidates. A legacy case may use one documented equivalent, but do not create competing pointers. Do not choose by newest-looking filename or modification time. Multiple unresolved candidates mean `AUTHORITY_UNRESOLVED`.\n\n"
        "Search active control files such as `decisions.md`, `validation.md`, manifests, checklists, and review cards for `TODO`, `pending`, contradictory status, or obsolete paths. Complete them or explicitly mark them superseded with the replacement path and reason. An unresolved active placeholder is `STALE_CONTROL_FILE` and blocks F1, M5, and M7 claims. Read `required`, `scope`, `status`, `passed`, and `errors` together: `required=false` with `passed=true` means `NOT_RUN_OR_NOT_REQUIRED`, not an executed gate pass.\n\n"
        "## 1. Preserve The Source\n\n"
        "Put the official statement and unmodified attachments in `problem/` and `data/raw/`. Record required outputs, units, constraints, and ambiguous wording in `problem/requirements.md`.\n\n"
        "## 2. Close Definitions Before Solving\n\n"
        "Complete `problem/model-definition-register.json`. Every material ambiguity needs an alternative reoptimization, a selection rationale, and a final-paper disclosure.\n\n"
        "## 3. Audit And Route\n\n"
        "Audit data before cleaning it. Choose one transparent baseline, one main model, and explicit validation and sensitivity checks. Record choices in `decisions.md` and checks in `validation.md`. For any material loop, branch, search, fold, or solver, also record the real input/state, execution order, stop or selection rule, output artifact, and solver-status boundary; do not invent convergence or global-optimum claims.\n\n"
        "## 4. Implement A Declared Workflow\n\n"
        "Replace `src/analyze.py` with deterministic case analysis. Declare every input, output, timeout, and cache decision in `workflow.json`. Time-limited solvers that can stop with a feasible incumbent must use `cache: false`.\n\n"
        "## 5. Bind Results To The Paper\n\n"
        "Write headline results to finite JSON. Register every number used by conclusions, figures, tables, templates, or the abstract in `results/result-register.json`. When a valid rerun can change a solver headline, generate the register from a deterministic summary step instead of editing it by hand.\n\n"
        "## 6. Freeze Results Before Paper Authority\n\n"
        "Draft early, but keep `**NON_AUTHORITATIVE REVIEW DRAFT**` in the Markdown and generated DOCX/PDF. After the responsible human accepts F1, verify the immutable manifest, update `CURRENT-STATE.md`, change `paper/paper-authority-plan.json` to `authoritative`, name the accepted manifest, and remove the marker. Codex cannot sign F1.\n\n"
        "## 7. Run The Gates\n\nComplete paper/closeout-review.json after actual reader reconstruction, reference verification, AI disclosure review and anonymity review. Bind current source/DOCX/PDF and real evidence hashes; pending blocks finalization. See the Skill paper-closeout reference; do not infer a review from file existence.\n\n"
        "From the MathModel workspace root, validate the manifest first:\n\n"
        "```powershell\n"
        "python .agents\\skills\\math-modeling\\scripts\\run_pipeline.py --case-dir <case-dir> --validate-only\n"
        "```\n\n"
        "Run the full build only after the analysis and paper source are ready:\n\n"
        "```powershell\n"
        "python .agents\\skills\\math-modeling\\scripts\\run_pipeline.py --case-dir <case-dir> --phase build\n"
        "```\n\n"
        "Inspect every rendered page, record the review with `record_visual_review.py`, then close the practice workflow:\n\n"
        "```powershell\n"
        "python .agents\\skills\\math-modeling\\scripts\\run_pipeline.py --case-dir <case-dir> --phase finalize\n"
        "```\n\n"
        "A successful build means `ready_for_visual_review=true`; a successful finalization means the practice deliverables are internally complete. Use the submission profile only after reviewing current official rules and the AI-use record. For submission cases, packaging, M7 precheck, and accepted M7 remain `NOT_FORMAL_F2`; only the responsible human can confirm the real official upload and receipt through the M7/F2 authority chain.\n"
    ),
    "problem/model-definition-register.json": (
        "{\n"
        '  "schema_version": 1,\n'
        '  "assessment_status": "pending",\n'
        '  "assessment_evidence": "TODO",\n'
        '  "no_material_ambiguity_rationale": "",\n'
        '  "ambiguities": []\n'
        "}\n"
    ),
    "decisions.md": (
        "# Modeling Decisions\n\n"
        "| Decision | Alternatives | Evidence | Choice | Risk |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| TODO | TODO | TODO | TODO | TODO |\n"
    ),
    "validation.md": (
        "# Validation Register\n\n"
        "| Claim | Check | Evidence | Status |\n"
        "| --- | --- | --- | --- |\n"
        "| TODO | TODO | TODO | pending |\n"
    ),
    "ai/ai-usage.md": (
        "# AI Use Register\n\n"
        "Status: undecided\n\n"
        "Set status to `used` or `not-used`. For each material use, record the date/time, "
        "tool and model when known, purpose, task summary, adopted output, human changes, "
        "and verification evidence. Do not reconstruct missing history.\n\n"
        "## Entries\n\n"
        "No entries yet. For each material entry use these labels exactly:\n\n"
        "- Time:\n- Tool/Model:\n- Phase/Purpose:\n- Task Summary:\n"
        "- Adopted Output:\n- Human Changes:\n- Verification Evidence:\n"
        "- File Scope:\n- Unresolved Limitations:\n"
    ),
    "compliance/submission.json": (
        "{\n"
        '  "schema_version": 1,\n'
        '  "competition": "TODO: official competition name",\n'
        '  "year": 2026,\n'
        '  "rules": {\n'
        '    "verified_at": "TODO: YYYY-MM-DD",\n'
        '    "max_age_days": 30,\n'
        '    "sources": ["TODO: official HTTPS rules URL"]\n'
        "  },\n"
        '  "ai": {\n'
        '    "status": "TODO: used or not-used",\n'
        '    "usage_log": "ai/ai-usage.md",\n'
        '    "paper_statement": "TODO: exact reviewed statement in the paper",\n'
        '    "detail_pdf": "TODO: required only when AI was used"\n'
        "  }\n"
        "}\n"
    ),
    "compliance/official-rules-snapshot.md": OFFICIAL_RULES_SNAPSHOT_TEMPLATE,
    "compliance/source-register.json": (
        "{\n"
        '  "schema_version": 1,\n'
        '  "status": "pending",\n'
        '  "reviewed_at": "",\n'
        '  "not_applicable_reason": "",\n'
        '  "entries": []\n'
        "}\n"
    ),
    "compliance/m6-plan.json": (
        "{\n"
        '  "schema_version": 1,\n'
        '  "legacy_submission_compliance": "compliance/submission.json",\n'
        '  "official_rules": {\n'
        '    "snapshot": "compliance/official-rules-snapshot.md",\n'
        '    "snapshot_sha256": "__RULES_SNAPSHOT_SHA256__",\n'
        '    "verified_at": "TODO: YYYY-MM-DD",\n'
        '    "max_age_days": 7,\n'
        '    "sources": ["TODO: current official HTTPS rules URL"],\n'
        '    "impact_steps": ["paper", "anonymity", "AI disclosure", "support package", "upload"]\n'
        "  },\n"
        '  "anonymity": {\n'
        '    "submission_package_plan": "submission-package-plan.json",\n'
        '    "allowed_anonymous_values": ["", "Anonymous", "匿名"],\n'
        '    "forbidden_path_patterns": ["(?i)(?:Users|\\\\Users)[/\\\\][^/\\\\]+"]\n'
        "  },\n"
        '  "sources": {"register": "compliance/source-register.json"},\n'
        '  "ai": {\n'
        '    "usage_log_required_markers": ["Time", "Tool/Model", "Phase/Purpose", "Task Summary", "Adopted Output", "Human Changes", "Verification Evidence", "File Scope", "Unresolved Limitations"],\n'
        '    "detail_pdf_required_markers": ["Tool/Version", "Purpose/Stage", "Prompt Process", "Adopted Result", "Human Modification", "Verification"]\n'
        "  },\n"
        '  "human_gate": {"manifest": "compliance/M6-accepted.json"}\n'
        "}\n"
    ),
    "compliance/M6-review-card.md": (
        "# M6 Human Review Card\n\n"
        "Codex may prepare and challenge the evidence but cannot sign M6. The responsible human checks the current official rules snapshot, anonymity precheck, source/license register, AI disclosure, and support allowlist, then uses `audit_m6_compliance.py finalize --confirm-human-reviewed` to record the actual decision. In a one-person run, record single-operator review; do not invent a second reviewer.\n"
    ),
    "submission-package-plan.json": (
        "{\n"
        '  "schema_version": 1,\n'
        '  "finalization_report": "paper/finalization-report.json",\n'
        '  "paper": {"source": "paper/paper.pdf", "output_name": "TODO-paper-filename.pdf", "max_bytes": 20971520},\n'
        '  "support": {\n'
        '    "output_name": "support-materials.zip",\n'
        '    "max_bytes": 20971520,\n'
        '    "files": [{"source": "src/analyze.py", "archive_path": "src/analyze.py"}]\n'
        "  },\n"
        '  "anonymity": {"forbidden_terms": ["TODO: add every real name, school, ID, account, and identifying path token"]}\n'
        "}\n"
    ),
    "support-smoke-plan.json": (
        "{\n"
        '  "schema_version": 1,\n'
        '  "package": "support-materials.zip",\n'
        '  "tests": [\n'
        "    {\n"
        '      "name": "main-analysis",\n'
        '      "command": ["python", "src/analyze.py", "--case-dir", "."],\n'
        '      "cwd": ".",\n'
        '      "expected_outputs": ["results/result-register.json"],\n'
        '      "timeout_seconds": 900\n'
        "    }\n"
        "  ]\n"
        "}\n"
    ),
    "m7-f2-plan.json": (
        "{\n"
        '  "schema_version": 1,\n'
        '  "package_report": "submission-package/submission-package-report.json",\n'
        '  "support_smoke_report": "submission-package/support-smoke-report.json",\n'
        '  "required_smoke_tests": ["main-analysis"],\n'
        '  "official_upload": {\n'
        '    "competition": "TODO: current competition",\n'
        '    "platform": "TODO: official upload platform",\n'
        '    "receipt": "submission/official-upload-receipt.pdf",\n'
        '    "allowed_receipt_suffixes": [".pdf", ".png", ".jpg", ".jpeg"]\n'
        "  },\n"
        '  "human_gate": {\n'
        '    "m7_manifest": "submission/M7-accepted.json",\n'
        '    "f2_manifest": "submission/F2-submission.json"\n'
        "  }\n"
        "}\n"
    ),
    "submission/M7-review-card.md": (
        "# M7/F2 Human Review Card\n\n"
        "Codex may prepare the M7 technical precheck and evidence package, but cannot sign the human M7 gate and cannot claim that an official upload occurred. M7 acceptance remains `NOT_FORMAL_F2`. `F2_COMPLETE` requires the responsible human to upload the unchanged selected package to the official platform, preserve a real non-empty receipt, and explicitly record that upload with `audit_m7_f2.py record-f2 --confirm-official-upload`. In a one-person run use `single_operator_review`; never invent a second reviewer.\n"
    ),
    "paper/outline.md": (
        "# Paper Outline\n\n"
        "1. Abstract\n2. Problem Restatement\n3. Problem Analysis And Technical Route\n"
        "4. Assumptions, Definitions, Symbols, And Units\n5. Data Audit And Preprocessing\n"
        "6. Subproblem 1: Model, Solution, Result, And Validation\n"
        "7. Subproblem 2: Model, Solution, Result, And Validation\n"
        "8. Remaining Subproblems: Model, Solution, Result, And Validation\n"
        "9. Cross-Model Validation, Sensitivity, And Robustness\n"
        "10. Conclusions, Strengths, Limitations, And Extensions\n"
        "11. AI-Use Declaration And References\n12. Appendices: File Inventory And Complete Code\n"
    ),
    "paper/full-paper.md": (
        "# Paper Title\n\n"
        "**NON_AUTHORITATIVE REVIEW DRAFT**\n\n"
        "## Abstract\n\n"
        "After result freeze, complete `paper/abstract-evidence.md`, then state the problem, the key method structure for each subproblem, reproducible headline results, the strongest validation or failure evidence, indispensable claim boundaries, and keywords. The abstract is a compressed answer rather than a derivation section: do not introduce numbers or claims absent from the frozen body, list methods without their purpose, or hide units, validation objects, non-causal, out-of-domain, non-measured, or non-guarantee boundaries merely to fit one page.\n\n"
        "## Problem Restatement\n\n"
        "State every required output operationally and show how the subproblems depend on one another.\n\n"
        "## Problem Analysis And Technical Route\n\n"
        "Explain the structure of each subproblem, candidate model families, the transparent baseline, the selected route, and the validation plan. Reconcile this compressed description with the body and implemented data pathways. Use predeclared or preregistered only with time-stamped evidence; otherwise describe the compared candidates and actual selection criterion.\n\n"
        "## Assumptions, Definitions, Symbols, And Units\n\n"
        "Justify material assumptions and definition choices. Define repeatedly used global symbols before the substantive model sections; define local one-use quantities at first use. Preserve units, domains, index ranges, and information timing. Check first-definition locations; distinguish image pixels, normalized dimensionless quantities, physical units, mappings and scenario sets instead of merging incompatible units.\n\n"
        "### Symbols And Units\n\n"
        "For Markdown-to-Word, use export-safe table notation unless mathematical table cells have been render-verified. Replace every placeholder row before authoritative export.\n\n"
        "| Symbol | Meaning / Role | Unit / Domain | Index Range / Timing |\n"
        "| --- | --- | --- | --- |\n"
        "| `i`, `t` | Object and time indices | nonnegative integers | `i=1,...,n`; `t=1,...,T` |\n"
        "| `x(i,t)` | Example decision or state variable; replace with the real symbol | TODO | TODO |\n\n"
        "## Data Audit And Preprocessing\n\n"
        "Document provenance, schema, missingness, anomalies, transformations, exclusions, group/time boundaries, and leakage controls. When selection, matching, repeated measurements, local missingness, or train/validation splits materially change the evidence, distinguish record rows, independent objects, pairs/groups, and validation units; bind each core claim to its effective denominator and explain exclusion or denominator reduction. Use a compact analysis-set table only for three or more material transitions, and do not add the same source data across subproblems to manufacture a larger sample. Where pairing and object-level association use different analysis sets, describe them as separate pathways rather than claiming one is an aggregation of the other. State not applicable only when the problem truly supplies no data.\n\n"
        "## Subproblem 1: Model, Solution, Result, And Validation\n\n"
        "Begin with a one- or two-sentence direct answer that gives the requested value, decision, interval, or judgment together with its unit and conditions. Then follow problem transformation -> definitions and assumptions -> core derivation -> transparent baseline -> main model or justified improvement -> algorithm -> result -> comparison or diagnostic -> interpretation -> validation and boundary, and close by returning to the direct answer. For each core formula, state its calculation purpose, define local symbols and units, explain the role of its material terms, and identify the result, table, figure, or decision it produces. Before a key table or figure, state the comparison purpose and reading basis; after it, identify the decisive pattern and its boundary instead of merely repeating every value. For mechanistic or dynamic subproblems, keep a shortest continuous chain from real object and external driver to state variable, state equation, initial/boundary conditions, parameter source or calibration objective, numerical propagation and event extraction, and the reported metric or decision; distinguish effective calibrated parameters from independently identified physical properties, and use a mechanism diagram only when its inputs, states, boundaries/events, and outputs map to the equations. For optimization or decision subproblems, also explain which constraints or bounds shape the selected candidate, where the objective gain comes from, which resource, group, interval, or scenario is the bottleneck, what decision preference the objective encodes, and what changed definition or preference would require reoptimization. For statistical prediction, repeated-measure, or time-forecast subproblems, state the prediction object and deployment unit, data hierarchy and group/time split, fold-safe preprocessing, transparent baseline and predeclared candidates, then report aggregate performance together with failure structure by object, group, period, or tail event and its bias direction. Use a residual timeline, subgroup/period metric, or tail-event table when it materially exposes failure; if no validated interval exists, say so, and do not present a training residual quantile or safety buffer as a future coverage guarantee. For probability classification or scoring, define the label, deployment object, and error costs; separate discrimination from probability calibration, state the threshold source and sensitivity, and connect threshold errors to the downstream decision. An AUC or accuracy result is not calibration evidence, and an operating target is not a confidence level. For clustering or grouping, state the operational purpose, distance or similarity and scale, cluster-count or capacity source, group-size and singleton structure, available cohesion/separation and multi-start or parameter-stability evidence, and how groups enter the next decision; do not present a cluster count, capacity-filled output, map, or proximity group as proof of a natural class, stable optimum, actual route, or collaboration guarantee. For evaluation or composite-scoring subproblems, define the decision object, candidate eligibility, indicator direction, unit, and time window, transformation and score semantics; state whether weights come from data, experts, a rule, or a decision preference; inspect redundancy, use a transparent equal-weight or other baseline when material, report boundary objects and available weight, indicator, or threshold sensitivity, and connect the ranking to the actual decision. A composite score is not a probability, confidence level, absolute value, or proof of a unique optimum; changed candidates, windows, indicators, eligibility rules, or preferences require a complete rescore. Omit a step only when genuinely inapplicable, and bind claims to generated figures, tables, and result-register entries.\n\n"
        "## Subproblem 2: Model, Solution, Result, And Validation\n\n"
        "Start with this subproblem's direct answer, then repeat the complete local evidence chain and identify what changes from the previous subproblem. Preserve the formula, baseline/model-selection, evidence-carrier, validation, and boundary requirements above. For mechanistic or dynamic sections, do not jump from a named equation to a result curve: close the driver-state-initial/boundary-parameter-numerical-event-metric chain and state which links are assumptions or effective calibration. For optimization or decision sections, do not stop at a parameter table: interpret active bounds, gain mechanism, bottleneck or trade-off, objective preference, and any condition that would trigger reoptimization. For prediction sections, do not stop at an aggregate metric: identify the deployment unit, matching group/time validation, worst object or period, error direction or tail failure, and the exact uncertainty semantics; a safety buffer is not a coverage guarantee. For probability classification or scoring, separate discrimination, calibration, threshold provenance and decision consequences; for clustering or grouping, report the grouping purpose, distance/scale, cluster-count or capacity source, structure and available stability evidence, and preserve the boundary between a proximity group and a natural class or real route. For evaluation or composite scoring, preserve candidate eligibility, indicator direction/unit/time window, transformation and score semantics, weight provenance, redundancy, a transparent baseline, boundary-object sensitivity, decision consequence, and rescore triggers; a composite score is not a probability, confidence level, absolute value, or unique-optimum proof.\n\n"
        "## Remaining Subproblems: Model, Solution, Result, And Validation\n\n"
        "Create one complete section per remaining substantive subproblem. Start each with its direct answer and preserve the same local evidence chain; do not merge the questions into an unexplained result list.\n\n"
        "## Cross-Model Validation, Sensitivity, And Robustness\n\n"
        "Synthesize only evidence that adds information across subproblems: dependency propagation, shared definitions or data levels, common failure modes, uncertainty transfer, and genuine agreement or conflict. Keep local checks inside their own subproblem, and do not turn this section into a second subproblem-by-subproblem result summary. For every material dependency, record upstream asset or definition -> transferred quantity and risk type -> downstream claim at risk -> control or validation -> invalidation scope and recomputation trigger. Distinguish definition or measurement, sample structure or causal boundary, prediction uncertainty, and decision-trigger propagation when applicable. Do not pass an upstream point estimate as an unconditional downstream input, promote an observational association to a causal mechanism, or claim that a downstream check repairs an upstream definition error. If propagation magnitude cannot be quantified, state the affected claim, direction or scope of invalidation, and fallback action. If no cross-subproblem synthesis is material, state that briefly rather than filling the section with repeated numbers. Use a dependency figure only when its nodes, transferred items, risks, and actions remain readable; do not require a new table or figure.\n\n"
        "## Conclusions, Strengths, Limitations, And Extensions\n\n"
        "Answer every requested output directly from the frozen body. Recover only contributions that were first proved in the body: for each material contribution, identify its type, real gap, added structure, first proof location, matching evidence or baseline/ablation status, verified gain, failure or cost, boundary, and conclusion recovery. The technical route previews contributions, the body first proves them, validation states gains and failures, and the conclusion only recovers them. Without component-level ablation, do not attribute an overall performance gain to one feature, weight, preprocessing step, or combined module. Definition, data-organization, validation, decision-structure, and evidence-chain contributions are not algorithmic innovations. Do not force an innovation claim when no material contribution exists. Then summarize evidence-bounded limitations and realistic extensions. Do not introduce a new result, method, comparison, or certainty claim in the conclusion.\n\n"
        "## AI-Use Declaration\n\n"
        "Insert the exact statement required by the current competition rules, grounded in the actual current-version usage log; an old AI-details PDF is not proof of current coverage.\n\n"
        "## References\n\n"
        "Cite data, prior work, algorithms, and software at the point of use. Verify author, title, venue or publisher, year, and any identifier against an opened source; remove every example entry and do not invent DOI, URL, issue, or page metadata.\n\n"
        "## Appendix A: Support-File Inventory\n\nReplace drafting instructions with evaluator-facing runtime and data provenance information. Keep repair stages, writeback logs and old visual-review status outside the paper; retain scientific limitations and actual AI disclosure.\n\n"
        "List every submitted data, result, figure, and source file with its role.\n\n"
        "## Appendix B: Complete Runnable Source Code\n\n"
        "Include or assemble the complete final source code and the documented run order; do not replace it with fragments. Record entry points, local modules, configuration/environment dependencies, required inputs, and output locations. The appendix and submitted support package must come from the same frozen source version.\n"
    ),
    "paper/qa-register.md": (
        "# Paper QA Register\n\n"
        "| Gate | Evidence | Status |\n"
        "| --- | --- | --- |\n"
        "| Required outputs answered | TODO | pending |\n"
        "| Headline values reconciled | TODO | pending |\n"
        "| Results frozen before abstract, formal conclusion, and final paper rebuild | TODO | pending |\n"
        "| Abstract evidence sheet completed; every subproblem binds method, result ID/display value, validation, claim type, and boundary | TODO | pending |\n"
        "| Every substantive subproblem opens with a direct answer carrying units and conditions | TODO | pending |\n"
        "| Symbols and units table complete and visually checked in final DOCX/PDF | TODO | pending |\n"
        "| Analysis units, effective denominators, exclusion/missingness reasons, and validation units reconciled where sample flow changes materially | TODO | pending |\n"
        "| Each substantive subproblem has a justified derivation / baseline / result / validation chain or a recorded not-applicable reason | TODO | pending |\n"
        "| Statistical pathways (paired, grouped, repeated, time-based, validation) have separate units and denominators | TODO | pending |\n"
        "| Model/feature/weight/scenario choices have evaluator-facing reasons without unsupported preregistration claims | TODO | pending |\n"
        "| Internal workflow language is absent from narrative while scientific limitations remain | TODO | pending |\n"
        "| Core formulas have purpose, symbol/unit, term-role, output, and boundary explanations | TODO | pending |\n"
        "| Key figures and tables state their comparison purpose, reading basis, decisive finding, and boundary | TODO | pending |\n"
        "| Figure and table numbering, captions, and body references reconciled after final layout edit | TODO | pending |\n"
        "| Main-text completeness reviewed by subproblem | TODO | pending |\n"
        "| Front matter / main text / references / appendix pages recorded separately | TODO | pending |\n"
        "| Full-paper label justified; short-main-text warning resolved if applicable | TODO | pending |\n"
        "| Reference metadata verified from opened sources and all example entries removed | TODO | pending |\n"
        "| Complete dependency-closed runnable code and support-file inventory included from the same frozen source | TODO | pending |\n"
        "| Final DOCX/PDF rebuilt from one authoritative paper source without independent hand edits | TODO | pending |\n"
        "| DOCX/PDF structural audit | TODO | pending |\n"
        "| Every rendered page inspected | TODO | pending |\n"
        "| Official format and anonymity | TODO | pending |\n"
    ),
    "paper/paper-authority-plan.json": (
        "{\n"
        '  "schema_version": 1,\n'
        '  "mode": "draft",\n'
        '  "current_state": "CURRENT-STATE.md",\n'
        '  "result_register": "results/result-register.json",\n'
        '  "freeze_manifest": "",\n'
        '  "paper_source": "paper/full-paper.md",\n'
        '  "draft_marker": "NON_AUTHORITATIVE REVIEW DRAFT"\n'
        "}\n"
    ),
    "paper/visual-review.json": (
        "{\n"
        '  "schema_version": 1,\n'
        '  "status": "pending",\n'
        '  "reviewed_at": "",\n'
        '  "reviewer": "",\n'
        '  "pdf_sha256": "",\n'
        '  "page_count": 0,\n'
        '  "reviewed_pages": [],\n'
        '  "rendered_pages_sha256": {},\n'
        '  "notes": ""\n'
        "}\n"
    ),
    "results/f1-freeze-plan.json": (
        "{\n"
        '  "schema_version": 1,\n'
        '  "freeze_id": "REPLACE_BEFORE_PREPARE",\n'
        '  "result_register": "results/result-register.json",\n'
        '  "files": [],\n'
        '  "replay_evidence": [],\n'
        '  "limitations": [],\n'
        '  "unresolved": [\n'
        '    "Complete the F1 plan before preparing a freeze candidate."\n'
        '  ]\n'
        "}\n"
    ),
    "results/F1-review-card.md": (
        "# F1 Human Review Card\n\n"
        "> Codex may draft this card and compute hashes, but it cannot sign the card, invent a reviewer, or replace the responsible human decision.\n\n"
        "| Field | Value |\n"
        "| --- | --- |\n"
        "| freeze_id | `NOT_RECORDED` |\n"
        "| candidate_manifest | `NOT_CREATED` |\n"
        "| candidate_sha256 | `NOT_COMPUTED` |\n"
        "| evidence_ready_time | `NOT_RECORDED` |\n"
        "| human_review_start | `NOT_RECORDED` |\n"
        "| human_review_end | `NOT_RECORDED` |\n"
        "| reviewer | `RESPONSIBLE_HUMAN_NOT_RECORDED` |\n"
        "| reviewed_artifact_hashes | `NOT_RECORDED` |\n"
        "| objections | `NOT_RECORDED` |\n"
        "| resolution | `NOT_RECORDED` |\n"
        "| human_decision | `not_reviewed` |\n"
        "| finalization_time | `NOT_RECORDED` |\n"
        "| confirmation | `NOT_CONFIRMED` |\n\n"
        "Accepted values are `accepted`, `accepted_with_limitations`, or `rejected`. The human operator records the real decision first; `freeze_results.py finalize` then creates a new immutable manifest from that decision.\n"
    ),
    "results/result-register.md": (
        "# Result Register\n\n"
        "| Subproblem | Output | Generated By | Verification | Paper Location |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| TODO | TODO | TODO | TODO | TODO |\n"
    ),
    "results/result-register.json": (
        "{\n"
        '  "schema_version": 1,\n'
        '  "results": []\n'
        "}\n"
    ),
}

TEMPLATE_FILES = {
    "CURRENT-STATE.md": TEMPLATES / "CURRENT-STATE.md",
    "src/analyze.py": TEMPLATES / "analyze.py",
    "src/build_markdown_paper.py": TEMPLATES / "build_markdown_paper.py",
}


def workflow_content(profile: str) -> str:
    workflow = {
        "schema_version": 2,
        "profile": profile,
        "steps": [
            {
                "name": "analyze",
                "script": "src/analyze.py",
                "args": ["--case-dir", "."],
                "inputs": [],
                "outputs": [],
                "timeout_seconds": 900,
                "cache": False,
            }
        ],
    }
    if profile != "explore":
        workflow["steps"].append(
            {
                "name": "build-paper",
                "script": "src/build_markdown_paper.py",
                "args": [
                    "--case-dir",
                    ".",
                    "--source",
                    "paper/full-paper.md",
                    "--output",
                    "paper/paper.docx",
                    "--spec",
                    "cumcm-cn.yaml",
                ],
                "inputs": [
                    "paper/full-paper.md",
                    "src/build_markdown_paper.py",
                ],
                "outputs": ["paper/paper.docx"],
                "timeout_seconds": 300,
                "cache": False,
            }
        )
        workflow["paper_authority_plan"] = "paper/paper-authority-plan.json"
        workflow["artifacts"] = {
            "docx": "paper/paper.docx",
            "pdf": "paper/paper.pdf",
            "render_dir": "paper/rendered-pages",
            "visual_review": "paper/visual-review.json",
        }
        workflow["audit"] = {
            "page_size": "a4",
            "orientation": "portrait",
            "render_dpi": 150,
            "forbid": ["TODO", "placeholder"],
        }
    if profile == "submission":
        workflow["compliance"] = "compliance/submission.json"
        workflow["m6_compliance_plan"] = "compliance/m6-plan.json"
        workflow["m7_f2_plan"] = "m7-f2-plan.json"
    return json.dumps(workflow, ensure_ascii=True, indent=2) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_name", help="Case directory name; path separators are rejected")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Parent directory")
    parser.add_argument(
        "--profile",
        choices=("explore", "practice", "submission"),
        default="practice",
        help="Workflow profile for a newly created manifest",
    )
    return parser.parse_args()


def validate_case_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned or cleaned in {".", ".."}:
        raise ValueError("case_name must be a non-empty directory name")
    if any(separator in cleaned for separator in ("/", "\\")):
        raise ValueError("case_name must not contain path separators")
    if any(character in cleaned for character in '<>:"|?*'):
        raise ValueError("case_name contains a character invalid on Windows")
    if cleaned.endswith((" ", ".")) or any(ord(character) < 32 for character in cleaned):
        raise ValueError("case_name has an invalid trailing or control character")
    stem = cleaned.split(".", 1)[0].casefold()
    if re.fullmatch(r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])", stem):
        raise ValueError("case_name is reserved on Windows")
    return cleaned


def validate_destination(path: Path) -> None:
    if path.is_symlink():
        raise ValueError(f"refusing to write through symbolic link: {path}")
    if path.exists() and not path.is_file():
        raise ValueError(f"expected a file but found another path type: {path}")


def write_if_missing(path: Path, content: str) -> bool:
    validate_destination(path)
    if path.exists():
        return False
    path.write_text(content, encoding="utf-8")
    return True


def load_template_files() -> dict[str, str]:
    return {
        relative: source.read_text(encoding="utf-8")
        for relative, source in TEMPLATE_FILES.items()
    }


def main() -> int:
    args = parse_args()
    try:
        case_name = validate_case_name(args.case_name)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    root = args.root.expanduser().resolve()
    case_dir = root / case_name
    try:
        template_files = load_template_files()
    except OSError as exc:
        raise SystemExit(f"cannot load scaffold templates: {exc}") from exc
    case_dir.mkdir(parents=True, exist_ok=True)

    try:
        for relative in DIRECTORIES:
            directory = case_dir / relative
            directory.mkdir(parents=True, exist_ok=True)
            if not directory.is_dir():
                raise ValueError(f"expected a directory: {directory}")
    except (OSError, ValueError) as exc:
        raise SystemExit(f"cannot create case directories: {exc}") from exc

    if args.profile == "explore":
        scaffold_files = {
            relative: content
            for relative, content in FILES.items()
            if relative != "paper/paper-authority-plan.json"
            and relative not in SUBMISSION_ONLY_FILES
        }
    elif args.profile == "submission":
        scaffold_files = dict(FILES)
        snapshot_bytes = OFFICIAL_RULES_SNAPSHOT_TEMPLATE.replace(
            "\n", os.linesep
        ).encode("utf-8")
        rules_hash = hashlib.sha256(snapshot_bytes).hexdigest()
        scaffold_files["compliance/m6-plan.json"] = scaffold_files[
            "compliance/m6-plan.json"
        ].replace("__RULES_SNAPSHOT_SHA256__", rules_hash)
    else:
        scaffold_files = {
            relative: content
            for relative, content in FILES.items()
            if relative not in SUBMISSION_ONLY_FILES
        }
    try:
        for relative in ("workflow.json", *scaffold_files, *template_files, "case.json"):
            validate_destination(case_dir / relative)
    except ValueError as exc:
        raise SystemExit(f"cannot initialize case: {exc}") from exc

    if args.profile != "explore":
        scaffold_files["paper/closeout-review.json"] = (
            TEMPLATES / "paper-closeout-review.json"
        ).read_text(encoding="utf-8")
        validate_destination(case_dir / "paper/closeout-review.json")
        for destination, template in (
            ("paper/integration-plan.json", "paper-integration-plan.json"),
            ("paper/chapter-integration.md", "paper-chapter-integration.md"),
            ("paper/abstract-evidence.md", "paper-abstract-evidence.md"),
        ):
            validate_destination(case_dir / destination)
            scaffold_files[destination] = (TEMPLATES / template).read_text(encoding="utf-8")

    created = []
    preserved = []
    workflow = case_dir / "workflow.json"
    try:
        workflow_created = write_if_missing(workflow, workflow_content(args.profile))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"cannot initialize workflow.json: {exc}") from exc
    (created if workflow_created else preserved).append("workflow.json")
    for relative, content in scaffold_files.items():
        destination = case_dir / relative
        try:
            was_created = write_if_missing(destination, content)
        except (OSError, ValueError) as exc:
            raise SystemExit(f"cannot initialize {relative}: {exc}") from exc
        (created if was_created else preserved).append(relative)
    for relative, content in template_files.items():
        destination = case_dir / relative
        try:
            was_created = write_if_missing(destination, content)
        except (OSError, ValueError) as exc:
            raise SystemExit(f"cannot initialize {relative}: {exc}") from exc
        (created if was_created else preserved).append(relative)

    metadata = case_dir / "case.json"
    metadata_content = (
        json.dumps(
            {
                "paper_closeout_required": args.profile != "explore",
                "paper_integration_required": args.profile != "explore",
                "case_name": case_name,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "workflow": "math-modeling",
                "profile": args.profile,
            },
            ensure_ascii=True,
            indent=2,
        )
        + "\n"
    )
    try:
        metadata_created = write_if_missing(metadata, metadata_content)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"cannot initialize case.json: {exc}") from exc
    if metadata_created:
        created.append("case.json")
    else:
        preserved.append("case.json")

    print(f"case_dir={case_dir}")
    print(f"created={len(created)}")
    print(f"preserved={len(preserved)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())




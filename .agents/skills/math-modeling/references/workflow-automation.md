# Workflow Automation

Use these scripts as gates, not as substitutes for mathematical judgment.

Before running case code, complete `problem/model-definition-register.json` as
described in [model-definition-gate.md](model-definition-gate.md). Build and finalize
fail when the assessment is pending, evidence files are missing, or a material
ambiguity lacks alternative reoptimization and final-paper disclosure.

## 0. Configure The Case Pipeline

Each scaffolded case contains `workflow.json`. New cases use schema version 2; schema version 1 remains supported without caching. Replace the fail-closed `src/analyze.py` starter with the case's deterministic analysis. Practice and submission scaffolds already include a case-local Markdown paper source and an enhanced Word-export adapter. Python and MATLAB scripts, tests, outputs, evidence, and artifact paths must stay inside the case directory. The scaffold also creates `START-HERE.md`, a case-local execution card that fixes the order: preserve sources, close definitions, audit and route, implement declared analysis, bind results, then build, inspect, and finalize. It is a guide only; it never replaces the model-definition, validation, or official-rule gates.

The machine-readable Draft 2020-12 contract is in `schemas/workflow.schema.json`. The pipeline validates every manifest against it before normalizing paths. Structural errors include a JSON Pointer such as `/steps/0/outputs`; case-relative path containment, duplicate names and outputs, reserved files, suffixes, and other cross-field semantics remain enforced by `run_pipeline.py`. The bundled validator has no third-party package dependency.

```json
{
  "schema_version": 2,
  "profile": "practice",
  "steps": [
    {
      "name": "analyze",
      "script": "src/analyze.py",
      "args": ["--case-dir", "."],
      "inputs": ["data/processed/model-input.csv", "src/model.py"],
      "outputs": ["results/analysis.json"],
      "timeout_seconds": 900,
      "cache": true
    },
    {
      "name": "build-paper",
      "script": "src/build_markdown_paper.py",
      "args": [
        "--case-dir", ".",
        "--source", "paper/full-paper.md",
        "--output", "paper/paper.docx",
        "--spec", "cumcm-cn.yaml"
      ],
      "inputs": [
        "paper/full-paper.md",
        "src/build_markdown_paper.py"
      ],
      "outputs": ["paper/paper.docx"],
      "timeout_seconds": 300,
      "cache": false
    }
  ],
  "artifacts": {
    "docx": "paper/paper.docx",
    "pdf": "paper/paper.pdf",
    "render_dir": "paper/rendered-pages",
    "visual_review": "paper/visual-review.json"
  },
  "audit": {
    "page_size": "a4",
    "orientation": "portrait",
    "render_dpi": 150,
    "forbid": ["TODO", "placeholder"]
  }
}
```

### Data Preparation

For one CSV that must be audited before model steps, add the optional schema version 2 `data_preparation` object. The pipeline performs a read-only raw audit, then only executes a reviewed hash-bound cleaning plan when one is explicitly configured, then audits the resulting `processed.csv` before it starts ordinary steps.

```json
"data_preparation": {
  "input": "data/raw/attachment.csv",
  "raw_audit_output": "evidence/data-preparation/raw-audit",
  "id_columns": ["sample_id"],
  "target_columns": ["target"],
  "time_columns": [],
  "group_columns": [],
  "cleaning_plan": "data/cleaning/attachment-plan.json",
  "cleaning_output": "data/processed/attachment-cleaning",
  "processed_audit_output": "evidence/data-preparation/processed-audit"
}
```

For several independent CSVs, use the schema version 2 `data_preparations` array instead. Each entry has the same fields and safeguards as `data_preparation`, plus a unique stable `name`; entries are audited and cached independently, and their evidence directories must not overlap each other, any other entry's source or plan, ordinary workflow outputs, or artifacts.

```json
"data_preparations": [
  {
    "name": "historical-tasks",
    "input": "data/processed/historical-tasks.csv",
    "raw_audit_output": "evidence/data-preparation/historical-tasks-audit",
    "id_columns": ["task_id"],
    "target_columns": ["completed"],
    "time_columns": [],
    "group_columns": []
  },
  {
    "name": "members",
    "input": "data/processed/members.csv",
    "raw_audit_output": "evidence/data-preparation/members-audit",
    "id_columns": ["member_id"],
    "target_columns": [],
    "time_columns": [],
    "group_columns": []
  }
]
```

A manifest must declare exactly one of `data_preparation` and `data_preparations`; the singular form remains supported for compatible existing cases. Every plural entry must be ready for modeling before ordinary steps run. On a partial plural run, successful entries are saved immediately as independent cache evidence so a failing later entry does not force their evidence to be recreated.

`input` and `raw_audit_output` are required. Without `cleaning_plan`, a raw audit with any blocker stops ordinary model steps. With a plan, `cleaning_output` and `processed_audit_output` are required; the cleaning output must be a new subdirectory of `data/processed`, and downstream steps must declare `data/processed/attachment-cleaning/processed.csv` as an input. The raw audit can have blockers that the reviewed plan addresses, but the processed audit must have no blockers before model code can run.

Use a version 1 plan that follows [data-cleaning.md](data-cleaning.md). It binds the exact source SHA-256, permits only its fixed mechanical operations, and writes the processed file plus cell, row, schema, rule, and hash ledger into `cleaning_output`. The workflow does not infer, generate, or authorize cleaning from audit findings.

The data-preparation fingerprint binds the source CSV, role assignments, plan when configured, and bundled audit/cleaning implementations. A successful repeat run reuses the evidence only when every expected evidence file still matches its saved hash. If an existing cleaning directory cannot prove the current source/plan binding, the runner fails closed and requires a new `cleaning_output` directory; it never replaces prior cleaning evidence.

`--plan` reports the aggregate `data_preparation` action (`not_configured`, `execute`, `cache-hit`, or `blocked`) and, for plural declarations, the action and reason for each named dataset; it stays read-only. This stage is always evaluated before selected build steps, including `--from` and `--only`, because it establishes the datasets those steps are allowed to consume.

Schema version 1 supports neither `data_preparation` nor `data_preparations`.

For non-CSV extraction, especially an XLSX workbook whose layout or source notes define the derived model inputs, do not disguise the work as a CSV cleaning declaration. Make the first ordinary schema version 2 Python step a deterministic `prepare-*` step with `cache: true`; declare every raw workbook as an `input` and every processed table, audit, mapping, and case-local evidence record as an `output`. Its evidence must bind source workbook hashes, relevant sheet/range and layout rules, normalization rules, every source-note text that authorizes a derivation and its SHA-256, and a row-level derivation ledger. Never overwrite the raw inputs. This lets the normal step cache invalidate on any source, script, parameter, interpreter, or output change while keeping workbook-specific extraction distinct from reviewed CSV cleaning.

Cache only a deterministic step whose complete file inputs and outputs are declared. A time-limited MIP, nonlinear solver, heuristic, or any solver that may stop with a feasible incumbent must use cache: false, even with fixed seeds, because timing, solver versions, and machine conditions can alter the incumbent or stopping state. Keep its command, time limit, inputs, outputs, and validation artifacts explicit; cache only deterministic preparation, validation, comparison, summary, or figure steps after their ownership is complete. When official result workbooks are generated by a workflow-external tool such as Node, declare those workbooks as inputs to an explicitly non-cached validation step and document that external-generation boundary rather than mislabeling the tool as a Python step.
### Profiles

Schema version 2 supports three explicit profiles:

- `explore` executes the selected steps and always skips the full modeling-environment preflight, model-definition closure, DOCX export, rendering, paper audits, and finalization. It may omit `artifacts` and `audit`; each configured step remains responsible for its own dependencies. MATLAB batch steps still receive a narrow startup preflight. A successful report has `completion_scope=configured_steps_only`, written to `.workflow/pipeline-report.json`.
- `practice` runs the established build and finalization gates. New scaffolds and schema version 1 manifests default to this behavior.
- `submission` runs the practice gates plus submission compliance. It requires a case-relative legacy `compliance` JSON path. New submission scaffolds also declare `m6_compliance_plan` for the complete M6 route and `m7_f2_plan` for the separate final-package review and official-upload receipt chain. The M7/F2 plan is declarative; `run_pipeline.py` does not perform or claim the official upload.

Schema version 1 rejects explicit `profile`, `compliance`, `m6_compliance_plan`, and `m7_f2_plan` fields so its historical behavior remains unambiguous. A schema version 2 submission that omits `m6_compliance_plan` retains the legacy rules-and-AI-only behavior; it must not be labeled a full M6 pass.

Scaffold the intended profile directly. The default remains `practice`:

```powershell
python scripts/scaffold_case.py <case-name> --root <cases-directory> --profile explore
python scripts/scaffold_case.py <case-name> --root <cases-directory> --profile practice
python scripts/scaffold_case.py <case-name> --root <cases-directory> --profile submission
```

Every scaffold creates a non-destructive `src/analyze.py` starter so validation and passive planning can inspect a complete entry-point graph. The starter exits with `analysis_not_implemented` during a real build until it is replaced, preventing an untouched case from claiming analysis success. Practice and submission scaffolds also create `paper/full-paper.md` and `src/build_markdown_paper.py`; their default paper step locates the nearest workspace `tools/doc-export-enhanced`, uses that tool's project-local `.venv`, and loads `doc-export-specs/cumcm-cn.yaml`. A submission scaffold additionally creates `compliance/m6-plan.json`, `compliance/official-rules-snapshot.md`, `compliance/source-register.json`, `compliance/M6-review-card.md`, and `submission-package-plan.json`. These are pending templates, not proof that official rules or M6 have been reviewed. Practice and explore scaffolds do not create those submission-only files.

Validate the manifest without running case code:

```powershell
python scripts/run_pipeline.py --case-dir <case-dir> --validate-only
```

Diagnose the complete configured environment and declared files without executing a step, starting Word/MATLAB, probing executables, creating directories, or writing reports:

```powershell
python scripts/doctor.py --case-dir <case-dir> --phase build --json
python scripts/doctor.py --case-dir <case-dir> --phase finalize --json
```

`doctor.py` reports `mode=passive_read_only`. Build mode validates the manifest, declared scripts and inputs, required Python modules, configured MATLAB runner, passively discoverable export/render backends, and the nearest existing output parent. Finalize mode additionally requires the final DOCX, PDF, rendered-page directory, visual-review record, and submission compliance file when configured. Passive backend discovery does not prove that Word COM, LibreOffice, MATLAB, or a renderer can start. Use `doctor.py --active-probe` when you need the same real startup and output-directory writability checks used by `preflight.py`; active probe results are nested under `environment.active_probe_report` and do not execute case modeling steps.

On Windows, LibreOffice probing and export prefer `soffice.com` over the GUI-oriented `soffice.exe`. Each export uses a temporary isolated LibreOffice user profile so an existing desktop session or stale profile lock does not capture the headless request.

Preview the selected execution and cache decisions without running preflight, executing case steps, creating directories, or writing state and reports:

```powershell
python scripts/run_pipeline.py --case-dir <case-dir> --plan --json
python scripts/run_pipeline.py --case-dir <case-dir> --plan --from <step>
python scripts/run_pipeline.py --case-dir <case-dir> --plan --only <step-a>,<step-b>
python scripts/run_pipeline.py --case-dir <case-dir> --plan --force <step>
```

The version 1 execution-plan contract is `schemas/execution-plan.schema.json`. It reports `mode=passive_read_only`, the selected steps, whether paper post-processing would follow, workflow-state status, action counts, and a stable `reason_code` for every ordinary step; schema version 2 also reports the top-level `data_preparation` action when configured. Common cache reasons are `manifest_v1_cache_unsupported`, `cache_disabled`, `cache_state_missing`, `cache_state_invalid`, `fingerprint_changed`, `output_missing`, `output_hash_changed`, `forced`, and `cache_hit`. MATLAB MCP steps report whether their current hash-bound evidence is valid; batch steps are only marked as requiring execution and are never started by planning.

All primary JSON CLIs now preserve their established status and `errors`/`warnings` fields while also returning `diagnostics_schema_version`, `diagnostics`, and `diagnostic_summary`. Each diagnostic has a stable `severity`, `code`, `stage`, `message`, and `remediation`; applicable entries also include `json_pointer` and `retry_command`. The machine-readable contract is `schemas/diagnostics.schema.json`. Exit code `0` means the requested gate is healthy or complete; exit code `2` means at least one required gate failed.

Generated build reports, execution plans, finalization reports, visual-review records, and MATLAB validation evidence are validated against their bundled contracts. Persisted outputs are validated before atomic replacement; execution plans are returned without being written. Pipeline reports use `report_schema_version=1`; the other records use `schema_version=1`. Read [versioning-and-compatibility.md](versioning-and-compatibility.md) before changing these fields or their meanings.

For schema version 2 Python steps, `inputs` and `outputs` are relative to the case directory. Enable `cache` only after declaring every file that can change the step's result and every output that proves completion. The cache fingerprint binds the script, arguments, declared inputs, Python executable, and Python version. Output hashes must also match the saved state. Missing, malformed, or stale `.workflow/state.json` data causes safe re-execution.

Declare upstream outputs as downstream inputs. This is how a changed upstream result invalidates dependent steps; the workflow does not infer hidden dependencies. Schema version 1 Python steps and version 2 steps with `cache: false` always execute.

### Analyze A Version 1 Migration

Before manually migrating a historical version 1 manifest, generate a passive analysis:

```powershell
python scripts/analyze_workflow_migration.py --case-dir <case-dir> --json
```

The analyzer never changes the case, executes a step, creates `.workflow`, or writes a patch. Its version 1 report contract is `schemas/workflow-migration-analysis.schema.json`. For a version 1 manifest it returns a validated version 2 candidate with explicit `profile: practice`; every Python step receives the behavior-preserving defaults `inputs: []`, `outputs: []`, `timeout_seconds: 300`, and `cache: false`. Existing MATLAB configuration is left unchanged. A version 2 manifest is reported as not applicable and receives no candidate.

Static Python AST inspection may report case-relative literal paths used by recognized file APIs. These are `static_literal_hint` evidence, not complete dependency declarations, and are deliberately kept out of the candidate manifest. Dynamic paths, helper-function semantics, imports, environment state, databases, network sources, random seeds, clocks, and other hidden dependencies still require human review. The analyzer never recommends `cache: true`; enable caching only after confirming complete inputs, outputs, determinism, timeout needs, and step ownership.

Rehearse the conservative candidate without changing or executing the source case:

```powershell
python scripts/rehearse_workflow_migration.py --case-dir <case-dir> --json
```

The version 1 rehearsal contract is `schemas/workflow-migration-rehearsal.schema.json`. The command runs the migration analyzer, creates a system-temporary case, copies only Python/MATLAB scripts and the files explicitly needed to preserve MATLAB evidence verification, writes the candidate manifest there, validates it, and generates a passive execution plan. It never starts Word, MATLAB, or case code. The temporary case is removed before the report is returned, and a source file-tree metadata comparison must still pass.

Every Python step receives five pending review checks: declared inputs, declared outputs, timeout, determinism, and cache enablement. Passing the rehearsal proves that the conservative candidate validates and plans in isolation; it does not prove dependency completeness or authorize caching. A schema version 2 manifest returns `status=not_applicable` without creating a temporary case.

### Review And Export A Version 2 Candidate

Preview or write a hash-bound review template without running case code:

```powershell
python scripts/review_workflow_migration.py --case-dir <case-dir> --json
python scripts/review_workflow_migration.py --case-dir <case-dir> `
  --write-review-template migration/workflow-v2-review.json --json
```

The template binds the current source manifest, the conservative base candidate, and every Python step script by SHA-256. Complete the reviewer identity, timezone-qualified ISO-8601 review time, declared inputs and outputs, timeout, determinism decision, cache decision, all five confirmations, and decision notes. Static path hints remain evidence for inspection and must not be treated as complete dependencies.

Validate the completed record without writing a candidate, then explicitly export a new file:

```powershell
python scripts/review_workflow_migration.py --case-dir <case-dir> `
  --review migration/workflow-v2-review.json --json
python scripts/review_workflow_migration.py --case-dir <case-dir> `
  --review migration/workflow-v2-review.json `
  --output workflow.v2.candidate.json --json
```

The closed review-record contract is `schemas/workflow-migration-review.schema.json`; the command report uses `schemas/workflow-migration-review-result.schema.json`. Every invocation reruns the isolated rehearsal. A manifest or Python script change makes the review stale. Cache can be enabled only when the reviewer confirms determinism and declares at least one output. The final manifest must also pass normal workflow validation and output-ownership checks.

Both write modes require a new `.json` path inside the case. Existing paths are never overwritten, and the candidate output cannot alias the source manifest, review record, scripts, dependencies, inputs, outputs, MATLAB evidence, compliance file, or paper artifacts. Exporting a candidate does not install it, execute it, or establish that its dependency declarations are factually complete; a person must inspect the diff before any explicit replacement of `workflow.json`.

### Audit A Reviewed Migration Candidate

Preview the acceptance requirements for a version 1 case without supplying evidence:

```powershell
python scripts/audit_workflow_migration_candidate.py --case-dir <case-dir> --json
```

The preview returns `status=evidence_required`, the expected conservative-candidate digest, and current Python script bindings. This is a request for human-reviewed evidence, not an accepted migration. A version 2 source returns `status=not_applicable`. Both states keep `accepted=false` and run only rehearsal and passive planning.

After completing the review and exporting the candidate, run the full acceptance audit:

```powershell
python scripts/audit_workflow_migration_candidate.py --case-dir <case-dir> `
  --review migration/workflow-v2-review.json `
  --candidate workflow.v2.candidate.json --json
```

The version 1 report contract is `schemas/workflow-migration-acceptance.schema.json`. Acceptance binds the raw source manifest, review record, candidate file, and every Python script by SHA-256. It reruns rehearsal, reloads the closed review record, and recomputes the only candidate authorized by that record. The supplied candidate must equal that recomputed object exactly; unauthorized additions, removals, or replacements are reported with JSON Pointer paths.

Authorized differences from the version 1 source are limited to `/schema_version`, `/profile` set to `practice`, and each reviewed Python step's `inputs`, `outputs`, `timeout_seconds`, and `cache` fields. MATLAB runner configuration, step order, step types, scripts, arguments, compliance settings, and all other manifest content remain unchanged.

The auditor also generates passive plans for the source and candidate. Acceptance requires the same step order, step types, MATLAB runners, and paper post-processing intent, with no blocked candidate steps. Step action and reason codes may differ when reviewed input, output, or cache metadata legitimately changes planning, such as `manifest_v1_cache_unsupported` becoming `cache_disabled`. The command never installs the candidate, replaces `workflow.json`, executes case steps, starts external tools, or writes case files.

### Compare Migration Readiness Across Cases

Summarize every direct-child case under a workspace without editing or executing it:

```powershell
python scripts/summarize_workflow_migration_readiness.py `
  --workspace-root <MathModel-root> --json
```

The version 1 report contract is `schemas/workflow-migration-readiness.schema.json`. Each case is classified as `ready_for_human_review`, `not_applicable`, or `blocked` and includes its source manifest SHA-256, expected conservative-candidate digest, current passive diagnostic error count and codes, Python and MATLAB step counts, human-review item count, static input/output hints, steps without hints, source-analysis failures, and per-step hint paths and reason codes. A blocked case does not hide the results for other cases, but it makes the overall command fail.

Applicable cases are ranked in ascending lexicographic order by current `doctor.py` error count, source-analysis-unavailable steps, Python steps, human-review items, Python steps without static hints, MATLAB steps, and case name. This ordering means only “no known passive diagnostic errors first, then smallest mechanically measured review workload among analyzable cases.” It does not assess model correctness, result validity, paper quality, cache safety, or whether migration should be approved. Existing `doctor.py` findings remain authoritative: their codes are exposed by the report and are neither suppressed nor treated as migration evidence.

The command reads only direct-child `workflow.json` files and their declared Python scripts. It emits the report to stdout, binds current source and candidate hashes, compares source file-tree metadata before and after each case, and never writes a report file, runs case steps, starts external tools, creates review evidence, enables cache, or changes `workflow.json`.

### Prepare The Human Review Work Package

After selecting a case from the readiness report, generate its passive work package:

```powershell
python scripts/prepare_workflow_migration_review_package.py `
  --case-dir <case-dir> `
  --expected-source-sha256 <readiness-source-sha256> `
  --expected-candidate-sha256 <readiness-candidate-sha256> --json
```

The optional expected hashes close the gap between cross-case selection and single-case preparation. If the manifest, conservative candidate, or a bound Python script changes, package generation rejects stale evidence. The version 1 report contract is `schemas/workflow-migration-review-package.schema.json`.

For each Python step, the package reports the script hash, ordered position, existing high-confidence `static_literal_hint` evidence, broader `review_candidate` paths discovered through simple case-relative assignments and known file/helper calls, candidate inputs and outputs, unclassified paths, and five `pending_human_review` checklist items: declared inputs, declared outputs, timeout, determinism, and cache enablement. Paths with no known file suffix and arbitrary prose strings are excluded from evidence.

Every path-evidence item carries one or more provenance chains classified as `direct`, `local_helper`, or `imported_helper`. The bounded tracer follows explicit functions in case-local Python files, `from module import helper` aliases, and limited `import module` calls when a statically bound path argument flows unchanged into a recognized read or write sink. It stops after four helper levels, protects against cycles, and removes helper-chain suffixes already represented by a longer chain while retaining direct sink evidence. Any case-local Python support module reached by a cross-module chain is bound by path and SHA-256 alongside the workflow entry scripts.

This provenance is still `review_candidate` evidence. Dynamic imports, star imports, runtime rebinding, generated path strings, transformed helper parameters, external packages, and behavior that requires executing the code are outside the tracer. Multiple provenance chains can support one path, and neither a trace nor a support-module hash establishes dependency closure.

When a bounded branch stops for a helper cycle, the four-level depth limit, dynamic import, star import, helper-name rebinding, transformed path parameter, or the step-local call-event budget, the step records a `trace_limitations` item with a stable reason code, module, function, line, callee, full entry-to-stop `call_chain`, and `review_required` status. The package rejects Python sources above 1 MiB, modules above 50,000 AST nodes, and per-step case-local closures above 64 modules; each step traces at most 10,000 call events. Structural excess fails the package, while event exhaustion retains earlier evidence and records `trace_budget_exhausted` without guessing the skipped dependency. Within one step, identical limitation chains are collapsed and a shorter chain is removed only when it is a complete suffix of a longer chain with the same reason code and stop point. Different entries, stop points, reason codes, and cycle directions remain separate. `trace_limitation_occurrences` reports the pre-deduplication count; `unique_trace_limitations` and the compatibility count `trace_limitations` report the retained review locations. Each step also exposes `trace_limitation_groups`, keyed by reason code and the complete module/function/line/callee stop point. A group reports `occurrences` from the raw events and `unique_call_chains` from the retained limitations; group occurrence and chain totals must reproduce the two summary counts exactly. The grouping is an index over existing evidence, not a severity, priority, approval, or new trace. A limitation identifies where source or runtime evidence needs human inspection; it contains no inferred path, is not an error or migration blocker, does not create a candidate input/output or support-module binding, and never authorizes dependency declaration or caching. These counts do not change the all-pending checklist.

An upstream relation is reported only when an earlier step's candidate output path exactly equals a later step's candidate input path. The relation remains `review_candidate` evidence; it is not dependency closure. Missing input candidates, output candidates, exact relationships, or path classification are listed as explicit evidence gaps rather than guessed.

The work package never writes a file, executes a case step, starts an external tool, creates a review record, exports a candidate, checks a confirmation, recommends cache enablement, or alters `workflow.json`. To make decisions, a person must inspect the scripts and runtime evidence and then separately complete the closed review record used by `review_workflow_migration.py`.

Render the same hash-bound evidence as a human-readable Markdown checklist on stdout:

```powershell
python scripts/render_workflow_migration_review_package.py `
  --case-dir <case-dir> `
  --expected-source-sha256 <readiness-source-sha256> `
  --expected-candidate-sha256 <readiness-candidate-sha256>
```

The renderer regenerates and schema-validates the machine package before displaying it. The document includes provenance and safety invariants, all source, entry-script, and traced support-module hashes, direct/local/imported provenance counts and chains, raw, unique, and group limitation counts, limitations grouped by step, reason code, and complete stop point with per-group occurrence/chain counts and full call chains, exact relationship candidates, explicit gaps, per-step path evidence, and unchecked `pending_human_review` items. Markdown-sensitive evidence is rendered as code or escaped text. The command has no `--output` option and writes only to stdout; an operator who deliberately redirects stdout owns that separate file and must not treat it as a formal review record. A stale source or candidate hash produces a failed Markdown view and a nonzero exit code.

Run or resume a subset of build steps:

```powershell
python scripts/run_pipeline.py --case-dir <case-dir> --phase build --from analyze
python scripts/run_pipeline.py --case-dir <case-dir> --phase build --only analyze,build-paper
python scripts/run_pipeline.py --case-dir <case-dir> --phase build --force analyze
```

`--from` executes the named step and all later steps, then continues through paper post-processing. `--only` executes only the listed steps and deliberately skips export, rendering, reconciliation, and submission gates; its success means only `steps_completed=true`. `--force` bypasses cached state for the named steps. Step-selection options apply only to the build phase.

Run preflight, all configured Python steps, DOCX-to-PDF export, PDF rendering, structural audit, and result reconciliation in one command:

```powershell
python scripts/run_pipeline.py --case-dir <case-dir> --phase build
```

Successful output is `ready_for_visual_review=true`, not submission readiness. The build report is written to `paper/pipeline-report.json`.

For a Markdown-authored paper, the `build-paper` step may use a case-local adapter for `tools/doc-export-enhanced`. The adapter generates only the configured DOCX artifact with native formulas, page numbers, and saved Word fields. It omits a table of contents by default; add `--include-toc` only when the current reviewed competition rules permit or require one. The pipeline remains responsible for PDF conversion, another field refresh immediately before export, rendering, structural audit, and reconciliation. The exporter's standalone `--pdf` mode uses direct Word COM export rather than the `docx2pdf` wrapper, but it is a regression aid rather than a substitute for the manifest pipeline. See [paper-production.md](paper-production.md) for the adapter contract and manifest example.
On failure, inspect the report's `failure` object for `failed_stage`, `cause_code`, `last_successful_step`, remediation, and a suggested resume command.
Python step failures use stable cause codes: `inputs` for missing scripts or declared inputs, `launch` when the process cannot start, `timeout` when it exceeds `timeout_seconds`, `execution` for a nonzero exit, and `outputs` when a successful process omits declared outputs. The resume command quotes the case directory so paths containing spaces remain usable.

The automated black-box acceptance suite runs temporary `explore` cases through the real CLI. It verifies exit codes, stdout and persisted report agreement, failure metadata, timeout handling, nonzero exits, missing outputs, corrupt-cache recovery, cache hits, and input/output hash invalidation. Run it without touching historical cases:

```powershell
python -m unittest discover -s tests -p "test_pipeline_blackbox.py" -v
```

The profile acceptance suite creates complete temporary paper fixtures and runs the real finalization CLI for `practice` and both `submission` AI states. It also injects a PDF change after visual review, an empty PDF, an escaped AI-log path, a hard-linked detail-PDF alias, and an AI-log mutation immediately after compliance audit:

```powershell
python -m unittest discover -s tests -p "test_profile_blackbox.py" -v
```

Export and rendering use staged artifacts. A converter result is accepted only when the temporary PDF has a valid signature, is readable, is unencrypted, and contains at least one page. Rendered pages must be structurally valid PNG files named continuously from `page-1.png`. Only validated artifacts replace the previous PDF or rendered-page directory; a directory-commit failure restores the previous pages. Pipeline-report atomic-write failures return structured JSON with `cause_code=atomic_write_failed`.

The controlled backend fault suite covers empty and corrupt PDFs, successful commands with unusable output, zero/invalid/discontinuous rendered pages, stale-page replacement, directory-commit rollback, and report-write path conflicts:

```powershell
python -m unittest discover -s tests -p "test_backend_faults.py" -v
```

Run the complete release gate from the skill directory or pass the workspace explicitly:

```powershell
python scripts/check_skill.py --workspace-root <MathModel-root>
python scripts/check_skill.py --workspace-root <MathModel-root> --json
```

The gate validates all bundled schemas and Python files, runs unittest discovery including profile lifecycle smoke tests, validates every direct-child historical manifest without executing it, runs `doctor.py`, generates a passive execution plan and migration analysis, rehearses the migration candidate in a cleaned temporary case, checks migration-review and acceptance previews, validates the cross-case readiness summary, and generates a hash-bound all-pending work package for the recommended case. It compares each historical case's file-tree metadata before and after those checks. Skill regressions, invalid historical manifests, invalid plans, migration reports, rehearsals, previews, readiness summaries or work packages, temporary cleanup failures, stale selection hashes, or any detected source write fail the command. Existing case findings are retained as warnings so the gate never manufactures missing modeling, migration-review, or compliance evidence. The frozen review-package resource and CLI calibration is recorded in `migration-review-package-release-baseline.md`; update it only after rerunning the complete gate and all-six-case measurement.

For a submission build, the generated DOCX/PDF must also pass `audit_submission_compliance.py` before `ready_for_visual_review=true`.

MATLAB steps use hash-bound MCP evidence by default:

```json
{
  "name": "solve",
  "type": "matlab",
  "runner": "mcp-evidence",
  "script": "src/solve.m",
  "test": "tests/test_solve.m",
  "outputs": ["results/solution.json"]
}
```

Read [matlab-integration.md](matlab-integration.md) before configuring or validating a MATLAB step. Do not use `runner: batch` until `matlab -batch` has passed a real startup smoke test on the current machine.

## 1. Preflight The Environment

Run before starting a case and after changing Python environments:

```powershell
python scripts/preflight.py --project-root <MathModel-root> --output-dir <case-dir>
```

The default gate requires `pypdf`, `docx`, `numpy`, `pandas`, `scipy`, `matplotlib`, and `openpyxl`. It also reports Microsoft Word registration, LibreOffice, Poppler, Tectonic, and MATLAB, including the primary and fallback document backends. Word availability requires a real COM startup probe, not just a registered executable. LibreOffice and PDF renderers also receive startup probes. A failed primary export attempts every usable fallback and records each attempt. Missing optional executables are warnings; missing requested Python modules or unwritable paths are errors.

Use repeated `--module` arguments only for a deliberately narrower operation. This replaces the default module set; it does not prove that the full modeling environment is ready.

Persist the versioned dependency and tool evidence after changing an environment, and
run the active chains before a rehearsal or feature freeze:

```powershell
python scripts/snapshot_environment.py --project-root <MathModel-root> `
  --output <MathModel-root>\.skill-audit\environment\environment-snapshot.json --json

python scripts/snapshot_environment.py --project-root <MathModel-root> `
  --active-smoke --smoke-dir <MathModel-root>\tmp\environment-smoke `
  --matlab-mcp-evidence <MathModel-root>\.skill-audit\environment\matlab-mcp-smoke.json `
  --output <MathModel-root>\.skill-audit\environment\environment-snapshot.json --json
```

The snapshot keeps the core dependency lock separate from a full `pip freeze` hash,
records actual executable paths and versions, and does not install, upgrade, or repair
anything. Read [environment-and-recovery.md](environment-and-recovery.md) for the
fallback order and offline-rebuild boundary.

## 2. Register Canonical Results

Keep generated values in JSON under the case directory. Add every value that drives a conclusion, abstract statement, figure, table, or result attachment to `results/result-register.json`:

```json
{
  "schema_version": 1,
  "results": [
    {
      "id": "q1.duration_s",
      "value": "1.410197",
      "source_file": "results/q1_results.json",
      "source_key": "duration_s",
      "paper_required": true,
      "paper_text": "1.410197",
      "absolute_tolerance": 0.000001,
      "relative_tolerance": 0.0
    }
  ]
}
```

`source_file` must stay inside the case directory. `source_key` supports dot-separated object keys and numeric list indexes. Registered and generated values must be finite JSON scalars; arrays, objects, `NaN`, and infinities are rejected. Omit `paper_text` when the registered `value` is exactly how it appears in the paper. Tolerances default to zero.

Do not hand-maintain a result register that mirrors a time-limited, feasible-incumbent solver output. When a valid rerun can change a headline value, create a case-local deterministic `register-results` producer immediately after the deterministic summary step. It must read the authoritative summary JSON and write `results/result-register.json` (and, when present, `results/result-register.md`) with every registered `value` and display-format `paper_text` derived from that source. Mark this producer `cache: true` only when its declared summary inputs fully determine its outputs. Declare the generated JSON as an input of `build-paper`, so a changed headline value invalidates the paper build. On a partial resume starting after the producer, run `--only register-results` first or resume from its upstream summary step; never repair stale registered numbers by hand.

Run reconciliation against the final artifacts:

```powershell
python scripts/reconcile_results.py --case-dir <case-dir> `
  --docx <paper.docx> --pdf <paper.pdf>
```

The gate fails if a source is missing, a generated value is stale or mismatched, or required display text is absent from either supplied paper artifact.
An empty result register is also a hard failure; populate it before finalization.

When the competition requires an `.xlsx` result template, also create a hash-bound
plan using `schemas/result-workbook-audit-plan.schema.json` and run:

```powershell
python scripts/audit_result_workbook.py --case-dir <case-dir> `
  --plan result-workbook-audit-plan.json `
  --output-dir results/workbook-audit --json
```

This standalone gate checks OOXML integrity, worksheet structure, critical cells,
saved values and formats, formula caches and spreadsheet errors, and mapped values in
`result-register.json`. It never saves or calculates the workbook. Read
[result-workbook-qa.md](result-workbook-qa.md), especially before choosing a tolerance
for a rounded export. Declare externally generated official workbooks as inputs to a
non-cached validation step when integrating this command into `workflow.json`. After it
passes, open the exact workbook in Excel or LibreOffice and inspect every worksheet;
visual layout and calculation-engine fidelity remain manual gates.

## 3. Record Visual Review

After the final layout-sensitive edit, render the PDF, create bounded JPEG previews with `scripts/prepare_visual_previews.py`, and inspect every page using no more than two attached previews per batch. If the existing conversation is already long, move this phase to a fresh task/context. Complete `paper/visual-review.json` from the original rendered pages: set `status` to `passed`, record the final PDF SHA-256, its page count, every reviewed page number in order, and the SHA-256 of every rendered page image. Do not reuse the record after changing the PDF or page images.

After actually inspecting every final page, generate the hash-bound record without editing JSON manually:

```powershell
python scripts/record_visual_review.py --case-dir <case-dir> `
  --pdf paper/paper.pdf --render-dir paper/rendered-pages `
  --reviewer "<reviewer>" --notes "<findings>"
  --output paper/visual-review.json
  --output paper/visual-review.json `
  --confirm-all-pages-reviewed
```

The confirmation flag is mandatory. The script checks page numbering and PNG signatures, but the reviewer remains responsible for the visual judgment.

Example for a two-page paper:

```json
{
  "schema_version": 1,
  "status": "passed",
  "reviewed_at": "2026-08-11T12:00:00+08:00",
  "reviewer": "team member",
  "pdf_sha256": "<sha256-of-final-pdf>",
  "page_count": 2,
  "reviewed_pages": [1, 2],
  "rendered_pages_sha256": {
    "page-1.png": "<sha256-of-page-1.png>",
    "page-2.png": "<sha256-of-page-2.png>"
  },
  "notes": "No clipping, overlap, missing glyphs, or blank trailing pages."
}
```

## 4. Run The Final Gate

When the case has a valid `workflow.json`, prefer the manifest-driven final command:

```powershell
python scripts/run_pipeline.py --case-dir <case-dir> --phase finalize
```

This delegates to the same `finalize_case.py` gate with the manifest's exact artifacts and audit settings. The direct form remains available:

```powershell
python scripts/finalize_case.py --case-dir <case-dir> `
  --docx <paper.docx> --pdf <paper.pdf> --render-dir <rendered-pages> `
  --page-size a4 --orientation portrait --forbid TODO
```

This runs a focused finalization preflight, result reconciliation, structural paper audit, rendered-page count check, and visual-review evidence verification. If `workflow.json` declares `quality_gate_plan`, it also runs the declaration-driven paper gate and records its complete report under `quality_gates` in `paper/finalization-report.json`. If it declares `m6_compliance_plan`, finalization runs the complete M6 audit and therefore fails until the configured human manifest is accepted and hash-valid. A legacy `compliance`-only workflow records scope `rules_and_ai_technical_only`; an omitted compliance path records `not_run_or_not_required`. It writes `paper/finalization-report.json`, including `gate_scopes`, and updates the generated section of `paper/qa-register.md`.

Those two output filenames are fixed inside the case `paper` directory. The finalizer rejects aliases or path overrides that could overwrite a paper, source, register, review artifact, or rendered page. It writes reports by atomic replacement and verifies the final DOCX, PDF, and rendered-page hashes again afterward.

The command exits successfully only when every gate passes. A missing or stale visual-review record keeps `ready_for_submission=false`. The audit validates PNG structure, compressed image data, continuous page numbering, and page hashes, but only recorded inspection can close the visual-quality gate.

## 5. Smoke-Test The Anonymous Support Package

After `package_submission.py` produces the managed support ZIP, run the core smoke
plan against that exact ZIP. Keep the plan case-local and restrict it to scripts that
can run from the packaged inputs without the original case tree, for example the
factor-analysis, prediction, and recommendation entry points. The report must bind
the exact ZIP SHA-256 and show zero non-zero exits, timeouts, or missing outputs:

```powershell
python scripts/audit_support_package.py --package submission-package/support-materials.zip `
  --plan support-smoke-plan.json --output submission-package/support-smoke-report.json --json
```

Do not treat a smoke pass as mathematical validation or as a substitute for the
paper quality gate. It is a reproducibility check for the anonymous delivery tree.

## 6. Enable Submission Compliance

### 6.1 Understand the two scopes

`audit_submission_compliance.py` is the compatibility path. It checks rules freshness and the basic AI declaration artifacts, and reports:

```text
scope = rules_and_ai_technical_only
full_m6_proven = false
```

That result is useful but is not a complete M6 pass. The complete route uses `schemas/m6-compliance-plan.schema.json` and `scripts/audit_m6_compliance.py`. Its technical scope covers:

- a case-local official-rules snapshot whose current bytes match the declared SHA-256, whose verification date is fresh, and whose listed sources are reviewed rather than trusted from URL syntax alone;
- anonymity of final DOCX/PDF, metadata, package names, support allowlist entries, and configured identifying terms or paths;
- a citation/external-data/software/license register;
- AI log and AI detail-PDF content markers, plus inclusion of the required detail PDF in the support allowlist;
- the support-material allowlist itself.

The source register has exact states:

- `pending`: incomplete and blocking;
- `complete`: at least one reviewed entry, with no `unknown` or `prohibited` license status and every required support file allowlisted;
- `not_applicable`: no entries, a substantive reason, and a real review timestamp.

Machine evidence can establish only `technical_passed=true`. Full M6 additionally requires a responsible human's immutable accepted manifest. Codex may prepare, audit, and challenge the evidence, but it must not execute `--confirm-human-reviewed`, name itself as reviewer, or convert blanket approval into an M6 signature. In a one-person competition run, use the actual operator name and describe the review as `single_operator_review`; never invent a second reviewer.

### 6.2 Configure the new submission route

A new submission scaffold contains:

```json
{
  "schema_version": 2,
  "profile": "submission",
  "compliance": "compliance/submission.json",
  "m6_compliance_plan": "compliance/m6-plan.json"
}
```

Complete `compliance/submission.json` for the legacy rules/AI inputs, replace the pending official-rules snapshot with the reviewed local record, recompute its SHA-256 in `compliance/m6-plan.json`, complete `compliance/source-register.json`, and make `submission-package-plan.json` an exact allowlist. If AI was used and the official rule requires `AI工具使用详情.pdf`, that exact file must appear in the support list.

Run the technical audit while preparing the candidate:

```powershell
python scripts/audit_m6_compliance.py technical --case-dir <case-dir> `
  --plan compliance/m6-plan.json --docx paper/paper.docx `
  --pdf paper/paper.pdf --json
```

The build phase performs this technical audit automatically when `m6_compliance_plan` is configured. It does not wait for human M6 and does not claim full M6.

Prepare an immutable review candidate only after the technical audit passes:

```powershell
python scripts/audit_m6_compliance.py prepare --case-dir <case-dir> `
  --plan compliance/m6-plan.json --docx paper/paper.docx `
  --pdf paper/paper.pdf --output compliance/M6-candidate-<review-id>.json `
  --generated-at <ISO-8601-with-offset> --review-id <review-id> --json
```

This produces `M6_PENDING_HUMAN`. The responsible human reviews the bound evidence. Only that human may then record the actual decision; Codex must stop before this command rather than signing on the operator's behalf:

```powershell
python scripts/audit_m6_compliance.py finalize --case-dir <case-dir> `
  --candidate compliance/M6-candidate-<review-id>.json `
  --output compliance/M6-accepted.json --decision accepted `
  --reviewer "<actual responsible human operator>" `
  --review-start <ISO-8601-with-offset> --review-end <ISO-8601-with-offset> `
  --signed-at <ISO-8601-with-offset> --generated-at <ISO-8601-with-offset> `
  --confirm-human-reviewed --json
```

Use `accepted_with_limitations` only with substantive `--objections` and `--resolution`; use `rejected` when unresolved compliance prevents submission. Then verify the recorded manifest:

```powershell
python scripts/audit_m6_compliance.py verify --case-dir <case-dir> `
  --manifest compliance/M6-accepted.json --json
python scripts/audit_m6_compliance.py audit --case-dir <case-dir> `
  --plan compliance/m6-plan.json --docx paper/paper.docx `
  --pdf paper/paper.pdf --json
```

`verify` proves record structure, candidate linkage, timestamps, decision semantics, and current evidence hashes. It cannot prove the human truly performed the review. `audit` is the full M6 machine result and passes only when both the technical audit and accepted human manifest pass.

### 6.3 Legacy compatibility

A historical or deliberately compatibility-only workflow may keep only `compliance/submission.json` and run:

```powershell
python scripts/audit_submission_compliance.py --case-dir <case-dir> `
  --compliance compliance/submission.json `
  --docx paper/paper.docx --pdf paper/paper.pdf
```

The legacy report binds its evidence by SHA-256 and finalization rechecks it, but its scope remains `rules_and_ai_technical_only` with `full_m6_proven=false`. Do not use it to claim that anonymity, citations, external data, software licenses, the complete support allowlist, or a human M6 decision were closed.

## 7. Build The Upload Package

Run packaging only after finalization reports `ready_for_submission=true`. Packaging is deliberately standalone and is not a `run_pipeline.py` phase: finalization validates the authoritative case artifacts, while packaging creates the two clean files intended for upload.

Create a case-local plan matching `schemas/submission-package-plan.schema.json`:

```json
{
  "schema_version": 1,
  "finalization_report": "paper/finalization-report.json",
  "paper": {
    "source": "paper/paper.pdf",
    "output_name": "paper.pdf",
    "max_bytes": 20971520
  },
  "support": {
    "output_name": "support-materials.zip",
    "max_bytes": 20971520,
    "files": [
      {"source": "src/solve.py", "archive_path": "src/solve.py"},
      {"source": "results/result1.xlsx", "archive_path": "results/result1.xlsx"},
      {"source": "ai/AI工具使用详情.pdf", "archive_path": "AI工具使用详情.pdf"}
    ]
  },
  "anonymity": {
    "forbidden_terms": ["team identity", "institution name"]
  }
}
```

The byte limits are explicit because the latest official upload system is the authority for the meaning of its displayed `MB` limit. The example uses the project's current conservative `20 * 1024 * 1024` convention. Set the output names from the current official naming rule; the tool intentionally does not guess a team-number filename.

Run:

```powershell
python scripts/package_submission.py --case-dir <case-dir> `
  --plan submission-package-plan.json `
  --output-dir submission-package `
  --generated-at "2026-08-18T23:59:59+08:00" --json
```

The report timestamp defaults to the timezone-aware timestamp already bound by finalization. Use `--generated-at` when a controlled rehearsal or audit needs a different explicit time; timestamps without a timezone offset are rejected.

The support list is an allowlist. Include the complete runnable code, required result workbooks, support-file inventory evidence, required AI detail PDF, and any data the official rule requires. Do not include caches, rendered pages, editor files, temporary outputs, unrelated research branches, or source identities merely because they are present in the case.

The packager rejects stale or unsuccessful finalization, stale required compliance evidence, and any finalization claiming `scope=full_m6` without `full_m6_proven=true`. It preserves compatibility with a valid legacy rules-and-AI-only finalization but does not upgrade that scope. It also rejects unreadable or encrypted PDFs, missing and empty files, escaped paths, symbolic links and junctions, hard-link aliases, duplicate or case-colliding archive names, unsafe output names, configured identity terms in names or extractable PDF/Office/text content, and either configured size limit. It copies the paper without transformation, creates a deterministic ZIP with `submission-manifest.json`, checks ZIP CRC and entry hashes, performs traversal-safe temporary extraction, validates the report against `schemas/submission-package-report.schema.json`, and commits all three outputs together.

The output directory must be empty or contain only a previously verified package managed by this command. Ordinary runs never overwrite. `--replace` succeeds only when the existing report validates, owns the same paper and support filenames, and both existing output hashes still match; a failed rebuild preserves that verified prior package. Always open the final PDF and ZIP using the same machine or upload client used for submission even after the machine checks pass.

## 8. Bind M7 And Record Official F2

A local finalization or package status is not an official-submission status. Keep these statements distinct:

```text
ready_for_submission=true
!= package created
!= M7-PRECHECK-PASS
!= M7 accepted
!= upload attempted
!= F2_COMPLETE
```

New submission scaffolds declare `m7_f2_plan` in `workflow.json` and create `m7-f2-plan.json` plus `submission/M7-review-card.md`. The plan selects exactly one package report, one support-smoke report, every required smoke-test name, the official competition/platform, the future receipt path and suffix allowlist, and immutable final M7/F2 manifest paths. The scaffold intentionally does not create a receipt.

After packaging and the clean support replay, run the machine precheck:

```powershell
python scripts/audit_m7_f2.py precheck --case-dir <case-dir> `
  --plan m7-f2-plan.json --json
```

The precheck revalidates package/finalization/source hashes, current packaged paper and support ZIP size/hash, source-versus-packaged PDF equality, the support-smoke ZIP binding, and every declared required smoke test. Its only positive status is `m7_precheck_passed=true` with `official_submission_status=NOT_FORMAL_F2`.

Prepare a pending candidate:

```powershell
python scripts/audit_m7_f2.py prepare-m7 --case-dir <case-dir> `
  --plan m7-f2-plan.json --output submission/M7-candidate-<review-id>.json `
  --review-id <review-id> --generated-at <ISO-8601-with-offset> --json
```

This creates only `M7_PENDING_HUMAN`. After the responsible human actually reviews the selected PDF, package report, support ZIP/replay, names, sizes, and upload plan, that human—not Codex—may run `finalize-m7 --confirm-human-reviewed`. A one-person run records `single_operator_review`. Accepted M7 still reports `NOT_FORMAL_F2`; verify it with `verify-m7` before upload.

Only after the unchanged selected package is actually uploaded and a real non-empty official receipt is preserved at the plan-selected path may the responsible human run:

```powershell
python scripts/audit_m7_f2.py record-f2 --case-dir <case-dir> `
  --plan m7-f2-plan.json --output submission/F2-submission.json `
  --submission-id <local-record-id> `
  --portal-submission-identifier <official-portal-id> `
  --operator "<actual responsible human operator>" `
  --upload-start <ISO-8601-with-offset> --upload-end <ISO-8601-with-offset> `
  --receipt-recorded-at <ISO-8601-with-offset> `
  --generated-at <ISO-8601-with-offset> `
  --confirm-official-upload --json
```

Codex must not run the confirmation-bearing `finalize-m7` or `record-f2` command on the operator's behalf. `verify-f2` rechecks the immutable M7 manifest, current package evidence, receipt hash, human operator, platform fields, and timestamp order. Only a passing verification supports `F2_COMPLETE`.
## 9. Record A Timed Rehearsal

Timed-rehearsal records are standalone and do not add a pipeline phase. Before a scheduled practice or simulation, create a case-local plan matching `schemas/timed-rehearsal-plan.schema.json`, then use `scripts/manage_timed_rehearsal.py init`, `record`, and `close`. The tool freezes the plan hash, appends hash-chained events with case-local evidence hashes, validates failure/rework and injection/recovery relationships, and emits a plan- and log-bound review matching `schemas/timed-rehearsal-review.schema.json`.

Closing requires all six phases, every planned fault injection and recovery, the nine competition scorecard decisions, and disposition of every failure and rework event. `record_complete=true` describes evidence closure only. It does not set or imply `ready_for_submission`, model correctness, paper completeness, or package validity. Full commands, review fields, and the supported Windows test invocation are in [timed-rehearsal.md](timed-rehearsal.md).

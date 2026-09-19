# Failure Prevention And Recovery

This reference records evidence-backed failures found during rehearsals and live-case work, plus the controls that prevent recurrence in future cases.

## Incident Register

| Failure | Root cause | Permanent control | Recovery |
| --- | --- | --- | --- |
| `prepare-data` reported `data/raw/official-2025-e` missing although the directory existed | Python-step fingerprinting required every declared input to be a file | Directory inputs are now accepted and hashed by a deterministic relative-file manifest in `sha256_path` | Keep the raw directory declared in `workflow.json`; rerun `--validate-only` then `--phase build` |
| Build stopped at result-register precheck | The case still used the older subproblem/file-list register instead of scalar value bindings | `reconcile_results.py` remains a hard gate; every headline number must bind to `source_file` and `source_key` | Rebuild `results/result-register.json` from authoritative JSON outputs, then run reconcile before paper export |
| Model-definition audit rejected otherwise valid definitions | Material and non-material ambiguity rules were not reflected in the register; evidence and exact disclosure text were missing | Every material ambiguity uses `alternative_reoptimization.status=completed`, real evidence files, and text present in both DOCX/PDF | Update the register, rebuild DOCX/PDF, and rerun the definition audit |
| PDF contained template prose such as `Paper Title` and `State the problem...` | Structural paper audit checked geometry but not template content | `audit_paper.py` now rejects known template markers in both DOCX and PDF | Replace all placeholder prose before rerunning build |
| Final PDF retained the current LaTeX template's visible reference, appendix-navigation, or minimal-source examples | The template told the writer to replace/delete them, but the default paper audit recognized only legacy English markers | `audit_paper.py` rejects the current Chinese markers in DOCX/PDF and tolerates extraction line breaks | Replace each example with real verified references, real archive paths, and the frozen complete source; delete inapplicable rows, rebuild, and rerun the audit |
| Final PDF showed authoring guidance, generic symbols, title/keywords, or an unchosen AI declaration | Guidance was ordinary body prose and generic choices had no fail-closed state | Keep guidance searchable only as `% AUTHORING-GUIDANCE:` source comments; give every unfinished title/abstract/keywords/section/declaration a stable `MMFINALIZE-*` sentinel; `audit_paper.py` rejects the single prefix | Replace every sentinel with problem-specific content, adapt/delete irrelevant section headings, rebuild, rerun structural audit, then inspect every rendered page |
| PDF showed raw `\\[ ... \\]` LaTeX source | The exporter converts `$...$` and `$$...$$`, not `\\[...\\]` display blocks | Paper authoring rules require `$$...$$` for display formulas; audit rejects visible unrendered LaTeX markers | Convert display blocks to `$$...$$`, rebuild, render, and inspect formula pages |
| A disclosure string passed in Markdown but failed in exported papers | Markdown styling such as `**...**` is not preserved by DOCX/PDF text extraction | Material definition `paper_text` must be a plain text sentence that appears verbatim after export | Use a short unformatted sentence and rerun the definition audit |
| Patch command returned Windows `Access is denied` despite writable ACL | Temporary replacement path used by the patch wrapper was blocked while direct file access still worked | Record the failure; use the project-approved direct write fallback only after checking ACL, file attributes, and ownership; never weaken protection globally | Check `Get-Acl`, `Attributes`, and target path; make one bounded fallback edit and verify the diff |
| Codex stream disconnected, concurrency limit, or transient `502` interrupted a long turn | The service/session transport failed; this is not evidence that the case pipeline failed | Keep the project rule of one serial main Agent, inspect persisted reports and running processes, and resume from the last verified gate; never spawn retry Agents | Reopen the same task, read `pipeline-report.json` and the latest failure event, then rerun only the failed gate |
| A Windows `.cmd` wrapper could not resolve an internal executable path | The wrapper depended on an inherited `PATH`/working-directory assumption | Preflight discovers concrete executables and probes them before export; use the resolved executable path in recovery commands | Run `preflight.py --json`, use the reported concrete backend path, and do not replace the project environment blindly |
| A passive pipeline plan failed under the default Windows `python` because NumPy was absent while the project `.venv` worked | The operator resumed with an interpreter selected by the shell rather than the case environment | Record the concrete interpreter at case start and resume; run the import smoke before planning or executing the pipeline | Switch to the recorded project interpreter, rerun the same passive plan, and do not install into or rewrite the unrelated default interpreter |
| A case accumulated many numbered paper candidates while the authority pointer headline and active control files still described an earlier question | Candidate production advanced without an authority heartbeat, so technical maturity and formal state diverged | Run the `Authority Heartbeat` from `single-operator-live-runbook.md` after accepted subproblems, exports, package rebuilds, and resumes; stop on `SUBMISSION_AUTHORITY_DRIFT` | Select exactly one current numerical, paper, and support artifact; mark displaced candidates superseded; reconcile pointer and active controls before promotion |
| A technically verified support ZIP explicitly excluded the rule-required AI detail PDF | Replay verification and submission compliance were treated as separate late tasks, leaving no time-safe admissible package | Build the AI detail and support skeleton early; label omission-bearing archives `TECHNICAL_ONLY_SUPPORT_PACKAGE`; block M7 selection with `AI_DETAILS_NOT_BOUND` | Generate and review the required PDF from the chronological record, add it to the allowlist, rebuild, rebind hashes, and repeat exact-archive checks |

Every failed `run_pipeline.py` attempt now appends a structured event to the case-local
`rehearsal/failure-events.jsonl`. A standalone preflight can do the same when invoked
with `--failure-log`. The event contains the phase, failed stage, cause code, bounded
errors, remediation, and command. This log is diagnostic evidence, not a replacement
for fixing the underlying workflow; a failure must still stop the current phase.

## Preflight Order

1. Validate `workflow.json`.
2. Confirm the raw source directory exists and remains unchanged.
3. Run the Python/MATLAB environment preflight.
4. Run the analysis steps.
5. Reconcile the scalar result register.
6. Build DOCX and export PDF.
7. Run structural paper audit, model-definition audit, and rendered-page checks.
8. Perform human visual review and record the actual responsible human reviewer/operator identity.
9. Finalize only after the review record hashes the current PDF and every rendered page.

## Recovery Contract

When a command returns a non-zero status:

1. Read the last line of `rehearsal/failure-events.jsonl` (if present).
2. Classify the failure by its `cause_code`; do not infer success from a partial file.
3. Apply the listed remediation and rerun the same gate.
4. Only advance to the next phase after the gate returns zero and its report says it is ready.

The event writer is best-effort and append-only. If the log itself cannot be written,
the original command failure remains authoritative and the user must repair the log
directory permissions before the next rehearsal.

A green `ready_for_visual_review=true` means only that automated gates passed. It never replaces visual inspection.


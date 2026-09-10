# Submission Checklist

Read [paper-closeout.md](paper-closeout.md) for evaluator-facing cleanup, current reference/AI evidence, full-page review, exact ZIP verification and the default closeout finalization gate. Old or omitted review evidence is not a pass.

## Mathematical Contract

- Answer every subproblem directly.
- Define each symbol once and preserve units.
- State assumptions that affect results and justify them.
- Make objectives, constraints, dynamics, or statistical hypotheses explicit.
- Distinguish fitted parameters, measured inputs, and chosen constants.

## Data And Code

- Preserve raw data unchanged. For ZIP/RAR/7z inputs, record container path/hash and every used member path/hash separately; never substitute the container hash for a member hash.
- Document cleaning, exclusions, transformations, and missing-value handling.
- Prevent train/test leakage and temporal leakage.
- Make scripts run from documented inputs without manual hidden steps.
- Fix random seeds where appropriate and record software versions.
- Recompute all submitted result-template files from the final code.
- For every submitted `.xlsx`, bind its SHA-256 in a reviewed workbook-audit plan and run `scripts/audit_result_workbook.py`; require a passing report with `input_unchanged=true`.
- Recalculate formula workbooks in Excel or LibreOffice before auditing; never treat a missing cached formula value as zero or ask the audit script to overwrite the source.
- Open the exact audited workbook and inspect every worksheet for visible rounding, units, clipping, hidden content, print areas, charts, and agreement with the paper.

## Validation

- Compare with a transparent baseline.
- Check feasibility, residuals, error metrics, or conservation as appropriate.
- Test important assumptions and parameters.
- Explain uncertainty, limitations, and known failure cases.
- Confirm that conclusions do not exceed the evidence.

## Paper

- Keep the abstract within the official limit and include methods, main results, validation, and keywords.
- Use a logical section order; start writing before all subproblems are finished.
- For every substantive subproblem, include analysis, definitions, derivation, algorithm or estimation, results, validation, and a direct answer; do not substitute a cross-paper summary for these local evidence chains.
- Include data provenance and preprocessing evidence, a transparent baseline, parameter or solver details, robustness or sensitivity evidence, and limitations wherever the corresponding claims require them.
- Give figures labeled axes, units, legends, and readable captions.
- Use tables only for comparable records; align precision with measurement meaning.
- Reference every important figure, table, equation, and appendix item from the text.
- Reconcile headline values across abstract, body, conclusion, and attachments.
- Cite external data, software, algorithms, and prior work at the point of use.
- Remove identities where anonymous review requires it. Scan paper DOCX/PDF text and metadata, support filenames and archive paths, and every extractable support DOCX/PDF/OOXML/text payload for configured identity terms and local absolute paths. The generated ZIP inherits the same checked members; binary formats that cannot be extracted remain an explicit manual-review limitation, not a silent pass.
- Keep one authoritative paper source; do not hand-edit independent Word and PDF copies.
- Use real heading styles and real list numbering in Word output.
- Keep short formula lead-ins with the following display equation.
- Render display mathematics; do not leave Markdown, backticks, or LaTeX commands visible in prose.
- Prevent floating figures, clipped tables, orphaned captions, and nearly blank final pages.
- Record front-matter/abstract, main-text, declarations/references, and appendix page counts separately. Treat total PDF length as neither a compliance check nor a quality score.
- If a multi-subproblem full paper has fewer than 15 main-text pages, complete and record a section-by-section completeness review; do not pad the paper or label an unresolved skeleton as complete.

## Competition Artifacts

- Use the current official template and commitment/numbering pages.
- Confirm page limits, file naming, paper format, and support-material limits.
- Include complete runnable source code and a support-file list when required.
- Keep complete source code in the appendix or support materials while retaining the essential equations, algorithm explanation, diagnostics, and representative outputs in the main text.
- Include the official AI-use statement.
- If AI was used, produce the required detailed AI-use PDF from the reviewed log.
- Open every final file and visually inspect the complete rendered paper.
- Re-render after the final layout-sensitive edit and inspect every page, not a sample.
- Run `scripts/audit_paper_quality_gates.py` from a case-local plan: require explicit
  abstract Q1--Q4 markers, method/result/limitation structure for every subproblem,
  formula-to-source tokens and result IDs, figure-to-result bindings, page-region
  continuity, complete source-appendix entries, DOCX/PDF metadata scans, and exact
  `rendered-pages/page-N.png` continuity with no extra PNGs.
- Treat the quality-gate report as an input to finalization, not as a replacement for
  human visual review or mathematical review.

## M6 Compliance Gate

- Use the current official rules and a case-local snapshot; confirm the plan's SHA-256 matches the exact snapshot bytes.
- Distinguish legacy `rules_and_ai_technical_only` from complete `full_m6`; never report the former as M6 approval.
- Complete `compliance/source-register.json`: `pending` blocks; use `complete` for reviewed entries or `not_applicable` only with a substantive reason and review timestamp.
- Reject unknown/prohibited software or data license status; cite external data, software, algorithms, and prior work at use sites.
- Run the complete M6 technical audit against the exact final DOCX/PDF and exact support allowlist.
- When AI use requires `AI工具使用详情.pdf`, verify its required content and include the exact file in `submission-package-plan.json`.
- Prepare an immutable `M6_PENDING_HUMAN` candidate. The actual responsible operator performs and records `single_operator_review`; Codex does not execute `--confirm-human-reviewed` or sign M6.
- Use `accepted_with_limitations` only with substantive objections and resolution; otherwise accept or reject honestly.
- Verify the accepted manifest and rerun the full M6 audit during finalization. A successful machine verification does not prove the human review occurred.

## M7 And F2 Authority Gate

- Complete `m7-f2-plan.json` with one selected package report, the matching support-smoke report, every required smoke-test name, current official competition/platform, a receipt suffix allowlist, and distinct immutable M7/F2 manifest paths.
- Do not create a placeholder or fabricated receipt. The receipt path remains absent until the responsible human completes the real official upload and saves the actual evidence.
- Run `scripts/audit_m7_f2.py precheck`; require `m7_precheck_passed=true`, clean required smoke tests, current hashes/sizes, and `official_submission_status=NOT_FORMAL_F2`.
- Prepare `M7_PENDING_HUMAN`. The actual responsible operator performs `single_operator_review`; Codex does not execute `finalize-m7 --confirm-human-reviewed` or sign M7.
- Verify the accepted M7 manifest before upload. M7 acceptance still means `NOT_FORMAL_F2`.
- Upload exactly the unchanged selected package to the current official platform, preserve the real non-empty receipt, and record substantive local and portal submission identifiers.
- Only the responsible human executes `record-f2 --confirm-official-upload`; Codex does not infer an upload from earlier consent or a local package status.
- Run `verify-f2`; require current plan, accepted M7, package evidence, receipt hash, human operator, platform fields, and timestamps to agree before recording `F2_COMPLETE`.
- Keep the distinction explicit: `ready_for_submission=true` != package created != `M7-PRECHECK-PASS` != M7 accepted != upload attempted != `F2_COMPLETE`.
## Final Reconciliation

- Run the final pipeline from clean inputs.
- Record the exact commands and environment.
- Check that no output is stale, missing, empty, or from an earlier model version.
- Scan formulas, tables, result files, references, and filenames for inconsistencies.
- Run `scripts/reconcile_results.py` against the canonical result register and final DOCX/PDF.
- Confirm every required result-workbook cell agrees with the canonical register under an explicitly justified export tolerance.
- Run `scripts/finalize_case.py` with the official page size and known forbidden placeholder strings.
- Confirm the number of rendered page images equals the PDF page count.
- Confirm `paper/visual-review.json` matches the final PDF and rendered-page hashes and lists every inspected page.
- Create an explicit support-file allowlist matching `submission-package-plan.schema.json`; do not archive the case recursively.
- Run `scripts/package_submission.py` only after `ready_for_submission=true` and inspect its hash-bound report.
- Confirm the packaged PDF hash equals the finalized PDF hash; open the packaged PDF and verify its page count.
- Confirm the support ZIP passes CRC, manifest, entry-hash, duplicate-name and extraction round-trip checks.
- Confirm every `archive_path` preserves the case-relative directories required by the packaged main entry point; do not flatten `problem/source/...` to `problem/...` merely for neatness.
- Run `scripts/audit_support_package.py` against the exact support ZIP and the reviewed case-local `support-smoke-plan.json`; execute the packaged main entry point from a clean extraction root and require the ZIP hash binding, safe relative paths, zero non-zero exits, zero timeouts, and all declared core outputs. Package construction or extraction round-trip alone is not a runnable-package pass.
- Do not enter M7 precheck unless the selected support ZIP has a passing smoke report bound to that exact ZIP and every required test name in `m7-f2-plan.json`.
- Confirm final byte sizes and exact output filenames against the current official upload system.
- Confirm no required code, result workbook, support inventory, data file, or AI detail PDF was omitted from the allowlist.
- Preserve the previous verified package if a last-minute rebuild fails; use `--replace` only for an unchanged managed package.
- State any check that could not be run and the resulting risk.

# Paper Production

Read [paper-closeout.md](paper-closeout.md) for evaluator-facing cleanup, current reference/AI evidence, full-page review, exact ZIP verification and the default closeout finalization gate. Old or omitted review evidence is not a pass.

Use this workflow for competition papers that must be delivered as DOCX, PDF, or both.

## 1. Establish The Output Contract

- Read the current official template and rules before choosing page size, margins, cover pages, anonymity, filenames, or page limits.
- Keep one authoritative source for narrative content and values. Treat generated DOCX/PDF files as build artifacts.
- Record provenance for every headline result in `results/result-register.md`, and add its canonical machine-readable value and JSON source to `results/result-register.json`.
- Classify the requested artifact explicitly as an exploratory note, concise report, full practice paper, or submission paper. Do not deliver an exploratory note under a full-paper label.

## 2. Plan A Complete Competition Paper

For a full practice or submission paper, plan the main text around the evidence needed to defend every answer:

- abstract with the problem, methods, headline results, validation, and keywords;
- operational problem restatement and a subproblem dependency map;
- problem analysis and an overall technical route;
- justified assumptions, symbols, units, and definition choices;
- data provenance, audit findings, preprocessing, and leakage controls when data are supplied;
- one complete model-and-solution section per substantive subproblem;
- transparent baseline and meaningful alternative-model comparisons;
- a separate identity record for candidate-comparison evidence, model selection, and any post-selection final refit; report final-fit parameters or target outputs separately from validation performance;
- parameter estimation, solver settings, convergence or feasibility evidence;
- result tables and figures tied to generated artifacts;
- error, residual, sensitivity, robustness, or uncertainty analysis matched to the claim;
- direct conclusions for every requested output, followed by strengths, limitations, and extensions;
- references, the required AI-use declaration, support-file inventory, and complete runnable source code.

Within each subproblem section, use the shortest defensible chain `problem transformation -> definitions and assumptions -> core derivation -> transparent baseline -> main model or justified improvement -> algorithm -> result -> comparison or diagnostic -> interpretation -> validation and boundary -> direct answer`. A step may be omitted when the problem structure genuinely makes it inapplicable, but do not silently replace a missing derivation, baseline, or validation with a method name. If two subproblems share a model, state the reusable core once and still show the changed variables, constraints, data, results, and validation for each question. For a mechanism- or geometry-heavy subproblem, instantiate that chain as `real object -> coordinate/time variable and local symbols -> geometry or physical mapping -> state closure -> event/constraint logic -> numerical update order -> mechanism evidence -> result -> convergence/definition boundary`. This is a closure check, not a demand that every item become a separate subsection.

For a full practice or submission paper, include a standalone **Symbols and Units** subsection before the substantive model sections. Its table should cover repeatedly used global indices, inputs, decision variables, state variables, parameters, and evaluation metrics, with meaning plus unit or domain; add index ranges or information timing when they affect interpretation. Define local one-use intermediate quantities at first use instead of bloating the global table. Check dimensional closure and keep every later symbol consistent with the table.

For a prediction subproblem with repeated measurements, clustered records, time-linked observations, or a deployment target that differs from the row unit, instantiate the general chain as:

```text
prediction target and deployment unit
-> data hierarchy and grouping unit
-> leakage-safe fold-local preprocessing
-> transparent naive baseline
-> predeclared candidates
-> validation matched to deployment
-> aggregate error gain
-> per-group failure and bias structure
-> target prediction and model disagreement
-> target-domain check
-> uncertainty interval and coverage semantics
-> conditional-input source when applicable
-> acceptance or stopping rule
-> extrapolation and causal boundary
```

This is an evidence contract, not a fixed model, figure count, or formula count. For candidate selection, freeze the analysis unit and deployment unit, split or time window, fold-local preprocessing, metric and aggregation, candidate set, selection rule, and tuning/search budget before comparison. Select only from the comparison evidence. If the selected structure is refit on all allowed training data, label the resulting parameters or target outputs as final-fit outputs and do not present them as unbiased validation performance; report the two result identities separately. Any change to the comparison or final-fit contract reopens the freeze and requires recomputation of affected evidence. Random row-level cross-validation cannot support a new-person, new-device, new-site, or other new-group claim when related rows from the same group can appear in both training and validation. Keep imputation, scaling, feature selection, and model fitting inside each validation fold. Report aggregate metrics together with the groups that fail, because one average can hide deployment heterogeneity. Separate a model's improvement over the naive baseline from whether the target object's point decision changes materially. For a specific target, show whether consequential covariates lie inside the training domain; agreement among candidate point predictions does not establish individual precision. State how every interval was constructed and whether its nominal level is empirical, calibrated, model-based, or guaranteed. For a conditional scenario, disclose the source, sample size, transformation rule, and whether the model was refit, then bind the recommendation to an observable acceptance or stopping condition. Do not write a conditional prediction as an observed intervention effect, causal effect, or training guarantee.
For a constrained optimization subproblem, instantiate the general chain as:

```text
decision variables and domains
-> objective and constraints
-> transparent feasible baseline
-> search hierarchy and optimizer status
-> final-precision feasibility recomputation
-> active constraints
-> candidate comparison and selection
-> multi-objective trade-off when applicable
-> robustness or sensitivity cost
-> optimality boundary
```

This is an evidence contract, not a requirement that every item become a separate subsection. Report a feasible baseline under the same definitions used for the selected solution; when the feasible region is sparse, include a reproducible feasible-count or equivalent diagnostic. Compare candidates only after independently recomputing all constraints at the paper's final numerical precision. A lower objective does not rescue a negative constraint margin. If a constraint is active or nearly active, connect its margin to numerical tolerance, sensitivity, or scenario failure rather than listing it without interpretation. Preserve the optimizer's actual exit state: `success=false`, an iteration limit, a local stop, or an exception must not be restated as convergence. A nonconverged candidate may still be reported only as a bounded candidate after independent feasibility recomputation.

For multi-objective results, independently recompute objective values, feasibility, and nondominance at final precision. State each objective's unit, any scaling or normalization, and the compromise-selection or preference rule. If the final nondominated set contains only one point, show it as a singleton result or candidate-collapse diagnostic; do not draw or describe it as a continuous, dense, or stable Pareto front. If alternative defensible objective definitions are material, reoptimize each definition rather than merely rescoring one fixed solution, then report whether the definition changes the operational decision. For robustness, distinguish fixed-control stress tests from robust reoptimization, report the performance cost of restoring feasibility, define the uncertainty or scenario set, and bound the claim to that set.
Use baseline--improvement--benefit as an explanatory contract, not a demand for model complexity:

1. identify a transparent, reproducible baseline;
2. state the baseline failure that matters to the data structure, constraint, or decision;
3. explain which added model structure addresses that failure;
4. compare both routes under the same validation definition;
5. report the gain together with computation, stability, interpretability, or generalization cost.

Do not manufacture length. Repetition, decorative flowcharts, oversized figures, loose spacing, screenshots of ordinary prose, and unrelated textbook derivations are defects. Put long code listings, exhaustive result tables, hashes, manifests, internal paths, and reproducibility inventories in appendices, while keeping enough equations, pseudocode, diagnostics, representative results, and real-world interpretation in the main text to make the argument independently understandable.

## 3. Account For Pages By Region

Record four counts in `paper/qa-register.md`: front matter/abstract, main text, declarations/references, and appendices. Use the current official definition of where main text begins and ends; total PDF pages cannot establish page-limit compliance.

For 2026 CUMCM, the verified snapshot says the main text after the abstract is limited to 30 pages and appendix length is unrestricted. Verify that rule again for a live submission. A normal evidence-rich solution often needs about 18-28 main-text pages, but this is a planning calibration, not a score or minimum-page rule. A multi-subproblem full paper below 15 main-text pages triggers a completeness review: either expand missing evidence or document why each required component is genuinely compact. Never pad to cross the threshold.

## 4. Build Semantic Word Structure

- Use real Heading styles, real numbered/bulleted lists, explicit table geometry, and inline images.
- Keep headings with the following paragraph and captions with their figures or tables.
- Keep short lead-ins ending in phrases such as “如下”“为”“故”“因此” with the following display equation.
- Restart numbered lists when a new logical list begins; visually confirm the rendered numbers.
- Put long paths, filenames, and commands in short list items or code blocks rather than justified prose, which can create stretched spacing.
- Avoid floating images unless the official template requires them.

### Local Formatting Change Guard

Before a targeted DOCX size/bold/alignment repair, preserve the selected base and save
a case-local plan copied from [docx-local-format-plan.json](../templates/docx-local-format-plan.json).
Use the read-only inspector to obtain base-bound addresses:

```powershell
python scripts/audit_docx_local_format.py --before <base.docx> --describe
python scripts/audit_docx_local_format.py --before <base.docx> --after <candidate.docx> --plan <plan.json>
```

The inspector is not an allowlist: choose only the intended paragraph/run. The plan
binds `before_sha256`, each target's `node_sha256` and zero-based child-index `path`
from `w:body`, plus exact expected property attributes. Addresses are valid only for
that base; never reuse an address after another edit or regenerate hashes merely to
accept unexplained drift. Store the plan before editing, outside the protected base.

Supported direct properties are `w:sz`, `w:szCs`, `w:b`, `w:bCs` on a text or OMML
run, and `w:jc`, `w:spacing`, `w:ind`, `w:keepNext`, `w:keepLines` on a paragraph.
Sizes are OOXML half-points: `{"w:sz":{"w:val":"24"}}` means 12 pt. Values are
attribute maps; `null` requires removal. The tool checks exact expected attributes,
not whether a proposed font size or line spacing is visually appropriate.

All other element content and properties in the main document must remain unchanged.
Other ZIP members are byte-protected: shared styles, themes, numbering, relationships,
media, headers, footers and metadata are not silently exempted. Formula text/structure,
equation numbers, symbol-table text and section geometry cannot be changed under a
format-only plan. Native math run size may change only when that run is explicitly
selected. Tables are not a blanket formatting target; select affected cell runs.

A failure blocks promotion as a **local-format-only candidate**. Inspect the located
part or scope error, repair or rebase intentionally; do not broaden the allowlist to
hide unexpected changes. Word saves that rewrite metadata or runs can conservatively
fail this guard without proving scientific corruption. Shared-style changes, text
rewrites, inserted/deleted objects and unsupported repairs require a separately scoped
review, not bypass flags. The guard is deliberately narrow and is not a new finalizer
gate automatically invoked for every historical case.

Run the guard before exporting/promoting the candidate. A pass means only permitted
OOXML changes; it does not prove mathematical correctness, actual rendered font size,
or readability. Changed DOCX bytes set `requires_export_and_page_review=true` and
`visual_review_passed=false`. Re-export and perform the existing final full-page review,
reconcile current source/DOCX/PDF hashes and rebuild affected package bindings. Do not
reuse the prior PDF's visual PASS. Changed pagination can affect every following page.

## 5. Render Mathematics Deliberately

- Render display equations with a math engine or native equation objects. For fractions, roots, integrals, sums, matrices, piecewise definitions, or nested subscripts/superscripts, use native LaTeX mathematics, Word OMML, or another verified structured-math path. A centered run in Cambria Math or another math font is still plain text and is only an emergency degradation mode; it must not be described as professional equation rendering.
- Convert simple inline mathematics to readable native text or equation runs. The enhanced exporter replaces every inline formula in a paragraph as one ordered operation; keep the multi-formula regression test passing, and still inspect the final sentence order. If another exporter moves or drops symbols, use stable native-text notation or separate display equations.
- After formula injection or any change between plain text and native mathematics, export the PDF again, recount the applicable page regions, and inspect every page again. Native formulas can increase line height and move tables, figures, references, or appendices, so no previous visual-review record survives a formula-rendering change.
- In Markdown-to-Word tables, do not assume `$...$` or other inline-LaTeX delimiters will become native mathematics. Use an export-safe notation such as `D(i,t)` when table-math rendering has not been verified. If table cells use mathematical markup, inspect the final DOCX/PDF and fail the paper review when delimiters or commands remain visible. LaTeX source tables may use normal math mode.
- Do not expose Markdown delimiters, backticks, or LaTeX commands such as `\qquad`, `\le`, or `\in` in visible prose.
- Use code fonts only for real paths, filenames, commands, or source identifiers. Use a math/body font for values and symbols.
- Check that a formula and its lead-in do not split across pages.


## 6. Control Tables And Figures

- Give every table explicit widths, cell padding, repeatable headers, and expandable row heights.
- Keep numeric precision consistent with the claim and result files.
- Before producing a figure or table, write the claim it must support. Prefer visuals that reveal data structure, model necessity, baseline comparison, parameter influence, feasibility, uncertainty, or failure boundaries; do not add a chart merely to prove that a step was run. A mechanism figure must reveal a specific geometry-to-state mapping, event trigger, active constraint, computation relation, or mechanism-to-result check. A generic process diagram with no binding to equations, data, or results is decorative and does not satisfy the claim contract.
- Label axes, units, legends, sample or time scope, and important comparison definitions. Explain the visible pattern and its decision meaning in the body, then state the limitation when the figure cannot support a stronger claim.
- After inserting, deleting, or moving any figure or table, reconcile unique numbering, continuous order where the selected format uses it, captions, body references, and the final rendered pages. A successful text replacement or export is not a numbering pass.
- Render images inline and set stable sizes so later text edits do not shift the page unexpectedly.

## 7. Export And Inspect

1. Generate DOCX from the authoritative source.
2. Export PDF with an available office or document engine.
3. Render the final PDF to one image per page.
4. Create bounded JPEG review previews without replacing the original rendered pages:

   ```powershell
   python scripts/prepare_visual_previews.py `
     --input-dir paper/rendered-pages `
     --output-dir paper/review-previews `
     --max-width 800 --quality 72
   ```

5. Inspect every page at readable zoom after the last layout-sensitive change, in batches of no more than two attached preview images. If the conversation is already long, perform visual review in a fresh task/context.
6. Fix and repeat until there are no clipped objects, overlaps, missing glyphs, stretched justification, broken lists, orphaned captions, or nearly blank trailing pages. `audit_paper.py` fails built-in checks when either DOCX or PDF still contains the known unresolved-TOC placeholder; an empty reserved TOC page remains a visual failure. Refresh the TOC successfully or omit it when the competition format permits.

Structural audits support this gate but do not replace visual review. During drafting, use:

```powershell
python scripts/audit_paper.py --docx <paper.docx> --pdf <paper.pdf> `
  --render-dir <rendered-pages> `
  --page-size a4 --orientation portrait `
  --expect <headline-value> --forbid <visible-placeholder>
```

Repeat `--expect` and `--forbid` as needed. DOCX extraction preserves paragraph, table-row, and table-cell boundaries so numeric result reconciliation does not merge adjacent cells. `--render-dir` verifies that the PNG count equals the PDF page count. Select `letter` for competitions whose official template requires US Letter, or `any` only when the rules genuinely do not constrain page size.

### Markdown-to-Word workflow adapter

When the workspace provides `tools/doc-export-enhanced`, keep the Markdown paper inside the case and call the exporter from the manifest's normal `build-paper` Python step. The case-local adapter must resolve the source and DOCX output inside the case, invoke the tool's own `.venv`, and enable native formulas, page numbers, and field refresh. It must not add a table of contents by default. For CUMCM, the reviewed 2026 format snapshot says the main text has no table of contents, so the default `cumcm-cn.yaml` route omits `--include-toc`. Use `--include-toc` only for another competition or template whose current reviewed rule snapshot explicitly permits or requires one. Keep PDF conversion out of that adapter: `run_pipeline.py` owns DOCX-to-PDF conversion, final field refresh, page rendering, structural audit, and result reconciliation.

Example manifest step:

```json
{
  "name": "build-paper",
  "type": "python",
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
```

The default practice and submission scaffolds create this adapter and Markdown source non-destructively. The adapter searches upward for the workspace tool, accepts Windows and POSIX project-local `.venv` layouts, and confines the selected export spec to `doc-export-specs`. Do not point the manifest directly at a script outside the case; the case-local adapter keeps manifest validation, provenance, and failure reporting inside the normal workflow boundary.

`structural_ok=true` means only that the machine-readable checks passed. The script deliberately reports `visual_review=not_performed`, even when `--render-dir` is supplied, because counting PNG files cannot prove that pages are readable or free of layout defects.

### 7.1 表达修复后的版本血缘与交付证据

当论文表达提升已经在候选稿中完成、但最终导出发现局部渲染或版式问题时，必须把“内容改进”和“渲染修复”分开记录，避免把哈希变化误判为模型或结果变化：

1. 在修复前保存权威源快照，并记录候选稿、修复前快照和当前源的 SHA-256；
2. 对源文件做差异分类，确认变更仅限符号显示、公式/表格渲染或其他已声明的表达层；若涉及数据、代码、结果登记、验证口径、图表数据或模型参数，必须按结果冻结规则解冻并重算；
3. 重新生成 DOCX/PDF，记录当前源—DOCX—PDF 的哈希绑定，并重新检查原生公式、图表、文本可提取性和原始 LaTeX 泄漏；
4. 任何 PDF 哈希、页数或版式变化都会使旧视觉审查记录失效；必须按当前 PDF 重新完成规定范围的视觉审查，不能沿用旧记录；
5. 任何最终交付包、冻结清单或 manifest 仍绑定旧 PDF 时，只能作为历史证据，不能证明当前版本已完成交付。当前版本必须重新 finalization、打包、干净解压烟测、匿名/AI/规则审计并生成新的冻结绑定。

报告应明确区分：已直接验证、由差异证据支持的高可信判断、尚未重跑的交付步骤，以及不得推出的更强结论。局部表达修复不自动证明模型正确；成功导出也不自动证明正式提交合规。

### Optional LaTeX adapter (not bundled)

The downloaded class, fonts and derived template are excluded from this edition pending source review. Choose a separately reviewed template permitted for your contest. Recheck formulas, symbol units, visible numbering, anonymity and every final PDF page. Neither a source template nor compilation success establishes compliance.


### Full-review consistency and validation checks

For every rapid/full pair, keep a `rapid_full_delta_register`. Explain each dimension change with newly inspected evidence, a corrected scope, contrary evidence, or reviewer uncertainty. A zero total-score change does not prove that no new evidence was found, because positive and negative changes may offset.

Before scoring problem coverage, reconstruct the formal subproblem list from the original problem statement. Do not count sensitivity studies, model evaluation, appendices, or optional extensions as additional formal subproblems unless the problem statement requires them.

In the full review, trace each headline result through the paper claim, mathematical definition, parameter value, implementation or appendix evidence, and reported output. The presence of code text is not execution evidence. Distinguish code visibility, code executability, output reproducibility, and independent reconciliation. When an external paper does not expose the complete project, mark the missing link `unverified`; do not convert unavailable evidence into an accusation of fabrication.

Apply the following validation semantics:

- training-set fit is not predictive validation;
- a future or scenario curve must disclose whether it is an end-to-end model output, post-processing result, interpolation, external input, or manually specified path;
- repeated parameters and headline values must agree across prose, formulas, tables, figures, appendices, and code, after accounting for declared rounding and differing definitions;
- correlation, historical decomposition, simulation, prediction, and conditional scenarios do not by themselves establish causal intervention effects or real-world guarantees.

For optimization and numerical claims:

- if a later subproblem relaxes constraints while retaining the same objective, carry the earlier feasible solution forward as a dominance baseline;
- a heuristic, local, binary-search-like, or finite-candidate procedure may be called globally optimal only with a complete enumeration, a valid structural proof, a certified bound, or equivalent evidence; otherwise use a bounded phrase such as “best candidate found within the declared search space”;
- a large sample count, ray count, mesh size, iteration count, or simulation length is not convergence evidence. Use refinement levels, output changes, cost, and an acceptance threshold, or compare with an analytical or independent benchmark.

Use PDF text extraction for navigation, not as the sole authority for formulas, signs, units, subscripts, or values. Confirm consequential anomalies on rendered pages before assigning a paper defect.

Do not score innovation by method-name count or fashion. Evaluate whether the method choice is necessary, whether the mechanism or data definition is transparent, whether it improves a defensible baseline, and whether it changes the decision or explanatory value.

Automated checks may validate the review record, score arithmetic, required evidence references, enumerations, claim boundaries, and explicit `unverified` risks. Agent or human review remains responsible for mathematical correctness, assumption quality, innovation necessity, semantic claim boundaries, visual persuasiveness, and award interpretation. Local directory labels such as “优秀论文” are source labels only, not official award evidence.

When storing an external review sample, mark it explicitly as diagnostic and non-production, for example `not_production_gate=true` and `sample_kind=case_external_structured_sample`.




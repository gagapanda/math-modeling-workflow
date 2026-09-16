# Migration Review Package Stability

Use this matrix when changing `prepare_workflow_migration_review_package.py`, its schema, renderer, tests, or release gate. The package remains schema version 1 and is passive review preparation, not migration approval. The measured release-candidate thresholds, compatibility summary, and CLI behavior are frozen in `migration-review-package-release-baseline.md`.

## Contract Matrix

| Concern | Producer | Schema | Renderer | Release gate | Tests | Stable meaning |
| --- | --- | --- | --- | --- | --- | --- |
| Safety | Emits all safety flags as `false` and verifies source immutability | Fixes flag values and requires `source_unchanged` | Displays every flag | Rechecks flags and case metadata | Covers stdout-only and stale-hash behavior | No case execution, writes, external tools, review record, candidate export, or cache enablement |
| Bindings | Hashes manifest, candidate, entry scripts, and traced support modules | Validates binding shapes and SHA-256 values | Displays every binding | Matches readiness hashes and preserves the case | Covers stale bindings and support modules | Bindings identify evidence; they do not declare dependencies |
| Path evidence | Emits candidate-only direct and bounded helper traces | Separates access, confidence, and provenance | Displays candidates and full provenance chains | Recounts provenance kinds | Covers path flow and conservative stops | Evidence never becomes an automatic input, output, or relationship |
| Limitations | Emits located `review_required` records with full call chains | Allows older located records and current call chains | Displays every retained chain | Rechecks fields and call-chain tails | Covers every allowed reason code and conservative deduplication | A limitation is review evidence, not an error, blocker, priority, or approval |
| Aggregation | Groups raw events by step, reason, and complete stop point | Allows optional groups and counts | Shows occurrence and unique-chain counts before chains | Reconstructs every group and summary count | Covers tampering and step isolation | Groups are indexes over limitations and never replace evidence |
| Human decisions | Leaves five checklist items pending per Python step | Fixes checklist codes and pending status | Renders unchecked items | Recounts all pending items | Covers pending-only output | No dependency, timeout, determinism, or cache decision is completed |
| Repeatability | Sorts derived sets and normalizes displayed paths to forward slashes | Rejects structurally unstable output | Renders the validated order without timestamps | Runs the same passive producers against bound evidence | Compares repeated JSON and Markdown bytes under deep Unicode and space-containing paths | Identical source bytes and paths produce identical stdout bytes on one host |
| Failure recovery | Returns a validated failed report and never accepts an output path | Keeps failure and safety fields explicit | Emits failure only to stdout | Treats nonzero or invalid output as failure | Covers syntax failure, stale hashes, rejected file-output arguments, and unchanged trees | There is no package artifact to roll back, resume, or merge with human content |
| Resource bounds | Rejects entry or helper sources above 1 MiB, modules above 50,000 AST nodes, or steps above 64 local modules; stops after 10,000 traced call events | Allows the stable `trace_budget_exhausted` limitation | Displays the bounded stop like every other limitation | Accepts only allowed codes and rechecks aggregation | Low-limit fixtures exercise every budget without large files | Structural excess fails closed; event exhaustion keeps prior evidence and adds no inferred dependency or decision |

## Frozen Semantics

- `trace_limitation_occurrences` is the number of raw tracer stop events before deduplication.
- `unique_trace_limitations` and `trace_limitations` both count retained limitation records. The latter remains the compatibility field.
- `trace_limitation_groups` counts step-local groups keyed by reason code plus module, function, line, and callee.
- A group's `occurrences` counts raw events; `unique_call_chains` counts retained limitations in that group. Group totals must reconstruct the corresponding summary counts.
- Deduplication removes exact duplicates and shorter complete-chain suffixes only for the same step, reason code, and stop point. Different entries, stops, reasons, and cycle directions remain.
- Schema version 1 continues to accept packages with no limitation fields, located limitations without call chains, and call-chain limitations without groups. Current producers emit the complete contract and validate its cross-field semantics.
- Machine and Markdown views remain stdout-only. They expose no output-path option, never overwrite human-authored content, and leave no partial package artifact after failure.
- Repeated generation from unchanged bytes is deterministic on one host. Displayed absolute paths use forward slashes; case-relative evidence remains POSIX-style and UTF-8 text is preserved.
- Invalid UTF-8, syntax errors, missing or escaped entry scripts, oversized sources or ASTs, and excessive case-local module closure return a machine-readable failed report with no case writes. Path resolution follows real targets, so `..`, absolute paths, and supported symlink or junction escapes cannot enter evidence.
- The call-event budget is step-local. Exhaustion produces one located `trace_budget_exhausted` limitation only when a call would otherwise be traced; it does not discard earlier evidence or infer a path, bind a module, block migration, complete a checklist item, or enable caching.

## Change Gate

Prefer presentation or validation improvements over new machine fields. Add a field only when existing evidence cannot express a required human-review fact, the value can be derived without case execution, old schema version 1 documents remain valid, and release-gate tests can prove that tampering fails closed.

A schema-version change is required if an existing field changes meaning, an older valid package must become invalid, passive behavior is weakened, or review preparation begins recording decisions or approval state.

After the release-candidate freeze, prefer feedback-driven defect fixes and renderer or validation improvements. Any resource-limit change must repeat the all-six-case calibration and refresh the normalized release baseline.

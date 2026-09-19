# Migration Review Package Release Baseline

This is the frozen release-candidate baseline for the passive workflow migration review package as measured on 2026-08-14. It records normalized facts only; no temporary paths or raw probe output are part of the baseline.

## Resource Calibration

The limits are inclusive: a source or step exactly at its limit is accepted. Structural input above a limit fails closed. Trace-event exhaustion retains prior evidence and adds one step-local, non-blocking `trace_budget_exhausted` limitation when another call would otherwise be traced.

| Boundary | Release limit | Largest historical observation | Headroom |
| --- | ---: | ---: | ---: |
| Python source bytes per module | 1,048,576 | 39,808 | 26.34x |
| AST nodes per module | 50,000 | 7,074 | 7.07x |
| Case-local modules per step | 64 | 3 | 21.33x |
| Traced call events per step | 10,000 | 3,896 | 2.57x |

The observations cover all Python steps in the six historical cases. Default limits produced no `trace_budget_exhausted` limitation. Call events were measured by wrapping the existing budget-consumption function while running the passive producer; no case code, build, finalization, external tool, or case write was performed.

## CLI Contract

| State | Exit code | stdout | stderr | Files written |
| --- | ---: | --- | --- | ---: |
| `ready_for_human_review` | 0 | Valid JSON with `--json` | Empty | 0 |
| `not_applicable` | 0 | Valid JSON with `--json` | Empty | 0 |
| Stale expected hash | 2 | Valid failed JSON with `--json` | Empty | 0 |
| Corrupt, unreadable, escaped, or resource-excess source | 2 | Valid failed JSON with `--json` | Empty | 0 |
| Invalid CLI option | 2 | Empty | Argparse diagnostic | 0 |

Machine and Markdown forms remain stdout-only. Neither command accepts a persistent output path, creates a formal review record, exports a candidate, executes a case step, or enables caching.

## Compatibility Baseline

- The machine package remains schema version 1 with additive compatibility.
- Validation accepts all three supported generations: packages without limitation fields, located limitations without call chains, and current call-chain limitations with groups.
- The current producer emits full call chains and step-local groups and validates their cross-field aggregation.
- Limitations and groups remain review-preparation evidence. They carry no inferred path, support-module binding, severity, priority, approval, migration block, or cache decision.
- Every dependency, timeout, determinism, and cache checklist item remains pending human review.

For the readiness-recommended historical case, the frozen normalized package summary is 54 raw limitation occurrences, 36 retained unique limitations, 36 compatibility limitations, and 13 groups. Default resource budgets do not add a budget limitation.

## Release Gate Baseline

The frozen candidate passes 15 JSON schemas, 35 Python AST parses, and 104 unit tests, followed by passive checks of all six historical cases. The recommended review package and Markdown renderer pass with the normalized `54 / 36 / 36 / 13` limitation summary. The three pre-existing `model_definition_register_missing` findings remain warnings; the gate introduces no new diagnostic error.

The six historical manifests and their file-tree metadata must remain unchanged. The release gate must also leave no `math-modeling-migration-*` temporary directory, skill-local `__pycache__` directory, or `.pyc` file.

## Change Policy

After this freeze, maintain the package from actual review usage and defect evidence. Do not widen the tracer or add schema fields, reason codes, or tools speculatively.

Recalibrate a resource limit only when a reproducible ordinary case approaches it, an adversarial case demonstrates excessive cost, or implementation complexity materially changes the meaning of the measurement. A limit change requires boundary tests, all-six-case measurement, compatibility review, the complete release gate, and a refreshed normalized baseline. The 2.57x trace-event margin is the first boundary to monitor.

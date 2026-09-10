# Model Definition Gate

Use this gate when natural-language terms can change the mathematical claim: point
versus extended target, partial versus complete coverage, open versus closed boundary,
instantaneous versus interval conditions, sum versus union, average versus worst case,
deterministic versus probabilistic constraints, or alternative units/time origins.

## Required Sequence

1. Enumerate materially plausible definitions before optimization.
2. Select and justify one primary definition.
3. Evaluate the same feasible strategy under every material alternative.
4. Decide materiality using the competition's precision, ranking, feasibility, and
   conclusion, not an arbitrary percentage alone.
5. If material, reoptimize directly under the alternative definition. Post-hoc
   reevaluation is not enough.
6. Validate both objectives at higher numerical resolution than used for search.
7. Put a concise definition-and-impact statement in the final DOCX and PDF.

Record this in `problem/model-definition-register.json`. A material entry passes only
when comparison evidence and alternative-reoptimization evidence exist and the exact
registered disclosure text occurs in both final paper artifacts.

For no material ambiguity, set `assessment_status` to `completed`, leave
`ambiguities` empty, and provide a substantive `no_material_ambiguity_rationale`.
Do not use `TODO`, `pending`, or `placeholder` as evidence.

Run the gate directly with:

```powershell
python scripts/audit_model_definitions.py --case-dir <case-dir> `
  --docx <paper.docx> --pdf <paper.pdf>
```

The manifest-driven build and finalize commands run the same gate automatically.

# Result Workbook QA

Use this path for final `.xlsx` files that must be submitted or included in support
materials. It is a read-only mechanical audit. It never calculates formulas, edits a
cell, saves the workbook, or proves that a model result is scientifically correct.

## Competition Contract

Create one case-local plan that validates against
`schemas/result-workbook-audit-plan.schema.json`. Bind the exact workbook SHA-256,
declare every required worksheet, and list the critical cells that answer a problem
or appear in the paper. For each critical cell, declare the expected type and, when
meaningful, the exact saved value, tolerance, and required number format.

Map headline cells to `results/result-register.json` with `registered_results`. The
mapping uses the register tolerance by default. If the workbook intentionally stores
a rounded export value, declare a separate mapping tolerance that is justified by the
saved precision. Do not loosen the canonical source-to-register tolerance merely to
make a rounded workbook pass.

Example:

```json
{
  "schema_version": 1,
  "workbook": "results/result.xlsx",
  "workbook_sha256": "<lowercase-sha256>",
  "result_register": "results/result-register.json",
  "required_sheets": ["Results", "Notes"],
  "forbid_extra_sheets": true,
  "required_cells": [
    {
      "id": "q1.objective",
      "sheet": "Results",
      "cell": "B2",
      "expected": 26.0,
      "expected_type": "number",
      "absolute_tolerance": 1e-9,
      "required_number_format": "0.00"
    }
  ],
  "registered_results": [
    {
      "result_id": "q1.objective",
      "sheet": "Results",
      "cell": "B2",
      "absolute_tolerance": 1e-6
    }
  ]
}
```

Run the audit into a new evidence directory:

```powershell
python scripts/audit_result_workbook.py --case-dir <case-dir> `
  --plan result-workbook-audit-plan.json `
  --output-dir results/workbook-audit --json
```

The output directory must not exist. A passing run atomically creates only
`report.json`; a failing run creates no evidence directory and returns its structured
report on standard output. Preserve that failure output in the rehearsal log when it
reveals a real delivery defect.

## Blocking Checks

The audit blocks when the input hash changes, the OOXML package is corrupt, a required
sheet or critical value is missing, a critical type or number format differs, a numeric
value is non-finite, or a mapped cell differs from the result register beyond its
declared tolerance. Critical cells may not be placed on hidden sheets or in hidden rows
or columns.

All formula cells are inspected with both `data_only=False` and `data_only=True`. A
formula with no cached value is a blocker because `openpyxl` does not calculate it.
Recalculate in Excel or LibreOffice, save deliberately, update the workbook hash in a
reviewed plan, and rerun the audit. Spreadsheet errors such as `#REF!`, `#DIV/0!`,
`#VALUE!`, `#NAME?`, `#N/A`, `#NUM!`, and `#NULL!` are blockers. Never let the audit
invoke a spreadsheet application that overwrites the authoritative file.

Hidden sheets, hidden rows or columns away from critical cells, merged ranges, external
links, and parser warnings remain explicit review warnings. Resolve them when they can
confuse a judge or conceal data; otherwise record the reason they are acceptable.

## Unsupported And Manual Checks

The production baseline accepts `.xlsx` only. Route legacy `.xls` through a separately
reviewed conversion, and do not treat `.xlsm` as ordinary input because macro retention
and execution require a dedicated security and fidelity review. The audit never saves
the source, because saving through `openpyxl` can alter unsupported workbook features.

After a passing mechanical audit, open the exact hash-bound workbook in Microsoft Excel
or LibreOffice. Inspect every worksheet for clipping, column widths, row heights, frozen
panes, merged headers, print areas, pagination, charts, units, labels, and displayed
rounding. Confirm that the visible result agrees with the paper. A successful open, a
clean formula scan, or matching cells do not validate the model, source data, or result.

The controlled fixture is under
`.skill-audit/result-workbook-qa/controlled-result-workbook`; the historical read-only
evidence uses `2023-cumcm-b-full-practice/results/result1.xlsx`.

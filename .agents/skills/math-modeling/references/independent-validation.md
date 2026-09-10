# Independent Validation

Use this guide when a model is calibrated from one historical trace, one
experiment, one site, or another narrow data source and the requested result
will be used to recommend a control, forecast, or physical-process setting.

## Calibration is not validation

A curve used to estimate model parameters is calibration evidence. Replaying
that same curve, changing the solver tolerance, or splitting nearby points
from the same trace does not establish independent predictive performance.
State this boundary plainly in results and paper text.

When no independent observations exist, report the model as calibrated or
exploratory. Do not call it validated, production-ready, statistically
confirmed, or globally reliable solely because it fits its calibration data.

## Plan the holdout before collecting it

Define the validation protocol before looking at new measurements:

1. Name the prediction claim and the operating conditions to be tested.
2. Reserve new runs, later time periods, separate physical units, or separate
   sites that were not used for fitting or model-selection decisions.
3. Give every trace or unit a stable identifier and retain its original source
   export unchanged.
4. Record settings, time origin, measurement location, acquisition method,
   and deviations alongside each trace.
5. Predefine error measures, missing-metric handling, and engineering screens.
   Label screens as proposed practice criteria unless independently justified.

For physical profiles and time traces, check that the declared controls and
transit or sampling timing are internally consistent before model comparison.
A mechanically clean file does not prove that the data are physically
independent.

## Keep evidence roles separate

Use separate locations and identifiers for:

- raw source exports, which are never overwritten;
- deterministic standardized or assembled datasets, each bound to its input
  hashes and conversion metadata;
- audit outputs, which diagnose format and plausibility but do not fit;
- calibration data, used to estimate parameters;
- independent validation data, compared with fixed parameters only.

Do not silently promote validation data into calibration data after an
unfavorable result. Freeze the evaluation set. If refitting is justified, use a
separately designated calibration set, rerun downstream analysis, and evaluate
the changed model on a new independent holdout.

## Compare without refitting

For each held-out trace or unit, retain the calibration parameters and model
structure unchanged. Report per-unit errors, summary errors, failed screens,
and metrics that are not evaluable because a required event or crossing did
not occur. Never count a non-evaluable metric as zero error or as a pass.

Investigate timing, measurement placement, source-data integrity, operating
condition realization, and residual patterns before changing the model. A
screen failure may reveal instrumentation or protocol problems; it is not by
itself proof that a new model is correct.

## Minimum conclusion language

Use wording matched to the evidence:

- No new data: "The model is calibrated on the available historical data; independent predictive validation remains pending."
- New data pass defined screens: "The fixed model met the stated engineering screens on the documented independent test set." State the test-set scope.
- New data fail a screen: "The fixed model did not meet the stated screen under the documented condition." Preserve the result and avoid post-hoc validation claims.

This guide addresses prediction evidence. It does not replace competition
rules, laboratory safety procedures, equipment qualification, or a statistical
power analysis when inferential confidence is the actual claim.
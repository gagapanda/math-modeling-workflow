# Model Routing

Select methods from mathematical structure, not surface topic.

Use [integration-routing.md](integration-routing.md) for the beginner-facing first pass. This table is the detailed model-selection reference after the task contract and structural signals have been extracted.

| Structural signal | Baseline | Candidate methods | Required checks |
| --- | --- | --- | --- |
| Choose controllable variables to maximize/minimize one or several conflicting objectives | simple feasible heuristic, single-objective endpoints, or linear relaxation | LP, MILP, NLP, dynamic programming, optimal control, multi-objective optimization | feasibility, residuals, bounds, multi-start/gap; for Pareto claims also reference-front binding, nondominance, scale handling, multi-seed stability and preference sensitivity |
| Rank or score alternatives from several indicators | equal weights and transparent normalization | AHP, entropy weight, TOPSIS, grey relation, fuzzy evaluation | normalization effects, weight sensitivity, rank stability |
| Reduce correlated numeric indicators or diagnose collinearity | correlation matrix and mean reconstruction | PCA, factor analysis, regularization, feature selection | scale effects, explained variance, reconstruction error, loading/subspace stability, downstream validation |
| Predict a continuous time-dependent value | persistence, mean, or seasonal naive | regression, ARIMA/ETS, grey prediction, state-space, tree boosting, neural models | rolling validation, leakage, residuals, uncertainty |
| Compare a univariate relationship within the observed range | linear curve | predeclared linear/quadratic/cubic curves, PCHIP | development-set cross-validation, one-standard-error selection, untouched test set, residuals, parameter/mean-response/prediction intervals, no extrapolation claim |
| Classify or detect anomalies | majority/rule baseline | logistic regression, trees, SVM, ensembles, anomaly detection | class imbalance, calibration, threshold choice, leakage |
| Explain conditional associations among variables | correlations and predeclared OLS with explicit covariance | OLS diagnostics, GLM, nonlinear regression, multivariate analysis, PLS; causal designs only when identification assumptions permit | covariance and independent-unit declaration, residual/specification diagnostics, collinearity, influence review, identifiability, confounding, no automatic deletion or model switching |
| Find routes, flows, matchings, or network structure | direct route, source/sink capacity bound, or shortest-path baseline | shortest path, MST, max flow, matching, vehicle routing, network optimization | edge semantics and direction; for shortest path, continuity and recomputed cost; for maximum flow, capacity, conservation and max-flow/min-cut equality; scalability |
| Model continuous dynamics | equilibrium, initial-derivative, or analytic simplified baseline | ODE, PDE, difference equations, state-space, compartment models | units and initial/boundary conditions; independently derived conservation, limiting behavior or analytic references; tolerance and maximum-step sensitivity; parameter and structural uncertainty kept separate |
| Represent queues, inventory, reliability, or random events | expectation calculation | queueing, Markov chains, Monte Carlo, discrete-event simulation | distribution fit, repeated runs, confidence intervals, convergence |
| Reconstruct geometry, trajectories, images, or video motion | direct geometric calculation or linear curve | coordinate transforms, predeclared curve fitting, tracking, image processing, inverse problems | calibration, coordinate frames, observed fitting range, development/test isolation, residuals, conditional intervals, error propagation, visual overlays |
| Optimize a difficult black-box objective | random/grid search baseline | Bayesian optimization, genetic algorithm, particle swarm, simulated annealing | seed control, budget parity, repeated runs, comparison with baseline |

## Selection Rules

1. Make the output and constraints explicit before naming a method.
2. Reject models whose assumptions contradict the data-generating process.
3. Prefer interpretable methods when decisions or policy recommendations are central.
4. Use machine learning only with enough independent samples and a valid evaluation split.
5. Do not use AHP, entropy weighting, TOPSIS, PCA, or clustering interchangeably; they answer different questions.
6. Do not claim global optimality for heuristic solutions without a bound or proof.
7. Do not report fit on training data as predictive validation.
8. Treat sensitivity analysis as a model check, not a decorative final section.
9. Bind every recommended candidate to an explicit next action: data audit, model-definition register, baseline execution, or paper review.
10. Keep continuous prediction and coefficient inference separate: prediction needs an untouched evaluation split; OLS inference needs a declared sampling/covariance structure and diagnostics.
11. Separate admissibility from preference: conservation, feasibility and solver convergence can admit multiple candidates; they do not alone rank physical validity, predictive quality or decision utility. State whether selection rests on a structural convention, matched performance comparison or independent observations. Apply the metric-identity and evaluation-role checks in `paper-claim-figure-innovation-card.md` before promoting a superiority claim.

## Lead-Time Startup And Information Availability

For inventory, scheduling, delayed control, rolling forecasts, and other models with a lead time or lag, route the startup period as a separate definition problem before comparing algorithms:

1. list each decision time, lead time, state, initial inventory, in-transit quantity, and lagged value;
2. mark when each value becomes observable and whether the decision maker could know it at that time;
3. preserve any problem-statement startup exception exactly at its stated horizon—an `L=1` exception is not evidence for `L>=2`;
4. initialize longer pipelines only from stated initial conditions, historical information available before the decision, or an explicit assumption disclosed in the paper;
5. if future realized demand or another unavailable value enters initialization, mark dependent outputs `DO_NOT_FREEZE`, correct the definition, and replay the startup segment separately;
6. compare lead-time variants only after their startup states and information sets are definition-consistent.

A feasible solver run, deterministic hash, or good full-period average cannot repair startup information leakage.

## Aggregation Denominator And Weighting Gate

Whenever a reported service level, accuracy, risk, error, fairness, efficiency, or satisfaction metric aggregates heterogeneous groups, define the denominator and weights before comparing models or freezing results. At minimum:

1. identify the atomic unit and the population being summarized;
2. state whether the primary metric is macro/unweighted (equal weight per item, class, region, athlete, scenario, or period) or micro/volume-weighted (weight by demand, observations, exposure, population, cost, or another declared quantity);
3. when both definitions are mathematically meaningful and the choice can change the decision, compute and register both from the same underlying records;
4. declare one primary interpretation in the paper, label the other as definition sensitivity, and explain which stakeholders or failure modes each emphasizes;
5. if the preferred model, feasibility claim, threshold decision, or policy conclusion changes across defensible weighting rules, do not present a unique robust conclusion; narrow the claim or preserve both alternatives.

A high aggregate value cannot hide a low subgroup minimum. Report consequential minima, tails, or subgroup failures separately. Never change the denominator after seeing which version makes the model look better, and never use a price-, demand-, or population-weighted proxy as if it were an undeclared causal or economic objective.

## Candidate Comparison

For each serious candidate, record:

- target subproblem;
- variables and assumptions;
- data requirements;
- objective or loss;
- computational method;
- validation design;
- expected interpretability;
- known failure modes.

Choose the primary method with evidence from this comparison. Preserve rejected candidates and reasons in `decisions.md`.

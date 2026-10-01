---
name: define-metrics
description: Produce a precise, actionable Metric-Driven spec for statistical model performance — target metric with its confidence interval, honest baselines, split strategy justified by the data, guardrails and a stopping criterion. Writes the spec (or returns it as markdown when orchestrated by `/create-issue`); it never trains a model or runs an evaluation. The third counterpart to `define-tests` (deterministic code) and `define-evals` (LLM output quality).
---

# Define Metrics

You are a machine-learning evaluation architect. Your job is to define how the **statistical
performance** of a model will be judged, before anyone trains one. You do NOT train, tune, or
evaluate. You produce a specification document.

## Why this exists as a third skill

`define-tests` and `define-evals` between them do not cover model performance:

| | Verdict | Example |
|---|---|---|
| `define-tests` | Binary, repeatable | "rejects a row with no customer id" |
| `define-evals` | Binary, on an LLM output | "the answer cites a retrieved document" |
| **`define-metrics`** | **A distribution with a threshold** | "AUC-PR ≥ 0.42, CI95 lower bound above baseline" |

Model performance is neither. Forcing it into `define-tests` produces `assert auc > 0.85` inside
a test suite: a flaky test that gets marked `skip`, after which no test in the repository carries
authority. Forcing it into `define-evals` produces an LLM-as-Judge for something a bootstrap
confidence interval answers exactly.

Use this skill when the issue involves a trained model — supervised, unsupervised, or deep
learning. Never for deterministic code, never for LLM output quality.

## Input

The modelling task: $ARGUMENTS

If no arguments were provided, ask:
1. What decision does this model change? (If none, there is nothing to build — say so.)
2. What is the unit of observation, and at what instant is the prediction made?
3. Where are the data, and is there an existing data audit?

## Before starting: the data ceiling is a hard input

**Read the data audit before writing any target number.** Look for `experiments/*/DATA_AUDIT.md`
or the JSON from the `data-audit` / `data-profiling` scripts (read the JSON, not a chart).

If neither exists, **stop and say so**. A target metric written without knowing what the data can
support is a wish, not a criterion. Ask for the `analyst` data gate to run first.

From the audit, extract and carry into the spec:

- **The plausible performance ceiling.** Any target above it is unattainable, and this spec is
  where that gets caught — not three weeks later during evaluation.
- **Whether a random split is legitimate.** Repeated entities require grouping; temporal order
  requires a time-based split. Almost every dataset fails one of these.
- **Any suspected leakage.** A single feature reaching AUC above 0.90 on its own must be resolved
  before a target is set: the ceiling means nothing while a leak is in the data.

## Methodology

### Phase 1: The decision this serves

State in one sentence what changes according to the model's output, who acts on it, and at what
threshold. Everything below derives from this. A model whose output changes no decision needs no
metric because it needs no model.

### Phase 2: Primary metric — exactly one

Choose one metric and justify it against the decision, not against convention.

- Imbalanced classification → AUC-PR before AUC-ROC; report the confusion matrix at the operating
  threshold, not at 0.5.
- Ranking → the metric at the k the business actually consumes.
- Regression → the error that matches the cost function; if errors are asymmetric, say so.
- Unsupervised → stability under resampling is the primary signal. Internal criteria alone
  (silhouette, gap) do not establish that a structure is real.

The decision threshold is a business decision, not a default. If a cost function exists, the
threshold is optimised against it and that is stated here.

### Phase 3: Baselines — the honest floor

Two are mandatory, both with their current value if known:

1. **Trivial**: majority class, mean, or persistence for time series.
2. **Simple**: regularised linear model or a single tree.

A candidate that does not clearly beat the simple baseline rarely justifies the operational cost
of a complex model. State that explicitly so nobody has to relitigate it later.

### Phase 4: Split strategy — justified, not defaulted

Name the scheme (`StratifiedKFold`, `GroupKFold`, `TimeSeriesSplit`) and **justify it from the
data audit**. Random is presumed wrong until the absence of temporal and group structure is shown.

Define the three sets and their rules:

| Set | Use | How often it may be touched |
|---|---|---|
| Train | Fit parameters | Continuous |
| Dev | Select model and hyperparameters | Continuous |
| Test | Final unbiased estimate | **Once**, at decision time |

State the test partition's path and how it was carved. Every look is recorded with
`python3 gates/holdout_ledger.py record <path> <metric> <value> <issue>`.

### Phase 5: The acceptance criterion

Write it so that two people reading it reach the same verdict:

```
### Metric: [name]

**Primary metric**: [exact metric]
**Target**: [number] on the test partition
**Uncertainty**: bootstrap, n≥1000, CI95 reported. The lower bound must exceed [baseline value]
**Set**: test | dev
**Data ceiling**: [from the audit] — the target must sit below this
**Rationale**: what this buys the decision in Phase 1

#### Guardrails (must not degrade)
- [metric]: [bound] — e.g. p95 latency, cost per prediction, recall on a critical segment

#### Segmentation
Performance reported by [class / business group / period]. A good aggregate hiding a broken
critical segment is a failure, not a pass.

#### Stopping criterion
Accept when: [condition]
Iterate while: the primary metric improves beyond the confidence interval
Kill when: two consecutive iterations fail to improve beyond the CI, or [date]
```

**A criterion without a stopping rule is a bottomless pit.** Every metric spec carries one.

### Phase 6: Error analysis plan

State up front how failures will be examined: sample size, how they will be categorised, and who
looks. Error analysis directs the next iteration better than any hyperparameter search, and it
only happens if it is planned before the results arrive and everyone is excited.

### Phase 7: Summary

| Metric | Type | Target | Set | Ceiling | Guardrails |
|--------|------|--------|-----|---------|------------|

Then state:

- **Reproducibility**: seed, commit hash, dependency versions, and where the run is logged.
- **What NOT to report**: metrics that would be misleading here, and why. Accuracy on an
  imbalanced problem is the standard example.
- **Feasibility verdict**: given the ceiling, is this target attainable? If not, **say so plainly
  and propose an attainable one.** This verdict is the whole reason this skill reads the audit
  first, and it is the cheapest correction available anywhere in the cycle.

## Output Format

Write to `experiments/[topic-slug]/METRIC_SPEC.md`, creating the directory if needed. When
orchestrated by `/create-issue`, return the markdown and persist no file.

Also emit the machine-readable criterion for `ACCEPTANCE.yaml`, so CI can check it:

```yaml
  - id: AC-n
    statement: "AUC-PR on the test partition >= 0.42, CI95 lower bound above the persistence baseline"
    verification: metric
    reference: evals/<topic>/auc_pr
    threshold: 0.42
    set: test
```

## Key Principles (Non-Negotiable)

1. **One primary metric.** The rest are guardrails, not decision criteria.
2. **No number without an interval.** A point estimate hides whether the improvement is real.
3. **The ceiling constrains the target.** A target above what the data support is not ambitious,
   it is unattainable, and the correct response is to fix the spec.
4. **The test partition is touched once**, at decision time, and the look is recorded. Past the third
   look the estimate is no longer unbiased and the report must say so.
5. **Baselines are honest.** A deliberately under-tuned baseline makes any model look good and
   teaches you nothing.
6. **Never an assert.** A model metric never becomes an assertion in a test suite. That is
   `FRONT001` in `gates/py_audit.py` and it fails the build.
7. **Every spec has a stopping criterion**, with a number and a date.
8. **No execution.** This skill produces a document. It does not train, tune, or evaluate.

---
name: data-audit
description: Target-aware data audit before anyone models — leakage signals (single-feature AUC, target copies, missingness that depends on the outcome), duplicates, split strategy with evidence, and an optional diagnostic probe that estimates a plausible performance ceiling. Use for the pre-modelling data gate, for any metric criterion, and whenever a reported result looks too good.
---

The data gate for a modelling task. It answers three questions: is there leakage, which split does
the structure demand, and what can these data plausibly deliver. It cannot know what a column
means, so **every finding is a symptom to verify with a person**.

## Run it

```bash
python3 .claude/skills/data-audit/scripts/audit_data.py --data <path> --target <col> \
    [--time <col>] [--group <col>] [--ignore id_col,other] [--probe] \
    [--task auto|binary|multiclass|regression] [--positive <value>] \
    [--folds 5] [--seed 0] [--sample N] [--probe-rows 50000] --out experiments/<id>/audit.json
```

- Pass `--time` and `--group` whenever the data have them. The recommended split comes from these.
- `--ignore` known identifier columns so they do not distort the probe.
- `--probe` runs a **fixed, untuned** gradient-boosting model under the recommended split (and under
  a random split for comparison). It is a diagnostic for this audit, not a candidate model.
- Profile first (`data-profiling`): this script assumes you already know the shape of the data.

## Finding codes

| Code | Severity | What to check |
|---|---|---|
| `TARGET_COPY` | blocker | Column is the target, a linear or monotone transform of it, or the same partition. Remove it |
| `LEAK_SIGNAL` | blocker | One feature alone reaches AUC ≥ 0.90 (regression: \|Spearman\| ≥ 0.95). When is it filled in? |
| `NULL_PATTERN` | blocker / risk | Whether the column is missing depends on the target: usually populated only after the event |
| `SUSPECT_SIGNAL` | risk | AUC 0.80–0.90 (\|Spearman\| 0.85–0.95): explain the mechanism before using it |
| `NAME_OVERLAP` | risk | Column named like the target (`churn_reason`): often a consequence of the event |
| `ROW_ORDER` | risk | Row order correlates with the target: the file is sorted; do not split sequentially |
| `DUPLICATES`, `DUP_ACROSS_SPLIT` | risk | Exact twins; twins that would sit on both sides of the split |
| `LABEL_CONFLICT` | risk | Same features, different label: noise that caps the achievable score |
| `RANDOM_SPLIT_INFLATES` | risk | The probe scores higher under a random split than under the structural one |
| `GROUP_RANDOM_SPLIT` | info | Share of validation rows whose group is already in train under a random split |

## The split

Recommended scheme, in order: `time` if there is a time column (train on the past, validate on the
future); `group` if entities repeat (whole groups on one side); otherwise stratified / K-fold, with
the reminder that **random is presumed wrong until someone confirms there is no entity or temporal
structure**. The output reports the evidence (group overlap under a random split, duplicates
crossing the recommended split).

## The ceiling

With `--probe`, `ceiling_reference` is the probe's mean plus two standard deviations across folds,
computed with suspect columns removed. Read it as a heuristic: an untuned model on these features
under the correct split scores about this much. A target well above it needs a stated mechanism
(features the probe cannot exploit, a better model family, domain knowledge). When the probe reports
"almost no learnable signal", say so plainly: the data may not support the target at all.
Compare it against the criteria in `ACCEPTANCE.yaml` and write the comparison in the first line of
the audit.

## Write the audit

Fill `DATA_AUDIT_TEMPLATE.md` (next to this file) into `experiments/<id>/DATA_AUDIT.md`: blockers
with evidence first, then risks, the recommended split with its justification, the plausible
ceiling with its basis, and what only a person can confirm.

## Rules

- Audit the train/dev extract only. Never run this on a test partition or an eval golden set's test
  split: that is a look at a one-look resource.
- A `blocker` is not resolved by dropping the column and moving on. Find out why it is there: the
  mechanism is often the most valuable thing in the audit.
- Keep the seed. The JSON records it so the numbers can be reproduced.

---
name: statistical-analysis
description: Statistical inference with uncertainty always attached — bootstrap confidence intervals, two-group comparisons with effect sizes, proportions with Wilson intervals, correlations with bootstrap CIs, and sample-size calculations. Use whenever a claim of the form "A differs from B", "X is related to Y" or "the rate is Z" needs support.
---

Never report a point estimate alone. This skill wraps the tests so that the interval, the effect
size and the seed always come with the number.

## Run it

```bash
S=.claude/skills/statistical-analysis/scripts/stat_tests.py
python3 $S ci          --data <path> --col <x> [--stat mean|median|std|p90] [--by <group>]
python3 $S compare     --data <path> --value <x> --group <g> [--a <label> --b <label>]
python3 $S proportion  --data <path> --outcome <y> --group <g> [--success <value>] [--a <l> --b <l>]
python3 $S corr        --data <path> --x <x> --y <y> [--method both|pearson|spearman]
python3 $S sample-size (--mean-diff <d> --sd <s>) | (--p1 <p> --p2 <p>) [--power 0.8]
```

Common: `--n-boot 2000` (minimum 1000, enforced), `--seed 0`, `--alpha 0.05`. Output is JSON.
`difference_…_b_minus_a` means group `b` minus group `a`.

## Which one

| Question | Command | Read |
|---|---|---|
| "What is the typical value, and how sure are we?" | `ci` | Interval width, not just the estimate |
| "Is the mean/median different between two groups?" | `compare` | Difference and its CI first, then effect size (Cohen's d, Cliff's δ), then p-values |
| "Is the conversion / churn / error rate different?" | `proportion` | Wilson CIs per group, difference CI, Fisher exact |
| "Are two numeric variables related?" | `corr` | Pearson and Spearman; a gap above 0.15 between them means outliers or non-linearity |
| "How much data do I need to detect this?" | `sample-size` | Do it before collecting or testing, not after |

## Rules

- **Effect size and interval before p-value.** A tiny p-value with a negligible effect is a
  detectable nothing. A large p-value is not evidence of no difference: read the interval.
- **State the comparison before you look.** Trying many subgroups and reporting the one that
  "worked" is multiple comparisons; count them, and correct (Bonferroni or Holm) or say you did not.
- **Check the assumptions you lean on.** Independence (repeated customers are not independent rows:
  aggregate to the customer or resample by group), sample size per group, heavy tails (prefer the
  median and Mann-Whitney).
- **Do not peek.** For A/B tests, fix the sample size and the stopping rule first.
- **Correlation is not causation.** Check confounders and time ordering before wording a cause.
- `p_value: 0.0` means below floating-point range (about 1e-300); report it as "< 1e-300".
- The seed is echoed in the output. Keep it in your report so the interval can be reproduced.

## Data hygiene

Rows with missing values in the columns used are dropped and counted (`n_dropped…`).

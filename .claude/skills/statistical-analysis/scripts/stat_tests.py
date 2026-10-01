#!/usr/bin/env python3
"""Statistical helpers that never report a point estimate without its uncertainty.

Every interval is a percentile bootstrap (default 2000 resamples, minimum 1000, fixed seed that is
echoed in the output so the number can be reproduced). Every comparison reports an effect size
next to its p-value: a p-value says a difference is detectable, not that it matters.

Subcommands (output is JSON):
  ci           --col X [--stat mean|median|std|p90] [--by G]       CI of a statistic, overall or per group
  compare      --value X --group G [--a A --b B]                   two groups: difference, effect size, tests
                                                                    (more than two groups: Kruskal-Wallis)
  proportion   --outcome Y --group G [--success V]                 rates with Wilson CIs, difference, tests
  corr         --x X --y Y [--method both|pearson|spearman]        correlation with bootstrap CI
  sample-size  (--mean-diff D --sd S) | (--p1 P --p2 P)            sample size per group, normal approximation

Common: --data PATH --n-boot 2000 --seed 0 --alpha 0.05
"""

import argparse
import json
import math
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")
MIN_BOOT = 1000
STATS = {
    "mean": np.mean,
    "median": np.median,
    "std": lambda v: np.std(v, ddof=1),
    "p90": lambda v: np.quantile(v, 0.9),
}


# Duplicated in the sibling analysis skills on purpose: each skill directory stays
# self-contained, so it can be copied or symlinked on its own.
def load_table(path):
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in (".csv", ".txt"):
        return pd.read_csv(p)
    if suffix == ".tsv":
        return pd.read_csv(p, sep="\t")
    if suffix in (".parquet", ".pq"):
        return pd.read_parquet(p)
    if suffix == ".feather":
        return pd.read_feather(p)
    if suffix == ".json":
        return pd.read_json(p)
    if suffix in (".jsonl", ".ndjson"):
        return pd.read_json(p, lines=True)
    raise SystemExit(f"Unsupported format: {suffix or p.name}")


def r(v, digits=4):
    if v is None:
        return None
    v = float(v)
    return None if (math.isnan(v) or math.isinf(v)) else round(v, digits)


def pv(p):
    """p-value with 3 significant digits, so 1e-12 does not collapse into 0.0."""
    return None if p is None or math.isnan(float(p)) else float(f"{float(p):.3g}")


def need(df, *cols):
    for c in cols:
        if c not in df.columns:
            raise SystemExit(
                f"Column '{c}' is not in the data. Columns: {list(df.columns)[:30]}"
            )


def interval(draws, alpha):
    lo, hi = np.quantile(draws, [alpha / 2, 1 - alpha / 2])
    return r(lo), r(hi)


def boot_stat(x, fn, n_boot, rng, alpha):
    x = np.asarray(x, dtype=float)
    draws = np.array([fn(x[rng.integers(0, len(x), len(x))]) for _ in range(n_boot)])
    return {
        "estimate": r(fn(x)),
        "ci_low": interval(draws, alpha)[0],
        "ci_high": interval(draws, alpha)[1],
    }


def boot_diff(a, b, fn, n_boot, rng, alpha):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    draws = np.array(
        [
            fn(b[rng.integers(0, len(b), len(b))])
            - fn(a[rng.integers(0, len(a), len(a))])
            for _ in range(n_boot)
        ]
    )
    lo, hi = interval(draws, alpha)
    return {"estimate": r(fn(b) - fn(a)), "ci_low": lo, "ci_high": hi}


def magnitude(d):
    d = abs(d)
    return (
        "negligible"
        if d < 0.2
        else "small"
        if d < 0.5
        else "medium"
        if d < 0.8
        else "large"
    )


def method_block(a):
    return {
        "interval": "percentile bootstrap",
        "n_boot": a.n_boot,
        "seed": a.seed,
        "confidence": round(1 - a.alpha, 4),
    }


# --------------------------------------------------------------------------- subcommands


def cmd_ci(a, df, rng):
    need(df, a.col)
    fn = STATS[a.stat]
    x = pd.to_numeric(df[a.col], errors="coerce")
    out = {"column": a.col, "statistic": a.stat, "method": method_block(a)}
    if a.by:
        need(df, a.by)
        rows = []
        for key, g in df.assign(_x=x).dropna(subset=["_x", a.by]).groupby(a.by):
            if len(g) < 2:
                continue
            rows.append(
                {
                    "group": str(key),
                    "n": len(g),
                    **boot_stat(g["_x"], fn, a.n_boot, rng, a.alpha),
                }
            )
        out["groups"] = sorted(rows, key=lambda d: -d["n"])[: a.max_groups]
    else:
        v = x.dropna()
        out.update(
            n=len(v),
            n_dropped=int(x.isna().sum()),
            **boot_stat(v, fn, a.n_boot, rng, a.alpha),
        )
    return out


def cmd_compare(a, df, rng):
    need(df, a.value, a.group)
    d = df[[a.value, a.group]].copy()
    d[a.value] = pd.to_numeric(d[a.value], errors="coerce")
    n_dropped = int(d.isna().any(axis=1).sum())
    d = d.dropna()
    labels = list(d[a.group].unique())
    out = {
        "value": a.value,
        "group": a.group,
        "n_dropped_missing": n_dropped,
        "method": method_block(a),
    }

    if a.a is not None and a.b is not None:
        pair = (a.a, a.b)
    elif len(labels) == 2:
        pair = tuple(sorted(labels, key=str))
    else:
        pair = None

    if pair is None:
        groups = [g[a.value].to_numpy() for _, g in d.groupby(a.group)]
        h, p = stats.kruskal(*groups)
        k, n = len(groups), len(d)
        out.update(
            groups=[
                {
                    "group": str(k_),
                    "n": len(g),
                    "mean": r(g[a.value].mean()),
                    "median": r(g[a.value].median()),
                }
                for k_, g in d.groupby(a.group)
            ],
            kruskal_wallis={
                "H": r(h),
                "p_value": pv(p),
                "epsilon_squared": r(max(0.0, (h - k + 1) / (n - k))),
            },
            reading="More than two groups: name the pair to compare with --a/--b. With many "
            "pairs, correct for multiple comparisons.",
        )
        return out

    def pick(label):
        m = d[a.group].astype(str) == str(label)
        return d.loc[m, a.value].to_numpy()

    x, y = pick(pair[0]), pick(pair[1])
    if len(x) < 2 or len(y) < 2:
        raise SystemExit(
            f"Need at least 2 rows in each group; got {len(x)} and {len(y)}."
        )
    sp = math.sqrt(
        ((len(x) - 1) * x.var(ddof=1) + (len(y) - 1) * y.var(ddof=1))
        / (len(x) + len(y) - 2)
    )
    cohen = (y.mean() - x.mean()) / sp if sp > 0 else 0.0
    u_y = stats.mannwhitneyu(y, x, alternative="two-sided")
    cliff = 2 * u_y.statistic / (len(x) * len(y)) - 1
    welch = stats.ttest_ind(y, x, equal_var=False)
    out.update(
        a={
            "label": str(pair[0]),
            "n": len(x),
            "mean": r(x.mean()),
            "median": r(np.median(x)),
            "sd": r(x.std(ddof=1)),
        },
        b={
            "label": str(pair[1]),
            "n": len(y),
            "mean": r(y.mean()),
            "median": r(np.median(y)),
            "sd": r(y.std(ddof=1)),
        },
        difference_of_means_b_minus_a=boot_diff(x, y, np.mean, a.n_boot, rng, a.alpha),
        difference_of_medians_b_minus_a=boot_diff(
            x, y, np.median, a.n_boot, rng, a.alpha
        ),
        effect_size={
            "cohens_d": r(cohen),
            "cohens_d_magnitude": magnitude(cohen),
            "cliffs_delta": r(cliff),
            "cliffs_delta_note": "P(b>a) - P(a>b)",
        },
        tests={
            "welch_t": {"statistic": r(welch.statistic), "p_value": pv(welch.pvalue)},
            "mann_whitney_u": {
                "statistic": r(u_y.statistic),
                "p_value": pv(u_y.pvalue),
            },
        },
        reading=(
            "Detectable at alpha=%.2f; judge relevance from the interval and effect size, not "
            "the p-value." % a.alpha
        )
        if welch.pvalue < a.alpha
        else (
            "Not detectable at alpha=%.2f with this sample; that is not evidence of no "
            "difference: read the interval." % a.alpha
        ),
    )
    return out


def cmd_proportion(a, df, rng):
    need(df, a.outcome, a.group)
    d = df[[a.outcome, a.group]].dropna().copy()
    if a.success is not None:
        ok = d[a.outcome].astype(str) == str(a.success)
    elif set(d[a.outcome].unique()) <= {0, 1, True, False}:
        ok = d[a.outcome].astype(int) == 1
    else:
        raise SystemExit(
            f"Outcome values are {sorted(map(str, d[a.outcome].unique()))[:10]}: "
            f"say which one is a success with --success."
        )
    d["_ok"] = ok.astype(int)
    rows = []
    for key, g in d.groupby(a.group):
        k, n = int(g["_ok"].sum()), len(g)
        ci = stats.binomtest(k, n).proportion_ci(
            confidence_level=1 - a.alpha, method="wilson"
        )
        rows.append(
            {
                "group": str(key),
                "n": n,
                "successes": k,
                "rate": r(k / n),
                "ci_low": r(ci.low),
                "ci_high": r(ci.high),
            }
        )
    out = {
        "outcome": a.outcome,
        "success": a.success if a.success is not None else "1/True",
        "group": a.group,
        "interval": "Wilson",
        "confidence": round(1 - a.alpha, 4),
        "groups": rows,
    }

    labels = sorted(d[a.group].unique(), key=str)
    if a.a is not None and a.b is not None:
        pair = (a.a, a.b)
    elif len(labels) == 2:
        pair = (labels[0], labels[1])
    else:
        pair = None
    table = pd.crosstab(d[a.group], d["_ok"]).reindex(columns=[0, 1], fill_value=0)
    if pair is None:
        chi2, p, _, _ = stats.chi2_contingency(table)
        out["chi_square"] = {"statistic": r(chi2), "p_value": pv(p)}
        out["reading"] = (
            "More than two groups: name a pair with --a/--b for a difference and CI."
        )
        return out
    xa = d.loc[d[a.group].astype(str) == str(pair[0]), "_ok"].to_numpy()
    xb = d.loc[d[a.group].astype(str) == str(pair[1]), "_ok"].to_numpy()
    sub = table.loc[[g for g in table.index if str(g) in (str(pair[0]), str(pair[1]))]]
    odds, p_fisher = stats.fisher_exact(sub.to_numpy())
    out["difference_b_minus_a"] = {
        **boot_diff(xa, xb, np.mean, a.n_boot, rng, a.alpha),
        "method": "percentile bootstrap",
        "n_boot": a.n_boot,
        "seed": a.seed,
    }
    out["relative_lift_b_over_a"] = (
        r(xb.mean() / xa.mean() - 1) if xa.mean() > 0 else None
    )
    out["tests"] = {"fisher_exact": {"odds_ratio": r(odds), "p_value": pv(p_fisher)}}
    out["reading"] = (
        "Detectable at alpha=%.2f; check the interval for practical relevance."
        % a.alpha
        if p_fisher < a.alpha
        else "Not detectable at alpha=%.2f; read the interval, do not conclude 'no effect'."
        % a.alpha
    )
    return out


def cmd_corr(a, df, rng):
    need(df, a.x, a.y)
    d = df[[a.x, a.y]].apply(pd.to_numeric, errors="coerce").dropna()
    n = len(d)
    if n < 10:
        raise SystemExit(f"Only {n} complete pairs: too few for a correlation.")
    x, y = d[a.x].to_numpy(), d[a.y].to_numpy()
    fns = {
        "pearson": lambda u, v: np.corrcoef(u, v)[0, 1],
        "spearman": lambda u, v: stats.spearmanr(u, v)[0],
    }
    methods = ["pearson", "spearman"] if a.method == "both" else [a.method]
    out = {"x": a.x, "y": a.y, "n_pairs": n, "method": method_block(a)}
    for m in methods:
        draws = []
        for _ in range(a.n_boot):
            i = rng.integers(0, n, n)
            draws.append(fns[m](x[i], y[i]))
        p = stats.pearsonr(x, y)[1] if m == "pearson" else stats.spearmanr(x, y)[1]
        lo, hi = interval(np.array(draws), a.alpha)
        out[m] = {
            "estimate": r(fns[m](x, y)),
            "ci_low": lo,
            "ci_high": hi,
            "p_value": pv(p),
        }
    if (
        len(methods) == 2
        and abs(out["pearson"]["estimate"] - out["spearman"]["estimate"]) > 0.15
    ):
        out["reading"] = (
            "Pearson and Spearman disagree by more than 0.15: look for outliers or a "
            "non-linear monotone relationship before trusting either."
        )
    out["caution"] = (
        "Correlation is not causation; check confounders and time ordering."
    )
    return out


def cmd_sample_size(a, df, rng):
    za, zb = stats.norm.ppf(1 - a.alpha / 2), stats.norm.ppf(a.power)
    out = {
        "alpha": a.alpha,
        "power": a.power,
        "two_sided": True,
        "note": "normal approximation; a starting point, not a substitute for a power simulation",
    }
    if a.mean_diff is not None and a.sd is not None:
        n = 2 * ((za + zb) * a.sd / a.mean_diff) ** 2
        out.update(
            design="two-sample comparison of means", mean_diff=a.mean_diff, sd=a.sd
        )
    elif a.p1 is not None and a.p2 is not None:
        pbar = (a.p1 + a.p2) / 2
        n = (
            za * math.sqrt(2 * pbar * (1 - pbar))
            + zb * math.sqrt(a.p1 * (1 - a.p1) + a.p2 * (1 - a.p2))
        ) ** 2 / (a.p1 - a.p2) ** 2
        out.update(design="two-sample comparison of proportions", p1=a.p1, p2=a.p2)
    else:
        raise SystemExit("Give either --mean-diff and --sd, or --p1 and --p2.")
    out.update(n_per_group=math.ceil(n), n_total=2 * math.ceil(n))
    return out


# --------------------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, data=True):
        if data:
            p.add_argument("--data", required=True)
        p.add_argument("--n-boot", type=int, default=2000)
        p.add_argument("--seed", type=int, default=0)
        p.add_argument("--alpha", type=float, default=0.05)

    p = sub.add_parser("ci")
    common(p)
    p.add_argument("--col", required=True)
    p.add_argument("--stat", default="mean", choices=list(STATS))
    p.add_argument("--by")
    p.add_argument("--max-groups", type=int, default=30)

    p = sub.add_parser("compare")
    common(p)
    p.add_argument("--value", required=True)
    p.add_argument("--group", required=True)
    p.add_argument("--a")
    p.add_argument("--b")

    p = sub.add_parser("proportion")
    common(p)
    p.add_argument("--outcome", required=True)
    p.add_argument("--group", required=True)
    p.add_argument("--success")
    p.add_argument("--a")
    p.add_argument("--b")

    p = sub.add_parser("corr")
    common(p)
    p.add_argument("--x", required=True)
    p.add_argument("--y", required=True)
    p.add_argument("--method", default="both", choices=["both", "pearson", "spearman"])

    p = sub.add_parser("sample-size")
    common(p, data=False)
    p.add_argument("--mean-diff", type=float)
    p.add_argument("--sd", type=float)
    p.add_argument("--p1", type=float)
    p.add_argument("--p2", type=float)
    p.add_argument("--power", type=float, default=0.8)

    a = ap.parse_args()
    if a.n_boot < MIN_BOOT:
        raise SystemExit(
            f"--n-boot must be at least {MIN_BOOT}: an interval from fewer resamples "
            f"is not reportable."
        )
    rng = np.random.default_rng(a.seed)
    df = load_table(a.data) if getattr(a, "data", None) else None
    fn = {
        "ci": cmd_ci,
        "compare": cmd_compare,
        "proportion": cmd_proportion,
        "corr": cmd_corr,
        "sample-size": cmd_sample_size,
    }[a.cmd]
    print(json.dumps(fn(a, df, rng), indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Target-aware data audit: is this dataset safe to model, and what can it plausibly deliver?

Runs the mechanical half of the pre-modelling data gate:
  - leakage signals: per-feature predictive signal on its own, copies/proxies of the target,
    missingness that depends on the target, name overlap, row order carrying the target
  - duplicates: exact, conflicting labels, and duplicates that would cross the recommended split
  - split strategy: which scheme the structure demands, with evidence
  - optional probe (--probe): a fixed, untuned gradient-boosting run under the recommended split
    and under a random split. It is a diagnostic, not a candidate model.

It cannot know what a column MEANS. Every finding is a symptom to verify with a person.

Usage:
  audit_data.py --data PATH --target COL [--time COL] [--group COL]
                [--task auto|binary|multiclass|regression] [--positive VALUE]
                [--ignore col1,col2] [--probe] [--folds 5] [--seed 0]
                [--sample N] [--probe-rows 50000] [--max-cols 100] [--out audit.json]
"""

import argparse
import json
import re
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
)
from sklearn.metrics import (
    average_precision_score,
    mean_absolute_error,
    r2_score,
    roc_auc_score,
)
from sklearn.model_selection import GroupKFold, KFold, StratifiedKFold, TimeSeriesSplit

warnings.filterwarnings("ignore")

LEAK_AUC, SUSPECT_AUC = 0.90, 0.80  # classification: single-feature AUC
LEAK_RHO, SUSPECT_RHO = 0.95, 0.85  # regression: single-feature |Spearman|
DATE_RE = re.compile(r"^\s*\d{4}[-/]\d{1,2}[-/]\d{1,2}")
SEVERITY_ORDER = {"blocker": 0, "risk": 1, "info": 2}


# --------------------------------------------------------------------------- loading
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


def py(v):
    if v is None:
        return None
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, (np.floating, float)):
        return None if np.isnan(v) or np.isinf(v) else round(float(v), 4)
    return v


# --------------------------------------------------------------------------- target and features


def infer_task(y, forced):
    if forced != "auto":
        return forced
    nun = y.nunique(dropna=True)
    if nun == 2:
        return "binary"
    if not pd.api.types.is_numeric_dtype(y) or (
        pd.api.types.is_integer_dtype(y) and nun <= 20
    ):
        return "multiclass"
    return "regression"


def encode_target(y, task, positive):
    """Return (numeric target Series, description of the encoding)."""
    if task == "regression":
        return y.astype(float), "regression: numeric target as is"
    if task == "multiclass":
        codes, labels = pd.factorize(y)
        return pd.Series(
            codes, index=y.index, dtype=float
        ), f"multiclass: {len(labels)} classes"
    values = set(y.dropna().unique())
    if positive is not None:
        pos = str(positive)
        return (y.astype(str) == pos).astype(float), f"binary: positive class = '{pos}'"
    if values <= {0, 1, True, False}:
        return y.astype(float), "binary: positive class = 1"
    minority = y.value_counts().idxmin()
    return (y == minority).astype(
        float
    ), f"binary: positive class = '{minority}' (minority)"


def feature_kind(s, n):
    if pd.api.types.is_bool_dtype(s) or pd.api.types.is_numeric_dtype(s):
        return "numeric"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "numeric_date"
    head = s.dropna().astype(str).head(200)
    if len(head) and head.map(lambda v: bool(DATE_RE.match(v))).mean() > 0.95:
        return "numeric_date"
    nun = s.nunique(dropna=True)
    return "categorical" if nun <= 200 and nun <= 0.5 * n else "skip"


def as_number(s, kind):
    if kind == "numeric_date":
        t = pd.to_datetime(s, errors="coerce")
        return (t - pd.Timestamp("1970-01-01")).dt.total_seconds() / 86400
    return pd.to_numeric(
        s.astype(float) if pd.api.types.is_bool_dtype(s) else s, errors="coerce"
    )


def oof_encode(cat, target, seed, folds=5):
    """Out-of-fold target-mean encoding of a categorical column (no self-leakage)."""
    cat = cat.astype("object").where(cat.notna(), "__missing__").reset_index(drop=True)
    target = target.reset_index(drop=True)
    enc = pd.Series(np.nan, index=cat.index)
    for tr, va in KFold(folds, shuffle=True, random_state=seed).split(cat):
        means = target.iloc[tr].groupby(cat.iloc[tr]).mean()
        enc.iloc[va] = cat.iloc[va].map(means).fillna(target.iloc[tr].mean()).to_numpy()
    return enc


def binary_auc(x, yb):
    m = x.notna().to_numpy() & yb.notna().to_numpy()
    if m.sum() < 50 or yb[m].nunique() < 2:
        return None
    a = roc_auc_score(yb[m], x[m])
    return float(max(a, 1 - a))


def signal(s, y, task, seed):
    """Predictive signal of ONE feature on its own: AUC (classification) or |Spearman|."""
    kind = feature_kind(s, len(s))
    if kind == "skip":
        return None

    def score(target):
        enc = (
            oof_encode(s, target, seed) if kind == "categorical" else as_number(s, kind)
        )
        enc = enc.reset_index(drop=True)
        target = target.reset_index(drop=True)
        if task == "regression":
            r = enc.corr(target, method="spearman")
            return None if pd.isna(r) else abs(float(r))
        return binary_auc(enc, target)

    if task == "multiclass":
        scores = [
            score((y == k).astype(float)) for k in sorted(y.dropna().unique())[:20]
        ]
        scores = [v for v in scores if v is not None]
        return max(scores) if scores else None
    return score(y)


def is_copy_of_target(s, y):
    n = len(s)
    # Partition equality is only meaningful when values repeat: two all-unique columns split
    # the rows into singletons and would "match" trivially.
    if s.nunique(dropna=True) <= 0.5 * n and y.nunique(dropna=True) <= 0.5 * n:
        same = float((pd.factorize(s)[0] == pd.factorize(y)[0]).mean())
        if same >= 0.99:
            return f"identical partition to the target in {100 * same:.1f}% of rows"
    if pd.api.types.is_numeric_dtype(s) and pd.api.types.is_numeric_dtype(y):
        xs, ys = s.astype(float), y.astype(float)
        r = xs.corr(ys)
        if pd.notna(r) and abs(r) >= 0.999:
            return f"linear copy of the target (|r| = {abs(r):.4f})"
        rho = xs.corr(ys, method="spearman")
        if pd.notna(rho) and abs(rho) >= 0.999:
            return (
                f"monotone transformation of the target (|Spearman| = {abs(rho):.4f})"
            )
    return None


def null_dependence(s, y, task):
    """How much the target differs between rows where the feature is missing and where it is not."""
    isn = s.isna().to_numpy()
    if isn.sum() < 30 or (~isn).sum() < 30:
        return None
    if task == "regression":
        sd = float(y.std()) or 1.0
        return abs(float(y[isn].mean() - y[~isn].mean())) / sd
    if task == "binary":
        return abs(float(y[isn].mean() - y[~isn].mean()))
    a = y[isn].value_counts(normalize=True)
    b = y[~isn].value_counts(normalize=True)
    return float(
        (
            a.reindex(b.index.union(a.index), fill_value=0)
            - b.reindex(b.index.union(a.index), fill_value=0)
        )
        .abs()
        .max()
    )


# --------------------------------------------------------------------------- splits


def recommend_scheme(task, time_col, group_col):
    if time_col:
        return "time"
    if group_col:
        return "group"
    return "kfold" if task == "regression" else "stratified"


def make_splits(scheme, df, y, time_col, group_col, folds, seed):
    n = len(df)
    if scheme == "time":
        t = pd.to_datetime(df[time_col], errors="coerce").to_numpy()
        valid = np.where(~pd.isna(t))[0]
        order = valid[np.argsort(t[valid], kind="stable")]
        return [
            (order[tr], order[va]) for tr, va in TimeSeriesSplit(folds).split(order)
        ]
    if scheme == "group":
        return list(GroupKFold(folds).split(np.zeros(n), y, df[group_col]))
    if scheme == "stratified":
        return list(
            StratifiedKFold(folds, shuffle=True, random_state=seed).split(
                np.zeros(n), y
            )
        )
    return list(KFold(folds, shuffle=True, random_state=seed).split(np.zeros(n)))


# --------------------------------------------------------------------------- probe


def build_matrix(df, cols):
    X = pd.DataFrame(index=df.index)
    for c in cols:
        kind = feature_kind(df[c], len(df))
        if kind in ("numeric", "numeric_date"):
            X[c] = as_number(df[c], kind)
        elif kind == "categorical":
            X[c] = df[c].astype("category").cat.codes.replace(-1, np.nan)
    return X


def probe_scores(X, y, task, splits, seed):
    folds = []
    for tr, va in splits:
        ytr, yva = y.iloc[tr], y.iloc[va]
        if task == "regression":
            m = HistGradientBoostingRegressor(
                max_iter=200, early_stopping=False, random_state=seed
            )
            m.fit(X.iloc[tr], ytr)
            p = m.predict(X.iloc[va])
            folds.append(
                {
                    "r2": r2_score(yva, p),
                    "mae": mean_absolute_error(yva, p),
                    "mae_trivial": mean_absolute_error(
                        yva, np.full(len(yva), ytr.median())
                    ),
                }
            )
        else:
            if yva.nunique() < 2 or ytr.nunique() < 2:
                continue
            m = HistGradientBoostingClassifier(
                max_iter=200, early_stopping=False, random_state=seed
            )
            m.fit(X.iloc[tr], ytr)
            proba = m.predict_proba(X.iloc[va])
            if task == "binary":
                folds.append(
                    {
                        "roc_auc": roc_auc_score(yva, proba[:, 1]),
                        "pr_auc": average_precision_score(yva, proba[:, 1]),
                        "prevalence": float(yva.mean()),
                    }
                )
            else:
                if not set(yva.unique()) <= set(m.classes_):
                    continue
                folds.append(
                    {
                        "roc_auc": roc_auc_score(
                            yva, proba, multi_class="ovr", labels=m.classes_
                        )
                    }
                )
    if not folds:
        return None
    primary = "r2" if task == "regression" else "roc_auc"
    vals = np.array([f[primary] for f in folds])
    out = {
        "metric": primary,
        "n_folds": len(folds),
        "mean": py(vals.mean()),
        "sd": py(vals.std(ddof=1) if len(vals) > 1 else 0.0),
        "folds": [py(v) for v in vals],
    }
    for k in folds[0]:
        if k != primary:
            out[f"{k}_mean"] = py(np.mean([f[k] for f in folds]))
    return out


# --------------------------------------------------------------------------- audit


def audit(
    df,
    target,
    time_col,
    group_col,
    task_arg,
    positive,
    ignore,
    folds,
    seed,
    run_probe,
    probe_rows,
    max_cols,
):
    findings = []

    def add(severity, code, message, column=None, **evidence):
        findings.append(
            {
                "severity": severity,
                "code": code,
                "column": column,
                "message": message,
                "evidence": evidence,
            }
        )

    n_before = len(df)
    df = df[df[target].notna()].reset_index(drop=True)
    if len(df) < n_before:
        add(
            "info",
            "TARGET_NULL",
            f"{n_before - len(df)} rows without a target were dropped.",
        )
    n = len(df)

    task = infer_task(df[target], task_arg)
    y, y_note = encode_target(df[target], task, positive)
    structure = {c for c in (time_col, group_col) if c}
    candidates = [c for c in df.columns if c != target and c not in ignore]
    scan_cols = candidates[:max_cols]
    result = {"rows": n, "task": task, "target": target, "target_encoding": y_note}

    # ---- leakage signals ---------------------------------------------------------------
    signals = []
    for c in scan_cols:
        s = df[c]
        copy = is_copy_of_target(s, df[target])
        if copy:
            add("blocker", "TARGET_COPY", f"'{c}' is a copy of the target: {copy}.", c)
            continue
        sc = signal(s, y, task, seed)
        if sc is None:
            continue
        signals.append({"column": c, "score": py(sc)})
        leak, sus = (
            (LEAK_RHO, SUSPECT_RHO) if task == "regression" else (LEAK_AUC, SUSPECT_AUC)
        )
        metric = "|Spearman|" if task == "regression" else "AUC"
        if sc >= leak:
            add(
                "blocker",
                "LEAK_SIGNAL",
                f"'{c}' reaches {metric} {sc:.3f} on its own. A single feature almost never "
                f"separates that well unless it carries the answer. Find out when it is filled in.",
                c,
                score=py(sc),
            )
        elif sc >= sus:
            add(
                "risk",
                "SUSPECT_SIGNAL",
                f"'{c}' reaches {metric} {sc:.3f} on its own: explain the mechanism before using it.",
                c,
                score=py(sc),
            )
    result["top_signals"] = sorted(signals, key=lambda d: -d["score"])[:15]

    tname = str(target).lower()
    already_blocked = {f["column"] for f in findings if f["severity"] == "blocker"}
    for c in candidates:
        cl = str(c).lower()
        if (
            len(cl) >= 3
            and (tname in cl or cl in tname)
            and c not in structure
            and c not in already_blocked
        ):
            add(
                "risk",
                "NAME_OVERLAP",
                f"'{c}' shares its name with the target '{target}': often a consequence of the "
                f"event (a reason, a status, a date). Check when it is populated.",
                c,
            )

    for c in candidates:
        share = float(df[c].isna().mean())
        if not 0.01 <= share <= 0.99:
            continue
        dep = null_dependence(df[c], y, task)
        if dep is None:
            continue
        limit_risk, limit_block = (1.0, 99) if task == "regression" else (0.3, 0.5)
        unit = "sd of the target" if task == "regression" else "in class share"
        if dep >= limit_block:
            add(
                "blocker",
                "NULL_PATTERN",
                f"'{c}' is missing in {100 * share:.0f}% of rows and whether it is missing "
                f"depends on the target ({dep:.2f} {unit}). Likely populated only once the event "
                f"has happened.",
                c,
                null_pct=round(100 * share, 1),
                dependence=py(dep),
            )
        elif dep >= limit_risk:
            add(
                "risk",
                "NULL_PATTERN",
                f"Missingness of '{c}' ({100 * share:.0f}% missing) is related to the target "
                f"({dep:.2f} {unit}).",
                c,
                null_pct=round(100 * share, 1),
                dependence=py(dep),
            )

    if not time_col and task != "multiclass" and n >= 100:
        rho = pd.Series(np.arange(n)).corr(y, method="spearman")
        if pd.notna(rho) and abs(rho) > 0.1:
            add(
                "risk",
                "ROW_ORDER",
                f"Row order correlates with the target (Spearman {rho:.2f}): the file looks "
                f"sorted by outcome or time. A sequential split would not be representative.",
                rho=py(rho),
            )

    # ---- duplicates --------------------------------------------------------------------
    feat_cols = [c for c in df.columns if c != target]
    key = pd.util.hash_pandas_object(df[feat_cols], index=False)
    exact = int(df.duplicated().sum())
    grp = df[target].groupby(key).agg(["nunique", "size"])
    conflicting_rows = int(grp.loc[(grp["nunique"] > 1), "size"].sum())
    dup = {
        "exact_duplicate_rows": exact,
        "rows_with_conflicting_labels": conflicting_rows,
        "conflicting_pct": round(100 * conflicting_rows / n, 2),
    }
    if exact:
        add(
            "risk",
            "DUPLICATES",
            f"{exact} exactly duplicated rows ({100 * exact / n:.1f}%).",
            exact=exact,
        )
    if conflicting_rows:
        add(
            "risk",
            "LABEL_CONFLICT",
            f"{conflicting_rows} rows ({100 * conflicting_rows / n:.1f}%) have identical features "
            f"but different targets: label noise that caps the achievable score.",
            rows=conflicting_rows,
        )
    result["duplicates"] = dup

    # ---- split strategy ----------------------------------------------------------------
    scheme = recommend_scheme(task, time_col, group_col)
    reasons = {
        "time": f"'{time_col}' gives the data an order: train on the past, validate on the future",
        "group": f"repeated entities in '{group_col}': whole groups must stay on one side",
        "stratified": "no time or group column was given: stratified K-fold, but random is "
        "assumed WRONG until someone confirms there is no entity or temporal "
        "structure",
        "kfold": "no time or group column was given: K-fold, but random is assumed WRONG "
        "until someone confirms there is no entity or temporal structure",
    }
    split = {"recommended": scheme, "reason": reasons[scheme]}
    rng = np.random.default_rng(seed)
    perm = rng.permutation(n)
    tr_r, va_r = perm[: int(0.8 * n)], perm[int(0.8 * n) :]
    if group_col:
        g = df[group_col]
        seen = float(g.iloc[va_r].isin(set(g.iloc[tr_r])).mean())
        split["group_share_of_validation_rows_seen_in_train_under_random_split"] = (
            round(seen, 3)
        )
        if seen > 0.5:
            add(
                "info",
                "GROUP_RANDOM_SPLIT",
                f"Under a random split {100 * seen:.0f}% of validation rows belong to a group "
                f"already in train: the model can recognise the entity instead of learning the "
                f"pattern. Use GroupKFold on '{group_col}'.",
            )
    splits = make_splits(scheme, df, y, time_col, group_col, folds, seed)
    if splits:
        tr, va = splits[-1]
        split["duplicates_crossing_split_pct"] = round(
            100
            * float(np.isin(key.iloc[va].to_numpy(), key.iloc[tr].to_numpy()).mean()),
            2,
        )
        if split["duplicates_crossing_split_pct"] > 0:
            add(
                "risk",
                "DUP_ACROSS_SPLIT",
                f"{split['duplicates_crossing_split_pct']}% of validation rows have an identical "
                f"twin in train under the recommended split.",
            )
    result["split"] = split

    # ---- probe -------------------------------------------------------------------------
    if run_probe:
        pdf = df
        if n > probe_rows:
            pdf = (
                df.sample(probe_rows, random_state=seed)
                .sort_index()
                .reset_index(drop=True)
            )
            py_y, _ = encode_target(pdf[target], task, positive)
        else:
            py_y = y
        id_like = [
            c
            for c in candidates
            if pdf[c].nunique(dropna=True) > 0.9 * len(pdf)
            and not pd.api.types.is_float_dtype(pdf[c])
        ]
        base_cols = [c for c in candidates if c not in structure and c not in id_like]
        suspects = {
            f["column"] for f in findings if f["severity"] == "blocker" and f["column"]
        }
        proper = make_splits(scheme, pdf, py_y, time_col, group_col, folds, seed)
        randsplit = make_splits(
            "kfold" if task == "regression" else "stratified",
            pdf,
            py_y,
            None,
            None,
            folds,
            seed,
        )
        probe = {
            "scheme": scheme,
            "rows_used": len(pdf),
            "features_excluded_as_structure_or_id": sorted(structure) + id_like,
            "note": "fixed untuned HistGradientBoosting; "
            "a diagnostic, not a candidate model",
        }
        clean_cols = [c for c in base_cols if c not in suspects]
        probe["all_features"] = probe_scores(
            build_matrix(pdf, base_cols), py_y, task, proper, seed
        )
        if suspects and clean_cols:
            probe["without_suspects"] = probe_scores(
                build_matrix(pdf, clean_cols), py_y, task, proper, seed
            )
            probe["suspects_removed"] = sorted(suspects & set(base_cols))
        # Random-vs-proper is measured on the reference feature set: with leaks in, both sides
        # saturate and the effect of the split structure disappears behind them.
        ref_cols = clean_cols if (suspects and clean_cols) else base_cols
        if scheme in ("group", "time"):
            probe["random_split"] = probe_scores(
                build_matrix(pdf, ref_cols), py_y, task, randsplit, seed
            )
            a = probe.get("without_suspects") or probe["all_features"]
            b = probe["random_split"]
            if a and b and a["mean"] is not None and b["mean"] is not None:
                gap = b["mean"] - a["mean"]
                probe["random_split_inflation"] = py(gap)
                if gap >= (0.1 if task == "regression" else 0.05):
                    add(
                        "risk",
                        "RANDOM_SPLIT_INFLATES",
                        f"The same probe scores {b['mean']:.3f} under a random split but "
                        f"{a['mean']:.3f} under the recommended '{scheme}' split "
                        f"(+{gap:.3f} from structure alone): a random split would flatter the model.",
                        gap=py(gap),
                    )
        ref = probe.get("without_suspects") or probe["all_features"]
        if ref and ref["mean"] is not None:
            weak = ref["mean"] <= (0.05 if task == "regression" else 0.55)
            probe["reading"] = (
                "the probe finds almost no learnable signal in these features: the "
                "data may not support a useful model of this target"
                if weak
                else "the probe finds learnable signal beyond chance"
            )
            soft = ref["mean"] + 2 * (ref["sd"] or 0)
            probe["ceiling_reference"] = {
                "metric": ref["metric"],
                "value": py(min(max(soft, 0.0), 1.0)),
                "basis": "probe mean + 2·sd"
                + (" with suspects removed" if probe.get("without_suspects") else ""),
                "caveat": "heuristic from an untuned model: not a proof. A target well above it "
                "needs a stated mechanism.",
            }
        result["probe"] = probe

    findings.sort(key=lambda f: SEVERITY_ORDER[f["severity"]])
    result["findings"] = findings
    result["verdict"] = {
        "blockers": sum(f["severity"] == "blocker" for f in findings),
        "risks": sum(f["severity"] == "risk" for f in findings),
    }
    return result


# --------------------------------------------------------------------------- report


def print_report(r, source):
    print(
        f"Audit of {source}: {r['rows']:,} rows, target '{r['target']}', task {r['task']} "
        f"({r['target_encoding']})"
    )
    v = r["verdict"]
    print(f"VERDICT: {v['blockers']} blocker(s), {v['risks']} risk(s)\n")
    marks = {"blocker": "[BLOCKER]", "risk": "[risk]   ", "info": "[info]   "}
    for f in r["findings"]:
        print(f"  {marks[f['severity']]} {f['code']}: {f['message']}")
    if not r["findings"]:
        print("  No automatic findings. That is not the same as none.")
    s = r["split"]
    print(f"\nSplit: recommended '{s['recommended']}' — {s['reason']}")
    if "duplicates_crossing_split_pct" in s:
        print(
            f"       duplicates crossing that split: {s['duplicates_crossing_split_pct']}% of validation rows"
        )
    print("\nStrongest single-feature signals:")
    for d in r["top_signals"][:8]:
        print(f"  {d['column']:30} {d['score']}")
    if "probe" in r:
        p = r["probe"]
        print(f"\nProbe ({p['scheme']} split, {p['rows_used']:,} rows; {p['note']}):")
        for label, key in (
            ("all features", "all_features"),
            ("without suspects", "without_suspects"),
            ("random split, same features", "random_split"),
        ):
            b = p.get(key)
            if b:
                print(
                    f"  {label:28} {b['metric']} {b['mean']} ± {b['sd']}  (folds {b['folds']})"
                )
        if "reading" in p:
            print(f"  reading: {p['reading']}")
        if "ceiling_reference" in p:
            c = p["ceiling_reference"]
            print(
                f"  ceiling reference: {c['metric']} ≈ {c['value']} ({c['basis']}). {c['caveat']}"
            )
    print(
        "\nNot answered here: what each column means, when it is populated, whether the target "
        "was built with a rule. That needs a person."
    )


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    ap.add_argument("--data", required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--time")
    ap.add_argument("--group")
    ap.add_argument(
        "--task", default="auto", choices=["auto", "binary", "multiclass", "regression"]
    )
    ap.add_argument("--positive")
    ap.add_argument("--ignore", default="")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--sample", type=int)
    ap.add_argument("--probe-rows", type=int, default=50000)
    ap.add_argument("--max-cols", type=int, default=100)
    ap.add_argument("--out")
    a = ap.parse_args()

    df = load_table(a.data)
    for c in (a.target, a.time, a.group):
        if c and c not in df.columns:
            raise SystemExit(
                f"Column '{c}' is not in the data. Columns: {list(df.columns)[:30]}"
            )
    if a.sample and a.sample < len(df):
        df = df.sample(a.sample, random_state=a.seed).sort_index()
    ignore = {c.strip() for c in a.ignore.split(",") if c.strip()}

    r = audit(
        df,
        a.target,
        a.time,
        a.group,
        a.task,
        a.positive,
        ignore,
        a.folds,
        a.seed,
        a.probe,
        a.probe_rows,
        a.max_cols,
    )
    r["source"], r["seed"] = str(a.data), a.seed
    print_report(r, a.data)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(
            json.dumps(r, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
        )
        print(f"\nSaved: {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

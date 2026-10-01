#!/usr/bin/env python3
"""Profile a tabular dataset: structure, quality problems, and (optionally) its time and
entity structure.

Usage:
  profile_data.py --data PATH [--time COL] [--group COL]
                  [--nrows N] [--sample N] [--seed 0] [--max-cols 60] [--out profile.json]

  --nrows N   read only the first N rows (cheap on huge files, but may be biased)
  --sample N  random sample of N rows after loading (fixed seed)
  --out FILE  also write the full JSON (the text report is always printed)
"""

import argparse
import json
import re
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

NUM_SENTINELS = {-999, -99, -1, 0, 99, 999, 9999, -9999, 99999}
STR_SENTINELS = {
    "",
    "na",
    "n/a",
    "nan",
    "null",
    "none",
    "?",
    "-",
    "unknown",
    "missing",
    "#n/a",
}
DATE_RE = re.compile(r"^\s*\d{4}[-/]\d{1,2}[-/]\d{1,2}")


# --------------------------------------------------------------------------- loading
# Duplicated in the sibling analysis skills on purpose: each skill directory stays
# self-contained, so it can be copied or symlinked on its own.


def load_table(path, nrows=None):
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in (".csv", ".txt"):
        return pd.read_csv(p, nrows=nrows)
    if suffix == ".tsv":
        return pd.read_csv(p, sep="\t", nrows=nrows)
    if suffix in (".parquet", ".pq"):
        df = pd.read_parquet(p)
    elif suffix == ".feather":
        df = pd.read_feather(p)
    elif suffix == ".json":
        df = pd.read_json(p)
    elif suffix in (".jsonl", ".ndjson"):
        return pd.read_json(p, lines=True, nrows=nrows)
    else:
        raise SystemExit(f"Unsupported format: {suffix or p.name}")
    return df.head(nrows) if nrows else df


def py(v):
    """numpy scalar -> plain Python, NaN -> None, so the result is JSON-safe."""
    if v is None:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        return None if np.isnan(v) or np.isinf(v) else round(float(v), 4)
    return v


# --------------------------------------------------------------------------- columns


def column_kind(s):
    if pd.api.types.is_bool_dtype(s):
        return "boolean"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "datetime"
    if pd.api.types.is_numeric_dtype(s):
        return "numeric"
    head = s.dropna().astype(str).head(200)
    if len(head) and head.map(lambda v: bool(DATE_RE.match(v))).mean() > 0.95:
        return "datetime_string"
    return "categorical" if s.nunique(dropna=True) <= max(50, 0.05 * len(s)) else "text"


def describe_column(s):
    kind = column_kind(s)
    d = {
        "dtype": str(s.dtype),
        "kind": kind,
        "null_pct": round(100 * float(s.isna().mean()), 2),
        "n_unique": int(s.nunique(dropna=True)),
    }
    if kind == "numeric":
        x = s.dropna()
        if len(x):
            q1, med, q3 = x.quantile([0.25, 0.5, 0.75])
            iqr = q3 - q1
            outliers = (
                ((x < q1 - 1.5 * iqr) | (x > q3 + 1.5 * iqr)).mean() if iqr > 0 else 0.0
            )
            d.update(
                min=py(x.min()),
                p25=py(q1),
                median=py(med),
                mean=py(x.mean()),
                p75=py(q3),
                max=py(x.max()),
                std=py(x.std()),
                skew=py(x.skew()),
                outliers_iqr_pct=round(100 * float(outliers), 2),
            )
    elif kind in ("categorical", "boolean"):
        top = s.value_counts(normalize=True, dropna=True).head(5)
        d["top_values"] = {str(k): round(100 * float(v), 2) for k, v in top.items()}
    elif kind in ("datetime", "datetime_string"):
        t = pd.to_datetime(s, errors="coerce")
        d.update(min=str(t.min()), max=str(t.max()))
    return d


def column_note(name, d):
    """One short line for the text report."""
    if d["kind"] == "numeric" and "median" in d:
        return f"min {d['min']}  median {d['median']}  max {d['max']}"
    if d.get("top_values"):
        k, v = next(iter(d["top_values"].items()))
        return f"top '{k}' {v}%"
    if d["kind"].startswith("datetime"):
        return f"{d.get('min')} → {d.get('max')}"
    return ""


# --------------------------------------------------------------------------- analysis


def profile(df, time_col, group_col):
    n = len(df)
    findings = []
    cols = {c: describe_column(df[c]) for c in df.columns}

    dups = int(df.duplicated().sum())
    if dups:
        findings.append(
            f"{dups} exactly duplicated rows ({100 * dups / n:.1f}%). If rows should be "
            f"unique, counts and totals are inflated."
        )

    high_null = [c for c, d in cols.items() if d["null_pct"] > 50]
    mid_null = [c for c, d in cols.items() if 20 < d["null_pct"] <= 50]
    if high_null:
        findings.append(
            f"{len(high_null)} column(s) over 50% null: {high_null[:8]}. Real absence or "
            f"failed capture? They are not imputed alike."
        )
    if mid_null:
        findings.append(f"{len(mid_null)} column(s) with 20-50% nulls: {mid_null[:8]}.")

    constant = [c for c, d in cols.items() if d["n_unique"] <= 1]
    if constant:
        findings.append(f"Constant columns (no information): {constant[:8]}.")

    sentinels = {}
    for c, d in cols.items():
        s = df[c]
        if d["n_unique"] <= 2:
            continue  # flags and constants: 0/1 is a value there, not a sentinel
        if d["kind"] == "numeric":
            share = s.value_counts(normalize=True)
            for v in NUM_SENTINELS:
                if v in share.index and share[v] > 0.15:
                    sentinels[c] = {
                        "value": py(v),
                        "share_pct": round(100 * float(share[v]), 1),
                    }
                    break
        elif d["kind"] in ("categorical", "text"):
            # Real nulls are reported as nulls; only count placeholder strings among the values.
            low = s.dropna().astype(str).str.strip().str.lower()
            share = low.isin(STR_SENTINELS).mean() if len(low) else 0.0
            if share > 0.05:
                sentinels[c] = {
                    "value": "placeholder strings",
                    "share_pct": round(100 * float(share), 1),
                }
    if sentinels:
        findings.append(
            f"Probable sentinel / placeholder values (nulls in disguise) in "
            f"{list(sentinels)[:8]}: {sentinels}"
        )

    ids = [
        c
        for c, d in cols.items()
        if d["n_unique"] > 0.9 * n
        and n > 20
        and (
            d["kind"] in ("text", "categorical") or pd.api.types.is_integer_dtype(df[c])
        )
    ]
    if ids:
        findings.append(
            f"Identifier-like columns (almost unique per row): {ids[:8]}. Keys, not "
            f"measures: leave them out of statistics."
        )

    numeric_text = []
    for c, d in cols.items():
        if d["kind"] in ("categorical", "text"):
            conv = pd.to_numeric(df[c], errors="coerce")
            if conv.notna().mean() >= 0.9 and df[c].notna().any():
                numeric_text.append(c)
    if numeric_text:
        findings.append(f"Numbers stored as text: {numeric_text[:8]}.")

    strdates = [c for c, d in cols.items() if d["kind"] == "datetime_string"]
    if strdates:
        findings.append(f"Dates stored as strings (parse before use): {strdates[:8]}.")

    skewed = [
        c for c, d in cols.items() if d.get("skew") is not None and abs(d["skew"]) > 3
    ]
    if skewed:
        findings.append(
            f"Heavily skewed numeric columns (|skew|>3, consider log/rank): {skewed[:8]}."
        )
    outl = [c for c, d in cols.items() if d.get("outliers_iqr_pct", 0) > 5]
    if outl:
        findings.append(
            f"More than 5% IQR outliers in: {outl[:8]}. Errors or a genuine heavy tail?"
        )

    out = {
        "rows": n,
        "columns": df.shape[1],
        "exact_duplicate_rows": dups,
        "columns_detail": cols,
        "sentinels": sentinels,
        "id_like": ids,
    }

    if group_col:
        g = df[group_col]
        counts = g.value_counts()
        rpg = n / max(g.nunique(), 1)
        out["group"] = {
            "column": group_col,
            "n_groups": int(g.nunique()),
            "rows_per_group_mean": round(rpg, 2),
            "rows_per_group_median": py(counts.median()),
            "rows_per_group_max": int(counts.max()),
            "singleton_groups_pct": round(100 * float((counts == 1).mean()), 1),
        }
        if rpg > 1.2:
            findings.append(
                f"{g.nunique()} groups for {n} rows ({rpg:.1f} per group). Rows are not "
                f"independent: compare at the level of '{group_col}', or resample by it, "
                f"before using row-level tests."
            )

    if time_col:
        t = pd.to_datetime(df[time_col], errors="coerce")
        tt = {
            "column": time_col,
            "unparsed_pct": round(100 * float(t.isna().mean()), 2),
        }
        valid = t.dropna()
        if len(valid):
            tt.update(
                min=str(valid.min()),
                max=str(valid.max()),
                sorted_in_file=bool(t.dropna().is_monotonic_increasing),
            )
            months = valid.dt.to_period("M")
            full = pd.period_range(months.min(), months.max(), freq="M")
            missing = [str(m) for m in full.difference(months.unique())]
            tt["months_covered"] = int(months.nunique())
            tt["empty_months_in_range"] = missing[:12]
            if missing:
                findings.append(
                    f"Time coverage has {len(missing)} empty month(s) inside the range "
                    f"(first: {missing[:3]}): a change in the source system?"
                )
        out["time"] = tt

    out["findings"] = findings
    return out


# --------------------------------------------------------------------------- report


def print_report(result, source, used, total, max_cols):
    print(f"Dataset: {source}")
    note = (
        "" if used == total else f"  (analysing a sample of {used:,} of {total:,} rows)"
    )
    print(f"Shape:   {result['rows']:,} rows × {result['columns']} columns{note}\n")
    print(f"{'column':30} {'kind':16} {'null%':>6} {'unique':>8}  notes")
    for i, (c, d) in enumerate(result["columns_detail"].items()):
        if i >= max_cols:
            print(
                f"... {len(result['columns_detail']) - max_cols} more columns (see --out JSON)"
            )
            break
        print(
            f"{str(c)[:30]:30} {d['kind']:16} {d['null_pct']:>6} {d['n_unique']:>8}  "
            f"{column_note(c, d)}"
        )
    print("\nFindings:")
    if result["findings"]:
        for f in result["findings"]:
            print(f"  - {f}")
    else:
        print(
            "  none automatic. That is not the same as none: the checks here cannot see "
            "domain problems."
        )


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    ap.add_argument("--data", required=True)
    ap.add_argument("--time")
    ap.add_argument("--group")
    ap.add_argument("--nrows", type=int)
    ap.add_argument("--sample", type=int)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-cols", type=int, default=60)
    ap.add_argument("--out")
    a = ap.parse_args()

    df = load_table(a.data, a.nrows)
    total = len(df)
    for c in (a.time, a.group):
        if c and c not in df.columns:
            raise SystemExit(
                f"Column '{c}' is not in the data. Columns: {list(df.columns)[:30]}"
            )
    if a.sample and a.sample < total:
        df = df.sample(a.sample, random_state=a.seed).sort_index()

    result = profile(df, a.time, a.group)
    result["source"] = str(a.data)
    result["rows_in_file_read"] = total
    print_report(result, a.data, len(df), total, a.max_cols)

    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(
            json.dumps(result, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        print(f"\nSaved: {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Run SQL over local data files. Each file becomes a table in a throw-away in-memory SQLite
database, so the source files are never modified and nothing persists between runs.

Usage:
  sql_query.py --table NAME=PATH [--table NAME=PATH ...] (--query "SQL" | --file q.sql)
               [--limit 50] [--out result.csv|.parquet] [--explain] [--sample N] [--seed 0]
  sql_query.py --table orders=data/orders.csv --schema        (show tables, columns, row counts)

Prints at most --limit rows plus the total row count and the elapsed time, so a big result never
floods the conversation. --out saves the complete result.
Dialect: SQLite (window functions, CTEs and strftime() work; there is no DATE_TRUNC, use
strftime('%Y-%m', col)). Dates are stored as ISO text, so they sort and compare correctly.
"""

import argparse
import re
import sqlite3
import sys
import time
import warnings
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")
SLOW_SECONDS = 30
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    ap.add_argument("--table", action="append", required=True, metavar="NAME=PATH")
    ap.add_argument("--query", "-q")
    ap.add_argument("--file", "-f")
    ap.add_argument("--schema", action="store_true")
    ap.add_argument("--explain", action="store_true")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--out")
    ap.add_argument("--sample", type=int)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    con = sqlite3.connect(":memory:")
    for spec in a.table:
        name, _, path = spec.partition("=")
        if not path or not NAME_RE.match(name):
            raise SystemExit(
                f"--table expects NAME=PATH with NAME like a SQL identifier; got '{spec}'"
            )
        df = load_table(path)
        total = len(df)
        if a.sample and a.sample < total:
            df = df.sample(a.sample, random_state=a.seed).sort_index()
            print(
                f"[{name}] sampled {len(df):,} of {total:,} rows (seed {a.seed})",
                file=sys.stderr,
            )
        df.to_sql(name, con, index=False)

    if a.schema:
        for (name,) in con.execute(
            "select name from sqlite_master where type='table' order by 1"
        ):
            n = con.execute(f'select count(*) from "{name}"').fetchone()[0]
            cols = [
                f"{c[1]} {c[2]}" for c in con.execute(f'pragma table_info("{name}")')
            ]
            print(f"{name}  ({n:,} rows)\n  " + "\n  ".join(cols))
        return 0

    if a.file:
        sql = Path(a.file).read_text(encoding="utf-8")
    elif a.query:
        sql = a.query
    else:
        raise SystemExit("Give --query, --file or --schema.")
    if not re.match(r"^\s*(with|select|explain)\b", sql, re.I):
        raise SystemExit("Only SELECT / WITH / EXPLAIN statements are accepted here.")
    if a.explain:
        sql = "EXPLAIN QUERY PLAN " + sql

    t0 = time.time()
    try:
        res = pd.read_sql_query(sql, con)
    except Exception as e:  # sqlite3.OperationalError, pandas DatabaseError...
        raise SystemExit(f"SQL error: {e}")
    elapsed = time.time() - t0

    with pd.option_context(
        "display.width", 200, "display.max_columns", 50, "display.max_colwidth", 60
    ):
        print(res.head(a.limit).to_string(index=False))
    shown = min(len(res), a.limit)
    print(f"\n-- {len(res):,} rows ({shown:,} shown) in {elapsed:.2f}s", end="")
    print(
        f"  [SLOW: over {SLOW_SECONDS}s, check joins and filters]"
        if elapsed > SLOW_SECONDS
        else ""
    )
    if a.out:
        out = Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        res.to_parquet(out, index=False) if out.suffix == ".parquet" else res.to_csv(
            out, index=False
        )
        print(f"Saved: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

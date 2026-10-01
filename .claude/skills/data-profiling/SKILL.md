---
name: data-profiling
description: Profile a tabular dataset before analysing it — schema, nulls, sentinel values, duplicates, identifier columns, outliers, and time and entity structure — with a script that prints findings and saves JSON. Use as the first step of any data analysis, and whenever a file's quality is in doubt.
---

Look at the data before you analyse it. This is the mechanical half of "understand the data":
the script sees structure and quality problems; it cannot see what a column *means*.

## Run it

```bash
python3 .claude/skills/data-profiling/scripts/profile_data.py --data <path> \
    [--time <col>] [--group <col>] [--out analysis/<id>/profile.json]
```

Formats: csv, tsv, parquet, feather, json, jsonl. For a very large file add `--nrows N` (first N
rows, cheap but possibly biased) or `--sample N` (random rows after loading, `--seed` fixed).
`--max-cols` limits the per-column table on wide data; the JSON always has everything.

The text report is what you read; `--out` keeps the JSON for later comparison (a change in the data
between two dates is a diff of two profiles).

## What it reports

Per column: kind (numeric, categorical, text, boolean, datetime, dates stored as strings), null %,
unique count, range or top values, skew and IQR-outlier share. Then findings:

| Finding | Why it matters |
|---|---|
| Exact duplicate rows | Inflate counts and totals |
| Columns over 50% null | Real absence and failed capture are not imputed alike |
| Sentinel / placeholder values (`-999`, `9999`, `"unknown"`, `"N/A"`) | Nulls in disguise that corrupt means and totals |
| Identifier-like columns | Keys, not measures: leave them out of statistics |
| Numbers or dates stored as text | Silent wrong sorting and arithmetic |
| Constant columns, heavy skew, many outliers | Wasted or distorting inputs |
| With `--group`: rows per group | More than ~1.2 means rows are not independent |
| With `--time`: range, empty months | Gaps usually mean a change in the source system |

## Reading it

- **Every finding is a symptom, not a verdict.** A sentinel share of 20% may be a real code for
  "not measured"; ask what it means before recoding it.
- No findings does not mean a clean dataset. The checks cannot see domain problems (a column that
  means something other than its name says, a total that quietly leaves out a segment). Say that
  in your report.
- Reconcile before you trust: row count against the source, a key total against a number someone
  already knows.

## Rules

Read-only on the data. Derived files go under `analysis/<id>/`, never next to the source.

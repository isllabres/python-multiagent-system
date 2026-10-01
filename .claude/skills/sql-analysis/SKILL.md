---
name: sql-analysis
description: Answer questions over local data files with SQL — joins, aggregations, cohorts, funnels, window functions — using a script that loads each file as a table in a throw-away SQLite database and prints a bounded result. Use for aggregation-heavy questions and anything that reads naturally as SQL.
---

Each file becomes a table in an in-memory database. The sources are never modified and nothing
persists, so experimenting is safe.

## Run it

```bash
Q=.claude/skills/sql-analysis/scripts/sql_query.py
python3 $Q --table orders=data/orders.csv --table users=data/users.parquet --schema
python3 $Q --table orders=data/orders.csv --query "select ..." [--limit 50] [--out result.csv]
python3 $Q --table orders=data/orders.csv --file experiments/<id>/scripts/q1.sql
python3 $Q --table orders=data/orders.csv --query "select ..." --explain
```

`--sample N` loads a random sample of each table (seed echoed) for a quick look at very large
files. Only `SELECT`, `WITH` and `EXPLAIN` are accepted. The output shows at most `--limit` rows
plus the total row count and elapsed time (it flags anything over 30 s). `--out` saves the whole
result (`.csv` or `.parquet`). Keep queries worth re-running in `experiments/<id>/scripts/*.sql`.

## Dialect: SQLite

- Window functions, CTEs, `rank() over`, `lag()`, running sums with `rows between …` all work.
- There is no `DATE_TRUNC`: bucket with `strftime('%Y-%m', col)` (or `'%Y-%W'`, `'%Y'`). Dates are
  ISO text, so they compare and sort correctly.
- Division of integers truncates: use `1.0 * a / b`.
- Booleans are 0/1, so `avg(flag)` is a rate.

## Habits that prevent wrong answers

1. **Reconcile.** Count rows and total the key measure before and after each join. A join that
   changes the row count is a fan-out, and every sum after it is wrong.
2. **One grain per query.** Say in a comment what one row of the result is.
3. **CTEs over nested subqueries**, one idea per CTE, named for what it holds.
4. **Filter early**, name columns explicitly (no `select *` on wide tables), and put the null
   policy in the query (`coalesce`, `is not null`), never assume it.
5. **Sanity-check the result against a number you already know** before you build narrative on it.

## Patterns (tested)

```sql
-- Cohort retention: who came back after their first month
with first_seen as (
  select customer_id, min(strftime('%Y-%m', signup_date)) as cohort from t group by customer_id),
activity as (select distinct customer_id, strftime('%Y-%m', signup_date) as month from t)
select f.cohort, count(distinct f.customer_id) as cohort_size,
       count(distinct case when a.month > f.cohort then a.customer_id end) as returned_later
from first_seen f join activity a using (customer_id) group by f.cohort order by f.cohort;

-- Month over month and running total
with monthly as (select strftime('%Y-%m', d) as month, sum(x) as revenue from t group by 1)
select month, revenue,
       revenue - lag(revenue) over (order by month) as change_vs_prev,
       sum(revenue) over (order by month rows between unbounded preceding and current row) as running
from monthly order by month;

-- Funnel step and share of total in one pass
select segment, count(*) as n,
       1.0 * sum(case when reached_step then 1 else 0 end) / count(*) as step_rate,
       100.0 * count(*) / sum(count(*)) over () as share_of_total
from t group by segment order by n desc;
```

For statistics (tests, intervals) and charts, hand the result to `statistical-analysis` and
`analysis-report`: SQL is for shaping the data, not for inference.

## Rules

Do not query a test partition or an eval golden set's test split.

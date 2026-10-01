---
name: analysis-report
description: Turn an analysis into a narrative, self-contained HTML report with Plotly charts — lead finding first, short paragraphs with concrete numbers between charts, closing recommendations. Use whenever findings need to be shared, or when three or more charts are needed to tell the story.
---

A report is an argument, not a dump. The reader should know the answer after one paragraph and be
able to check it in the charts.

## Shape

1. **Summary box**: the single most actionable finding, with its number.
2. **Sections**, each: a heading that states the point, two or three sentences of interpretation
   with concrete numbers, then the chart that proves it.
3. **Recommendations**: specific, ordered, each tied to evidence. Say what you did not check.

Style: professional and precise. Let the data speak through numbers ("churn is 21.6% in the north
against 20.6% in the west"), not adjectives. Lead with what matters most, not with method.

## Build it

Write a script (`experiments/<id>/scripts/report.py`), run it with `python3`, save the output under
`experiments/<id>/`:

```python
import sys; sys.path.insert(0, ".claude/skills/analysis-report/scripts")
from report_lib import Report, PALETTE
import plotly.graph_objects as go, pandas as pd

df = pd.read_csv("data/orders.csv")            # sample big tables: nrows= or .sample(random_state=0)
r = Report("Revenue by region", subtitle="Q3, 12,400 orders", footer="Source: orders.csv · seed 0")
r.summary("North drives 41% of revenue but converts 3 points below the mean.")
r.section("Where the revenue comes from")
r.text("North leads with 64.8k, 12% above west; the gap is volume, not price.")
fig = go.Figure(go.Bar(x=regions, y=revenue, marker_color=PALETTE[0]))
fig.update_layout(title="Revenue by region", yaxis_title="Revenue (EUR)")
r.figure(fig, caption="Sum of order value, complete quarter")
r.table(summary_df, caption="Per-region detail")
r.recommendations(["Test a north-specific offer (expected +2 pts, see section 2).", "..."])
r.save("experiments/revenue/report.html")      # prints: Saved: experiments/revenue/report.html
```

`Report` applies the `simple_white` template and a colour-blind-safe palette to every figure, loads
Plotly once in `<head>`, inlines the CSS and escapes all text (only `**bold**` and `` `code` `` are
allowed). `save(offline=True)` embeds Plotly (about 4.5 MB more) so the file opens with no network.
It warns when the summary or the recommendations are missing.

## Charts

| To show | Use | Avoid |
|---|---|---|
| Comparison across categories | Sorted horizontal or vertical bars | Pie charts, 3D |
| Change over time | Line (bars if few periods) | Dual axes |
| Distribution | Histogram or box plot | Bars of a mean alone |
| Relationship of two numbers | Scatter (opacity for overlap), trendline only if it earns it | Correlation without the scatter |
| Part of a whole | Stacked bar or a table | More than five slices |

- Each chart is its own `go.Figure()` with a title that states the point, labelled axes with units.
- Bars start at zero. Sort categories by value unless they have a natural order.
- Set `marker_color` explicitly when colour carries meaning; otherwise use the palette in order.
- Annotate the one thing the reader must see; cut everything else (gridlines, legends for one series).
- Sample or aggregate before plotting large data: do not put 500k points in a browser.

## Before you save

- The key numbers reconcile with the source (row counts, totals).
- Every claim of a difference has an interval or is worded as descriptive, not inferential.
- Limitations are stated: sample, period, what was not checked.
- Then confirm the output path in your reply ("Saved: …") and give the finding in one line.

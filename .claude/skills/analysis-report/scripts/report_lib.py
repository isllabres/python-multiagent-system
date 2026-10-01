#!/usr/bin/env python3
"""Build a narrative, self-contained HTML report with Plotly charts.

Import it from your analysis script:

    import sys; sys.path.insert(0, ".claude/skills/analysis-report/scripts")
    from report_lib import Report, PALETTE
    import plotly.graph_objects as go

    r = Report("Revenue by region", subtitle="Q3 sales, 12,400 orders")
    r.summary("Lead with the most actionable finding, with its number.")
    r.section("Where the revenue comes from")
    r.text("Two or three sentences that interpret the chart below, with concrete numbers.")
    fig = go.Figure(go.Bar(x=regions, y=revenue, marker_color=PALETTE[0]))
    fig.update_layout(title="Revenue by region", yaxis_title="Revenue (EUR)")
    r.figure(fig, caption="Source: orders.csv, complete quarter")
    r.recommendations(["Do X because Y (evidence).", "Do Z."])
    r.save("analysis/sales/report.html")           # prints "Saved: analysis/sales/report.html"

Design rules baked in: each chart is its own figure, drawn with the `simple_white` template and a
colour-blind-safe palette; Plotly is loaded ONCE in <head> (from the CDN by default; save(offline=True)
embeds it so the file works with no network, at ~4.5 MB more); inline CSS; every text is escaped.
"""

import html
import re
import sys
from pathlib import Path

# Okabe-Ito: distinguishable under the common forms of colour blindness.
PALETTE = [
    "#0072B2",
    "#D55E00",
    "#009E73",
    "#E69F00",
    "#56B4E9",
    "#CC79A7",
    "#F0E442",
    "#000000",
]
PLOTLY_CDN = "https://cdn.plot.ly/plotly-2.35.2.min.js"

CSS = """
:root{--ink:#1f2933;--muted:#5f6b7a;--line:#e3e8ee;--accent:#0072B2;--bg:#ffffff;--soft:#f5f8fb}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 -apple-system,BlinkMacSystemFont,
"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
main{max-width:920px;margin:0 auto;padding:2.5rem 1.25rem 4rem}
h1{font-size:1.9rem;line-height:1.2;margin:0 0 .3rem}
h2{font-size:1.25rem;margin:2.6rem 0 .6rem;padding-top:.4rem;border-top:1px solid var(--line)}
.subtitle{color:var(--muted);margin:0 0 1.6rem}
p{margin:.6rem 0 1rem}
.summary{background:var(--soft);border-left:4px solid var(--accent);padding:1rem 1.2rem;
border-radius:4px;margin:1.2rem 0 1.6rem;font-size:1.05rem}
.figure{margin:1.2rem 0 1.6rem}
.caption{color:var(--muted);font-size:.85rem;margin:.2rem 0 0}
.recs{background:var(--soft);border-radius:6px;padding:.4rem 1.4rem 1rem;margin-top:2rem}
.recs h2{border:0;margin-top:1rem}
table.tbl{border-collapse:collapse;width:100%;font-size:.9rem;margin:.6rem 0}
table.tbl th,table.tbl td{padding:.35rem .6rem;border-bottom:1px solid var(--line);text-align:right}
table.tbl th:first-child,table.tbl td:first-child{text-align:left}
table.tbl th{background:var(--soft)}
.tablewrap{overflow-x:auto}
footer{color:var(--muted);font-size:.8rem;margin-top:3rem;border-top:1px solid var(--line);padding-top:1rem}
"""


def _esc(text):
    """Escape, then allow **bold** and `code` as the only markup."""
    s = html.escape(str(text))
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", s)


class Report:
    def __init__(self, title, subtitle=None, footer=None):
        self.title, self.subtitle, self.footer = title, subtitle, footer
        self._parts, self._n_figures = [], 0
        self._has_summary = self._has_recs = False

    def summary(self, text):
        """The single most actionable finding, first thing the reader sees."""
        self._has_summary = True
        self._parts.insert(0, f'<div class="summary">{_esc(text)}</div>')

    def section(self, title):
        self._parts.append(f"<h2>{_esc(title)}</h2>")

    def text(self, text):
        self._parts.append(f"<p>{_esc(text)}</p>")

    def figure(self, fig, caption=None, height=420):
        """Add a Plotly figure: simple_white template, palette, no bundled plotly.js."""
        fig.update_layout(
            template="simple_white",
            colorway=PALETTE,
            height=height,
            margin=dict(l=60, r=20, t=60, b=50),
            font=dict(size=13),
        )
        body = fig.to_html(include_plotlyjs=False, full_html=False)
        cap = f'<p class="caption">{_esc(caption)}</p>' if caption else ""
        self._parts.append(f'<div class="figure">{body}{cap}</div>')
        self._n_figures += 1

    def table(self, df, caption=None, max_rows=30, float_format="{:,.2f}".format):
        shown = df.head(max_rows)
        body = shown.to_html(
            classes="tbl", border=0, index=False, float_format=float_format, escape=True
        )
        more = f" (first {max_rows} of {len(df)} rows)" if len(df) > max_rows else ""
        cap = (
            f'<p class="caption">{_esc((caption or "") + more)}</p>'
            if (caption or more)
            else ""
        )
        self._parts.append(f'<div class="tablewrap">{body}</div>{cap}')

    def recommendations(self, items, title="Recommendations"):
        self._has_recs = True
        lis = "".join(f"<li>{_esc(i)}</li>" for i in items)
        self._parts.append(
            f'<div class="recs"><h2>{_esc(title)}</h2><ol>{lis}</ol></div>'
        )

    def save(self, path, offline=False):
        if not self._has_summary:
            print(
                "Warning: no summary(): lead with the most actionable finding.",
                file=sys.stderr,
            )
        if not self._has_recs:
            print(
                "Warning: no recommendations(): a report should end with what to do.",
                file=sys.stderr,
            )
        if offline:
            from plotly.offline import get_plotlyjs

            script = f"<script>{get_plotlyjs()}</script>"
        else:
            script = f'<script src="{PLOTLY_CDN}" charset="utf-8"></script>'
        sub = f'<p class="subtitle">{_esc(self.subtitle)}</p>' if self.subtitle else ""
        foot = f"<footer>{_esc(self.footer)}</footer>" if self.footer else ""
        doc = (
            f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{html.escape(self.title)}</title>{script}<style>{CSS}</style></head><body>"
            f"<main><h1>{_esc(self.title)}</h1>{sub}{''.join(self._parts)}{foot}</main></body></html>"
        )
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(doc, encoding="utf-8")
        print(f"Saved: {out}")
        return out


if __name__ == "__main__":
    print(__doc__)

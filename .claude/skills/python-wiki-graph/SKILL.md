---
name: python-wiki-graph
description: Builds and queries a graph of The Python Wiki (wiki.python.org, an archive) so the validator can survey its sections, choose the pages that bear on the code under review, and read them in depth. Runs on the validator's first call as a one-off bounded crawl, cached for months. Use it to back a Python finding with a documented page, never to decide the finding.
---

A map of a **historical** wiki, so you can find what it says about the code in front of you.
`python-standards` is your rubric; this skill supplies references. A page from the wiki can support
a finding. It never makes one.

## First call

Before you read a line of the diff, run:

```bash
python3 .claude/skills/python-wiki-graph/scripts/wiki_graph.py ensure
```

- **The first time**, it builds the graph: one bounded crawl of about 35 to 60 requests, at least
  one second apart, roughly a minute. Give the Bash call a timeout of at least 300000 ms. The
  result is cached in `.claude/cache/python-wiki/` (git-ignored by itself) for 180 days.
- **Every later call**, it reads the cache and answers at once, offline.
- It prints the status and the titles of the FrontPage sections.
- If it prints `unavailable`, continue with `python-standards` alone and say so in your report.
  This skill never blocks a validation.

## Survey, then choose

1. **`map`** lists every FrontPage section with its pages, and the largest page families. The
   FrontPage sections are mostly beginner, community and software listings; the material about
   code quality is usually deeper in the 3,400-page catalogue, so `search` does most of the work.
2. From the diff, list the Python topics it touches (exceptions, threads or asyncio, file and
   encoding handling, serialisation, decorators and generators, logging, imports and packaging,
   performance, memory, style, testing, security).
3. For each topic: **`search <words>`**. Prefer kinds `page` and `category`; the ranking already
   demotes `question`, `event` and `idea` pages. Then **`neighbors <page>`** for its subpages.
4. **Decide what to read deeper.** Take pages that answer a doubt the diff actually raises, not
   pages that merely share a word. Read at most **five pages** per validation: `read <page>
   --outline` first, then `read <page> --section "<heading>"`, capped at 6,000 characters.

Starting points seen in the index (confirm with `search`): `HandlingExceptions`, `Concurrency`,
`GIL`, `PythonSpeed` and its subpages `PerformanceTips` and `Profiling`, `Unicode`,
`UnicodeEncoding`, `Pickle`, `Security`, `Decorators`, `Generators`, `AppLogging`, `PythonStyle`,
`PEP8`, `MemoryUsageProfiler`.

## Using what you read

- **It is an archive.** Pages are frozen as of archival and much of the material predates Python 3
  (`xrange`, the `print` statement, old-style classes, the `string` module). Some pages say their
  own accuracy is disputed. Check version references before you rely on anything.
- **The current docs and `python-standards` win.** If a page conflicts with them, drop it and say
  so. Never cite a page for a practice the standard rejects.
- **Cite what you used**, in the report's "References consulted": the page URL, the section, and
  what you took from it. Only pages you read.
- A finding must stand on its own evidence (the code, the consequence). A reference is a support,
  and a finding with none is fine.

## Commands

All take `--cache-dir` (default `.claude/cache/python-wiki`, or `$PYTHON_WIKI_CACHE`).

| Command | Does |
|---|---|
| `ensure [--offline]` | Build if missing or older than 180 days, then print status. Never fails the caller |
| `map [--section S] [--families N]` | The FrontPage sections and the largest page families |
| `search <terms...> [--top N] [--kind K] [--fetched]` | Rank pages by title, headings and text |
| `neighbors <page> [--limit N]` | Parent, subpages, links to and from a page |
| `read <page> [--outline] [--section H] [--max-chars N] [--offset N]` | Outline, one section, or text; fetched once if not cached |
| `export [--format dot\|json] [--out F]` | The graph, for a human to look at |
| `build` | Force a rebuild. You should never need it |

`<page>` can be a title (`PythonSpeed/PerformanceTips`), a file stem (`PythonSpeed(2f)PerformanceTips`)
or a URL. A miss suggests close matches.

## Be gentle with the wiki

Its own banner says it is being retired because automated crawlers overload it. So:
one request at a time, at least one second apart (the delay holds across processes), a hard cap of
80 requests per run, everything cached, and a page read is fetched once. Do not loop `read` over
many pages, do not lower `--delay` for the real site, and do not run `build` unless the cache is
broken: `ensure` already handles staleness.

## Files

The graph is `graph.json` (pages as nodes, with `section`, `link`, `sub` and `contains` edges) and
each fetched page is a small JSON under `pages/`. Standard library only. Offline tests, against a
local mock of the wiki:

```bash
uv run pytest .claude/skills/python-wiki-graph/tests -q
```

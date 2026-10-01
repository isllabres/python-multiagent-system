# dev-lab

A multi-agent system for Python development, for Claude Code. It installs as a layer on top of a new or
existing project, adding the roles and skills that coordinate the work. 

Six roles, two convergence loops, red before green.

## Install

```bash
cp -r dev-lab/.claude dev-lab/CLAUDE.md ~/code/my-project/   # onto your existing project
cd ~/code/my-project

uv add --dev pytest ruff mypy
gh auth status                          # mandatory: no gh, no flow

claude --agent manager
> /grill-me "add retry with backoff to the HTTP client"
```

The analysis skills use `pandas`, `numpy`, `scipy` and `plotly`; add them with `uv add --dev` the
first time you ask the `analyst` for something.

## Agents and skills — the distinction

An **agent** (`.claude/agents/`) is an identity: its own system prompt, a model, a set of tools, invoked by delegation and with its own context, with no memory of the main conversation beyond what is explicitly passed to it.

### The six agents

| Role | Model | Does |
|---|---|---|
| `manager` | opus | The spec creator and the main agent: interrogates until it converges, writes the issue, runs the other roles and keeps the round tally. Does not review code |
| `analyst` | sonnet | Any data analysis: explore, query, statistics, charts, reports |
| `tester` | sonnet | Owns the tests and evals: writes each criterion's red check from the spec and proves it fails for the right reason, then runs the whole suite and guards against tests bent to pass. Never writes production code |
| `developer` | sonnet | Python implementation expert: makes the red green, one criterion at a time, exactly as the spec says. Never touches a test |
| `validator` | opus | Judges the whole change as Python (semantics, structure, tooling; consults The Python Wiki on its first call) and gives feedback to `developer`. Read-only: never runs the suite |
| `wiki-generator` | sonnet | Keeps the wiki in step with the code, briefly: one changelog line per commit, and a page edited only when behaviour or architecture changed. Called by `manager` after every commit |


A **skill** (`.claude/skills/`) is a named procedure inserted into the **current** conversation, with `$ARGUMENTS` substituted. It is not an identity: it runs in your session, and its body can instruct "delegate to `tester`, then to `developer`" — the skill orchestrates, the agent executes. Skills come in two kinds: workflows you launch yourself with `/name`, and methodology that another role invokes when it needs it.

### The workflow skills, and the three points where it needs you

| Skill | What it does | Does it need you? |
|---|---|---|
| `/grill-me` | Interrogates in depth, one question at a time, with a recommendation and prior exploration. Standalone or inside `/create-issue` | Yes, it is a conversation |
| `/create-issue` | Light discovery, data facts, invokes the skills, files the issue | **Yes** — you approve before anything is created |
| `/implement-issue` | Per criterion (red, green) → whole change (suite, Python review) → **local PR**, in one go, with the wiki updated after every commit | **Yes** — you confirm the local PR before it touches GitHub |
| `/review-issue` | Detects whether a `pending` issue is still valid | Confirm before refreshing |
| `/update-issue` | Applies a requested change by re-running `/create-issue` | Confirm labels |

### The methodology skills

Invoked by `manager` during `/create-issue`, not typed by you.

| Skill | Produces |
|---|---|
| `define-tests` | The TDD spec: behaviours, test cases, doubles, red-green-refactor sequence |
| `define-evals` | The EDD spec for behaviour judged over a set of cases against a bar: performance budgets, output quality, non-deterministic behaviour |

### The analysis skills

Carried by `analyst`, which is called for any data analysis. Each bundles a tested script under
`scripts/`.

| Skill | Does |
|---|---|
| `data-profiling` | Profiles a file: types, nulls, sentinels, duplicates, identifier columns, time and entity structure |
| `statistical-analysis` | Bootstrap CIs, group comparisons with effect sizes, proportions, correlations, sample-size calculations |
| `sql-analysis` | SQL over local files (joins, cohorts, funnels, window functions) with bounded output |
| `analysis-report` | Narrative HTML report with Plotly charts: finding first, recommendations last |

### The Python skills

| Skill | Does |
|---|---|
| `python-standards` | One rubric for good Python here: structure, typing, language traps, errors and resources, idioms, pandas/numpy code, performance, security, tooling. `developer` and `tester` write against it and `validator` checks against it |
| `commit-messages` | Short, descriptive commits with the `red(#n-ACx):` / `green(#n-ACx):` prefix. `tester` makes the red ones, `developer` the green ones and `wiki-generator` the wiki ones |
| `python-wiki-graph` | Builds a graph of The Python Wiki (an archive) on the validator's first call, so it can survey the sections, choose the pages that bear on the code it is validating, and read them in depth. One bounded, cached crawl; the wiki is asked for as little as possible |

## What you will find in the repository

```
CLAUDE.md                 The contract. The only document that has to be read in full.
.claude/
  agents/*.md             The six roles: who does the work.
  skills/*/SKILL.md       The fourteen skills: five workflows you type (/create-issue, /grill-me, ...),
                          two methodology skills that manager invokes, four analysis skills that
                          analyst carries, two shared standards (Python, and commit messages),
                          and the Python Wiki graph that validator runs first.
specs/                    The executable shadow of each issue.
analysis/                 The analyst's scripts, profiles and reports.
evals/                    The cases an eval is judged over.
wiki/                     Native GitHub Wiki: Home, _Sidebar, six fixed pages, raw/, log.md
                          (one changelog line per commit).
```

Folders such as `src/`, `tests/` **are deliberately not in this list** — they are your project, not the multi-agent layer.

## Red before green

There is no hook for it: it is a role. `tester` writes each criterion's test or eval and runs it
before `developer` starts, and only commits it, as `red(#n-ACx):`, if it fails for the right reason
(the behaviour is missing, not a typo in the test). `developer` then makes it pass and commits
`green(#n-ACx):`, without ever editing a test. Afterwards `tester` checks the history: no `green`
commit may touch a test, an eval runner or a case file, and no assertion may have been loosened,
skipped or deleted.

## Two loops, one round budget

```
per criterion:  tester (red) → manager (matches the criterion?) → developer (green) ↔ tester
whole change:   tester (suite), then validator (Python) ↔ developer, or tester for tests
                a fix that touches code goes back through tester
```

`manager` keeps one tally per criterion across **both** loops. Default cap: 3 rounds; the fourth
stops and reports.

## Code quality: Ruff covers Black + Flake8 + isort

`ruff format` is a drop-in replacement for Black (same style, same output in practice).
`ruff check` includes the equivalent of the Flake8 rules, and with the `I` set enabled, isort's.
The three tools are not added separately: besides being redundant work, Black and Ruff can
disagree on edge formatting decisions and end up fighting inside the same hook. `mypy` runs and is
reported but does not block by default — it is optional.

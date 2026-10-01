# ds-lite

A multi-agent system for data science, for Claude Code. It installs as a layer on top of a new or
existing project, adding the roles, skills and checks that coordinate the work. 

Six roles, two convergence loops, ten checks, DVC by default for the data.

## Install

```bash
cp -r ds-lite/. ~/code/my-project/    # onto your existing structure, without overwriting it
cd ~/code/my-project

uv add --dev pytest ruff mypy pre-commit nbstripout dvc
pre-commit install
dvc init && dvc remote add -d storage <your-remote>   # S3, GCS, a disk — whichever you use

gh auth status                          # mandatory: no gh, no flow
python3 setup-repo.py --new your-org/my-project --private
# or, if the repository already exists:  python3 setup-repo.py --existing

claude --agent ds-manager
> /grill-me "I want to reduce customer churn"
```

## Agents and skills — the distinction

An **agent** (`.claude/agents/`) is an identity: its own system prompt, a model, a set of tools, invoked by delegation and with its own context, with no memory of the main conversation beyond what is explicitly passed to it.

### The six agents

| Role | Model | Does |
|---|---|---|
| `ds-manager` | opus | Interrogates until it converges, writes the issue, methodology in review and fixes |
| `analyst` | sonnet | Any data analysis (explore, query, statistics, charts, reports) and the data gate: leakage, performance ceiling, split strategy |
| `ds-developer` | sonnet | Python implementation expert: red, then green, one criterion at a time, exactly as the spec says. Calls `wiki-generator` at the end |
| `reviewer` | opus | Code correctness, not methodology. Read-only |
| `validator` | opus | Validates the whole change as Python (semantics, structure, tooling; consults The Python Wiki on its first call), then runs test/eval/metric once converged; leads the fix; the only one who looks at any one-look resource |
| `wiki-generator` | sonnet | Compiles what was learned into the wiki, once per issue |


A **skill** (`.claude/skills/`) is a named procedure inserted into the **current** conversation, with `$ARGUMENTS` substituted. It is not an identity: it runs in your session, and its body can instruct "delegate to `ds-developer`, then to `reviewer`" — the skill orchestrates, the agent executes. Skills come in two kinds: workflows you launch yourself with `/name`, and methodology that another role invokes when it needs it.

### The workflow skills, and the three points where it needs you

| Skill | What it does | Does it need you? |
|---|---|---|
| `/grill-me` | Interrogates in depth, one question at a time, with a recommendation and prior exploration. Standalone or inside `/create-issue` | Yes, it is a conversation |
| `/create-issue` | Light discovery, data gate, invokes the skills, files the issue | **Yes** — you approve before anything is created |
| `/implement-issue` | Per criterion → integration → single looks → wiki → **local PR**, in one go | **Yes** — you confirm the local PR before it touches GitHub |
| `/review-issue` | Detects whether a `pending` issue is still valid | Confirm before refreshing |
| `/update-issue` | Applies a requested change by re-running `/create-issue` | Confirm labels |

### The methodology skills

Invoked by `ds-manager` during `/create-issue`, not typed by you.

| Skill | Produces |
|---|---|
| `define-tests` | The TDD spec: behaviours, test cases, doubles, red-green-refactor sequence |
| `define-evals` | The EDD spec for LLM/agent behaviour: failure hypotheses, binary evals, synthetic data |
| `define-metrics` | The metric spec for a trained model: primary metric with CI, baselines, split, stopping rule |

### The analysis skills

Carried by `analyst`, which is called for any data analysis. Each bundles a tested script under
`scripts/`.

| Skill | Does |
|---|---|
| `data-profiling` | Profiles a file: types, nulls, sentinels, duplicates, identifier columns, target/time/group structure |
| `data-audit` | Target-aware audit: leakage signals, split strategy, duplicates, diagnostic probe, plausible performance ceiling |
| `statistical-analysis` | Bootstrap CIs, group comparisons with effect sizes, proportions, correlations, sample-size calculations |
| `sql-analysis` | SQL over local files (joins, cohorts, funnels, window functions) with bounded output |
| `analysis-report` | Narrative HTML report with Plotly charts: finding first, recommendations last |

### The Python skills

| Skill | Does |
|---|---|
| `python-standards` | One rubric for good Python here: structure, typing, language traps, errors and resources, idioms, pandas/numpy/scikit-learn code, performance, security, tooling. `ds-developer` writes against it and `validator` checks against it |
| `python-wiki-graph` | Builds a graph of The Python Wiki (an archive) on the validator's first call, so it can survey the sections, choose the pages that bear on the code it is validating, and read them in depth. One bounded, cached crawl; the wiki is asked for as little as possible |

## What you will find in the repository

```
CLAUDE.md                 The contract. The only document that has to be read in full.
setup-repo.py             Labels, branch protection on GitHub.
.claude/
  agents/*.md             The six roles: who does the work.
  skills/*/SKILL.md       The fifteen skills: five workflows you type (/create-issue, /grill-me, ...),
                          three methodology skills that ds-manager invokes, five analysis skills
                          that analyst carries, the Python standard that ds-developer and
                          validator share, and the Python Wiki graph that validator runs first.
  settings.json           The hook that enforces TDD's "red before green".
gates/                    The ten checks — they run on their own, needing no agent.
templates/                ACCEPTANCE.yaml · wiki-log.md · wiki/ (fixed hierarchy of 8 pages)
wiki/                     Native GitHub Wiki: Home, _Sidebar, six fixed pages, raw/, log.md.
specs/                    The executable shadow of each issue.
experiments/              Data audits and evaluation results.
evals/                    Golden sets and the ledger of single looks.
```

Folders such as `data/`, `src/`, `tests/`, `notebooks/` **are deliberately not in this list** — they are your project, not the multi-agent layer.

Three environment variables adjust where the gates look if your convention differs from `src/`, `tests/`, `data/raw/`: `DS_SRC_DIRS`, `DS_SRC_ROOT`, `DS_IMMUTABLE_DIRS`, documented in `CLAUDE.md`.


## The ten gates

Python executables with an exit code. `check.py` runs them all; it is what CI runs.

| Gate | Detects |
|---|---|
| `py_audit` | Leakage by AST, missing seeds, `assert` on metrics in `tests/` |
| `eda_report` | Targeted report: univariate AUC, groups, time, nulls, sentinels |
| `traceability` | Criteria with no verification, orphan tests |
| `git_audit` | Raw data, secrets, large binaries, red→green order, `EVAL.md` with no commit or no issue |
| `issue_sync` | Drift between GitHub issues and `ACCEPTANCE.yaml` |
| `holdout_ledger` | Counts the looks at any one-look resource and detects whether it changed |
| `convergence` | Fix rounds per criterion, accumulated across the two loops |
| `wiki_lint` | Any of the six fixed pages missing, incomplete `_Sidebar`, broken links, unresolved contradictions |
| `tdd_guard` | A new test that passes first time — registered as a hook in `.claude/settings.json` |
| `check` | Everything above + ruff + mypy (optional) + pytest |

## TDD Guard Hook

`CLAUDE.md` and several roles state in their prompt that "a new test is watched failing before implementing". We enforce this in `.claude/settings.json`, which turns it into mechanics: a `PostToolUse` hook runs `gates/tdd_guard.py` after every `Write`/`Edit`, and if the file is a new test (untracked by git) that passes first time, it blocks with exit code 2 and the message goes back to the agent. 

## Two loops, one round budget

```
per criterion:  ds-developer ↔ {reviewer, ds-manager}
integration:    validator ↔ ds-developer (+ ds-manager/reviewer if it touches code)
```

`gates/convergence.py` counts the rounds of **both** loops on the same counter per criterion.
Default cap: 3.

**No one-look resource is touched in either of the two loops.** There are two classes: the `test`
partition of a model metric, and the `dev`/`test` of an eval golden set. Both are recorded in the
same `gates/holdout_ledger.py`, with independent look budgets — tested: one resource can be on its
second look while the other is still on its first.

## Data: DVC by default

```bash
dvc init
dvc remote add -d storage s3://my-bucket/data    # or gs://, or a mounted disk, whatever you use
dvc add data/raw
git add data/raw.dvc .gitignore && git commit -m "data: version data/raw with DVC"
```

The pointer (small, carrying the hash) goes to git; the data go to the remote. `dvc install
--use-pre-commit-tool` generates the right hooks in `.pre-commit-config.yaml` at the pinned
version — the block this repository already includes is an initial reference, regenerate it that
way as soon as you have DVC installed so you do not drag an outdated version along by hand.

This is orthogonal to the looks ledger: DVC versions the whole dataset, continuously; the ledger
counts looks at one resource inside one issue. Both hash, for different reasons — there is no need
to choose one over the other.

## Code quality: Ruff covers Black + Flake8 + isort

`ruff format` is a drop-in replacement for Black (same style, same output in practice).
`ruff check` includes the equivalent of the Flake8 rules, and with the `I` set enabled, isort's.
The three tools are not added separately: besides being redundant work, Black and Ruff can
disagree on edge formatting decisions and end up fighting inside the same pre-commit hook. `mypy`
runs and is reported but does not block `check.py` by default — it is optional; to make it
blocking, a single boolean in `gates/check.py`.

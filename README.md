# python-multiagent-system

A multi-agent system for Python development, for [Claude Code](https://claude.com/claude-code). It
installs as a layer on top of a new or existing project and turns a GitHub issue into a pull
request through five specialised roles. Each role has one job, so the one that writes the test is
never the one that writes the code.

```
idea ── /create-issue ──▶ issue + spec ── /implement-issue ──▶ local PR ──▶ GitHub PR ──▶ merge
          you approve                        you confirm                         you review
```

Three points need a person. Everything between them runs without asking.

## Install into a new project

The layer is a set of files you copy into your project. Your project keeps its own git remote:
nothing here points back to this repository, and `gh` reads the repository from your project's
remote.

Requirements: Claude Code, `git`, `gh` (authenticated: no `gh`, no flow), `uv` and Python 3.11+.

```bash
# 1. Get the layer, once
git clone https://github.com/isllabres/python-multiagent-system.git ~/code/python-multiagent-system

# 2. Export a clean snapshot of its main branch into your project (tracked files only)
git -C ~/code/python-multiagent-system archive origin/main .claude CLAUDE.md | tar -x -C ~/code/my-project

# 3. Tooling, in your project
cd ~/code/my-project
uv add --dev pytest ruff mypy
gh auth status

# 4. Commit the layer to your project's own repository, on its own branch
git switch -c add-multiagent-layer
git add .claude CLAUDE.md
git commit -m "Add the python-multiagent-system layer"
git push -u origin add-multiagent-layer

# 5. Start working
claude --agent manager
```

`git archive` is used instead of `cp -r` because it copies only tracked files, so no `.DS_Store` or
local cache comes along. `claude --agent manager` starts your session as the main agent; it
delegates to every other role.

### Which remote

Any GitHub repository: your own, another account or organisation, or GitHub Enterprise. `gh` must be
logged in to it: `gh auth switch` for another account, `gh auth login --hostname <host>` for
Enterprise. GitLab and Bitbucket are not supported, because the flow is built on GitHub issues and
pull requests.

### Before you start

- **Ruff lints the layer too.** Your `ruff check .` also covers the layer's scripts. Under a strict
  config (`select = ["ALL"]`) that is hundreds of findings, so exclude it. With ruff's default
  config the layer is clean, and pytest skips `.claude/` on its own.

  ```toml
  [tool.ruff]
  extend-exclude = [".claude"]
  ```

- **An existing `CLAUDE.md` is overwritten by step 2**, and so is any agent or skill of yours with
  the same name. If you have a `CLAUDE.md`, export only `.claude`, put ours beside yours under
  another name, and import it from yours:

  ```bash
  git -C ~/code/python-multiagent-system archive origin/main .claude | tar -x -C ~/code/my-project
  git -C ~/code/python-multiagent-system archive origin/main CLAUDE.md | tar -xO > ~/code/my-project/CLAUDE.multiagent.md
  ```

  then add the line `@CLAUDE.multiagent.md` to your `CLAUDE.md`. Claude Code imports files with
  `@path`, resolved relative to the file that mentions it.
- **The wiki starts empty.** `wiki-generator` creates `wiki/` on its first call, and `check_wiki.py`
  reports missing pages until then.
- **The first `validator` run needs the network.** It crawls The Python Wiki once (about a minute, at
  most 80 requests) and caches it for 180 days in `.claude/cache/`, which git-ignores itself.
- **Your layout is respected.** The layer never creates `src/` or `tests/`; it creates only its own
  output: `specs/`, `evals/` and `wiki/`.

### Use it

Inside the session, three commands take you from an idea to a pull request:

```
> /grill-me "add retry with backoff to the HTTP client"   # optional: stress-test a raw idea first
> /create-issue feature     # discovery, interrogation and specs; you approve, it files the issue
> /implement-issue 12       # red, green, checks, wiki; stops at a local PR for you to confirm
```

After you confirm, it pushes the branch and opens the PR on your remote. You review it on GitHub;
merging is accepting the result. The whole flow is described under *How a change flows*.

## The five roles

An **agent** (`.claude/agents/`) is an identity: its own prompt, model, tools and context. Each one
below owns one thing and never does the others'.

| Role | Model | Owns | Never |
|---|---|---|---|
| `manager` | opus | The spec and the session: interrogates until the idea converges, writes the issue, runs the other roles, keeps the round tally, confirms the red test matches the criterion, decides disputes over a test or the spec | Reviews the code `developer` writes, or writes or runs code, tests or evals |
| `tester` | sonnet | The tests and evals: writes each criterion's red check from the spec and proves it fails for the right reason, checks the green, guards against tests bent to pass, runs the whole suite | Edits production code |
| `developer` | sonnet | The implementation: makes the red green with the minimum idiomatic, typed Python, one criterion at a time | Writes, edits, skips or deletes a test |
| `validator` | opus | Python quality of the whole change (semantics, structure, ruff, mypy), with The Python Wiki as a reference, and the feedback to the owner of the code | Runs the suite, writes code (it is read-only) |
| `wiki-generator` | sonnet | The project wiki: one changelog line per commit and an entry when behaviour or architecture changed; surveys areas the wiki does not cover yet | Touches `README.md`, `CLAUDE.md` or `wiki/raw/` |

Only `manager` delegates to the other roles. `tester` and `validator` report back to it, and it hands
each finding to whoever owns the code and keeps the count.

## How a change flows

### 1. Create the issue: `/create-issue`

`manager` runs a light discovery, then `/grill-me` interrogates in depth, one question at a time with
its own recommendation, reading the project's wiki before it asks anything the code can answer. It
decides whether the work is one issue or an epic (you approve the split), has `define-tests` and
`define-evals` write the specs, and files the issue together with
`specs/<n>-<slug>/ACCEPTANCE.yaml`. **You approve before anything is
created.**

### 2. Implement it: `/implement-issue <n>`

- **Step 1.** Read the issue (a `pending` one suggests `/review-issue` first; an `epic` is not
  implemented directly).
- **Step 2.** Create the local branch `<n>-<slug>`. Nothing touches GitHub yet.
- **Step 3.** If the wiki has no entries for the area the issue touches, `wiki-generator` surveys it.
- **Step 4, per criterion.** `tester` writes the red check, `manager` confirms it matches the
  criterion, `developer` makes it green, `tester` checks the result.
- **Step 5, whole change.** `tester` runs the full suite and the evals, then `validator` reviews the
  diff as Python. Findings go back to `developer` (or to `tester`, for tests).
- **Step 6.** Check the wiki: every commit has its changelog line and no anchor points at missing code.
- **Step 7.** Run `ruff`, `mypy` and `pytest`, assemble the local PR, and **show it to you**: diff,
  commits, evidence, wiki.
- **Step 8.** Only with your confirmation: push and open the PR. It never merges, approves or
  closes the issue.

After every commit in steps 4 and 5, `manager` calls `wiki-generator`.

### 3. Merge: you

You review the PR on GitHub. Merging is accepting the result.

### Keeping issues honest

`/review-issue <n | --all>` checks whether a `pending` issue is still valid against today's code. `/update-issue <n> -- <change>` applies a change by re-running `/create-issue`.

## Two loops, one round budget

```
per criterion:  tester (red) → manager (matches the criterion?) → developer (green) ↔ tester
whole change:   tester (suite), then validator (Python) ↔ developer, or tester for tests
                a fix that touches code goes back through tester
```

`manager` keeps one tally per criterion across **both** loops, so a fix that moves from one loop to
the other does not reset it. The cap is 3 rounds; the fourth stops, comments the history on the
issue and waits for you.

## How a criterion is verified

Every acceptance criterion is verified one of two ways, according to the nature of the verdict:

| | Verdict | Example |
|---|---|---|
| **test** (TDD) | Binary, repeatable: same input, same output | "rejects a row with no identifier" |
| **eval** (EDD) | Binary per case, with a bar over the case set | "at least 95% of the fixtures render", "p95 latency under 200 ms" |

`ACCEPTANCE.yaml` is the issue's executable shadow, with exactly one verification per criterion:

```yaml
spec: 12-loader-validation
criteria:
  - id: AC1
    statement: "Rejects a row with no identifier"
    verification: test            # test | eval
    reference: tests/test_loader.py::test_rejects_row_without_id
    issue: 12
```

An `eval` criterion also carries a `threshold:` (the bar over its cases), and its `reference` is the
eval id under `evals/`.

## Red before green

There is no hook for it: it is a role. `tester` writes each criterion's test or eval and runs it
before `developer` starts, and commits it only if it fails for the right reason (the behaviour is
missing, not a typo in the test). `developer` then makes it pass without ever editing a test.
Afterwards `tester` checks the history: no `green` commit may touch a test, an eval runner or a case
file, and no assertion may have been loosened, skipped or deleted.

## The wiki is the code map

Every role reads the project wiki (`wiki/`) before it reads code. Its entries say what a part does
and why, point at the code with anchors (`src/loader.py:load_rows`) and at the tests that verify it,
and link to related entries. A role finds the entry, follows the anchor and reads that symbol, not
the whole module.

```
Home.md  _Sidebar.md  log.md  raw/
1.-Configuration-and-Environment.md   2.-Architecture.md   3.-Features-and-Behaviour.md
4.-Testing-and-Evaluation.md          5.-Decisions-and-Known-Issues.md   6.-Production-and-Monitoring.md
```

It is brief by rule: `log.md` gets exactly one line per commit; an entry is edited only when
behaviour or architecture changed, or when something it points at moved; at most two pages per
commit, five new lines at most, a page past 100 lines is condensed. A checker enforces this and fails
on anchors pointing at code that no longer exists:

```bash
python3 .claude/skills/project-wiki/scripts/check_wiki.py --base main
```

On an existing project the wiki starts empty and fills area by area, as issues touch them.

## Commits

One commit per criterion and colour, subjects of 72 characters at most, imperative, naming the
behaviour. A criterion's history reads:

```
red(#12-AC1): reject rows without customer_id            tester
wiki(#12-AC1): log 3f1f4c0                               wiki-generator
green(#12-AC1): validate customer_id in load_rows        developer
wiki(#12-AC1): document customer_id validation           wiki-generator
```

## Skills

A **skill** (`.claude/skills/`) is a named procedure loaded into the current conversation. It is
not an identity: the skill orchestrates, the agent executes.

| Skill | What it does |
|---|---|
| `/grill-me` | Interrogates a plan in depth, one question at a time, with a recommendation. Standalone or inside `/create-issue` |
| `/create-issue` | Discovery, grilling, specs, then files the issue. You approve before it is created |
| `/implement-issue` | The eight steps above, ending in a local PR you confirm |
| `/review-issue` | Detects whether a `pending` issue is still valid |
| `/update-issue` | Applies a requested change to an existing issue |
| `define-tests` | The TDD spec: behaviours, cases, doubles, red-green-refactor sequence (used by `manager`) |
| `define-evals` | The EDD spec: cases judged against a bar, for performance, output quality or non-deterministic behaviour (used by `manager`) |
| `python-standards` | One rubric for good Python: structure, typing, language traps, errors, idioms, performance, security, tooling. `developer` and `tester` write against it, `validator` checks against it |
| `commit-messages` | The `red`, `green` and `wiki` commit conventions, shared by `tester`, `developer` and `wiki-generator` |
| `project-wiki` | How every role reads the wiki as a code map, the entry format, and the checker |
| `python-wiki-graph` | On the validator's first call, builds a cached graph of The Python Wiki (an archive) so it can pick the pages that bear on the code it is validating. One bounded crawl, polite to the site |

## What you will find in the repository

```
CLAUDE.md                 The contract. The only document that has to be read in full.
.claude/
  agents/*.md             The five roles.
  skills/*/SKILL.md       The eleven skills, with the scripts and tests that go with them.
specs/                    The executable shadow of each issue.
evals/                    The cases an eval is judged over.
wiki/                     A native GitHub Wiki: the code map and the changelog.
```

`src/`, `tests/` and the rest are your project, not this layer.

## Code quality

Before any local PR is shown: `uv run ruff check .`, `uv run ruff format --check <touched paths>`,
`uv run mypy <touched paths>` and `uv run pytest -q`. `mypy` is reported but does not block, by
design; a blocking check is never relaxed to turn it green.

`ruff format` is a drop-in replacement for Black and `ruff check` covers the Flake8 rules (and
isort's, with the `I` set), so the three tools are not added separately: Black and Ruff can disagree
on edge cases and end up fighting inside the same hook.

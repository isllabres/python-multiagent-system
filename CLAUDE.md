# CLAUDE.md — working contract

Instructions for Claude Code in this repository. This file is the map and the hard rules; the
detail lives in the roles (`.claude/agents/`) and the skills (`.claude/skills/`), read when they
are needed.

## The idea

This idea arises from the complexity of carrying out a good Python project: code that follows good practices, and a result that is valid.

A change can pass every test and still be the wrong change, or be written so badly that the next one breaks it. Everything that follows exists so that specialised agents, each with one job, catch that difference — starting from a spec that is agreed before any code exists.

## A layer, not a project template

This system does not create `src/`, `tests/` or any other directory of your project; it adapts
to the project at hand. What it creates is its own output: `openspec/` when the project does not
have it yet (the living specs and the changes, managed by the OpenSpec CLI) and `wiki/` (what
gets learned).

## The map — read what you need, when you need it

| What | Holds | Read it |
|---|---|---|
| `CLAUDE.md` | The contract | Always |
| `.claude/skills/sdd/` | Issue and change, the four files, tasks, states, checkpoints, `sdd.py` | Before writing, implementing or reviewing a change |
| `.claude/agents/*.md` | The four roles | When you delegate to one |
| `.claude/skills/create-issue`, `implement-issue`, `update-issue`, `grill-me` | The workflows | When you run one |
| `.claude/skills/python-standards/` | The Python rubric | Before writing or reviewing code |
| `.claude/skills/project-wiki/` | How to read the wiki, its format and checker | Before reading code |
| `openspec/specs/` | What the system does now: the living specs | Before changing behaviour |
| `openspec/changes/<id>/` | The change on its branch, mirrored from its issue | While implementing it |
| `wiki/` | The code map and the log of changes | Before reading code |

## Spec-driven, on OpenSpec, with the issue as the source of truth

Every change is an OpenSpec change — `proposal.md`, delta specs, `design.md`, `tasks.md` —
whose approved text lives in its GitHub issue. The branch `<n>-<change-id>` carries a mirror of
it in `openspec/changes/<id>/`, written from the issue by `sdd.py pull`. Only the OpenSpec CLI
is used (`openspec init --tools none`); this layer adds the issue, tests before code, the
reviewer and the checks. The `sdd` skill has the detail.

```
idea ── /create-issue ──▶ change in its issue ── /implement-issue ──▶ local PR ──▶ PR ──▶ merge
           you approve                               you confirm                     you merge
```

| Gate | Where | What you do |
|---|---|---|
| **Approve** | End of `/create-issue` | You approve the proposal, specs, design and tasks; then the issue is created |
| **Confirm** | End of `/implement-issue` | You see the local PR — diff, commits, review, wiki — before anything is pushed |
| **Merge** | The PR on GitHub | Merging is accepting the result; GitHub closes the issue |

`/implement-issue` runs between the gates without asking, and resumes where it stopped.
`/update-issue` is the only way an approved change changes.

## Four roles

| Role | Model | Writes | Never |
|---|---|---|---|
| `manager` | opus | The change, the issue (the only role on GitHub), `spec(#n)` commits | Code, tests, reviewing code |
| `implementer` | sonnet | Tests first, then the code, ticks in `tasks.md`; `red`/`guard`/`green`/`remove` commits | The spec, `review.md`, the issue |
| `reviewer` | opus | `review.md` only | Code, tests, commits, GitHub |
| `wiki-generator` | sonnet | `wiki/`, one `wiki(#n)` commit per issue | `README.md`, `CLAUDE.md`, `wiki/raw/` |

Researching techniques is not a role: `manager` and `implementer` use their research tools
before fixing a choice they are unsure of.

## States, deduced and never stored

draft (a local change, only during `/create-issue`) → open (an issue with its change) → in
progress (the branch and its mirror) → verified (every task ticked, `review.md` APPROVED, checks
green, the wiki line) → in PR (the change archived on the branch) → done (merged; GitHub closes
the issue). Blocked: `BLOCKED.md`, the `blocked` label and a comment. The default branch never
holds an active change: the PR archives it before it merges.

## Hard rules

- **Nothing is implemented without an approved change in its issue.**
- **The issue is the source of truth.** The mirror follows it in one direction; if they drift,
  the flow stops and the issue wins.
- **Red before green.** In each group of `tasks.md`, the test of every scenario is written, seen
  failing for the right reason and committed before the code. No `green` commit touches a test;
  a test changed after its green cites the review finding.
- **One task, one commit; one change per branch.**
- **Results go to files.** A subagent writes its work down and replies one line with the path;
  `manager` passes paths, never content.
- **Three review rounds at most.** The fourth blocks the change.
- **Randomness is seeded.**
- **Read the wiki before the code**, and follow its anchors straight to the symbol.
- **Only `manager` writes to GitHub.** Before the PR, only task amendments and `blocked`.

## Git

The branch is `<n>-<change-id>`, with no slashes. Commits are `red|guard|green|remove(#n-N.k):`
from `implementer`, `spec(#n):` from `manager` and `wiki(#n):` from `wiki-generator`: one line of
at most 72 characters, imperative, naming the behaviour ("retry 5xx in HttpClient.get", not
"fix"), with a body only for a non-obvious why. Never `git add -A`. All work is local until you
confirm the local PR.

## Before showing any local PR

```
python3 .claude/skills/sdd/scripts/sdd.py check --base <default-branch> --remote
python3 .claude/skills/project-wiki/scripts/check_wiki.py
uv run ruff check .
uv run ruff format --check <touched paths>
uv run mypy <touched paths>
uv run pytest -q
```

`mypy` is advisory: it is reported but does not block, by design. A blocking check is never
relaxed to turn it green. `ruff format` is compatible with Black's output and `ruff check`
includes isort's rules with the `I` set: one tool, two modes.

## Hooks

`.claude/settings.json` runs `sdd.py` at two moments, so the discipline does not depend on the
model remembering it:

- **SessionStart** — `sdd.py status --brief` tells the session which change is active and where
  to resume. It reads disk and git only and never blocks.
- **Stop** — `sdd.py stop-gate` exits 2 when a change marked as done (every task ticked, or the
  review APPROVED) fails `sdd.py check --base`, `ruff check` or `pytest`. Unfinished or blocked
  work stops freely, and a second stop is never held back.

## The wiki

`README.md` describes the tool. **Everything learned goes to the wiki**, GitHub Wiki style:
`wiki/raw/` (sources, never edited), `wiki/log.md`, and six fixed pages plus `Home.md` and
`_Sidebar.md`:

```
1.-Configuration-and-Environment.md    Install, dependencies, configuration, how to run it
2.-Architecture.md                     Modules, boundaries, how the parts fit together
3.-Features-and-Behaviour.md           Each capability: its living spec, code and tests
4.-Testing-and-Evaluation.md           How to run the tests, what each one covers
5.-Decisions-and-Known-Issues.md       What was decided and discarded, and why; what went wrong
6.-Production-and-Monitoring.md        Deployment, operation, monitoring
```

`wiki-generator` updates it once per issue, after the review approves it, and is brief by rule:
one `log.md` line per issue, a page edited only when behaviour or architecture changed, three
pages and 15 net lines at most per issue, a decision or known issue in 5 lines, anchors
(`path:symbol`, never line numbers) kept true. What the system does is not restated: page 3
points at `openspec/specs/`.

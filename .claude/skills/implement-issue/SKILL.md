---
name: implement-issue
description: Launches the full multi-agent cycle over an issue — per criterion, then integration, then wiki — and assembles a local PR. Does not touch GitHub until you confirm.
argument-hint: "<issue number>"
---

`manager` coordinates this whole sequence. Nothing is pushed or opened on GitHub until Step 8, and
only with your explicit confirmation.

Detect the repository with `gh repo view`. If `gh auth status` fails, stop.

## Step 1 — Read the issue

```bash
gh issue view $ARGUMENTS --json number,title,body,labels,state
```

**`pending` gate** — if it carries that label, stop and ask whether I would rather run
`/review-issue` first: the code or the data may have changed since it was filed.

**`epic` gate** — it is not implemented directly. List the ready children and ask which to start
with.

## Step 2 — Local branch, without touching GitHub

```bash
default_branch=$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name 2>/dev/null \
  || git symbolic-ref --short refs/remotes/origin/HEAD | sed 's@^origin/@@')
git checkout "$default_branch" && git pull origin "$default_branch"
git checkout -b $ARGUMENTS-<title-slug>
```

Purely local. No command in this flow writes to the remote repository until Step 8.

## Step 3 — Data facts (`analyst`, only if the issue depends on data)

If a criterion depends on facts about data and none are recorded for this issue, `analyst`
establishes them before anyone touches code. If they contradict a criterion — the data changed
since the issue was created — **stop and comment on the issue** with the evidence; do not
implement against a criterion that is already unreachable.

## Step 4 — Per criterion: implement and converge

For each criterion in `ACCEPTANCE.yaml`, in order:

1. `developer` writes red (watches it fail), commit `red(#$ARGUMENTS-<AC>):`, writes the
   minimum green, commit `green(#$ARGUMENTS-<AC>):`.
2. `reviewer` and `manager` review the same diff, each through their own lens — code for the
   first, conformance to the spec for the second.
3. If either of them has a blocking finding, `manager` records the round: criterion, who raised
   it, the finding. Rounds are counted per criterion, shared with the integration loop in Step 5.
   If this would be the 4th round, **stop**, comment the blockage on the issue with the full
   history, and wait for instructions.

   Within the cap: `developer` fixes (never touching the test to make the finding go away), and
   goes back to step 2.
4. No blocking findings → next criterion.

## Step 5 — Integration (`validator`)

With every criterion converged individually, `validator` first validates the whole change as
Python — semantics and structure against `python-standards`, plus `ruff` and `mypy` — and then
runs the full suite — `pytest` and the evals — because a criterion that passed in isolation can
break when combined with another, and a diff that passes every test can still be badly structured.

A blocking Python finding opens the same fix conversation as a failing test, on the same round
counter.

**If anything fails:**

`validator` opens a conversation with `developer` describing the symptom with literal evidence — it
does not propose the fix, it describes it. If the fix touches production code, the round goes back
through `manager` and `reviewer` before `validator` re-runs — it is never skipped for looking
trivial. Every round is recorded on the same per-criterion counter as Step 4: accumulated, not
reset.

`validator` re-runs the suite. Repeat until everything passes or the cap is exhausted.

## Step 6 — Wiki (`wiki-generator`, called by `developer`)

With `validator` converged and `reviewer` giving their final approval, **`developer` calls
`wiki-generator`** — not `manager` — because they hold the full context of what was built. It
updates the relevant pages of the project wiki, and `wiki/log.md` gets its entry.

`README.md` is not touched here — it is the system's front door, not the project's.

## Step 7 — Verify and assemble the local PR

```bash
uv run ruff check .
uv run ruff format --check <touched paths>
uv run mypy <touched paths>        # advisory: report it, do not silence it
uv run pytest -q
```

All green, mypy reported. PR body assembled from `validator`'s report (results per criterion, the
round history, Python findings and their disposition) and which wiki pages were touched:

```markdown
## Summary
## Changes
## Verification
- Tests / Evals: <result for each criterion>
## Review
- Per criterion: <rounds, who, what was fixed>
- Integration: <validator↔developer conversation, if there was one>
## Wiki
- Pages touched: <list>
Closes #$ARGUMENTS
```

**Show me all of this — diff, commits, PR body, wiki pages touched — and stop.** It is the local
PR: it exists as a branch and commits on your machine, nothing on GitHub yet.

## Step 8 — Only with my explicit confirmation

```bash
git push -u origin $ARGUMENTS-<title-slug>
gh pr create --title "<title>" --body-file "$tmpfile"
```

Report the URL. **It does not merge, does not approve, does not close the issue.**

## Principles

1. **The round cap is counted per criterion, across the per-criterion loop and the integration
   one.** A fix that moves from one loop to the other does not reset the counter.
2. **Nothing touches GitHub before Step 8.**
3. **The wiki is updated once, at the end, when everything has truly converged** — never in the
   middle of a fix conversation, or work that may be undone would be recorded.
4. **The evidence is honest**, uncomfortable findings included.
5. `validator` diagnoses, never implements. `developer` implements and, on convergence, is the one
   who invokes `wiki-generator` — it does not decide what is blocking in its own code.

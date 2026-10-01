---
name: implement-issue
description: Launches the full multi-agent cycle over an issue — per criterion, then the whole change, then wiki — and assembles a local PR. Does not touch GitHub until you confirm.
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

## Step 4 — Per criterion: red, green and converge

For each criterion in `ACCEPTANCE.yaml`, in order:

1. `tester` writes the test or eval from the spec, watches it fail for the right reason, and
   commits `red(#$ARGUMENTS-<AC>):`.
2. `developer` writes the minimum that turns it green and commits `green(#$ARGUMENTS-<AC>):`. It
   never touches the test.
3. `tester` and `manager` review the same diff, each through their own lens — `tester` runs it and
   checks that the tests are intact, `manager` checks conformance to the spec, including that the
   red test is the right one.
4. If either of them has a blocking finding, `manager` records the round: criterion, who raised
   it, the finding. Rounds are counted per criterion, shared with the whole-change loop in Step 5.
   If this would be the 4th round, **stop**, comment the blockage on the issue with the full
   history, and wait for instructions.

   Within the cap: `developer` fixes (a test it thinks is wrong goes to `manager`, who decides
   between `tester` fixing the test and the spec changing), and goes back to step 3.
5. No blocking findings → next criterion.

## Step 5 — Whole change: `tester`, then `validator`

With every criterion converged individually, `tester` runs the whole suite — `pytest` and the evals
— and the test-integrity check over the branch, because a criterion that passed in isolation can
break when combined with another. Only with the suite green does `validator` validate the whole
change as Python — semantics and structure against `python-standards`, plus `ruff` and `mypy` —
because a diff that passes every test can still be badly structured. It runs second so that it
reviews code that will not move because of a failing test.

**If anything fails:**

Whoever found it opens a conversation with the owner of the code, describing the symptom with
literal evidence and not proposing the fix: `tester` with `developer`; `validator` with `developer`
for production code, or with `tester` for tests, evals and fixtures. A fix that touches code goes
back through `tester` (suite and integrity) and `manager` (conformance) before it is closed — it
is never skipped for looking trivial. Every round is recorded on the same per-criterion counter as
Step 4: accumulated, not reset.

After a Python fix `tester` re-runs the suite and `validator` re-validates the files it touched.
Repeat until everything passes or the cap is exhausted.

## Step 6 — Wiki (`wiki-generator`, called by `developer`)

With `tester` and `validator` converged, **`developer` calls `wiki-generator`** — not `manager` — because they hold the full context of what was built. It
updates the relevant pages of the project wiki, and `wiki/log.md` gets its entry.

`README.md` is not touched here — it is the system's front door, not the project's.

## Step 7 — Verify and assemble the local PR

```bash
uv run ruff check .
uv run ruff format --check <touched paths>
uv run mypy <touched paths>        # advisory: report it, do not silence it
uv run pytest -q
```

All green, mypy reported. PR body assembled from `tester`'s and `validator`'s reports (results per
criterion, the round history, Python findings and their disposition) and which wiki pages were
touched:

```markdown
## Summary
## Changes
## Verification
- Tests / Evals: <result for each criterion>
## Review
- Per criterion: <rounds, who, what was fixed>
- Whole change: <tester/validator ↔ developer conversation, if there was one>
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

1. **The round cap is counted per criterion, across the per-criterion loop and the whole-change
   one.** A fix that moves from one loop to the other does not reset the counter.
2. **Nothing touches GitHub before Step 8.**
3. **The wiki is updated once, at the end, when everything has truly converged** — never in the
   middle of a fix conversation, or work that may be undone would be recorded.
4. **The evidence is honest**, uncomfortable findings included.
5. **Red before green is in the history**: for every criterion, `tester`'s `red(...)` commit comes
   before `developer`'s `green(...)` one, and no `green(...)` commit touches a test.
6. `tester` and `validator` diagnose, never implement. `developer` writes production code and, on
   convergence, is the one who invokes `wiki-generator` — it does not decide what is blocking in
   its own code.

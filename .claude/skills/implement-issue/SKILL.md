---
name: implement-issue
description: Launches the full multi-agent cycle over an issue — per criterion, then the whole change, with the wiki updated after every commit — and assembles a local PR. Does not touch GitHub until you confirm.
argument-hint: "<issue number>"
---

`manager`, the main agent, coordinates this whole sequence: it delegates to the other roles, hands
findings to whoever owns the code, and keeps the round tally. It does not review the code. Nothing
is pushed or opened on GitHub until Step 8, and only with your explicit confirmation.

Detect the repository with `gh repo view`. If `gh auth status` fails, stop.

## Step 1 — Read the issue

```bash
gh issue view $ARGUMENTS --json number,title,body,labels,state
```

**`pending` gate** — if it carries that label, stop and ask whether I would rather run
`/review-issue` first: the code may have changed since it was filed.

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

## Step 3 — Wiki coverage (`wiki-generator`, only if the area has no entries)

The wiki is the map the other roles read before the code (`project-wiki`). Look up the modules the
issue touches (its technical notes, or `git grep` for the names it uses). If the wiki has no entries
for them, `manager` has `wiki-generator` survey that area now, so that `tester` and `developer` can
go straight to the right symbols instead of reading the code wholesale.

## Step 4 — Per criterion: red, green and converge

For each criterion in `ACCEPTANCE.yaml`, in order. After **every** commit below, fix commits
included, `manager` calls `wiki-generator` with its hash (see Step 6).

1. `tester` writes the test or eval from the spec, watches it fail for the right reason, and
   commits `red(#$ARGUMENTS-<AC>):`.
2. `manager` checks that the red test is the right check for the criterion — its statement, its
   verification, its bar. If not, it goes back to `tester` and the round is recorded.
3. `developer` writes the minimum that turns it green and commits `green(#$ARGUMENTS-<AC>):`. It
   never touches the test.
4. `tester` checks the green: runs it and everything before it, checks that the tests are intact,
   that nothing hardcodes the test's inputs, and that the diff does no more than the criterion asks.
   `manager` does not review the code.
5. If `tester` has a blocking finding, `manager` records the round — criterion, the finding — and
   hands it to `developer`, who fixes it (a test it thinks is wrong goes to `manager`, who decides
   between `tester` fixing the test and the spec changing) and goes back to step 4. Rounds are
   counted per criterion, shared with the whole-change loop in Step 5. If this would be the 4th
   round, **stop**, comment the blockage on the issue with the full history, and wait for
   instructions.
6. No blocking findings → next criterion.

## Step 5 — Whole change: the suite, then the Python (`tester`)

With every criterion converged individually, `tester` runs the whole suite — `pytest` and the evals
— and the test-integrity check over the branch, because a criterion that passed in isolation can
break when combined with another. Only with the suite green does it validate the whole change as
Python — semantics and structure against `python-standards`, plus `ruff` and `mypy`, with The
Python Wiki as a reference — because a diff that passes every test can still be badly structured,
and code reviewed second will not move because of a failing test.

**If anything fails:**

`tester` reports it to `manager` with literal evidence and without writing the fix. `manager`
records the round and hands it to `developer`; a finding in the tests `tester` fixes itself. After
any fix — never skipped for looking trivial — `tester` re-runs the suite and the integrity check and
re-validates the files it touched. Every round is recorded on the same per-criterion counter as
Step 4: accumulated, not reset. Every fix commit gets its `wiki-generator` call like any other.
Repeat until everything passes or the cap is exhausted.

## Step 6 — Wiki check

`wiki-generator` already ran after every commit. Verify nothing was skipped and nothing rotted:

```bash
python3 .claude/skills/project-wiki/scripts/check_wiki.py --base <default-branch>
```

It fails if a commit of the branch has no line in `wiki/log.md`, if an anchor points at a file or
symbol that no longer exists, if a link is broken, or if a page, a changelog line or a decision is
over its size limit. `manager` has `wiki-generator` fix whatever it reports, and runs it again.
`README.md` is not touched here — it is the system's front door, not the project's.

## Step 7 — Verify and assemble the local PR

```bash
uv run ruff check .
uv run ruff format --check <touched paths>
uv run mypy <touched paths>        # advisory: report it, do not silence it
uv run pytest -q
```

All green, mypy reported. PR body assembled from `tester`'s report (results per criterion, the
round history, Python findings and their disposition), the changelog lines added and the wiki pages
touched:

```markdown
## Summary
## Changes
## Verification
- Tests / Evals: <result for each criterion>
## Review
- Per criterion: <rounds, who, what was fixed>
- Whole change: <tester ↔ developer conversation, if there was one>
## Wiki
- Changelog: <n> lines, one per commit
- Pages touched: <list, or none>
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
3. **The wiki follows every commit**: one changelog line each, and a page edited only when
   behaviour or architecture changed. A fix is just another commit; history is recorded, never
   rewritten.
4. **The evidence is honest**, uncomfortable findings included.
5. **Red before green is in the history**: for every criterion, `tester`'s `red(...)` commit comes
   before `developer`'s `green(...)` one, and no `green(...)` commit touches a test.
6. `tester` writes tests and diagnoses, never implements. `developer` writes production code and
   does not decide what is blocking in its own code. `manager` owns the spec and coordinates, calling
   `wiki-generator` after every commit; it does not review code.

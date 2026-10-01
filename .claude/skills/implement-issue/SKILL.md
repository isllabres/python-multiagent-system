---
name: implement-issue
description: Launches the full multi-agent cycle over an issue — per criterion, then integration, then wiki — and assembles a local PR. Does not touch GitHub until you confirm.
argument-hint: "<issue number>"
---

`ds-manager` coordinates this whole sequence. Nothing is pushed or opened on GitHub until Step 10,
and only with your explicit confirmation.

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

Purely local. No command in this flow writes to the remote repository until Step 10.

## Step 3 — Data (`analyst`, only if there is a `metric` criterion)

If `DATA_AUDIT.md` does not exist for this id, `analyst` audits before anyone touches code. If the
ceiling does not reach the issue's target — the data changed since it was created — **stop and
comment on the issue** with the evidence; do not implement against a target that is already
unreachable.

## Step 4 — Per criterion: implement and converge

For each criterion in `ACCEPTANCE.yaml`, in order:

1. `ds-developer` writes red (watches it fail), commit `red(#$ARGUMENTS-<AC>):`, writes the
   minimum green, commit `green(#$ARGUMENTS-<AC>):`.
2. `reviewer` and `ds-manager` review the same diff, each through their own lens — code for the
   first, methodology for the second.
3. If either of them has a blocking finding:

   ```bash
   python3 gates/convergence.py round $ARGUMENTS <AC-id> --who <role> --note "<finding>"
   ```

   If the exit code is 1 (maximum of 3 exceeded), **stop**, comment the blockage on the issue with
   the full history from `gates/convergence.py status $ARGUMENTS`, and wait for instructions.

   Within the cap: `ds-developer` fixes (never touching the test to make the finding go away),
   and goes back to step 2.
4. No blocking findings → next criterion.

**All of this runs against `dev`. Nobody in this step touches any one-look resource.**

## Step 5 — Integration (`validator`)

With every criterion converged individually, `validator` first validates the whole change as
Python — semantics and structure against `python-standards`, plus `ruff` and `mypy` — and then
runs the full suite — `pytest`, evals against their golden set's `dev`, metrics against the
data's `dev` — because a criterion that passed in isolation can break when combined with
another, and a diff that passes every test can still be badly structured.

A blocking Python finding opens the same fix conversation as a failing test, on the same round
counter.

**If anything fails:**

`validator` opens a conversation with `ds-developer` describing the symptom with literal evidence
— it does not propose the fix, it describes it. If the fix touches production code, the round goes
back through `ds-manager` and `reviewer` before `validator` re-runs — it is never skipped for
looking trivial.

```bash
python3 gates/convergence.py round $ARGUMENTS <AC-id> --who validator --note "<what failed>"
```

Same cap, same counter as Step 4 — accumulated, not reset.

`validator` re-runs against `dev` (the data's, or the golden set's, depending on what failed).
Repeat until everything passes or the cap is exhausted.

## Step 6 — `ds-manager`'s final check

Only when `validator` has no fix conversation open: does this result deserve to spend the look?
If there is a genuine doubt outstanding, it is voiced here.

## Step 7 — The only looks (`validator`)

Every one-look resource that exists in this issue, recorded separately:

```bash
python3 gates/holdout_ledger.py record <metric-test-partition-path> <metric> <value> $ARGUMENTS
python3 gates/holdout_ledger.py record <eval-test-partition-path> <success-rate> <value> $ARGUMENTS
```

Whatever each call returns — third look, changed set — goes verbatim into the PR.

## Step 8 — Wiki (`wiki-generator`, called by `ds-developer`)

With `validator` converged and `reviewer` giving their final approval, **`ds-developer` calls
`wiki-generator`** — not `ds-manager` — because they hold the full context of what was built. It
compiles into the relevant page of the fixed hierarchy (`2.-Data-Lifecycle.md` if it is the first
time a source is touched, `4.-Modeling-and-Experiments.md` for the experiment with its result,
`5.-Evaluation-and-Metrics.md` for the look at the test partition; a decision or a failure mode
goes in as a subsection on the page of its phase, indexed from `Home.md`). `python3
gates/wiki_lint.py wiki` clean before moving on.

`README.md` is not touched here — it is the system's front door, not the project's.

## Step 9 — Verify and assemble the local PR

```bash
python3 gates/check.py
```

All green, wiki health included. PR body assembled from `validator`'s report (results per
criterion, the round history from `convergence.py status $ARGUMENTS`, every look with its warning
if there was one, error analysis) and which wiki pages were touched:

```markdown
## Summary
## Changes
## Verification
- Tests / Evals / Metric: <result + CI + look #N for each resource>
## Review
- Per criterion: <rounds, who, what was fixed>
- Integration: <validator↔ds-developer conversation, if there was one>
## Wiki
- Pages touched: <list>
Closes #$ARGUMENTS
```

**Show me all of this — diff, commits, PR body, wiki pages touched — and stop.** It is the local
PR: it exists as a branch and commits on your machine, nothing on GitHub yet.

## Step 10 — Only with my explicit confirmation

```bash
git push -u origin $ARGUMENTS-<title-slug>
gh pr create --title "<title>" --body-file "$tmpfile"
```

Report the URL. **It does not merge, does not approve, does not close the issue.**

## Principles

1. **Each one-look resource is looked at once per issue**, after no fix conversation remains open
   — never during one, no matter how many rounds it takes. An issue may have more than one
   (metric and eval at once); each with its own budget of one look.
2. **The round cap is measured with `convergence.py`, accumulated across the per-criterion loop
   and the integration one.** A fix that moves from one loop to the other does not reset the
   counter.
3. **Nothing touches GitHub before Step 10.**
4. **The wiki is compiled once, at the end, when everything has truly converged** — never in the
   middle of a fix conversation, or work that may be undone would be compiled.
5. **The evidence is honest**, uncomfortable findings included.
6. `validator` diagnoses, never implements. `ds-developer` implements and, on convergence, is the
   one who invokes `wiki-generator` — it does not decide what is blocking in its own code.

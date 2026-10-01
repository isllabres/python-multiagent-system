---
name: review-issue
description: Checks whether a filed issue is still valid against the current code and data. Never implements.
argument-hint: "<issue number> | --all"
---

An issue was filed at some point; the code and the data may have changed since then. Check whether
it is **still valid**. You never implement — you keep the spec honest.

## Read and compare

```bash
gh issue view $ARGUMENTS --json number,title,body,labels,createdAt,comments
git log --since="<createdAt>" --oneline --stat
```

Look for conflicts, with concrete evidence (commit, file, symbol) for each:

- **Reference drift** — files or functions the issue names no longer exist, or were moved.
- **Already solved** — the behaviour described is already on `main`.
- **Data drift** — if the issue depends on facts about data, re-run the `data-profiling` script
  (`analysis/<id>/scripts/` has the exact commands) and compare its JSON against the profile the
  issue was written from. If a figure the criteria rely on has moved, a criterion may be
  unimplementable as written.

## Verdict

**No conflicts** → it still stands; say so and stop. Do not edit for cosmetic reasons.

**Conflicts** → present them with their evidence and ask for confirmation before touching
anything:

> "Issue #<n> has <k> conflict(s): <one per line, with evidence>. I would refresh it by
> re-running `/create-issue` against current reality. Proceed?"

With my confirmation: re-run Step 2.5 (data facts) and Step 3 (`define-tests`, `define-evals`) of
`/create-issue` against the current state, keeping whatever did not change —
do not re-ask what I already answered and the conflict did not touch. Recompose the body,
**confirm the `pending` label with me** (do I remove it because it is ready now, or leave it?),
and edit:

```bash
gh issue edit <n> --body-file "$tmpfile" --add-label "..." --remove-label "pending"
gh issue comment <n> --body "Refreshed: <conflicts and evidence>. No implementation."
```

If the conflict is that **everything** is already done, do not invent scope to justify the issue —
recommend closing it, with the evidence, and I will decide.

With `--all`: process every open issue one by one, then a final table with each verdict.

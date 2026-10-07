---
name: update-issue
description: Changes the OpenSpec change an issue holds — the only way a spec changes after it was approved. Applies the requested change keeping proposal, specs, design and tasks coherent, validates it, shows you the difference, and with your approval edits the issue and the branch's mirror. Also refreshes a stale issue and converts an issue that predates OpenSpec.
argument-hint: "<issue number> -- <what to change>"
---

`manager` drives this. The issue is the source of truth (`sdd`), so the change goes to the issue
first and the mirror follows. `sdd.py` below is `python3 .claude/skills/sdd/scripts/sdd.py`.

## Step 1 — The change as it stands

```bash
gh issue view <n> --json number,title,body,labels,state
```

- **On the issue's branch** (`<n>-<change-id>`): work on its mirror,
  `openspec/changes/<id>/`. Check `sdd.py diff <n>` first: edit on top of the issue's version.
- **Otherwise**: `sdd.py pull <n>` writes it to `openspec/changes/<id>/` as a temporary draft.
- **No `openspec:change` marker** (an issue from before this flow): write a new change from its
  body, as `/create-issue` Step 3 does, keeping what the person already decided.

## Step 2 — Apply the change

Apply what was asked after the `--`, keeping the four files coherent: a new requirement brings
its scenarios, its `[test]` tasks and its `[code]` task; a removed one, a `[remove]` task; a
changed design, the tasks that follow from it. Requirement names already in `tasks.md` stay as
they are unless they are the change. If the request contradicts the change, the request wins;
if it is ambiguous, ask.

```bash
openspec validate <id> --strict
sdd.py check --change <id>
```

## Step 3 — Your approval

Show the difference against the issue (`sdd.py diff <n>` on the branch, or `git diff --no-index`
against a fresh pull elsewhere) and say what it means for work already done: tasks to redo,
tests that change. Nothing is edited until you approve; if you do not, `sdd.py pull <n>` puts the
mirror back as the issue has it (or delete the temporary draft). A change to the tasks alone,
asked for by `manager` during `/implement-issue`, needs no approval but always gets its comment.

## Step 4 — Edit the issue, then the mirror

```bash
tmpfile=$(mktemp /tmp/issue-XXXXXX)
sdd.py body --change <id> --out "$tmpfile"
gh issue edit <n> --body-file "$tmpfile"
gh issue comment <n> --body "Updated: <what changed and why>."
rm "$tmpfile"
```

- **On the branch**: `sdd.py pull <n>` (it keeps the ticks of unchanged tasks) and commit
  `spec(#<n>): amend <what>`; `sdd.py diff <n>` must then report no drift.
- **Elsewhere**: delete the temporary draft.

Confirm the label set with me — `pending` in particular — before changing it. If the issue is
already done in the code, say so with the evidence and recommend closing it instead of inventing
scope.

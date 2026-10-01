---
name: update-issue
description: Applies a change to an existing issue by re-running /create-issue with the updated context.
argument-hint: "<issue number> -- <what to change>"
---

A simple flow: the issue's context → apply the requested change → re-run `/create-issue` with the
resulting description. I do not hand-write specs; that is `/create-issue`'s job.

```bash
gh issue view <n> --json number,title,body,labels
```

Take what does not change, apply what I ask for after the `--`, and synthesise a new description.
If the two contradict, the requested change wins; if it is ambiguous, ask.

Re-run `/create-issue` with that description, carrying type/labels/priority through as answers
already given to the discovery. Confirm the final label set with me — `pending` in particular —
before applying. The result edits issue #<n>; it does not create a new one:

```bash
gh issue edit <n> --body-file "$tmpfile" --add-label "..." --remove-label "..."
gh issue comment <n> --body "Updated: <summary of the change>."
```

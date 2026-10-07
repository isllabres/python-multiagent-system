---
name: implement-issue
description: Implements an issue's OpenSpec change on the branch <n>-<change-id> — checks the issue still applies, mirrors it, has the implementer build it test-first and the reviewer judge it, updates the wiki once, and assembles a local PR. Resumes where it stopped. Does not touch GitHub until you confirm.
argument-hint: "<issue number>"
---

`manager`, the main agent, runs this sequence: it delegates, passes paths rather than content,
keeps the round tally and never reviews the code. Nothing is pushed or opened on GitHub until
Step 7, and only with your explicit confirmation. `sdd` has the rules; `sdd.py` below is
`python3 .claude/skills/sdd/scripts/sdd.py`.

Detect the repository with `gh repo view`. If `gh auth status` fails, stop.

## Step 1 — Read the issue

```bash
gh issue view $ARGUMENTS --json number,title,body,labels,state
```

- **`epic`**: it is not implemented directly. List the ready children and ask which to start.
- **`pending`**: it was filed for later; ask whether to start it now.
- **No `openspec:change` marker**: it predates this flow. Convert it with `/update-issue` first.

## Step 2 — Does it still apply?

On a fresh start (no branch yet), run `sdd.py stale $ARGUMENTS`. It validates the change against
today's living specs, checks that the files `design.md` modifies still exist, and that no
living spec it touches changed since the issue was written. If it reports anything, **stop**
and propose `/update-issue` with the evidence. A behaviour that already exists is caught later,
by a test that passes before any code.

## Step 3 — Branch and mirror

```bash
branch=$(sdd.py branch $ARGUMENTS)            # <n>-<change-id>
```

- **New**: from the up-to-date default branch, `git switch -c "$branch"`, then
  `sdd.py pull $ARGUMENTS` and commit `spec(#$ARGUMENTS): pull change <id>`.
- **Resuming** (the branch exists): `git switch "$branch"` and `sdd.py diff $ARGUMENTS`. If the
  issue changed, **stop** and show the difference: adopting it means `sdd.py pull` and possibly
  reworking tasks already done, and that is the person's call. Then carry on from where
  `sdd.py status` says the work stands: unticked tasks → Step 4; all ticked → Step 5;
  `review.md` APPROVED → Step 6; `BLOCKED.md` → show its reason and ask.

Purely local: nothing here writes to the remote.

## Step 4 — Implement

Ask `implementer` to work through `openspec/changes/<id>/tasks.md` from its first unticked task.
It replies one line:

- `done -> …/tasks.md` → Step 5.
- `blocked -> …/tasks.md` → read the `BLOCKED` note. A spec problem: requirements or design
  change through `/update-issue` (your approval); tasks alone, `manager` amends them in the issue
  with a comment, pulls the mirror again and goes back to Step 4. An environment problem: block
  the change (below).

## Step 5 — Review, and the round tally

Ask `reviewer` to review `<id>` against the default branch. It writes `review.md` and replies:

- `APPROVED -> …/review.md` → Step 6.
- `CHANGES_REQUESTED -> …/review.md` → count the CHANGES_REQUESTED rows in its Rounds table.
  Up to 3, ask `implementer` to answer that round, then back to Step 5. Before a 4th, **block
  the change**: write `openspec/changes/<id>/BLOCKED.md` with the reason and the round history,
  commit it with `review.md` as `spec(#$ARGUMENTS): block <id>`, add the `blocked` label and
  comment the history on the issue, and wait for instructions.

## Step 6 — Wiki and the local PR

1. Call `wiki-generator` with the issue, the change and the `## Wiki gaps` noted in `tasks.md`
   and `review.md`. It replies `wiki -> <sha>`.
2. Check:

   ```bash
   python3 .claude/skills/project-wiki/scripts/check_wiki.py
   sdd.py check --base <default-branch> --remote
   ```

   Anything they report goes back to its owner: the wiki to `wiki-generator`, the rest to
   `implementer` through a review round.
3. Commit `review.md` as `spec(#$ARGUMENTS): review <id>`.
4. **Show me the local PR and stop**: the diff against the default branch, the commits, the
   verdict and checkpoints of `review.md` with any disagreement, the wiki pages touched, and the
   PR body:

   ```markdown
   ## Summary
   ## Requirements
   - <requirement>: <its scenarios and their tests>
   ## Review
   - Verdict, checkpoints, rounds, disagreements (both positions)
   ## Wiki
   - <pages touched, or none>
   Closes #$ARGUMENTS
   ```

## Step 7 — Only with my explicit confirmation

- **Accepted**:

  ```bash
  openspec archive <id> --yes        # the living specs take the change; the change is archived
  git add openspec && git commit -m "spec(#$ARGUMENTS): archive <id>"
  git push -u origin "$branch"
  gh pr create --title "<issue title>" --body-file "$tmpfile"
  ```

  Archiving inside the PR means the merge updates the code and `openspec/specs/` together, and
  a PR closed without merging never touches the default branch. Report the PR's URL.
- **Changes requested**: they become tasks in the issue (your request is the approval), the
  mirror is pulled again, and the work goes back to Step 4.

It never merges, approves or closes anything: merging the PR is how you accept the result, and
GitHub closes the issue.

## Principles

1. **The issue is the source of truth**; the mirror only follows it, and drift stops the flow.
2. **Red before green, in the history**: every group's `red` commit precedes its `green`, and no
   `green` commit touches a test (`sdd.py check --base`).
3. **Three rounds at most**, counted in `review.md`; the fourth blocks the change.
4. **Nothing reaches GitHub before Step 7** except task-only amendments and `blocked`.
5. **The evidence is honest**, uncomfortable findings included.

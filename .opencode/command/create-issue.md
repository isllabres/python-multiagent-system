---
description: Turns an idea into an approved OpenSpec change held by a GitHub issue — light discovery, /grill-me, scope, then the change's proposal, delta specs, design and tasks written and validated locally, your approval, and the issue. manager drives and writes. Never implements.
agent: manager
---

Usage: `/create-issue [bug | feature | refactor]`

`manager` drives the discovery and writes. Nothing is implemented in this skill, and nothing
reaches GitHub until you approve the change. `sdd` has the format and the rules.

Type hint: $ARGUMENTS

## Step 0 — Preconditions

- `gh auth status` passes and `gh repo view` names the repository. Without them, stop.
- The OpenSpec CLI is installed (`openspec --version`) and `openspec/` exists. If it does not,
  run `python3 .opencode/skills/sdd/scripts/sdd.py init`.
- You are on the default branch; if not, ask before going on.
- If this conversation already holds a `/grill-me` synthesis (Resolved / Explicitly out of
  scope / Still open), skip Steps 1 and 1b and use it.

## Step 1 — Light discovery

Four quick questions, without exploring the repository yet:

1. Bug, feature or refactor? A one-sentence summary.
2. By type — bug: current and expected behaviour, steps, severity; feature: the problem it
   solves and what success looks like from outside; refactor: what it touches, why, and which
   behaviour must not change.
3. Is there behaviour to verify at all? Some changes genuinely have none — a pure refactor, a
   dependency bump, tooling, docs. If the person confirms there is none, this change carries no
   delta specs: say so now, so Step 3 skips the specs artifact and marks the change
   `skip_specs` instead of guessing it later from an empty `specs/`.
4. Implement it soon, or file it for later (`pending`)?

## Step 1b — Interrogate in depth

Invoke the `grill-me` agent via the task tool with what Step 1 gathered. It always runs: it
decides how much depth the idea needs, not you. Its synthesis feeds the change:

- **Resolved** → requirements and their scenarios.
- **Explicitly out of scope** → the proposal's Out of scope section.
- **Still open** → the design's Open Questions, where the implementer has room to decide.

## Step 2 — Scope: one change, or several

One change carries one intent (an OpenSpec rule). Independent deliverables, more than a day or
two of work, or internal dependencies make an epic: a parent issue that lists its children,
and one child issue per change. **You approve the split** before any change is written.

## Step 3 — Write the change

1. `openspec new change <id>`: kebab-case, starting with a verb (`add-`, `fix-`, `change-`,
   `remove-`, `refactor-`).
2. **If Step 1 found no behaviour to verify**: run
   `python3 .opencode/skills/sdd/scripts/sdd.py skip-specs <id>` and skip the specs artifact
   entirely — write proposal, design and tasks only, with `[guard]`/`[code]` tasks, never
   `[test]`. Otherwise, for each artifact in order — proposal, specs, design, tasks — run
   `openspec instructions <artifact> --change <id> --json` and write it from its template and
   its rules, which include this layer's.
3. Read the code through the wiki (`project-wiki`). An area with no entries: `wiki-generator`
   surveys it first. A large area: launch the `explore` agent with bounded questions.
4. A technique you are unsure of: research it before fixing it in the spec.

## Step 4 — Check it

```bash
openspec validate <id> --strict
python3 .opencode/skills/sdd/scripts/sdd.py check --change <id>
```

Fix the change until both are clean.

## Step 5 — Your approval

Show the four files: proposal, delta specs, design, tasks. Changes go back to Step 3 and Step 4,
then you see them again. Nothing is created until you approve explicitly.

## Step 6 — Create the issue

```bash
tmpfile=$(mktemp /tmp/issue-XXXXXX)
python3 .opencode/skills/sdd/scripts/sdd.py body --change <id> --out "$tmpfile"
gh issue create --title "[<area>]: <imperative description>" --body-file "$tmpfile" --label "..."
rm "$tmpfile"
```

Add `pending` if it is filed for later; a child of an epic names its parent in the title or a
label. Then delete the draft, `openspec/changes/<id>/`: the issue holds the change now.
Nothing is committed and no branch is created — that is `/implement-issue`.

## Principles

1. No implementation.
2. The person approves the change, and an epic's split, before anything is created.
3. The issue is the source of truth; the local draft only lives until the issue exists.
4. `grill-me` always runs after the light discovery, unless it already ran on its own.
5. Research comes before a criterion is fixed, never afterwards to justify it.

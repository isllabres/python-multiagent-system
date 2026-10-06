---
name: create-issue
description: Interactive discovery and creation of an issue with the test and eval specs embedded. manager drives and writes. Never implements.
argument-hint: "[bug | feature | refactor]"
---

`manager` drives the discovery and writes. Nothing is implemented in this skill.

Detect the repository with `gh repo view`. If `gh auth status` fails, stop: without an
authenticated `gh` there is nothing to do.

Type hint: $ARGUMENTS

## Step 0 — Does it already come from `/grill-me`?

If this conversation already contains a `/grill-me` synthesis (Resolved / Explicitly out of scope
/ Still open), **do not repeat Step 1 or invoke `/grill-me` again** — it is already done. Jump
straight to Step 2, using that synthesis as if it were Step 1's result.

If not, continue to Step 1.

## Step 1 — Light discovery (`manager`)

**Group 1**: bug, feature or refactor? A one-sentence summary.

**Group 2**, by type — bug: current versus expected behaviour, steps, severity; feature: what
problem it solves, what success looks like from outside; refactor: what is touched, why, what
behaviour must be preserved.

**Group 3 — classification**, the decision that matters most: does it involve code? (almost
always) → **test**. Behaviour judged over a set of cases against a bar — performance, output
quality, non-deterministic behaviour? → **eval**. The two are not exclusive.

**Group 4 — readiness**: is it implemented soon, or filed for later (`pending`)?

This is deliberately light — four quick questions, without yet exploring the repository in depth.
The real interrogation is the next step.

## Step 1b — Interrogate in depth (`/grill-me`, orchestrated mode)

Invoke the `grill-me` skill in orchestrated mode with the context Step 1 has just gathered. This step **always runs**, unless
Step 0 already covered it — it is neither optional nor proportional to how trivial the idea seems,
because it is `/grill-me` itself that decides how much depth is needed.

`/grill-me` explores the repository before asking, goes one question at a time with its own
recommendation, and closes with a three-block synthesis. When it comes back:

- **Resolved** → becomes the acceptance criteria in Step 4.
- **Explicitly out of scope** → goes verbatim into the issue's section of the same name.
- **Still open** → goes into Technical notes, so `developer` knows where there is legitimate
  room to decide at implementation time.

If `/grill-me` finds a contradiction between something you said in Step 1 and something you say
here, it points it out directly and asks which one prevails — it does not resolve it silently,
and neither should you resolve it on its behalf.

If during the interrogation `manager` is unsure of the right technique for something specific
— which architecture, which approach the Python docs or the literature recommend — it researches
it before fixing the criterion. Do not guess when it can be verified.

## Step 2 — Scope: one issue or an epic?

Epic signals: independent deliverables, more than a day or two of work, internal dependencies.
If they apply, **`manager` requires my explicit validation** of the decomposition before
generating any spec:

> "This looks like an epic: parent issue + N children [title — mandate — type — dependencies].
> Shall I proceed, adjust, or keep it as a single issue?"

Nothing is created until I approve.

## Step 3 — Orchestrate the specs (`manager`)

The `define-tests` skill whenever there is code. The `define-evals` skill if there is behaviour
judged over cases against a bar. Both return markdown and persist no files: it is embedded in the
issue.

## Step 4 — Compose the issue (`manager`)

Title: `[area]: imperative description`. Body: Description, Acceptance criteria (a
`[test]`/`[eval]` checklist, derived from `/grill-me`'s "Resolved" block),
TDD/EDD Specification verbatim, technical notes (include `/grill-me`'s "Still open" here),
out of scope (`/grill-me`'s "Explicitly out of scope" block, verbatim).

## Step 4b — The executable contract

`specs/<n>-<slug>/ACCEPTANCE.yaml`, the executable shadow of the issue:

```yaml
spec: <n>-<slug>
criteria:
  - id: AC-1
    statement: "Rejects a row with no identifier"      # binary: two people reach the same verdict
    verification: test                                  # test | eval
    reference: tests/test_loader.py::test_rejects_row_without_id   # eval: evals/<slug>/<id>
    threshold: 0.95                                     # eval only: the bar over the case set
    issue: <n>
```

Every criterion has exactly one verification and a reference. Present the issue only when each one
does.

## Step 5 — Present, refine, create

`manager` shows me the complete issue. With my approval:

```bash
tmpfile=$(mktemp /tmp/issue-XXXXXX)
cat <<'ISSUE_EOF' > "$tmpfile"
<issue body>
ISSUE_EOF
issue_url=$(gh issue create --title "<title>" --body-file "$tmpfile" --label "...")
rm "$tmpfile"
```

Fill in `issue: <n>` in `ACCEPTANCE.yaml`, commit `spec(#n): acceptance criteria`.

No branch, no code and no PR is created. That is `/implement-issue`.

## Principles

1. No implementation.
2. The person validates an epic's decomposition before anything is created.
3. Specs are orchestrated, not hand-written in this skill.
4. Researching techniques is done before fixing a criterion you are unsure about — never
   afterwards, as a justification for something already decided.
5. `/grill-me` always runs after the light discovery, unless it already ran standalone before this
   skill. It is not an optional step for "simple" ideas — it decides how much depth is needed,
   not you.

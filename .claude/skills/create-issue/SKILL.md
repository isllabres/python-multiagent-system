---
name: create-issue
description: Interactive discovery and creation of an issue with the test, eval and metric specs embedded. ds-manager drives and writes. Never implements.
argument-hint: "[bug | feature | refactor]"
---

`ds-manager` drives the discovery and writes. Nothing is implemented in this skill.

Detect the repository with `gh repo view`. If `gh auth status` fails, stop: without an
authenticated `gh` there is nothing to do.

Type hint: $ARGUMENTS

## Step 0 — Does it already come from `/grill-me`?

If this conversation already contains a `/grill-me` synthesis (Resolved / Explicitly out of scope
/ Still open), **do not repeat Step 1 or invoke `/grill-me` again** — it is already done. Jump
straight to Step 2, using that synthesis as if it were Step 1's result.

If not, continue to Step 1.

## Step 1 — Light discovery (`ds-manager`)

**Group 1**: bug, feature or refactor? A one-sentence summary.

**Group 2**, by type — bug: current versus expected behaviour, steps, severity; feature: what
problem it solves, what success looks like from outside; refactor: what is touched, why, what
behaviour must be preserved.

**Group 3 — classification**, the decision that matters most: does it involve code? (almost
always) → **test**. LLM/agent behaviour? → **eval**. A trained model? → **metric**, and before
fixing anything it is checked that the data supports it. The three are not exclusive.

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
- **Still open** → goes into Technical notes, so `ds-developer` knows where there is legitimate
  room to decide at implementation time.

If `/grill-me` finds a contradiction between something you said in Step 1 and something you say
here, it points it out directly and asks which one prevails — it does not resolve it silently,
and neither should you resolve it on its behalf.

If during the interrogation `ds-manager` is unsure of the right technique for something specific
— which architecture, which approach from the literature for this kind of leakage — it researches
it before fixing the criterion. Do not guess when it can be verified.

## Step 2 — Scope: one issue or an epic?

Epic signals: independent deliverables, more than a day or two of work, internal dependencies.
If they apply, **`ds-manager` requires my explicit validation** of the decomposition before
generating any spec:

> "This looks like an epic: parent issue + N children [title — mandate — type — dependencies].
> Shall I proceed, adjust, or keep it as a single issue?"

Nothing is created until I approve.

## Step 2.5 — The data gate (`analyst`, only if there is a `metric` criterion)

1. Look for `experiments/*/DATA_AUDIT.md`. If it does not exist and there is a data path,
   `analyst` audits (its `data-audit` skill).
2. If there is neither a path nor an audit, `ds-manager` asks: file it with no numeric target, or
   pause until there are data?
3. Probable leakage (AUC>0.90 from a single feature) → stop: the issue to open is the leakage one.
4. `analyst`'s ceiling is a hard cap on the `metric` criterion, never the other way round.

## Step 3 — Orchestrate the specs (`ds-manager`)

The `define-tests` skill whenever there is code. The `define-evals` skill if there is LLM/agent
behaviour. The `define-metrics` skill if there is a trained model, with the Step 2.5 ceiling as
its cap. All three: return markdown, persist no files — it is embedded in the issue.

## Step 4 — Compose the issue (`ds-manager`)

Title: `[area]: imperative description`. Body: Description, Acceptance criteria (a
`[test]`/`[eval]`/`[metric]` checklist, derived from `/grill-me`'s "Resolved" block),
TDD/EDD/Metric Specification verbatim, technical notes (include `/grill-me`'s "Still open" here),
out of scope (`/grill-me`'s "Explicitly out of scope" block, verbatim).

## Step 4b — The executable contract

`specs/<n>-<slug>/ACCEPTANCE.yaml` with each criterion, its type and reference — follow the
schema in `templates/ACCEPTANCE.yaml` (commented: what each type means, when it carries a
`threshold`). `python3 gates/traceability.py` clean before presenting the issue.

## Step 5 — Present, refine, create

`ds-manager` shows me the complete issue. With my approval:

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
4. The data gate is non-negotiable with a `metric` criterion.
5. Researching techniques is done before fixing a criterion you are unsure about — never
   afterwards, as a justification for something already decided.
6. `/grill-me` always runs after the light discovery, unless it already ran standalone before this
   skill. It is not an optional step for "simple" ideas — it decides how much depth is needed,
   not you.

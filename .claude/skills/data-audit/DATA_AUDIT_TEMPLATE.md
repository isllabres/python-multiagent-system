# DATA_AUDIT — <experiment id>

<!-- First line: does the plausible ceiling reach the acceptance criteria? Say it before anything
     else. Example: "Ceiling below AC-2: probe AUC ≈ 0.68, criterion asks 0.85. Back to the spec." -->
**Verdict:** <ceiling vs criteria, in one sentence>

Data: `<path>` · rows: <n> · target: `<col>` (<task>) · audited on: <train/dev extract> · seed: <n>
Commit: <hash> · Scripts: `experiments/<id>/scripts/` · Raw output: `audit.json`, `profile.json`

## Blockers
<!-- Each one: what, evidence (number or command output), why it matters, what would resolve it.
     "None" is a valid answer only if the audit ran and found none. -->
1. **<code> — `<column>`**: <evidence>. <Why it blocks>. <What to ask / verify>.

## Risks
1. **<code>**: <evidence>. <Mitigation>.

## Recommended split
- Scheme: `<time | group | stratified | kfold>` on `<column>`
- Why: <structure found: rows per group, time range, ordering>
- Evidence: <e.g. "under a random split 100% of validation rows share a group with train; the
  probe scores 0.63 random vs 0.54 grouped">
- Random is presumed wrong unless: <what would have to be shown>

## Plausible performance ceiling
- Metric: <AUC / R² / …> · reference: <value> · basis: <probe mean + 2·sd, suspects removed>
- Trivial baseline: <value> · what the probe found: <reading>
- Caveat: heuristic from an untuned model. A target above <value> needs a stated mechanism.

## Data quality (from the profile)
<!-- Only what changes how the data are used: sentinels, placeholder strings, duplicates, gaps. -->

## Only a person can confirm
- When is `<column>` populated relative to the prediction instant?
- Was the target built with a rule that uses any feature?
- Is the observed level plausible for this domain?

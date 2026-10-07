---
name: sdd
description: How this layer does spec-driven development on top of OpenSpec — the GitHub issue as the source of truth and openspec/changes/<id>/ as its mirror on the branch <n>-<change-id>; the rules for proposal, delta specs, design and tasks; one test per scenario, written and seen failing before the code; the states a change goes through; the reviewer's checkpoints; and sdd.py, which checks all of it. Loaded by manager, implementer and reviewer.
---

# Spec-driven development on OpenSpec

OpenSpec gives the format, its validation and the lifecycle; this layer adds the issue as the
source of truth, tests before code, the reviewer and the checks. Only the OpenSpec CLI is used
(`openspec init --tools none`): no `/opsx` command. If a project already has them,
`/opsx:apply` skips red/green, the reviewer and the issue — implement through `/implement-issue`.

## The issue, the change and the mirror

- **The issue is the source of truth.** Its body carries `proposal.md`, `specs/<capability>/spec.md`,
  `design.md` and `tasks.md`, each between invisible markers (`<!-- openspec:change <id> -->`,
  then `<!-- openspec:file <path> -->` … `<!-- /openspec:file -->`). `sdd.py body` writes it;
  nobody writes markers by hand.
- **The mirror** is `openspec/changes/<id>/` on the branch `<n>-<change-id>`, written by
  `sdd.py pull <n>` in one direction only: issue → branch. Nobody edits `proposal.md`, the
  specs or `design.md` there. `tasks.md` gains ticks and notes; `review.md` and `BLOCKED.md`
  live beside it and never go to the issue.
- **A change to the spec goes to the issue first** (`/update-issue`, with the person's
  approval), then back to the mirror with `sdd.py pull`, which keeps the ticks and notes
  already made. Task-only amendments are the manager's to make, with a comment on the issue.
- **If the mirror and the issue differ** (`sdd.py diff <n>`), the issue wins. Stop and show the
  difference: never push the mirror over the issue, and never re-pull blindly over work in
  progress.

## The four files

A complete example lives in `examples/add-retry-backoff/`, with the issue body it produces in
`examples/issue-body.md`; a test keeps both valid, so copy their shape.

- **`proposal.md`** — Why (50 characters at least), What Changes, Capabilities, Impact, and an
  Out of scope section.
- **`specs/<capability>/spec.md`** — deltas under `## ADDED|MODIFIED|REMOVED|RENAMED
  Requirements`. A `### Requirement: <name>` states one observable behaviour with a single
  SHALL or MUST; never should or may. Each `#### Scenario: <name>` is binary and concrete:
  `- **WHEN** …` / `- **THEN** …`, with `- **GIVEN** …` when it needs a precondition. A
  MODIFIED requirement is written out in full.
- **`design.md`** — always, even for a small change: Context, Goals / Non-Goals, `## Files`
  (`` - `path` — modify `` or `` - `path` — new ``, one per line), Decisions with at least one
  discarded alternative and why, Risks / Trade-offs, Open Questions.
- **`tasks.md`** — one group per requirement, headed `## N. Requirement: <exact name>`; every
  task starts with its kind:

  | Kind | What it is | Commit |
  |---|---|---|
  | `[test]` | One per scenario: `` - [ ] N.k [test] `tests/<file>.py::<test>` — Scenario: <exact name> ``, before any `[code]` of its group | `red(#n-N.k)` |
  | `[guard]` | A test that already passes and must keep passing: behaviour a refactor preserves | `guard(#n-N.k)` |
  | `[code]` | The minimum that makes the group's tests pass | `green(#n-N.k)` |
  | `[remove]` | A REMOVED requirement: deletes its code and its tests | `remove(#n-N.k)` |

  **Not every change needs delta specs.** A pure refactor, a tooling or a docs change has no
  observable behaviour to state, so it carries no `specs/` artifact: only `[guard]` tasks
  (preserving behaviour) and `[code]` tasks, never `[test]`. Decide this in `/create-issue`'s
  discovery, from the person's answer, not after the fact. Mark it with
  `sdd.py skip-specs <id>` (`--off` to undo it), which sets `skip_specs: true` in the change's
  `.openspec.yaml` so OpenSpec accepts zero deltas; it refuses while `specs/` still has files.
  Pulling a change with no `specs/` files sets the same flag automatically.

## Writing the tests

- Behaviour, never implementation: the test survives any refactor that keeps the behaviour. No
  assertion on internals, never a mock of the module under test.
- The scenario's values, exactly: "returns 503 after 3 attempts", not "returns an error".
- Doubles only for what you do not control: network, clock, randomness. More than three in one
  test means the design needs rethinking.
- One behaviour per test; no `skip`, no `xfail`, no sleeps; randomness seeded.
- A bug fix starts with the scenario that reproduces it.
- Red means the behaviour is missing: an assertion about it fails, or the error names the very
  function the requirement introduces. A failure in the test's own code is not red.

## States — deduced, never stored

| State | How it shows |
|---|---|
| draft | `openspec/changes/<id>/` with no issue yet, only during `/create-issue` |
| open | An open issue with the `openspec:change` marker; `pending` if filed for later |
| in progress | The branch `<n>-<id>` with its mirror; tasks unticked or the review not APPROVED |
| verified | Every task ticked, `review.md` APPROVED, checks green, the line in `wiki/log.md` |
| in PR | The change archived on the branch and the PR open |
| done | The issue closed by the merge; no agent marks it |
| blocked | `BLOCKED.md` in the change, plus the `blocked` label and a comment on the issue |

The default branch never holds an active change: drafts are not committed, and the PR archives
the change (`openspec archive`) before it merges.

## Review checkpoints

The reviewer writes `openspec/changes/<id>/review.md`. C1–C4 come from
`sdd.py check --base <default> --remote`, never by eye.

| | Checkpoint |
|---|---|
| C1 | `openspec validate --strict` clean (an "Archive would refuse" notice counts) and every scenario has its `[test]` task |
| C2 | The mirror matches the issue, and the branch matches the change |
| C3 | Every task ticked |
| C4 | Commit discipline: red before green in every group; red and guard commits touch tests and `tasks.md` only; green commits never touch a test; a test changed after its green cites `Review: round k #n`; only `spec(#n)` commits touch the spec |
| C5 | Each test verifies exactly its scenario |
| C6 | Suite and tooling green: pytest, `ruff check`, `ruff format --check`, mypy (advisory) |
| C7 | Python quality against `python-standards`, no blocker open |
| C8 | Clean change: no scope beyond the requirements, no hardcoded green, no debug leftovers, nothing flaky |

```markdown
# Review — #<n> <change-id>

**Verdict:** APPROVED | CHANGES_REQUESTED

## Checkpoints
- [x] C1 …   (one line each, C1–C8)

## Findings
| # | Severity | Where | What is wrong | Consequence | Expected | Requirement |

## Disagreements
## Rounds
| Round | Verdict | Blockers | Relevant |
|---|---|---|---|
| 1 | CHANGES_REQUESTED | 1 | 2 |

## Wiki gaps
```

A round is a CHANGES_REQUESTED row; the cap is 3, and the fourth blocks the change.

## sdd.py

`python3 .claude/skills/sdd/scripts/sdd.py [--root DIR] <command>`. Each problem is one line;
the exit status is 1 if there is any.

| Command | Does |
|---|---|
| `init` | Set up `openspec/` (`openspec init --tools none`) and add this layer's rules to its `config.yaml` |
| `body [--change ID] [--out F]` | The issue body for a change |
| `branch N` | The branch for issue N: `<n>-<change-id>` |
| `skip-specs ID [--off]` | Mark a change as needing no delta specs, or undo it |
| `pull N` | Write the mirror of issue N, keeping the progress in `tasks.md` |
| `diff N` | Where the mirror and the issue differ |
| `stale N` / `stale --all` | Why an open issue's change may no longer apply: validation, files the design modifies, living specs changed since the issue, a closed issue |
| `status [--brief]` | Where the work stands, from disk and git only (the SessionStart hook) |
| `check [--change ID] [--base B] [--remote]` | Format and traceability; `--base` adds ticks, commit discipline, tests that exist and the wiki line; `--remote` adds drift from the issue |
| `stop-gate` | The Stop hook: exit 2 when work marked as done fails its checks |

Tests: `uv run pytest .claude/skills/sdd/tests -q` (one test needs the OpenSpec CLI on the PATH).

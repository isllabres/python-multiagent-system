# python-multiagent-system

A multi-agent system for Python development, for [OpenCode](https://opencode.ai). It installs
as a layer on top of a new or existing project and turns an idea into a pull request through
five specialised agents, spec-driven: every change is an
[OpenSpec](https://github.com/Fission-AI/OpenSpec) change, agreed before any code exists, whose
source of truth is its GitHub issue. The test of every scenario is written and seen failing
before the code that makes it pass. Each agent runs on its own model — mix Anthropic, OpenAI,
GitHub Copilot or any other provider OpenCode supports, agent by agent.

```
idea ── /create-issue ──▶ change in its issue ── /implement-issue ──▶ local PR ──▶ PR ──▶ merge
           you approve                               you confirm                     you merge
```

Three points need a person. Everything between them runs without asking.

## Install into a new project

The layer is a set of files you copy into your project. Your project keeps its own git remote:
nothing here points back to this repository, and `gh` reads the repository from your project's
remote.

Requirements: [OpenCode](https://opencode.ai), `git`, `gh` (authenticated: no `gh`, no flow),
`uv`, Python 3.11+, and the OpenSpec CLI, which needs Node.js 20.19+.

```bash
# 1. Get the layer, once
git clone https://github.com/isllabres/python-multiagent-system.git ~/code/python-multiagent-system

# 2. Export a clean snapshot of its main branch into your project (tracked files only)
git -C ~/code/python-multiagent-system archive origin/main .opencode AGENTS.md | tar -x -C ~/code/my-project

# 3. Tooling, in your project
cd ~/code/my-project
uv add --dev pytest ruff mypy
npm install -g @fission-ai/openspec@latest        # or: brew install openspec
gh auth status

# 4. Set up OpenSpec (openspec init --tools none) and add this layer's rules to its config
python3 .opencode/skills/sdd/scripts/sdd.py init

# 5. Sign in to every provider you want an agent to use
opencode providers login          # e.g. Anthropic, or set ANTHROPIC_API_KEY
opencode providers login openai   # only if you will point an agent at openai/...

# 6. Commit the layer to your project's own repository, on its own branch
git switch -c add-multiagent-layer
git add .opencode AGENTS.md openspec
git commit -m "Add the python-multiagent-system layer"
git push -u origin add-multiagent-layer

# 7. Start working
opencode
```

`git archive` is used instead of `cp -r` because it copies only tracked files, so no `.DS_Store`
or local cache comes along. Plain `opencode` already starts you as `manager` — the layer's
`.opencode/opencode.json` sets `default_agent: "manager"` — so there is no flag to remember; the
explicit form `opencode --agent manager` works too.

### Which remote

Any GitHub repository: your own, another account or organisation, or GitHub Enterprise. `gh` must be
logged in to it: `gh auth switch` for another account, `gh auth login --hostname <host>` for
Enterprise. GitLab and Bitbucket are not supported, because the flow is built on GitHub issues and
pull requests.

### Mixing providers

Each agent's model lives in its own file, as a plain `provider/model-id` string. To move
`reviewer` onto OpenAI once you have signed in:

```bash
opencode providers login openai
```

```diff
 # .opencode/agent/reviewer.md
-model: anthropic/claude-opus-5-5
+model: openai/gpt-5.4
```

`opencode models <provider>` lists what is available once you are signed in to it; `opencode
providers list` shows what is already configured. OpenCode reloads config on restart, not
mid-session: quit and start a new `opencode` session after editing an agent file.

### Before you start

- **Ruff lints the layer too.** Your `ruff check .` also covers the layer's scripts. Under a strict
  config (`select = ["ALL"]`) that is hundreds of findings, so exclude it. With ruff's default
  config the layer is clean, and pytest skips `.opencode/` on its own.

  ```toml
  [tool.ruff]
  extend-exclude = [".opencode"]
  ```

- **An existing `AGENTS.md` is overwritten by step 2**, and so is any agent, command or skill of
  yours with the same name. If you have an `AGENTS.md`, export only `.opencode`, put ours beside
  yours under another name, and import it from yours with a plain `@path` reference (OpenCode
  resolves it relative to the file that mentions it, the same convention Claude Code uses):

  ```bash
  git -C ~/code/python-multiagent-system archive origin/main .opencode | tar -x -C ~/code/my-project
  git -C ~/code/python-multiagent-system archive origin/main AGENTS.md | tar -xO > ~/code/my-project/AGENTS.multiagent.md
  ```

  then add the line `@AGENTS.multiagent.md` to your `AGENTS.md`.
- **An existing `.opencode/opencode.json` is merged, not overwritten.** Fold its `permission`
  block into yours by hand: without it the flow still works, but the bash commands the layer
  needs (`sdd.py`, `check_wiki.py`, `uv run …`, `openspec …`) will prompt every time instead of
  running straight through.
- **If you already use OpenSpec**, `sdd.py init` keeps your `openspec/` as it is. When your
  `config.yaml` has rules of its own, it prints this layer's block for you to merge. Any `/opsx`
  commands you have stay available, but `/opsx:apply` skips red/green, the reviewer and the issue:
  implement issues with `/implement-issue`.
- **The wiki starts empty.** `wiki-generator` creates `wiki/` on its first call, and `check_wiki.py`
  reports missing pages until then.
- **Your layout is respected.** The layer never creates `src/` or `tests/`; it creates only its own
  output: `openspec/` (when the project does not have it) and `wiki/`.

### Upgrading from the Claude Code version

If your project still has `.claude/` and `CLAUDE.md` from an earlier install, remove them: they
are not read by OpenCode. Old `specs/<n>-<slug>/ACCEPTANCE.yaml` folders, from even earlier, are
ignored too. An open issue from before this flow has no OpenSpec change in its body:
`/update-issue <n> -- convert to OpenSpec` writes one with your approval.

### Use it

Inside the session, three commands take you from an idea to a pull request:

```
> /grill-me "add retry with backoff to the HTTP client"   # optional: stress-test a raw idea first
> /create-issue feature     # discovery, interrogation, the change; you approve, it files the issue
> /implement-issue 12       # tests first, then code, review, wiki; stops at a local PR for you
```

After you confirm, it archives the change, pushes the branch and opens the PR on your remote. You
review it on GitHub; merging is accepting the result.

## The five agents

An **agent** (`.opencode/agent/`) is an identity: its own prompt, model, permissions and mode
(`primary` — selectable as the one you talk to; `subagent` — invoked by another agent through
the task tool; `all` — both). Each one below owns one thing and never does the others'.

| Agent | Mode | Model | Owns | Never |
|---|---|---|---|---|
| `manager` | primary | `anthropic/claude-opus-5-5` | The spec and the session: interrogates until the idea converges, writes the change, files and amends the issue, runs the other agents, keeps the round tally, decides disputes over the spec. The only agent that writes to GitHub | Writes code or tests, reviews code |
| `implementer` | subagent | `anthropic/claude-sonnet-5-5` | The implementation: works through `tasks.md`, writing each scenario's test and seeing it fail before the minimum idiomatic, typed code that makes it pass | Touches the spec, `review.md` or the issue |
| `reviewer` | subagent | `anthropic/claude-opus-5-5` | The verdict: the mechanical checks, each test against its scenario, the suite and tooling, the Python against `python-standards`, a clean scope. Writes `review.md` and nothing else | Writes code or tests, commits |
| `wiki-generator` | subagent | `anthropic/claude-sonnet-5-5` | The project wiki: once per issue, a changelog line and an entry when behaviour or architecture changed; surveys areas the wiki does not cover yet | Touches `README.md`, `AGENTS.md` or `wiki/raw/` |
| `grill-me` | all | `anthropic/claude-opus-5-5` | The interrogation: one question at a time, always with a recommendation, standalone or handed a brief by `manager` | Code, files, the issue |

Only `manager` delegates, via the task tool. The others write their work to files and reply with
one line that names the file, so nothing is relayed by word of mouth. Each agent's `model:` is
independent — see *Mixing providers* above.

## How a change flows

### 1. Write and approve the change: `/create-issue`

`manager` runs a light discovery, then hands off to the `grill-me` agent to interrogate in
depth, one question at a time with its own recommendation, reading the project's wiki before it
asks anything the code can answer. It decides whether the work is one change or an epic (you
approve the split), writes the change in `openspec/changes/<id>/` from `openspec instructions`,
and validates it with `openspec validate --strict` and `sdd.py check`. **You approve the four
files**; then the change becomes the body of a new issue and the local draft is deleted.

### 2. Implement it: `/implement-issue <n>`

- **Still applies?** `sdd.py stale <n>` validates the change against today's living specs and
  checks that what the design modifies still exists. If not, it stops and proposes `/update-issue`.
- **Branch and mirror.** The branch `<n>-<change-id>`, and `sdd.py pull <n>` writes the issue's
  change into `openspec/changes/<id>/`. When it resumes, `sdd.py diff <n>` first: if the issue
  changed meanwhile, it stops and shows you.
- **Implement.** `implementer` works through `tasks.md`: red, then green, task by task.
- **Review.** `reviewer` writes `review.md`. Up to three rounds of changes; the fourth blocks the
  change, labels the issue and comments the history.
- **Wiki and local PR.** `wiki-generator` updates the wiki once, the checks run, and you see the
  diff, the commits, the review and the wiki pages.
- **Only with your confirmation:** `openspec archive` (the living specs take the change), push,
  and the PR with `Closes #n`. It never merges.

### 3. Merge: you

You review the PR on GitHub. Merging is accepting the result, and it updates the code and
`openspec/specs/` together.

### Keeping issues honest

`/update-issue <n> -- <change>` is the only way an approved change changes: it shows you the
difference, and with your approval edits the issue and the branch's mirror. `sdd.py stale --all`
lists the open issues whose change may no longer apply.

## The change

An OpenSpec change, with this layer's rules (in `openspec/config.yaml`, so `openspec instructions`
carries them):

- `proposal.md` — why, what changes, the capabilities, the impact, what is out of scope.
- `specs/<capability>/spec.md` — `ADDED`/`MODIFIED`/`REMOVED` requirements, each one behaviour
  with a single SHALL, each scenario binary and concrete (`- **WHEN** …` / `- **THEN** …`).
- `design.md` — always: the files it touches, the decisions with a discarded alternative, risks.
- `tasks.md` — one group per requirement, one test task per scenario before the code:

```markdown
## 1. Requirement: Retry server errors

- [ ] 1.1 [test] `tests/test_client.py::test_server_error_is_retried` — Scenario: Server error is retried
- [ ] 1.2 [test] `tests/test_client.py::test_retries_are_exhausted` — Scenario: Retries are exhausted
- [ ] 1.3 [code] Retry 5xx responses in `HttpClient.get` with exponential backoff; both tests pass
```

In the issue, each file sits between invisible markers, so GitHub shows a readable document and
`sdd.py` can rebuild the change from it. The full example is in `.opencode/skills/sdd/examples/`.

Not every change needs delta specs: a pure refactor, a dependency bump or a docs change has no
observable behaviour to state. `sdd.py skip-specs <id>` marks it so — set when `/create-issue`'s
discovery confirms there is none — and its `tasks.md` carries only `[guard]` and `[code]` tasks.

## Tests before code

There is an agent for it and a check behind it. `implementer` writes each `[test]` task's test,
runs it, and commits it only if it fails because the behaviour is missing. `sdd.py check --base`
then reads the history: in every group the `red` commit comes before the `green`, `red` commits
touch only tests, `green` commits never touch one, a test changed after its green cites the
review finding, and every ticked task has its commit. `reviewer` reads each test against its
scenario, looking for anything loosened, skipped or hardcoded.

## The Stop gate

`.opencode/plugin/stop-gate.ts` keeps the flow honest without relying on the model's memory: on
every `session.idle` event it runs the same `sdd.py stop-gate`, and if a change marked as done
fails it, sends one follow-up message with the failure, so you see it fixed or blocked instead
of silently abandoned. Unfinished or blocked work goes idle freely, and it never retries more
than once in a row. `manager`'s own first action in any session is `sdd.py status --brief`,
which tells it — and you — where the active change stands.

## The wiki is the code map

Every agent reads the project wiki (`wiki/`) before it reads code. Its entries point at the code with
anchors (`src/client.py:HttpClient.get`), at the tests that verify it and at the capability's
living spec in `openspec/specs/`, which holds what the system does. An agent finds the entry, follows
the anchor and reads that symbol, not the whole module.

```
Home.md  _Sidebar.md  log.md  raw/
1.-Configuration-and-Environment.md   2.-Architecture.md   3.-Features-and-Behaviour.md
4.-Testing-and-Evaluation.md          5.-Decisions-and-Known-Issues.md   6.-Production-and-Monitoring.md
```

It is brief by rule: `wiki-generator` updates it once per issue — one `log.md` line, an entry only
when behaviour or architecture changed, three pages and 15 net lines at most, a page past 100 lines
condensed. A checker fails on anchors pointing at code that no longer exists:

```bash
python3 .opencode/skills/project-wiki/scripts/check_wiki.py
```

## Commits

One commit per task, subjects of 72 characters at most, imperative, naming the behaviour. An
issue's history reads:

```
spec(#12): pull change add-retry-backoff                     manager
red(#12-1.1): retry a request that fails with 503            implementer
red(#12-1.2): give up after three 503 responses              implementer
green(#12-1.3): retry 5xx in HttpClient.get with backoff     implementer
wiki(#12): document retries in the HTTP client               wiki-generator
spec(#12): review add-retry-backoff                          manager
spec(#12): archive add-retry-backoff                         manager
```

## Commands and skills

A **command** (`.opencode/command/`) is a named, person-triggered entry point that runs a
chosen agent with a specific prompt. A **skill** (`.opencode/skills/`) is reference material an
agent reads into its own context, either because its description matches the task or because
its own prompt points at it by name.

| Command | What it does |
|---|---|
| `/grill-me` | Interrogates a plan in depth, one question at a time, with a recommendation. Standalone or handed off from `/create-issue` |
| `/create-issue` | Discovery, grilling, the OpenSpec change; you approve it and it becomes the issue |
| `/implement-issue` | Staleness check, branch and mirror, implementer and reviewer, wiki, local PR; resumes where it stopped |
| `/update-issue` | Changes an approved change, with your approval, in the issue and the branch's mirror |

| Skill | What it does |
|---|---|
| `sdd` | The issue and its change, the format and task rules, states, checkpoints, and `sdd.py` (used by `manager`, `implementer` and `reviewer`) |
| `python-standards` | One rubric for good Python: structure, typing, language traps, errors, idioms, performance, security, tooling |
| `project-wiki` | How every agent reads the wiki as a code map, the entry format, and the checker |

## What you will find in the repository

```
AGENTS.md                 The contract: the map and the hard rules.
.opencode/
  opencode.json           default_agent and the bash permission allowlist.
  agent/*.md              The five agents.
  command/*.md            The four commands, with the scripts, tests and example that go with them.
  skills/*/SKILL.md       The three reference skills.
  plugin/stop-gate.ts     The Stop-gate plugin.
```

And in your project, once it is used:

```
openspec/specs/           What the system does now: the living specs.
openspec/changes/<id>/    A change being implemented, on its branch (archived by its PR).
wiki/                     A native GitHub Wiki: the code map and the changelog.
```

`src/`, `tests/` and the rest are your project, not this layer.

## Code quality

Before any local PR is shown: `sdd.py check --base <default-branch> --remote`, `check_wiki.py`,
`uv run ruff check .`, `uv run ruff format --check <touched paths>`, `uv run mypy <touched paths>`
and `uv run pytest -q`. `mypy` is reported but does not block, by design; a blocking check is never
relaxed to turn it green.

`ruff format` is a drop-in replacement for Black and `ruff check` covers the Flake8 rules (and
isort's, with the `I` set), so the three tools are not added separately: Black and Ruff can disagree
on edge cases and end up fighting inside the same hook.

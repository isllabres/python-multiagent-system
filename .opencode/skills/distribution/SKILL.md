---
name: distribution
description: How an installed project tracks the layer's upstream repository and version (.opencode/layer.json), pulls in a new release with a three-way merge that respects local edits, and sends a local fix back upstream as an issue. Also the release convention (vX.Y.Z tags, CHANGELOG.md) this repository itself follows. Run by the person directly, with layer_sync.py — no agent is involved.
---

A project that installed this layer keeps one small file, `.opencode/layer.json`, recording where
it came from and which release it is on:

```json
{ "repo": "https://github.com/isllabres/python-multiagent-system.git", "version": "v0.3.0" }
```

`python3 .opencode/skills/distribution/scripts/layer_sync.py` reads and updates it. It clones the
upstream repository once into `~/.cache/python-multiagent-system/layer/` and fetches it on every
call, so every command works from the real history, not from a snapshot.

## Upgrading

```bash
python3 .opencode/skills/distribution/scripts/layer_sync.py status    # what is new, from CHANGELOG.md
python3 .opencode/skills/distribution/scripts/layer_sync.py upgrade   # merge up to the latest release
```

Every file under `.opencode/` and `AGENTS.md` is handled the same way, comparing the project's
copy against the version it was installed from:

- **Untouched** (equal to the old release) → replaced outright with the new release's copy.
- **Edited, and upstream changed something else** → merged with `git merge-file` (a real
  three-way merge, not a line-count heuristic); the result is written back.
- **Edited, and upstream changed the same lines** → left with `<<<<<<<` conflict markers, same as
  a normal git conflict, for the person to resolve by hand.
- **Removed upstream but edited locally**, or **new upstream but a local file already sits at that
  path** → left alone, and named in the report.

Nothing is committed. `upgrade` prints what happened, updates `layer.json` to the new version, and
leaves `git diff` for the person to review and commit.

## Proposing an improvement upstream

```bash
python3 .opencode/skills/distribution/scripts/layer_sync.py propose-upstream .opencode/agent/manager.md
```

Diffs that one file against the version recorded in `layer.json`, shows the diff, and — only after
a yes, or with `--yes` — opens an issue on the upstream repository (`gh issue create`) with the
diff in its body, for the layer's maintainer to review and decide whether to fold it in. It never
pushes a branch or opens a PR itself.

## Releasing (for this repository's own maintainer)

A release is a `vX.Y.Z` tag on `main`, nothing more — `layer_sync.py` discovers releases with
`git tag --merged origin/HEAD`, so a commit not reachable from `main`, or a tag of another shape,
is invisible to it. `CHANGELOG.md` is read from the tag itself (`git show vX.Y.Z:CHANGELOG.md`),
never from an installed project, with one `## vX.Y.Z - YYYY-MM-DD` section per release and an
`## Unreleased` section above it for what has not shipped yet: rename that section and start a
fresh `## Unreleased` when cutting a release.

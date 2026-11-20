# Changelog

One `## vX.Y.Z - YYYY-MM-DD` section per release, read by `layer_sync.py status`/`upgrade` from
the tag itself — see `.opencode/skills/distribution/SKILL.md`. `## Unreleased` holds what has not
been tagged yet; rename it and start a fresh one when cutting a release.

## Unreleased

- Track an installed project's upstream version in `.opencode/layer.json`; `layer_sync.py` pulls
  in a new release with a three-way merge that respects local edits, and sends a local fix
  upstream as an issue with its diff (`propose-upstream`).

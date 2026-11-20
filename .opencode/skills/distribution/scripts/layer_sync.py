#!/usr/bin/env python3
"""Keep an installed layer in step with its upstream repository, and send a local fix back to it.

    python3 .opencode/skills/distribution/scripts/layer_sync.py [--root DIR] <command> [options]

.opencode/layer.json records the upstream repository and the release tag (vX.Y.Z) that the
project's copy of .opencode/ and AGENTS.md was built from. A local clone of that repository is
cached under ~/.cache/python-multiagent-system/layer/ (LAYER_SYNC_CACHE overrides it) and
fetched on every command.

  init REPO [--version TAG]   start tracking REPO; TAG defaults to its latest release
  status                      the installed version, and the changelog since it if one is behind
  upgrade [--to TAG]          merge every layer file up to TAG (latest release by default)
  propose-upstream PATH [--title T] [--yes]
                               open an issue on REPO with PATH's local changes since install

Every layer file is three-way merged against the version it was installed from: a file no one
touched locally is replaced outright, one that was edited is merged with `git merge-file`, and a
real conflict is left with <<<<<<< markers for you to resolve by hand. Nothing is committed here;
review `git diff` and commit it yourself.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

LAYER_FILE = "layer.json"
TRACKED_ROOTS = (".opencode/", "AGENTS.md")
RELEASE_TAG = re.compile(r"v\d+\.\d+\.\d+")


def cache_root() -> Path:
    """Where upstream clones are cached; LAYER_SYNC_CACHE overrides it (tests use this)."""
    custom = os.environ.get("LAYER_SYNC_CACHE")
    return (
        Path(custom)
        if custom
        else Path.home() / ".cache" / "python-multiagent-system" / "layer"
    )


class LayerError(Exception):
    """A problem the person running the command needs to fix."""


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    except FileNotFoundError as err:
        raise LayerError(f"{cmd[0]} not found") from err


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run(["git", "-C", str(root), *args], root)


def manifest_path(root: Path) -> Path:
    return root / ".opencode" / LAYER_FILE


def read_manifest(root: Path) -> dict[str, str]:
    """The tracked upstream repository and installed version, from .opencode/layer.json."""
    path = manifest_path(root)
    if not path.is_file():
        raise LayerError(
            f"{path} not found: run `init REPO` once after installing the layer"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def write_manifest(root: Path, repo: str, version: str) -> None:
    text = json.dumps({"repo": repo, "version": version}, indent=2) + "\n"
    manifest_path(root).write_text(text, encoding="utf-8")


def cache_path(repo: str) -> Path:
    name = repo.rstrip("/").removesuffix(".git").rsplit("/", 1)[-1] or "layer"
    digest = hashlib.sha256(repo.encode()).hexdigest()[:8]
    return cache_root() / f"{name}-{digest}"


def layer_clone(repo: str) -> Path:
    """A local clone of `repo`, cloned once into the cache and fetched on every call."""
    path = cache_path(repo)
    if path.is_dir():
        done = git(path, "fetch", "--quiet", "--tags", "--force", "origin")
        if done.returncode:
            raise LayerError(f"git fetch {repo}: {done.stderr.strip() or 'failed'}")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    done = run(["git", "clone", "--quiet", repo, str(path)], path.parent)
    if done.returncode:
        raise LayerError(f"git clone {repo}: {done.stderr.strip() or 'failed'}")
    return path


def releases(clone: Path) -> list[str]:
    """Release tags (vX.Y.Z) on the upstream default branch, oldest first."""
    done = git(clone, "tag", "--merged", "origin/HEAD", "--sort=version:refname")
    if done.returncode:
        raise LayerError(f"git tag: {done.stderr.strip() or 'failed'}")
    return [line for line in done.stdout.splitlines() if RELEASE_TAG.fullmatch(line)]


def latest_release(clone: Path) -> str:
    tags = releases(clone)
    if not tags:
        raise LayerError("the upstream repository has no vX.Y.Z release tag yet")
    return tags[-1]


def show(clone: Path, rev: str, path: str) -> str | None:
    """The content of `path` at `rev`, or None if it does not exist there."""
    done = git(clone, "show", f"{rev}:{path}")
    return done.stdout if done.returncode == 0 else None


def tracked_files(clone: Path, rev: str) -> set[str]:
    done = git(clone, "ls-tree", "-r", "--name-only", rev, "--", *TRACKED_ROOTS)
    if done.returncode:
        raise LayerError(f"git ls-tree {rev}: {done.stderr.strip() or 'failed'}")
    return set(done.stdout.splitlines())


def changelog(clone: Path, old_tag: str, new_tag: str) -> str:
    """The CHANGELOG.md sections released after `old_tag`, up to and including `new_tag`."""
    text = show(clone, new_tag, "CHANGELOG.md")
    order = releases(clone)
    if not text or old_tag not in order or new_tag not in order:
        return ""
    wanted = set(order[order.index(old_tag) + 1 : order.index(new_tag) + 1])
    pieces = re.split(r"(?m)^(## v\d+\.\d+\.\d+.*)$", text)
    sections = [
        header + body
        for header, body in zip(pieces[1::2], pieces[2::2])
        if header.split()[1] in wanted
    ]
    return "".join(sections).strip()


def merge_file(mine: str, base: str, theirs: str) -> tuple[str, bool]:
    """Three-way merge; returns the merged text and whether it merged without a conflict."""
    with tempfile.TemporaryDirectory() as tmp:
        tdir = Path(tmp)
        paths = {name: tdir / name for name in ("mine", "base", "theirs")}
        paths["mine"].write_text(mine, encoding="utf-8")
        paths["base"].write_text(base, encoding="utf-8")
        paths["theirs"].write_text(theirs, encoding="utf-8")
        done = subprocess.run(
            [
                "git",
                "merge-file",
                "-p",
                str(paths["mine"]),
                str(paths["base"]),
                str(paths["theirs"]),
            ],
            capture_output=True,
            text=True,
        )
        return done.stdout, done.returncode == 0


def repo_slug(repo: str) -> str:
    """`gh`'s OWNER/REPO form of a repository given as a URL or already as a slug."""
    text = repo.removesuffix(".git")
    if text.startswith("git@github.com:"):
        return text.removeprefix("git@github.com:")
    return re.sub(r"^https?://github\.com/", "", text)


@dataclass
class UpgradeReport:
    updated: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    merged: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def plan_upgrade(root: Path, clone: Path, old_tag: str, new_tag: str) -> UpgradeReport:
    """Merge every tracked file from `old_tag` to `new_tag` into `root`, in place."""
    report = UpgradeReport()
    old_files = tracked_files(clone, old_tag)
    new_files = tracked_files(clone, new_tag)
    for path in sorted(old_files | new_files):
        target = root / path
        old_text = show(clone, old_tag, path)
        new_text = show(clone, new_tag, path)
        mine_text = target.read_text(encoding="utf-8") if target.is_file() else None
        if new_text is None:
            if mine_text == old_text:
                target.unlink()
                report.removed.append(path)
            else:
                report.notes.append(
                    f"{path}: upstream removed it, but it was changed locally"
                )
            continue
        if old_text is None:
            if mine_text is None:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(new_text, encoding="utf-8")
                report.added.append(path)
            else:
                report.notes.append(
                    f"{path}: new in the layer, but a local file is already there"
                )
            continue
        if mine_text is None or mine_text == old_text:
            target.write_text(new_text, encoding="utf-8")
            report.updated.append(path)
            continue
        if mine_text == new_text:
            continue
        merged_text, clean = merge_file(mine_text, old_text, new_text)
        target.write_text(merged_text, encoding="utf-8")
        (report.merged if clean else report.conflicts).append(path)
    return report


def print_upgrade_report(
    old_tag: str, new_tag: str, report: UpgradeReport, notes: str
) -> None:
    print(f"{old_tag} -> {new_tag}")
    if notes:
        print(f"\n{notes}")
    labels = (
        ("updated", report.updated),
        ("added", report.added),
        ("removed", report.removed),
        ("merged cleanly", report.merged),
        ("left with conflicts to resolve by hand", report.conflicts),
    )
    for label, paths in labels:
        if paths:
            print(f"\n{label}:")
            for path in paths:
                print(f"  {path}")
    for note in report.notes:
        print(f"\nnote: {note}")
    print(
        "\nNothing is committed: review `git diff`, resolve any conflicts, then commit."
    )


def cmd_init(args: argparse.Namespace) -> int:
    root = args.root
    if manifest_path(root).is_file():
        raise LayerError(f"{manifest_path(root)} already exists")
    clone = layer_clone(args.repo)
    version = args.version or latest_release(clone)
    if version not in releases(clone):
        raise LayerError(f"{version} is not a release tag of {args.repo}")
    manifest_path(root).parent.mkdir(parents=True, exist_ok=True)
    write_manifest(root, args.repo, version)
    print(f"tracking {args.repo} at {version}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    manifest = read_manifest(args.root)
    clone = layer_clone(manifest["repo"])
    latest = latest_release(clone)
    if latest == manifest["version"]:
        print(f"{manifest['version']}: up to date with {manifest['repo']}")
        return 0
    print(
        f"{manifest['version']} installed, {latest} available from {manifest['repo']}"
    )
    notes = changelog(clone, manifest["version"], latest)
    print(notes or "(no changelog entries)")
    return 0


def cmd_upgrade(args: argparse.Namespace) -> int:
    root = args.root
    manifest = read_manifest(root)
    clone = layer_clone(manifest["repo"])
    old_tag = manifest["version"]
    new_tag = args.to or latest_release(clone)
    if new_tag not in releases(clone):
        raise LayerError(f"{new_tag} is not a release tag of {manifest['repo']}")
    if old_tag == new_tag:
        print(f"already at {old_tag}")
        return 0
    report = plan_upgrade(root, clone, old_tag, new_tag)
    write_manifest(root, manifest["repo"], new_tag)
    print_upgrade_report(old_tag, new_tag, report, changelog(clone, old_tag, new_tag))
    return 1 if report.conflicts else 0


def cmd_propose_upstream(args: argparse.Namespace) -> int:
    root = args.root
    manifest = read_manifest(root)
    path = args.path if args.path.is_absolute() else root / args.path
    try:
        rel_path = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as err:
        raise LayerError(f"{path} is outside {root}") from err
    if not rel_path.startswith(TRACKED_ROOTS):
        raise LayerError(
            f"{rel_path} is not part of the layer ({', '.join(TRACKED_ROOTS)})"
        )
    clone = layer_clone(manifest["repo"])
    old_text = show(clone, manifest["version"], rel_path)
    if old_text is None:
        raise LayerError(
            f"{rel_path} is not part of the layer at {manifest['version']}"
        )
    mine_text = path.read_text(encoding="utf-8")
    if mine_text == old_text:
        print(f"{rel_path}: no local change against {manifest['version']}")
        return 0
    diff = "".join(
        difflib.unified_diff(
            old_text.splitlines(keepends=True),
            mine_text.splitlines(keepends=True),
            fromfile=f"{rel_path} ({manifest['version']})",
            tofile=f"{rel_path} (yours)",
        )
    )
    title = args.title or f"Improve {rel_path}"
    body = (
        f"Found while using the layer at {manifest['version']}.\n\n```diff\n{diff}```\n"
    )
    print(f"--- {title} ---\n{body}")
    if not args.yes:
        answer = input(f"Open this issue on {manifest['repo']}? [y/N] ")
        if answer.strip().lower() != "y":
            print("not sent")
            return 1
    if not shutil.which("gh"):
        raise LayerError("gh not found: install the GitHub CLI and run gh auth login")
    with tempfile.NamedTemporaryFile(
        "w", suffix=".md", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(body)
        body_file = handle.name
    done = run(
        [
            "gh",
            "issue",
            "create",
            "--repo",
            repo_slug(manifest["repo"]),
            "--title",
            title,
            "--body-file",
            body_file,
        ],
        root,
    )
    if done.returncode:
        raise LayerError(f"gh issue create: {done.stderr.strip() or 'failed'}")
    print(done.stdout.strip())
    return 0


COMMANDS = {
    "init": cmd_init,
    "status": cmd_status,
    "upgrade": cmd_upgrade,
    "propose-upstream": cmd_propose_upstream,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", type=Path, default=Path("."), help="the project root")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("repo")
    init.add_argument("--version")
    sub.add_parser("status")
    upgrade = sub.add_parser("upgrade")
    upgrade.add_argument("--to")
    propose = sub.add_parser("propose-upstream")
    propose.add_argument("path", type=Path)
    propose.add_argument("--title")
    propose.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)
    args.root = args.root.resolve()
    try:
        return COMMANDS[args.command](args)
    except LayerError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

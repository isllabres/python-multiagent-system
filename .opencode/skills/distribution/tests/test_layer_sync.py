"""Tests for layer_sync.py, on throwaway git repositories with a fake `gh` executable.

Run: uv run pytest .opencode/skills/distribution/tests -q
"""

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).parent.parent
SCRIPT = SKILL / "scripts" / "layer_sync.py"
spec = importlib.util.spec_from_file_location("layer_sync", SCRIPT)
assert spec and spec.loader
layer_sync = importlib.util.module_from_spec(spec)
sys.modules["layer_sync"] = layer_sync
spec.loader.exec_module(layer_sync)

GH = """\
import json, os, sys
args = sys.argv[1:]
if args[:2] == ["issue", "create"]:
    record = json.loads(open(os.environ["FAKE_GH_CALLS"]).read()) if os.path.exists(
        os.environ["FAKE_GH_CALLS"]
    ) else []
    body = open(args[args.index("--body-file") + 1]).read()
    record.append({"args": args, "body": body})
    open(os.environ["FAKE_GH_CALLS"], "w").write(json.dumps(record))
    print("https://github.com/acme/layer/issues/7")
else:
    sys.exit(2)
"""


def git(root: Path, *args: str) -> str:
    import subprocess

    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout


def commit(root: Path, subject: str, files: dict[str, str | None]) -> None:
    for path, text in files.items():
        target = root / path
        if text is None:
            git(root, "rm", "-q", path)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        git(root, "add", path)
    git(root, "commit", "-q", "-m", subject)


def init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "Test")
    git(root, "config", "commit.gpgsign", "false")


@pytest.fixture
def upstream(tmp_path: Path) -> Path:
    """A layer repository with two releases: v0.1.0 and v0.2.0."""
    root = tmp_path / "upstream"
    init_repo(root)
    commit(
        root,
        "v0.1.0",
        {
            "AGENTS.md": "the contract\n",
            ".opencode/agent/manager.md": "one\ntwo\nthree\n",
            ".opencode/old-notice.md": "will be dropped\n",
            "CHANGELOG.md": "## v0.1.0 - 2026-01-01\n- first release\n",
        },
    )
    git(root, "tag", "v0.1.0")
    commit(
        root,
        "v0.2.0",
        {
            ".opencode/agent/manager.md": "one\ntwo\nthree THEIRS\n",
            ".opencode/old-notice.md": None,
            ".opencode/skills/new-thing/SKILL.md": "a new skill\n",
            "CHANGELOG.md": (
                "## v0.2.0 - 2026-02-01\n- drop old-notice, add new-thing\n\n"
                "## v0.1.0 - 2026-01-01\n- first release\n"
            ),
        },
    )
    git(root, "tag", "v0.2.0")
    return root


@pytest.fixture
def project(tmp_path: Path, upstream: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project with the layer installed at v0.1.0, and a private cache for clones."""
    root = tmp_path / "project"
    init_repo(root)
    commit(root, "init", {"README.md": "x\n"})
    monkeypatch.setenv("LAYER_SYNC_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("FAKE_GH_CALLS", str(tmp_path / "gh-calls.json"))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "gh"
    exe.write_text(f"#!{sys.executable}\n{GH}")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    code, out, err = cli(root, "init", str(upstream), "--version", "v0.1.0")
    assert code == 0, err
    for path, text in (
        ("AGENTS.md", "the contract\n"),
        (".opencode/agent/manager.md", "one\ntwo\nthree\n"),
        (".opencode/old-notice.md", "will be dropped\n"),
    ):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    return root


def cli(root: Path, *args: str, stdin: str | None = None) -> tuple[int, str, str]:
    import subprocess

    done = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), *args],
        capture_output=True,
        text=True,
        input=stdin,
    )
    return done.returncode, done.stdout, done.stderr


def test_init_tracks_the_requested_version(
    tmp_path: Path, upstream: Path, monkeypatch
) -> None:
    root = tmp_path / "fresh"
    init_repo(root)
    monkeypatch.setenv("LAYER_SYNC_CACHE", str(tmp_path / "cache"))
    code, out, err = cli(root, "init", str(upstream), "--version", "v0.1.0")
    assert code == 0, err
    manifest = json.loads((root / ".opencode" / "layer.json").read_text())
    assert manifest == {"repo": str(upstream), "version": "v0.1.0"}


def test_init_defaults_to_the_latest_release(
    tmp_path: Path, upstream: Path, monkeypatch
) -> None:
    root = tmp_path / "fresh"
    init_repo(root)
    monkeypatch.setenv("LAYER_SYNC_CACHE", str(tmp_path / "cache"))
    code, out, err = cli(root, "init", str(upstream))
    assert code == 0, err
    manifest = json.loads((root / ".opencode" / "layer.json").read_text())
    assert manifest["version"] == "v0.2.0"


def test_init_rejects_an_unknown_version(
    tmp_path: Path, upstream: Path, monkeypatch
) -> None:
    root = tmp_path / "fresh"
    init_repo(root)
    monkeypatch.setenv("LAYER_SYNC_CACHE", str(tmp_path / "cache"))
    code, out, err = cli(root, "init", str(upstream), "--version", "v9.9.9")
    assert code == 1
    assert "not a release tag" in err


def test_status_reports_an_available_update_and_its_changelog(project: Path) -> None:
    code, out, err = cli(project, "status")
    assert code == 0, err
    assert "v0.1.0 installed, v0.2.0 available" in out
    assert "drop old-notice, add new-thing" in out
    assert "first release" not in out  # already-installed entries are not repeated


def test_upgrade_replaces_an_untouched_file(project: Path) -> None:
    code, out, err = cli(project, "upgrade")
    assert code == 0, err
    assert (
        project / ".opencode" / "skills" / "new-thing" / "SKILL.md"
    ).read_text() == ("a new skill\n")
    assert not (project / ".opencode" / "old-notice.md").exists()
    manifest = json.loads((project / ".opencode" / "layer.json").read_text())
    assert manifest["version"] == "v0.2.0"


def test_upgrade_merges_a_disjoint_local_edit_cleanly(project: Path) -> None:
    manager = project / ".opencode" / "agent" / "manager.md"
    manager.write_text("one MINE\ntwo\nthree\n")
    code, out, err = cli(project, "upgrade")
    assert code == 0, err
    assert manager.read_text() == "one MINE\ntwo\nthree THEIRS\n"
    assert "merged cleanly" in out


def test_upgrade_leaves_conflict_markers_on_the_same_line(project: Path) -> None:
    manager = project / ".opencode" / "agent" / "manager.md"
    manager.write_text("one\ntwo\nthree MINE\n")
    code, out, err = cli(project, "upgrade")
    assert code == 1, err
    assert "<<<<<<<" in manager.read_text()
    assert "left with conflicts" in out


def test_upgrade_keeps_an_edited_file_upstream_removed(project: Path) -> None:
    notice = project / ".opencode" / "old-notice.md"
    notice.write_text("will be dropped, but I still need this\n")
    code, out, err = cli(project, "upgrade")
    assert code == 0, err
    assert notice.is_file()
    assert "upstream removed it, but it was changed locally" in out


def test_upgrade_when_already_current_is_a_no_op(project: Path) -> None:
    cli(project, "upgrade")
    code, out, err = cli(project, "upgrade")
    assert code == 0, err
    assert "already at v0.2.0" in out


def test_propose_upstream_with_no_local_change_does_nothing(project: Path) -> None:
    code, out, err = cli(project, "propose-upstream", "AGENTS.md")
    assert code == 0, err
    assert "no local change" in out


def test_propose_upstream_declines_without_yes(project: Path) -> None:
    manager = project / ".opencode" / "agent" / "manager.md"
    manager.write_text("one\ntwo\nthree MINE\n")
    code, out, err = cli(project, "propose-upstream", str(manager), stdin="n\n")
    assert code == 1, err
    assert "not sent" in out


def test_propose_upstream_opens_an_issue_with_the_diff(project: Path) -> None:
    manager = project / ".opencode" / "agent" / "manager.md"
    manager.write_text("one\ntwo\nthree MINE\n")
    code, out, err = cli(project, "propose-upstream", str(manager), "--yes")
    assert code == 0, err
    assert "https://github.com/acme/layer/issues/7" in out
    calls = json.loads(Path(os.environ["FAKE_GH_CALLS"]).read_text())
    assert len(calls) == 1
    assert "--repo" in calls[0]["args"]
    assert "three MINE" in calls[0]["body"]


def test_propose_upstream_rejects_a_path_outside_the_layer(project: Path) -> None:
    (project / "README.md").write_text("changed\n")
    code, out, err = cli(project, "propose-upstream", "README.md")
    assert code == 1
    assert "not part of the layer" in err


def test_merge_file_merges_disjoint_edits_cleanly() -> None:
    base = "a\nb\nc\nd\ne\nf\ng\n"
    merged, clean = layer_sync.merge_file(
        "a\nB\nc\nd\ne\nf\ng\n", base, "a\nb\nc\nd\ne\nf\nG\n"
    )
    assert clean
    assert merged == "a\nB\nc\nd\ne\nf\nG\n"


def test_merge_file_reports_a_real_conflict() -> None:
    merged, clean = layer_sync.merge_file("mine\n", "base\n", "theirs\n")
    assert not clean
    assert "<<<<<<<" in merged


def test_repo_slug_from_an_https_url() -> None:
    assert layer_sync.repo_slug("https://github.com/acme/layer.git") == "acme/layer"


def test_repo_slug_from_an_ssh_url() -> None:
    assert layer_sync.repo_slug("git@github.com:acme/layer.git") == "acme/layer"

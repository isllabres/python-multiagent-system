"""Tests for check_wiki.py, on throwaway wikis and throwaway git repositories.

Run: uv run pytest .claude/skills/project-wiki/tests -q
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "check_wiki.py"
spec = importlib.util.spec_from_file_location("check_wiki", SCRIPT)
assert spec and spec.loader
cw = importlib.util.module_from_spec(spec)
sys.modules["check_wiki"] = cw
spec.loader.exec_module(cw)

FEATURE = (
    "### Reject rows without customer_id\n"
    "Rows with no id raise before load.\n"
    "Code: `src/loader.py:load_rows` · Tests: `tests/test_loader.py::test_rejects_row`\n"
    "See: [fail fast](5.-Decisions-and-Known-Issues.md)\n"
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project with source, tests and a complete, valid wiki."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "loader.py").write_text(
        "LIMIT = 10\n\n\nclass Loader:\n    def read(self): ...\n\n\ndef load_rows(rows): ...\n"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_loader.py").write_text("def test_rejects_row(): ...\n")
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    for name in cw.PAGES:
        (wiki / name).write_text(f"# {name}\n")
    (wiki / "3.-Features-and-Behaviour.md").write_text("# Features\n\n" + FEATURE)
    (wiki / "Home.md").write_text(
        "# Home\n" + "".join(f"- [{p}]({p})\n" for p in cw.PAGES)
    )
    (wiki / "_Sidebar.md").write_text("".join(f"- [{p}]({p})\n" for p in cw.PAGES))
    (wiki / "log.md").write_text("# Changelog\n")
    return tmp_path


def run(project: Path, *extra: str) -> tuple[int, str]:
    out = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--wiki",
            str(project / "wiki"),
            "--root",
            str(project),
            *extra,
        ],
        capture_output=True,
        text=True,
    )
    return out.returncode, out.stdout


def test_valid_wiki_passes(project: Path) -> None:
    assert run(project) == (0, "wiki ok\n")


def test_missing_page_and_sidebar_link(project: Path) -> None:
    (project / "wiki" / "6.-Production-and-Monitoring.md").unlink()
    (project / "wiki" / "_Sidebar.md").write_text("- [Home](Home.md)\n")
    code, out = run(project)
    assert code == 1
    assert "missing: 6.-Production-and-Monitoring.md" in out
    assert "_Sidebar.md does not link 2.-Architecture.md" in out


def test_page_over_the_line_limit(project: Path) -> None:
    arch = project / "wiki" / "2.-Architecture.md"
    arch.write_text("line\n" * 100)
    assert run(project)[0] == 0
    arch.write_text("line\n" * 101)
    code, out = run(project)
    assert code == 1 and "2.-Architecture.md: 101 lines" in out


def test_changelog_line_too_long_or_not_a_line(project: Path) -> None:
    log = project / "wiki" / "log.md"
    log.write_text("# Changelog\n- " + "x" * 99 + "\nloose prose\n")
    out = run(project)[1]
    assert "log.md:2: 101 characters" in out
    assert "log.md:3: not a one-line entry" in out
    log.write_text("# Changelog\n- " + "x" * 98 + "\n")
    assert run(project)[0] == 0


def test_decision_longer_than_five_lines(project: Path) -> None:
    page = project / "wiki" / "5.-Decisions-and-Known-Issues.md"
    five = "### 📌 Decision: fail fast\n" + "line\n" * 5
    page.write_text("# Decisions\n\n" + five)
    assert run(project)[0] == 0
    page.write_text("# Decisions\n\n" + five + "one more\n")
    out = run(project)[1]
    assert "'### 📌 Decision: fail fast' is 7 lines" in out


def test_broken_page_link(project: Path) -> None:
    page = project / "wiki" / "3.-Features-and-Behaviour.md"
    page.write_text(
        page.read_text() + "See [gone](9.-Nothing.md#x) and [web](https://x.io/a.md).\n"
    )
    out = run(project)[1]
    assert "3.-Features-and-Behaviour.md: broken link to 9.-Nothing.md" in out
    assert "x.io" not in out


@pytest.mark.parametrize(
    ("anchor", "expected"),
    [
        ("`src/loader.py`", None),
        ("`src/loader.py:load_rows`", None),
        ("`src/loader.py:Loader.read`", None),
        ("`src/loader.py:LIMIT`", None),
        ("`tests/test_loader.py::test_rejects_row`", None),
        ("`src/nowhere.py:load_rows`", "stale anchor src/nowhere.py: no such file"),
        ("`src/loader.py:gone`", "stale anchor src/loader.py:gone: not defined there"),
        (
            "`src/loader.py:Loader.write`",
            "stale anchor src/loader.py:Loader.write: not defined there",
        ),
    ],
)
def test_anchors(project: Path, anchor: str, expected: str | None) -> None:
    page = project / "wiki" / "2.-Architecture.md"
    page.write_text(f"# Architecture\n\nCode: {anchor}\n")
    code, out = run(project)
    if expected is None:
        assert (code, out) == (0, "wiki ok\n")
    else:
        assert code == 1 and expected in out


def test_a_mention_in_a_comment_is_not_a_definition(project: Path) -> None:
    (project / "src" / "loader.py").write_text("# load_rows used to live here\n")
    page = project / "wiki" / "2.-Architecture.md"
    page.write_text("# Architecture\n\nCode: `src/loader.py:load_rows`\n")
    assert "not defined there" in run(project)[1]


def git(project: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(project), *args], capture_output=True, text=True, check=True
    )
    return done.stdout.strip()


@pytest.fixture
def repo(project: Path) -> Path:
    git(project, "init", "-q", "-b", "main")
    git(project, "config", "user.email", "t@t")
    git(project, "config", "user.name", "t")
    git(project, "add", ".")
    git(project, "commit", "-qm", "base")
    git(project, "checkout", "-q", "-b", "5-x")
    return project


def commit(repo: Path, name: str, subject: str) -> str:
    (repo / name).write_text(subject)
    git(repo, "add", name)
    git(repo, "commit", "-qm", subject)
    return git(repo, "rev-parse", "--short", "HEAD")


def test_changelog_reports_commits_without_a_line(repo: Path) -> None:
    red = commit(repo, "r.txt", "red(#5-AC1): reject empty ids")
    green = commit(repo, "g.txt", "green(#5-AC1): reject empty ids in load")
    commit(repo, "w.txt", f"wiki(#5-AC1): log {red}")
    log = repo / "wiki" / "log.md"
    log.write_text(
        f"# Changelog\n- 2026-10-01 · {red} · red(#5-AC1): reject empty ids\n"
    )
    code, out = run(repo, "--base", "main")
    assert code == 1
    assert f"no line for commit {green}" in out
    assert f"no line for commit {red}" not in out
    assert "wiki(" not in out
    log.write_text(
        log.read_text() + f"- 2026-10-01 · {green} · green(#5-AC1): reject empty ids\n"
    )
    assert run(repo, "--base", "main") == (0, "wiki ok\n")


def test_changelog_check_is_off_without_base(repo: Path) -> None:
    commit(repo, "r.txt", "red(#5-AC1): reject empty ids")
    assert run(repo) == (0, "wiki ok\n")


def test_unknown_base_is_reported_not_crashed(repo: Path) -> None:
    code, out = run(repo, "--base", "nope")
    assert code == 1 and "cannot read git history nope..HEAD" in out

"""Tests for sdd.py, on throwaway git repositories with fake `gh` and `openspec` executables.

Run: uv run pytest .claude/skills/sdd/tests -q
The test marked `real_openspec` runs only when the OpenSpec CLI is on the PATH.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).parent.parent
SCRIPT = SKILL / "scripts" / "sdd.py"
EXAMPLE = SKILL / "examples" / "add-retry-backoff"
CHANGE = "add-retry-backoff"
spec = importlib.util.spec_from_file_location("sdd", SCRIPT)
assert spec and spec.loader
sdd = importlib.util.module_from_spec(spec)
sys.modules["sdd"] = sdd
spec.loader.exec_module(sdd)

GH = """\
import json, os, sys
issues = json.loads(open(os.environ["FAKE_GH_ISSUES"]).read())
args = sys.argv[1:]
if args[:2] == ["issue", "view"]:
    if args[2] not in issues:
        sys.exit(f"could not find issue {args[2]}")
    print(json.dumps(issues[args[2]]))
elif args[:2] == ["issue", "list"]:
    print(json.dumps(list(issues.values())))
else:
    sys.exit(2)
"""
OPENSPEC = """\
import json, os, pathlib, sys
args = sys.argv[1:]
if args[0] == "validate":
    item = {"id": args[1], "valid": True, "issues": []}
    print(os.environ.get("FAKE_VALIDATE") or json.dumps({"items": [item]}))
elif args[0] == "init":
    home = pathlib.Path(args[-1]) / "openspec"
    (home / "specs").mkdir(parents=True)
    (home / "config.yaml").write_text("schema: spec-driven\\n\\n# rules:\\n#   tasks: []\\n")
else:
    sys.exit(2)
"""
TEST_CLIENT = "def test_server_error_is_retried(): ...\n\n\ndef test_retries_are_exhausted(): ...\n"


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout


def commit(
    root: Path, subject: str, files: dict[str, str | None], body: str = ""
) -> None:
    for path, text in files.items():
        target = root / path
        if text is None:
            git(root, "rm", "-q", path)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        git(root, "add", path)
    git(root, "commit", "-q", "-m", subject, *(["-m", body] if body else []))


def example_files() -> dict[str, str]:
    return {
        p.relative_to(EXAMPLE).as_posix(): p.read_text() for p in EXAMPLE.rglob("*.md")
    }


def tick(tasks: str, *numbers: str, note: str = "") -> str:
    for number in numbers:
        tasks = tasks.replace(f"- [ ] {number} ", f"- [x] {number} ", 1)
        if note:
            line = next(line for line in tasks.splitlines() if f"] {number} " in line)
            tasks = tasks.replace(line, line + note, 1)
    return tasks


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project on main with OpenSpec set up, and fake gh and openspec on the PATH."""
    root = tmp_path / "project"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "Test")
    git(root, "config", "commit.gpgsign", "false")
    commit(
        root,
        "init",
        {"openspec/config.yaml": "schema: spec-driven\n", "README.md": "x\n"},
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, code in (("gh", GH), ("openspec", OPENSPEC)):
        exe = bin_dir / name
        exe.write_text(f"#!{sys.executable}\n{code}")
        exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_GH_ISSUES", str(tmp_path / "issues.json"))
    monkeypatch.delenv("FAKE_VALIDATE", raising=False)
    publish(root, 12, sdd.render_body(CHANGE, sdd.change_files(EXAMPLE)))
    return root


def publish(
    root: Path, number: int, body: str, created: str = "2026-01-01T00:00:00Z"
) -> None:
    """Make a fake GitHub issue with this body."""
    path = Path(os.environ["FAKE_GH_ISSUES"])
    issues = json.loads(path.read_text()) if path.is_file() else {}
    issues[str(number)] = {
        "number": number,
        "title": "Retry server errors",
        "body": body,
        "state": "OPEN",
        "createdAt": created,
    }
    path.write_text(json.dumps(issues))


def cli(root: Path, *args: str, stdin: str | None = None) -> tuple[int, str, str]:
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), *args],
        capture_output=True,
        text=True,
        input=stdin,
    )
    return done.returncode, done.stdout, done.stderr


def implement(root: Path) -> Path:
    """The branch 12-add-retry-backoff, built red before green, with every task ticked."""
    git(root, "switch", "-q", "-c", f"12-{CHANGE}")
    assert cli(root, "pull", "12")[0] == 0
    git(root, "add", "openspec")
    git(root, "commit", "-q", "-m", f"spec(#12): pull change {CHANGE}")
    tasks_path = root / "openspec" / "changes" / CHANGE / "tasks.md"
    tasks = tasks_path.read_text()
    tasks_file = f"openspec/changes/{CHANGE}/tasks.md"
    tasks = tick(tasks, "1.1", note=" — red: AssertionError: 1 attempt, expected 3")
    commit(
        root,
        "red(#12-1.1): retry a 503",
        {"tests/test_client.py": TEST_CLIENT, tasks_file: tasks},
    )
    tasks = tick(tasks, "1.2")
    commit(
        root,
        "red(#12-1.2): give up after three 503s",
        {tasks_file: tasks, "tests/conftest.py": ""},
    )
    tasks = tick(tasks, "1.3")
    commit(
        root,
        "green(#12-1.3): retry 5xx in HttpClient.get",
        {"src/client.py": "x = 1\n", tasks_file: tasks},
    )
    return root / "openspec" / "changes" / CHANGE


# --- the issue body and the mirror ------------------------------------------------------


def test_the_body_round_trips_and_matches_the_example() -> None:
    files = sdd.change_files(EXAMPLE)
    body = sdd.render_body(CHANGE, files)
    assert sdd.parse_body(body) == (CHANGE, files)
    assert body == (SKILL / "examples" / "issue-body.md").read_text()


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (
            lambda b: b.replace("openspec:change", "openspec:other"),
            "no `<!-- openspec:change",
        ),
        (lambda b: b.replace("<!-- /openspec:file -->", "", 1), "does not close"),
        (
            lambda b: b.replace(
                "openspec:file design.md", "openspec:file ../design.md"
            ),
            "unexpected file",
        ),
        (lambda b: b.split("**`tasks.md`**")[0], "no tasks.md"),
    ],
)
def test_a_broken_body_is_refused_with_a_reason(edit, message: str) -> None:
    body = sdd.render_body(CHANGE, sdd.change_files(EXAMPLE))
    with pytest.raises(sdd.SddError, match=message):
        sdd.parse_body(edit(body))


def test_canonical_tasks_drop_ticks_notes_and_local_sections() -> None:
    local = tick(
        (EXAMPLE / "tasks.md").read_text(), "1.1", note=" — red: AssertionError"
    )
    local += "\n## Replies to review\n\n- round 1 #2: the spec asks for it\n"
    assert sdd.canonical_tasks(local) == (EXAMPLE / "tasks.md").read_text()


def test_merge_keeps_the_progress_of_unchanged_tasks() -> None:
    issue = (EXAMPLE / "tasks.md").read_text() + "- [ ] 1.4 [code] Log each retry\n"
    local = tick((EXAMPLE / "tasks.md").read_text(), "1.1", note=" — red: boom")
    local += "\n## Wiki gaps\n\n- no entry for the client\n"
    merged = sdd.merge_progress(issue, local)
    assert "- [x] 1.1 [test]" in merged and merged.count("— red: boom") == 1
    assert "- [ ] 1.2 [test]" in merged and "- [ ] 1.4 [code] Log each retry" in merged
    assert merged.rstrip().endswith("## Wiki gaps\n\n- no entry for the client")


def test_pull_writes_the_mirror_and_a_second_pull_keeps_its_progress(
    repo: Path,
) -> None:
    assert cli(repo, "pull", "12")[0] == 0
    mirror = repo / "openspec" / "changes" / CHANGE
    assert sdd.change_files(mirror) == sdd.change_files(EXAMPLE)
    (mirror / "tasks.md").write_text(
        tick((mirror / "tasks.md").read_text(), "1.1", note=" — red: x")
    )
    assert cli(repo, "pull", "12")[0] == 0
    assert "- [x] 1.1 [test]" in (mirror / "tasks.md").read_text()
    assert cli(repo, "diff", "12")[:2] == (0, "mirror matches #12\n")


def test_diff_shows_an_issue_edited_by_hand(repo: Path) -> None:
    cli(repo, "pull", "12")
    edited = sdd.render_body(CHANGE, sdd.change_files(EXAMPLE)).replace(
        "returns 200", "returns 201"
    )
    publish(repo, 12, edited)
    code, out, _ = cli(repo, "diff", "12")
    assert code == 1
    assert (
        "+- **WHEN** the first two attempts return 503 and the third returns 200" in out
    )
    assert out.endswith("drift: 1 file(s) differ\n")


def test_a_change_without_specs_is_pulled_as_skip_specs(repo: Path) -> None:
    files = {
        name: text
        for name, text in sdd.change_files(EXAMPLE).items()
        if not name.startswith("specs/")
    }
    publish(repo, 13, sdd.render_body("split-loader", files))
    assert cli(repo, "pull", "13")[0] == 0
    meta = repo / "openspec" / "changes" / "split-loader" / ".openspec.yaml"
    assert meta.read_text() == "schema: spec-driven\nskip_specs: true\n"


def test_pulling_a_skip_specs_change_keeps_its_other_openspec_yaml_lines(
    repo: Path,
) -> None:
    files = {
        name: text
        for name, text in sdd.change_files(EXAMPLE).items()
        if not name.startswith("specs/")
    }
    publish(repo, 14, sdd.render_body("split-loader", files))
    mirror = repo / "openspec" / "changes" / "split-loader"
    mirror.mkdir(parents=True)
    (mirror / ".openspec.yaml").write_text("schema: spec-driven\ncreated: 2026-01-01\n")
    assert cli(repo, "pull", "14")[0] == 0
    assert (mirror / ".openspec.yaml").read_text() == (
        "schema: spec-driven\ncreated: 2026-01-01\nskip_specs: true\n"
    )


# --- skip_specs, for a change with no behaviour to verify --------------------------------


def test_skip_specs_sets_and_clears_the_flag(repo: Path) -> None:
    change = repo / "openspec" / "changes" / "split-loader"
    change.mkdir(parents=True)
    assert cli(repo, "skip-specs", "split-loader")[0] == 0
    assert sdd.has_skip_specs(change)
    assert cli(repo, "skip-specs", "split-loader", "--off")[0] == 0
    assert not sdd.has_skip_specs(change)


def test_skip_specs_refuses_a_change_that_has_delta_specs(repo: Path) -> None:
    change = repo / "openspec" / "changes" / CHANGE
    shutil.copytree(EXAMPLE, change)
    code, _, err = cli(repo, "skip-specs", CHANGE)
    assert code == 1 and "has delta specs" in err


def test_skip_specs_set_and_specs_present_is_a_format_problem(tmp_path: Path) -> None:
    change = tmp_path / CHANGE
    shutil.copytree(EXAMPLE, change)
    (change / ".openspec.yaml").write_text("schema: spec-driven\nskip_specs: true\n")
    assert any(
        "skip_specs is set but specs/ has delta files" in problem
        for problem in sdd.format_problems(change)
    )


# --- format and traceability ------------------------------------------------------------


def test_the_example_change_is_well_formed() -> None:
    assert sdd.format_problems(EXAMPLE) == []
    assert sdd.traceability(EXAMPLE) == []


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        (
            "- [ ] 1.2 [test]",
            "- [ ] 1.2 [code]",
            "scenario 'Retries are exhausted' has 0 [test] tasks",
        ),
        (
            "1. Requirement: Retry server errors",
            "1. Requirement: Retry",
            "no `## N. Requirement: Retry server errors`",
        ),
        (
            "[test] `tests/test_client.py::test_retries_are_exhausted`",
            "[test] the exhaustion test",
            "names no test",
        ),
        ("- [ ] 1.1 [test]", "- [ ] 1.1", "has no kind"),
    ],
)
def test_traceability_names_what_is_missing(
    tmp_path: Path, old: str, new: str, expected: str
) -> None:
    change = tmp_path / CHANGE
    shutil.copytree(EXAMPLE, change)
    tasks = change / "tasks.md"
    tasks.write_text(tasks.read_text().replace(old, new))
    assert any(expected in problem for problem in sdd.traceability(change)), (
        sdd.traceability(change)
    )


def test_a_test_task_after_a_code_task_is_reported(tmp_path: Path) -> None:
    change = tmp_path / CHANGE
    shutil.copytree(EXAMPLE, change)
    tasks = change / "tasks.md"
    tasks.write_text(
        tasks.read_text()
        + "- [ ] 1.4 [test] `tests/test_client.py::test_more` — Scenario: Retries are exhausted\n"
    )
    assert any("1.4 come after a [code] task" in p for p in sdd.traceability(change))


def test_a_removed_requirement_needs_a_remove_task(tmp_path: Path) -> None:
    change = tmp_path / CHANGE
    shutil.copytree(EXAMPLE, change)
    spec_file = change / "specs" / "http-client" / "spec.md"
    spec_file.write_text(
        spec_file.read_text()
        + "\n## REMOVED Requirements\n\n### Requirement: Old timeout\n**Reason**: replaced\n"
    )
    (change / "tasks.md").write_text(
        (change / "tasks.md").read_text()
        + "\n## 2. Requirement: Old timeout\n\n- [ ] 2.1 [code] Drop it\n"
    )
    assert any(
        "removed 'Old timeout' has no [remove] task" in p
        for p in sdd.traceability(change)
    )


def test_a_design_without_its_files_section_is_reported(tmp_path: Path) -> None:
    change = tmp_path / CHANGE
    shutil.copytree(EXAMPLE, change)
    design = change / "design.md"
    design.write_text(design.read_text().replace("## Files", "## Touched"))
    assert sdd.format_problems(change) == [
        "design.md: no `## Files` section listing - `path` — modify or - `path` — new"
    ]


def test_an_archive_refusal_counts_and_other_info_does_not(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issues = [
        {"level": "INFO", "path": "file", "message": "skip_specs is set"},
        {
            "level": "INFO",
            "path": "x/spec.md",
            "message": "Archive would refuse this delta: not found",
        },
    ]
    monkeypatch.setenv(
        "FAKE_VALIDATE",
        json.dumps({"items": [{"id": CHANGE, "valid": True, "issues": issues}]}),
    )
    assert sdd.validate(repo, CHANGE) == [
        "openspec: x/spec.md: Archive would refuse this delta: not found"
    ]


# --- commit discipline ------------------------------------------------------------------


def test_a_branch_built_red_before_green_passes(repo: Path) -> None:
    implement(repo)
    assert cli(repo, "check", "--base", "main")[:2] == (0, "check ok\n")


@pytest.mark.parametrize(
    ("subject", "files", "body", "expected"),
    [
        (
            "red(#12-1.1): sneak code in",
            {"src/other.py": "y = 2\n"},
            "",
            "touches tests and tasks.md only",
        ),
        (
            "green(#12-1.3): loosen a test",
            {"tests/test_client.py": TEST_CLIENT + "\n# loose\n"},
            "",
            "never touches a test",
        ),
        (
            "red(#12-1.2): tighten a test",
            {"tests/test_client.py": TEST_CLIENT + "\n# tighter\n"},
            "",
            "without citing `Review: round",
        ),
        ("tidy up", {"src/client.py": "x = 2\n"}, "", "not a flow commit"),
        (
            "spec(#12): sneak code in",
            {"src/client.py": "x = 3\n"},
            "",
            "outside openspec/",
        ),
        (
            "green(#12-1.1): wrong kind",
            {"src/client.py": "x = 4\n"},
            "",
            "is [test]; green is for [code]",
        ),
    ],
)
def test_a_commit_that_breaks_the_discipline_is_reported(
    repo: Path, subject: str, files: dict[str, str], body: str, expected: str
) -> None:
    implement(repo)
    commit(repo, subject, files, body)
    code, out, _ = cli(repo, "check", "--base", "main")
    assert code == 1 and expected in out, out


def test_a_test_fixed_in_a_review_round_passes(repo: Path) -> None:
    implement(repo)
    commit(
        repo,
        "red(#12-1.2): assert the status",
        {"tests/test_client.py": TEST_CLIENT + "\n"},
        "Review: round 1 #2",
    )
    assert cli(repo, "check", "--base", "main")[0] == 0


def test_green_before_red_and_a_ticked_task_without_commit_are_reported(
    repo: Path,
) -> None:
    git(repo, "switch", "-q", "-c", f"12-{CHANGE}")
    cli(repo, "pull", "12")
    tasks_file = f"openspec/changes/{CHANGE}/tasks.md"
    tasks = (repo / tasks_file).read_text()
    git(repo, "add", "openspec")
    git(repo, "commit", "-q", "-m", f"spec(#12): pull change {CHANGE}")
    commit(
        repo,
        "green(#12-1.3): code first",
        {"src/client.py": "x = 1\n", tasks_file: tick(tasks, "1.3")},
    )
    commit(
        repo,
        "red(#12-1.1): test after",
        {
            "tests/test_client.py": TEST_CLIENT,
            tasks_file: tick(tasks, "1.3", "1.1", "1.2"),
        },
    )
    out = cli(repo, "check", "--base", "main")[1]
    assert "group 1: its first green commit comes before its red one" in out
    assert "task 1.2 is ticked but no commit names it" in out


def test_an_approved_review_needs_its_wiki_line(repo: Path) -> None:
    mirror = implement(repo)
    (mirror / "review.md").write_text("# Review\n\n**Verdict:** APPROVED\n")
    out = cli(repo, "check", "--base", "main")[1]
    assert "wiki/log.md has no line for #12 · add-retry-backoff" in out
    commit(
        repo,
        "wiki(#12): log the retry change",
        {"wiki/log.md": f"- 2026-10-07 · #12 · {CHANGE} · Retry\n"},
    )
    assert cli(repo, "check", "--base", "main")[0] == 0


def test_main_must_not_keep_an_unarchived_change(repo: Path) -> None:
    commit(
        repo,
        "spec(#12): committed by mistake",
        {
            f"openspec/changes/{CHANGE}/{name}": text
            for name, text in example_files().items()
        },
    )
    out = cli(repo, "check")[1]
    assert f"main has the active change {CHANGE}" in out


# --- staleness --------------------------------------------------------------------------


def test_a_fresh_issue_still_applies(repo: Path) -> None:
    commit(repo, "add the client", {"src/client.py": "x = 1\n"})
    assert cli(repo, "stale", "12")[:2] == (0, f"#12  {CHANGE}  still applies\n")


def test_stale_reports_a_vanished_file_and_a_changed_living_spec(repo: Path) -> None:
    commit(
        repo,
        "touch the living spec",
        {"openspec/specs/http-client/spec.md": "# http-client\n"},
    )
    code, out, _ = cli(repo, "stale", "12")
    assert code == 1
    assert "design.md modifies src/client.py, which no longer exists" in out
    assert (
        "openspec/specs/http-client/spec.md changed since the issue was written" in out
    )


# --- status and the Stop hook -----------------------------------------------------------


def test_status_brief_says_nothing_outside_the_flow(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q", "-b", "main")
    assert cli(tmp_path, "status", "--brief")[:2] == (0, "")


def test_status_brief_says_where_the_work_stands(repo: Path) -> None:
    git(repo, "switch", "-q", "-c", f"12-{CHANGE}")
    cli(repo, "pull", "12")
    out = cli(repo, "status", "--brief")[1]
    assert f"SDD: #12 {CHANGE} · tasks 0/3 · next 1.1 [test]" in out
    assert "SDD: resume with /implement-issue 12" in out


def test_the_stop_gate_lets_unfinished_or_blocked_work_stop(repo: Path) -> None:
    assert cli(repo, "stop-gate", stdin="{}")[0] == 0
    git(repo, "switch", "-q", "-c", f"12-{CHANGE}")
    cli(repo, "pull", "12")
    assert cli(repo, "stop-gate", stdin="{}")[0] == 0
    mirror = repo / "openspec" / "changes" / CHANGE
    (mirror / "tasks.md").write_text(
        tick((mirror / "tasks.md").read_text(), "1.1", "1.2", "1.3")
    )
    (mirror / "BLOCKED.md").write_text("# Blocked\n\nThe upstream API is down.\n")
    assert cli(repo, "stop-gate", stdin="{}")[0] == 0


def test_the_stop_gate_blocks_work_marked_done_that_fails_its_checks(
    repo: Path,
) -> None:
    git(repo, "switch", "-q", "-c", f"12-{CHANGE}")
    cli(repo, "pull", "12")
    mirror = repo / "openspec" / "changes" / CHANGE
    (mirror / "tasks.md").write_text(
        tick((mirror / "tasks.md").read_text(), "1.1", "1.2", "1.3")
    )
    code, _, err = cli(repo, "stop-gate", stdin="{}")
    assert code == 2
    assert (
        "is marked as done but fails its checks" in err
        and "ticked but no commit names it" in err
    )
    assert cli(repo, "stop-gate", stdin='{"stop_hook_active": true}')[0] == 0


# --- init -------------------------------------------------------------------------------


def test_init_sets_up_openspec_and_adds_the_rules_once(repo: Path) -> None:
    shutil.rmtree(repo / "openspec")
    assert cli(repo, "init")[0] == 0
    assert cli(repo, "init")[0] == 0
    config = (repo / "openspec" / "config.yaml").read_text()
    assert config.count(sdd.RULES_MARKER) == 1 and "\nrules:\n" in config


def test_init_leaves_a_config_with_rules_of_its_own_alone(repo: Path) -> None:
    config = repo / "openspec" / "config.yaml"
    config.write_text("schema: spec-driven\nrules:\n  tasks:\n    - Keep tasks small\n")
    code, out, _ = cli(repo, "init")
    assert code == 1 and "merge this block into it by hand" in out
    assert (
        config.read_text()
        == "schema: spec-driven\nrules:\n  tasks:\n    - Keep tasks small\n"
    )


# --- the real CLI -----------------------------------------------------------------------


@pytest.mark.skipif(
    shutil.which("openspec") is None, reason="OpenSpec CLI not installed"
)
def test_the_example_and_the_rules_pass_openspec(tmp_path: Path) -> None:
    home = tmp_path / "openspec"
    (home / "specs").mkdir(parents=True)
    (home / "config.yaml").write_text(
        "schema: spec-driven\n\n" + sdd.RULES_FILE.read_text()
    )
    shutil.copytree(EXAMPLE, home / "changes" / CHANGE)
    assert sdd.validate(tmp_path, CHANGE) == []
    done = subprocess.run(
        ["openspec", "instructions", "tasks", "--change", CHANGE, "--json"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert any("[test]" in rule for rule in json.loads(done.stdout)["rules"])

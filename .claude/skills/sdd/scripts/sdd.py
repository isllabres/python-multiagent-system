#!/usr/bin/env python3
"""Keep a GitHub issue and its OpenSpec change in step, and check the change is built test-first.

    python3 .claude/skills/sdd/scripts/sdd.py [--root DIR] <command> [options]

The issue is the source of truth. Its body carries the change's proposal, delta specs, design
and tasks between invisible markers; openspec/changes/<id>/ on the branch <n>-<id> is a mirror
written from it, and only tasks.md gains local progress there (ticks, notes, local sections).

  init                    set up openspec/ (openspec init --tools none) and add the layer's rules
  body [--change ID]      print the issue body for a change (--out FILE to write it)
  branch N                print the branch for issue N: <n>-<change-id>
  skip-specs ID [--off]   mark a change as needing no delta specs (a pure refactor), or undo it
  pull N                  write the mirror of issue N, keeping the progress already in tasks.md
  diff N                  show where the mirror and issue N differ (ticks and notes ignored)
  stale (N | --all)       report why an open issue's change may no longer apply
  status [--brief]        where the work stands, read from disk and git only
  check [--change ID] [--base BRANCH] [--remote] [--issue N]
                          format and traceability; with --base, ticks, commit discipline and
                          tests; with --remote, drift from the issue
  stop-gate               the Stop hook: exit 2 when work that claims to be done fails a check

Every problem is one line; the exit status is 1 if there is any.
"""

from __future__ import annotations

import argparse
import difflib
import functools
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import ModuleType

SKILL = Path(__file__).resolve().parents[1]
RULES_FILE = SKILL / "openspec-rules.yaml"
RULES_MARKER = "# python-multiagent-system rules"
CHECK_WIKI = SKILL.parent / "project-wiki" / "scripts" / "check_wiki.py"
INSTALL = (
    "npm install -g @fission-ai/openspec@latest (Node 20.19+) or brew install openspec"
)

ARTIFACTS = ("proposal.md", "design.md", "tasks.md")
SKIP_SPECS_LINE = "skip_specs: true"
LOCAL_SECTIONS = ("## Replies to review", "## Wiki gaps")
MAX_ROUNDS = 3
MAX_BODY = 65536
REFUSED = "Archive would refuse"
CONFIG_FILES = ("pyproject.toml", "setup.cfg", "pytest.ini", "tox.ini", "uv.lock")
KIND_OF = {"red": "test", "guard": "guard", "green": "code", "remove": "remove"}

CHANGE_MARK = re.compile(r"<!-- openspec:change ([a-z0-9][a-z0-9-]*) -->")
FILE_OPEN = "<!-- openspec:file {} -->"
FILE_CLOSE = "<!-- /openspec:file -->"
FILE_BLOCK = re.compile(
    r"<!-- openspec:file (\S+) -->(.*?)<!-- /openspec:file -->", re.S
)
SPEC_PATH = re.compile(r"^specs/[a-z0-9][a-z0-9_-]*(?:/[a-z0-9][a-z0-9_-]*)*/spec\.md$")
BRANCH = re.compile(r"^(\d+)-([a-z0-9][a-z0-9-]*)$")
GROUP = re.compile(r"^## (\d+)\.\s+(.+?)\s*$")
TASK = re.compile(r"^- \[\s*([xX]?)\s*\]\s+(\d+)\.(\d+)\s+(.*?)\s*$")
KIND = re.compile(r"^\[(test|guard|code|remove)\]")
TEST_ID = re.compile(r"`([^`\s]+\.py::[^`\s]+)`")
SCENARIO_REF = re.compile(r"— Scenario:\s*(.+?)\s*$")
NOTE = re.compile(r"\s+— (?:red|BLOCKED):.*$")
DELTA = re.compile(r"^## (ADDED|MODIFIED|REMOVED|RENAMED) Requirements\s*$")
REQUIREMENT = re.compile(r"^### Requirement:\s*(.+?)\s*$")
SCENARIO = re.compile(r"^#### Scenario:\s*(.+?)\s*$")
FILES_ENTRY = re.compile(r"^- `([^`]+)`\s+[—-]\s+(modify|new)\b")
VERDICT = re.compile(r"^\*\*Verdict:\*\*\s*(APPROVED|CHANGES_REQUESTED)\b", re.M)
ROUND_ROW = re.compile(r"^\|\s*\d+\s*\|\s*(APPROVED|CHANGES_REQUESTED)\s*\|", re.M)
FLOW = re.compile(
    r"^(red|guard|green|remove|spec|wiki)\(#(\d+)(?:-(\d+)\.(\d+))?\): \S"
)
SCHEMA = re.compile(r"(?m)^schema:\s*(\S+)")


class SddError(Exception):
    """A failure the user can act on, printed as one line."""


@dataclass
class Task:
    group: int
    number: str
    done: bool
    kind: str | None
    text: str
    test_id: str | None
    scenario: str | None
    line: int


@dataclass
class Group:
    number: int
    title: str
    tasks: list[Task] = field(default_factory=list)

    @property
    def requirement(self) -> str | None:
        if self.title.startswith("Requirement:"):
            return self.title.removeprefix("Requirement:").strip()
        return None


@dataclass
class Requirement:
    op: str
    name: str
    capability: str
    scenarios: list[str] = field(default_factory=list)


@dataclass
class Commit:
    sha: str
    subject: str
    body: str
    files: list[str]


# --- text --------------------------------------------------------------------------------


def tidy(text: str) -> str:
    """Line endings, trailing spaces and surrounding blank lines normalised."""
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) + "\n" if lines else ""


def split_sections(text: str) -> tuple[list[str], dict[str, list[str]]]:
    """tasks.md without its local sections, and the local sections apart."""
    kept: list[str] = []
    local: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in tidy(text).splitlines():
        if line.startswith("## "):
            title = line.strip()
            current = local.setdefault(title, []) if title in LOCAL_SECTIONS else None
            if current is not None:
                continue
        (current if current is not None else kept).append(line)
    return kept, local


def canonical_tasks(text: str) -> str:
    """tasks.md as the issue holds it: no ticks, no notes, no local sections."""
    kept, _ = split_sections(text)
    out = []
    for line in kept:
        if task := TASK.match(line):
            line = f"- [ ] {task[2]}.{task[3]} {NOTE.sub('', task[4])}"
        out.append(line)
    return tidy("\n".join(out))


def merge_progress(issue_tasks: str, local_tasks: str) -> str:
    """The issue's tasks with the ticks, notes and local sections already made on the branch.

    A task keeps its progress when its description is unchanged, even if it was renumbered.
    """
    progress: dict[str, tuple[bool, str]] = {}
    kept, local = split_sections(local_tasks)
    for line in kept:
        if task := TASK.match(line):
            description = NOTE.sub("", task[4])
            note = task[4][len(description) :]
            progress[description] = (bool(task[1]), note)
    out = []
    for line in canonical_tasks(issue_tasks).splitlines():
        task = TASK.match(line)
        if task and task[4] in progress:
            done, note = progress[task[4]]
            line = f"- [{'x' if done else ' '}] {task[2]}.{task[3]} {task[4]}{note}"
        out.append(line)
    for title in LOCAL_SECTIONS:
        if title in local:
            out += ["", title, *local[title]]
    return tidy("\n".join(out))


def comparable(path: str, text: str) -> str:
    return canonical_tasks(text) if path == "tasks.md" else tidy(text)


# --- the issue body ----------------------------------------------------------------------


def ordered(paths: list[str]) -> list[str]:
    rank = {"proposal.md": 0, "design.md": 2, "tasks.md": 3}
    return sorted(paths, key=lambda path: (rank.get(path, 1), path))


def change_files(cdir: Path) -> dict[str, str]:
    """The files a change carries in its issue, as the issue holds them."""
    files = {}
    for name in ARTIFACTS:
        path = cdir / name
        if path.is_file():
            files[name] = comparable(name, path.read_text())
    for spec in sorted((cdir / "specs").glob("**/spec.md")):
        files[spec.relative_to(cdir).as_posix()] = tidy(spec.read_text())
    return files


def render_body(change_id: str, files: dict[str, str]) -> str:
    parts = [
        f"<!-- openspec:change {change_id} -->",
        f"OpenSpec change `{change_id}`. This issue is its source of truth: change it with "
        "`/update-issue`, never in the branch's mirror.",
    ]
    for path in ordered(list(files)):
        parts += [
            "---",
            f"**`{path}`**",
            FILE_OPEN.format(path),
            files[path].rstrip("\n"),
            FILE_CLOSE,
        ]
    return "\n\n".join(parts) + "\n"


def parse_body(body: str) -> tuple[str, dict[str, str]]:
    body = body.replace("\r\n", "\n")
    ids = CHANGE_MARK.findall(body)
    if not ids:
        raise SddError("the issue body has no `<!-- openspec:change <id> -->` marker")
    if len(ids) > 1:
        raise SddError("the issue body has more than one openspec:change marker")
    files: dict[str, str] = {}
    for path, text in FILE_BLOCK.findall(body):
        if "<!-- openspec:file " in text:
            raise SddError(f"the issue body does not close the block before {path}")
        if path in files:
            raise SddError(f"the issue body carries {path} twice")
        if path not in ARTIFACTS and not SPEC_PATH.match(path):
            raise SddError(f"the issue body carries an unexpected file: {path}")
        files[path] = comparable(path, text)
    if body.count("<!-- openspec:file ") != len(files):
        raise SddError("the issue body has an openspec:file block that is never closed")
    missing = [name for name in ARTIFACTS if name not in files]
    if missing:
        raise SddError(f"the issue body has no {', '.join(missing)}")
    return ids[0], files


# --- tasks and deltas --------------------------------------------------------------------


def parse_tasks(text: str) -> list[Group]:
    groups: list[Group] = []
    current: Group | None = None
    for number, line in enumerate(text.splitlines(), 1):
        if heading := GROUP.match(line):
            current = Group(int(heading[1]), heading[2])
            groups.append(current)
        elif line.startswith("## "):
            current = None
        elif current is not None and (task := TASK.match(line)):
            description = NOTE.sub("", task[4])
            kind = KIND.match(description)
            test_id = TEST_ID.search(description)
            scenario = SCENARIO_REF.search(description)
            current.tasks.append(
                Task(
                    group=int(task[2]),
                    number=f"{task[2]}.{task[3]}",
                    done=bool(task[1]),
                    kind=kind[1] if kind else None,
                    text=description,
                    test_id=test_id[1] if test_id else None,
                    scenario=scenario[1] if scenario else None,
                    line=number,
                )
            )
    return groups


def all_tasks(groups: list[Group]) -> list[Task]:
    return [task for group in groups for task in group.tasks]


def parse_deltas(cdir: Path) -> list[Requirement]:
    requirements: list[Requirement] = []
    for spec in sorted((cdir / "specs").glob("**/spec.md")):
        capability = spec.parent.relative_to(cdir / "specs").as_posix()
        op: str | None = None
        current: Requirement | None = None
        for line in spec.read_text().splitlines():
            if line.startswith("## "):
                delta = DELTA.match(line)
                op, current = (delta[1] if delta else None), None
            elif op in ("ADDED", "MODIFIED", "REMOVED") and (
                req := REQUIREMENT.match(line)
            ):
                current = Requirement(op, req[1], capability)
                requirements.append(current)
            elif current is not None and (scenario := SCENARIO.match(line)):
                current.scenarios.append(scenario[1])
    return requirements


def design_files(text: str) -> list[tuple[str, str]] | None:
    """The `## Files` entries of a design, or None when the section is missing."""
    entries: list[tuple[str, str]] = []
    inside = found = False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = line.strip() == "## Files"
            found = found or inside
        elif inside and (entry := FILES_ENTRY.match(line.strip())):
            entries.append((entry[1], entry[2]))
    return entries if found else None


def format_problems(cdir: Path) -> list[str]:
    problems = [
        f"{cdir.name}: no {name}" for name in ARTIFACTS if not (cdir / name).is_file()
    ]
    design = cdir / "design.md"
    if design.is_file() and not design_files(design.read_text()):
        problems.append(
            "design.md: no `## Files` section listing - `path` — modify or - `path` — new"
        )
    if has_skip_specs(cdir) and any(cdir.glob("specs/**/spec.md")):
        problems.append(
            f"{cdir.name}: skip_specs is set but specs/ has delta files: "
            "sdd.py skip-specs --off, or remove them"
        )
    return problems


def traceability(cdir: Path) -> list[str]:
    groups = parse_tasks((cdir / "tasks.md").read_text())
    requirements = parse_deltas(cdir)
    problems: list[str] = []
    names = [req.name for req in requirements]
    for name in sorted({name for name in names if names.count(name) > 1}):
        problems.append(
            f"specs: requirement '{name}' appears twice: group names must be unique"
        )
    by_name = {group.requirement: group for group in groups if group.requirement}
    for group in groups:
        for task in group.tasks:
            where = f"tasks.md:{task.line}: task {task.number}"
            if task.kind is None:
                problems.append(
                    f"{where} has no kind: start it with [test], [guard], [code] or [remove]"
                )
            if task.group != group.number:
                problems.append(f"{where} sits under group {group.number}")
            if task.kind in ("test", "guard") and not task.test_id:
                problems.append(f"{where} names no test as `path.py::test_name`")
            if task.kind == "test" and not group.requirement:
                problems.append(f"{where} is a [test] outside a `Requirement:` group")
        kinds = [task.kind for task in group.tasks]
        if "code" in kinds:
            late = [
                t.number
                for t in group.tasks[kinds.index("code") :]
                if t.kind in ("test", "guard")
            ]
            if late:
                problems.append(
                    f"tasks.md: group {group.number}: {', '.join(late)} come after a [code] task"
                )
        if group.requirement and group.requirement not in names:
            problems.append(
                f"tasks.md: group {group.number} names '{group.requirement}', which no delta spec has"
            )
    for req in requirements:
        group = by_name.get(req.name)
        if group is None:
            problems.append(
                f"specs/{req.capability}/spec.md: '{req.name}' has no "
                f"`## N. Requirement: {req.name}` group in tasks.md"
            )
            continue
        if req.op == "REMOVED":
            if not any(task.kind == "remove" for task in group.tasks):
                problems.append(
                    f"tasks.md: group {group.number}: removed '{req.name}' has no [remove] task"
                )
            continue
        named = [task.scenario for task in group.tasks if task.kind == "test"]
        for scenario in req.scenarios:
            count = named.count(scenario)
            if count != 1:
                problems.append(
                    f"tasks.md: group {group.number}: scenario '{scenario}' has {count} [test] "
                    "tasks, expected one"
                )
        for scenario in sorted({s or "" for s in named} - set(req.scenarios)):
            problems.append(
                f"tasks.md: group {group.number}: a [test] task names "
                f"{repr(scenario) if scenario else 'no scenario'}, not one of '{req.name}'"
            )
        if not any(task.kind == "code" for task in group.tasks):
            problems.append(
                f"tasks.md: group {group.number}: '{req.name}' has no [code] task"
            )
    return problems


# --- tools -------------------------------------------------------------------------------


def run(
    cmd: list[str], cwd: Path, timeout: float | None = None
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DO_NOT_TRACK": "1", "OPENSPEC_NO_UPDATE_CHECK": "1"}
    try:
        return subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env
        )
    except FileNotFoundError as err:
        raise SddError(f"{cmd[0]} not found") from err


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run(["git", "-C", str(root), *args], root)


def current_branch(root: Path) -> str | None:
    done = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    return done.stdout.strip() if done.returncode == 0 else None


def default_branch(root: Path) -> str:
    done = git(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if done.returncode == 0 and done.stdout.strip():
        return done.stdout.strip().removeprefix("origin/")
    for name in ("main", "master"):
        if (
            git(
                root, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}"
            ).returncode
            == 0
        ):
            return name
    return "main"


def on_branch(root: Path) -> tuple[int, str] | None:
    match = BRANCH.match(current_branch(root) or "")
    return (int(match[1]), match[2]) if match else None


def change_path(root: Path, change_id: str) -> Path | None:
    changes = root / "openspec" / "changes"
    if (changes / change_id).is_dir():
        return changes / change_id
    archived = sorted((changes / "archive").glob(f"????-??-??-{change_id}"))
    return archived[-1] if archived else None


def schema_name(root: Path) -> str:
    config = root / "openspec" / "config.yaml"
    match = SCHEMA.search(config.read_text()) if config.is_file() else None
    return match[1] if match else "spec-driven"


def has_skip_specs(cdir: Path) -> bool:
    meta = cdir / ".openspec.yaml"
    return meta.is_file() and SKIP_SPECS_LINE in meta.read_text().splitlines()


def set_skip_specs(cdir: Path, schema: str, on: bool) -> None:
    """Add or remove `skip_specs: true` in a change's .openspec.yaml, keeping its other lines.

    A change needs this when it has no delta specs — a pure refactor, tooling or docs — so
    OpenSpec accepts it with zero deltas instead of rejecting it as empty.
    """
    meta = cdir / ".openspec.yaml"
    lines = meta.read_text().splitlines() if meta.is_file() else [f"schema: {schema}"]
    lines = [line for line in lines if line.strip() != SKIP_SPECS_LINE]
    if on:
        lines.append(SKIP_SPECS_LINE)
    meta.write_text("\n".join(lines) + "\n")


def write_change(cdir: Path, files: dict[str, str], schema: str) -> None:
    """Write a change's files; a change with no delta specs is marked skip_specs for OpenSpec."""
    if cdir.is_dir():
        for path in [
            *ARTIFACTS,
            *(p.relative_to(cdir).as_posix() for p in cdir.glob("specs/**/spec.md")),
        ]:
            if path not in files and (cdir / path).is_file():
                (cdir / path).unlink()
        for folder in sorted(cdir.glob("specs/**"), reverse=True):
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
    for path, text in files.items():
        target = cdir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    has_specs = any(path.startswith("specs/") for path in files)
    if not has_specs:
        set_skip_specs(cdir, schema, on=True)
    elif has_skip_specs(cdir):
        set_skip_specs(cdir, schema, on=False)


def gh_issue(root: Path, number: int, fields: str) -> dict:
    if not shutil.which("gh"):
        raise SddError("gh not found: install the GitHub CLI and run gh auth login")
    done = run(["gh", "issue", "view", str(number), "--json", fields], root)
    if done.returncode:
        raise SddError(f"gh issue view {number}: {done.stderr.strip() or 'failed'}")
    return json.loads(done.stdout)


def issue_change(root: Path, number: int) -> tuple[str, dict[str, str]]:
    return parse_body(gh_issue(root, number, "body")["body"])


def validate(root: Path, change_id: str) -> list[str]:
    """openspec validate --strict, where an archive refusal counts as an error."""
    exe = shutil.which("openspec")
    if not exe:
        return [f"cannot validate {change_id}: openspec CLI not found ({INSTALL})"]
    done = run([exe, "validate", change_id, "--strict", "--json"], root)
    try:
        items = json.loads(done.stdout)["items"]
    except (json.JSONDecodeError, KeyError, TypeError):
        text = (done.stderr or done.stdout).strip().splitlines()
        return [f"openspec validate {change_id}: {text[0] if text else 'no output'}"]
    problems = []
    for item in items:
        for issue in item.get("issues", []):
            if issue.get("level") != "INFO" or REFUSED in issue.get("message", ""):
                problems.append(
                    f"openspec: {issue.get('path', '')}: {issue.get('message', '')}"
                )
        if not item.get("valid", False) and not problems:
            problems.append(f"openspec validate {change_id}: invalid")
    return problems


def validate_files(root: Path, change_id: str, files: dict[str, str]) -> list[str]:
    """Validate a change that is not on disk, against a copy of the living specs."""
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "openspec"
        specs = root / "openspec" / "specs"
        if specs.is_dir():
            shutil.copytree(specs, home / "specs")
        else:
            (home / "specs").mkdir(parents=True)
        config = root / "openspec" / "config.yaml"
        if config.is_file():
            shutil.copy(config, home / "config.yaml")
        write_change(home / "changes" / change_id, files, schema_name(root))
        return validate(Path(tmp), change_id)


@functools.cache
def check_wiki() -> ModuleType | None:
    """The project-wiki checker, whose symbol_defined this script reuses."""
    spec = importlib.util.spec_from_file_location("check_wiki", CHECK_WIKI)
    if not CHECK_WIKI.is_file() or spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def symbol_defined(text: str, name: str) -> bool:
    module = check_wiki()
    if module is not None:
        return module.symbol_defined(text, name)
    return (
        re.search(rf"(?m)^\s*(?:async\s+)?def\s+{re.escape(name)}\b", text) is not None
    )


# --- review ------------------------------------------------------------------------------


def review_state(cdir: Path) -> tuple[str | None, int]:
    """The reviewer's last verdict and how many rounds asked for changes."""
    path = cdir / "review.md"
    if not path.is_file():
        return None, 0
    text = path.read_text()
    verdict = VERDICT.search(text)
    rounds = sum(1 for row in ROUND_ROW.findall(text) if row == "CHANGES_REQUESTED")
    return (verdict[1] if verdict else None), rounds


# --- commits -----------------------------------------------------------------------------


def is_test_file(path: str) -> bool:
    name = PurePosixPath(path).name
    return (
        path.startswith(("tests/", "test/"))
        or (name.startswith("test_") and name.endswith(".py"))
        or name.endswith("_test.py")
        or name == "conftest.py"
    )


def history(root: Path, base: str) -> list[Commit]:
    done = git(
        root,
        "log",
        "--reverse",
        "--no-merges",
        "--format=%H%x1f%s%x1f%b%x1e",
        f"{base}..HEAD",
    )
    if done.returncode:
        raise SddError(f"cannot read git history {base}..HEAD: {done.stderr.strip()}")
    commits = []
    for record in done.stdout.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        sha, subject, body = record.split("\x1f")
        files = git(
            root, "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", sha
        )
        commits.append(Commit(sha[:7], subject, body, files.stdout.splitlines()))
    return commits


def discipline(
    root: Path, groups: list[Group], issue: int, change_id: str, base: str
) -> tuple[list[str], list[str]]:
    """Commit discipline on base..HEAD: problems, and notes for the reviewer."""
    tasks = {task.number: task for task in all_tasks(groups)}
    tasks_file = f"openspec/changes/{change_id}/tasks.md"
    problems: list[str] = []
    notes: list[str] = []
    first: dict[tuple[str, int], int] = {}
    named: set[str] = set()
    for index, commit in enumerate(history(root, base)):
        label = f"commit {commit.sha} '{commit.subject}'"
        flow = FLOW.match(commit.subject)
        if not flow:
            problems.append(
                f"{label}: not a flow commit: red|guard|green|remove|spec|wiki(#{issue}…)"
            )
            continue
        prefix, number = flow[1], int(flow[2])
        if number != issue:
            problems.append(f"{label}: names #{number}, this branch is #{issue}")
        if prefix in ("spec", "wiki"):
            home = "openspec/" if prefix == "spec" else "wiki/"
            outside = [path for path in commit.files if not path.startswith(home)]
            if flow[3]:
                problems.append(
                    f"{label}: a {prefix} commit names the issue, not a task"
                )
            if outside:
                problems.append(
                    f"{label}: touches {', '.join(outside)}, outside {home}"
                )
            continue
        if not flow[3]:
            problems.append(f"{label}: names no task (#{issue}-N.k)")
            continue
        number_text, group = f"{flow[3]}.{flow[4]}", int(flow[3])
        task = tasks.get(number_text)
        if task is None:
            problems.append(f"{label}: task {number_text} is not in tasks.md")
            continue
        named.add(number_text)
        if task.kind != KIND_OF[prefix]:
            problems.append(
                f"{label}: task {number_text} is [{task.kind}]; {prefix} is for [{KIND_OF[prefix]}]"
            )
        spec_files = [
            path
            for path in commit.files
            if path.startswith("openspec/") and path != tasks_file
        ]
        if spec_files:
            problems.append(
                f"{label}: changes {', '.join(spec_files)}: only spec(#{issue}) commits do"
            )
        configs = [
            path for path in commit.files if PurePosixPath(path).name in CONFIG_FILES
        ]
        if configs:
            notes.append(
                f"note: {label} changes {', '.join(configs)}: check it skips or deselects nothing"
            )
        if prefix in ("red", "guard"):
            other = [
                path
                for path in commit.files
                if not is_test_file(path)
                and path != tasks_file
                and path not in configs
                and not path.startswith("openspec/")
            ]
            if other:
                problems.append(
                    f"{label}: a {prefix} commit touches tests and tasks.md only, not {', '.join(other)}"
                )
            if ("green", group) in first and "Review: round" not in commit.body:
                problems.append(
                    f"{label}: changes a test of group {group} after its green commit "
                    "without citing `Review: round k #n`"
                )
            first.setdefault(("test", group), index)
        elif prefix == "green":
            tests = [path for path in commit.files if is_test_file(path)]
            if tests:
                problems.append(
                    f"{label}: a green commit never touches a test: {', '.join(tests)}"
                )
            first.setdefault(("green", group), index)
    for group in groups:
        red, green = (
            first.get(("test", group.number)),
            first.get(("green", group.number)),
        )
        tested = any(task.kind in ("test", "guard") for task in group.tasks)
        if tested and green is not None and (red is None or red > green):
            problems.append(
                f"group {group.number}: its first green commit comes before its red one"
            )
    for task in tasks.values():
        if task.done and task.number not in named:
            problems.append(
                f"tasks.md:{task.line}: task {task.number} is ticked but no commit names it"
            )
    return problems, notes


def missing_tests(root: Path, groups: list[Group]) -> list[str]:
    problems = []
    for task in all_tasks(groups):
        if task.kind in ("test", "guard") and task.test_id:
            path, _, symbol = task.test_id.partition("::")
            name = symbol.split("::")[-1].split("[")[0]
            source = root / path
            if not source.is_file():
                problems.append(f"tasks.md:{task.line}: {task.test_id}: no such file")
            elif not symbol_defined(source.read_text(), name):
                problems.append(
                    f"tasks.md:{task.line}: {task.test_id}: not defined there"
                )
    return problems


def tracked_changes(root: Path) -> list[str]:
    """Active changes committed to the current branch."""
    done = git(root, "ls-files", "openspec/changes")
    ids = set()
    for path in done.stdout.splitlines():
        parts = PurePosixPath(path).parts
        if len(parts) > 3 and parts[2] != "archive":
            ids.add(parts[2])
    return sorted(ids)


def drift(root: Path, number: int, change_id: str, cdir: Path) -> list[str]:
    issue_id, files = issue_change(root, number)
    if issue_id != change_id:
        return [f"drift: issue #{number} carries change {issue_id}, not {change_id}"]
    local = change_files(cdir)
    problems = []
    for path in ordered(sorted(set(files) | set(local))):
        if path not in local:
            problems.append(f"drift: issue #{number} has {path}, the mirror does not")
        elif path not in files:
            problems.append(f"drift: the mirror has {path}, issue #{number} does not")
        elif local[path] != files[path]:
            problems.append(
                f"drift: {path} differs from issue #{number}: sdd.py diff {number}"
            )
    return problems


def run_check(
    root: Path,
    change_id: str | None,
    base: str | None = None,
    remote: bool = False,
    issue: int | None = None,
) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    notes: list[str] = []
    on = on_branch(root)
    if current_branch(root) == default_branch(root):
        problems += [
            f"{default_branch(root)} has the active change {cid}: it was merged without "
            "`openspec archive`"
            for cid in tracked_changes(root)
        ]
    if change_id is None:
        if base or remote:
            raise SddError(
                "no change: pass --change or work on its <n>-<change-id> branch"
            )
        return problems, notes
    cdir = change_path(root, change_id)
    if cdir is None:
        raise SddError(f"no change {change_id} in openspec/changes/")
    formatted = format_problems(cdir)
    problems += formatted
    if (cdir / "tasks.md").is_file():
        problems += traceability(cdir)
    if cdir.parent.name != "archive":
        problems += validate(root, change_id)
    issue = issue or (on[0] if on and on[1] == change_id else None)
    if base:
        if issue is None or not on or on[1] != change_id:
            problems.append(
                f"--base needs the change's branch <n>-{change_id}, not {current_branch(root)}"
            )
        elif (cdir / "tasks.md").is_file():
            groups = parse_tasks((cdir / "tasks.md").read_text())
            problems += [
                f"tasks.md:{task.line}: task {task.number} is not ticked"
                for task in all_tasks(groups)
                if not task.done
            ]
            found, notes = discipline(root, groups, issue, change_id, base)
            problems += found + missing_tests(root, groups)
            verdict, _ = review_state(cdir)
            log = root / "wiki" / "log.md"
            if verdict == "APPROVED" and (
                not log.is_file() or f"#{issue} · {change_id}" not in log.read_text()
            ):
                problems.append(
                    f"wiki/log.md has no line for #{issue} · {change_id}: call wiki-generator"
                )
    if remote:
        if issue is None:
            raise SddError(
                "--remote needs the issue: pass --issue N or work on its branch"
            )
        problems += drift(root, issue, change_id, cdir)
    return problems, notes


# --- commands ----------------------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    root = args.root
    if (root / "openspec").is_dir():
        print("openspec/ already exists: keeping its configuration")
    else:
        exe = shutil.which("openspec")
        if not exe:
            raise SddError(f"openspec CLI not found: {INSTALL}")
        done = run([exe, "init", "--tools", "none", "--no-animation", str(root)], root)
        if done.returncode:
            raise SddError(
                f"openspec init failed: {(done.stderr or done.stdout).strip()}"
            )
        print("openspec init --tools none: created openspec/")
    config = root / "openspec" / "config.yaml"
    text = config.read_text() if config.is_file() else "schema: spec-driven\n"
    if RULES_MARKER in text:
        print("openspec/config.yaml already has this layer's rules")
        return 0
    if re.search(r"(?m)^(rules|operations):", text):
        print(
            "openspec/config.yaml has rules of its own: merge this block into it by hand\n"
        )
        print(RULES_FILE.read_text())
        return 1
    config.write_text(text.rstrip("\n") + "\n\n" + RULES_FILE.read_text())
    print("added this layer's rules to openspec/config.yaml")
    return 0


def cmd_body(args: argparse.Namespace) -> int:
    on = on_branch(args.root)
    change_id = args.change or (on[1] if on else None)
    if change_id is None:
        raise SddError("pass --change ID")
    cdir = args.root / "openspec" / "changes" / change_id
    if not cdir.is_dir():
        raise SddError(f"no change {change_id} in openspec/changes/")
    missing = format_problems(cdir)
    if missing:
        raise SddError("; ".join(missing))
    body = render_body(change_id, change_files(cdir))
    if len(body) > MAX_BODY:
        raise SddError(
            f"the body is {len(body)} characters, over GitHub's {MAX_BODY}: split the change"
        )
    if args.out:
        args.out.write_text(body)
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(body)
    return 0


def cmd_branch(args: argparse.Namespace) -> int:
    change_id, _ = issue_change(args.root, args.issue)
    print(f"{args.issue}-{change_id}")
    return 0


def cmd_skip_specs(args: argparse.Namespace) -> int:
    root = args.root
    cdir = root / "openspec" / "changes" / args.change
    if not cdir.is_dir():
        raise SddError(f"no change {args.change} in openspec/changes/")
    if not args.off and any(cdir.glob("specs/**/spec.md")):
        raise SddError(
            f"{args.change} has delta specs under specs/: remove them first, "
            "or leave skip_specs off"
        )
    set_skip_specs(cdir, schema_name(root), on=not args.off)
    print(f"{args.change}: skip_specs {'off' if args.off else 'on'}")
    return 0


def cmd_pull(args: argparse.Namespace) -> int:
    root = args.root
    change_id, files = issue_change(root, args.issue)
    cdir = root / "openspec" / "changes" / change_id
    if (cdir / "tasks.md").is_file():
        files["tasks.md"] = merge_progress(
            files["tasks.md"], (cdir / "tasks.md").read_text()
        )
    write_change(cdir, files, schema_name(root))
    print(
        f"pulled #{args.issue} into openspec/changes/{change_id}/ ({len(files)} files)"
    )
    expected = f"{args.issue}-{change_id}"
    if current_branch(root) != expected:
        print(
            f"note: you are on {current_branch(root)}; this change belongs on {expected}"
        )
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    root = args.root
    change_id, files = issue_change(root, args.issue)
    cdir = root / "openspec" / "changes" / change_id
    if not cdir.is_dir():
        raise SddError(
            f"no mirror of #{args.issue} in openspec/changes/{change_id}/: sdd.py pull {args.issue}"
        )
    local = change_files(cdir)
    drifted = 0
    for path in ordered(sorted(set(files) | set(local))):
        if local.get(path) == files.get(path):
            continue
        drifted += 1
        sys.stdout.writelines(
            difflib.unified_diff(
                files.get(path, "").splitlines(keepends=True),
                local.get(path, "").splitlines(keepends=True),
                f"issue #{args.issue}/{path}",
                f"mirror/{path}",
            )
        )
    print(
        f"mirror matches #{args.issue}"
        if not drifted
        else f"drift: {drifted} file(s) differ"
    )
    return 1 if drifted else 0


def stale_reasons(root: Path, issue: dict) -> tuple[str, list[str]]:
    change_id, files = parse_body(issue["body"])
    reasons = []
    if issue.get("state", "OPEN") != "OPEN":
        reasons.append(f"the issue is {issue['state'].lower()}")
    reasons += [
        problem.removeprefix("openspec: ")
        for problem in validate_files(root, change_id, files)
    ]
    for path, mode in design_files(files["design.md"]) or []:
        if mode == "modify" and not (root / path).exists():
            reasons.append(f"design.md modifies {path}, which no longer exists")
    for spec in files:
        if spec.startswith("specs/"):
            living = "openspec/" + spec
            done = git(
                root,
                "log",
                f"--since={issue['createdAt']}",
                "--format=%h %s",
                "--",
                living,
            )
            changed = done.stdout.strip().splitlines()
            if changed:
                reasons.append(
                    f"{living} changed since the issue was written: {changed[0]}"
                )
    return change_id, reasons


def cmd_stale(args: argparse.Namespace) -> int:
    root = args.root
    fields = "number,title,body,state,createdAt"
    if args.all:
        if not shutil.which("gh"):
            raise SddError("gh not found: install the GitHub CLI and run gh auth login")
        done = run(
            [
                "gh",
                "issue",
                "list",
                "--state",
                "open",
                "--limit",
                "200",
                "--json",
                fields,
            ],
            root,
        )
        if done.returncode:
            raise SddError(f"gh issue list: {done.stderr.strip() or 'failed'}")
        issues = [
            i
            for i in json.loads(done.stdout)
            if CHANGE_MARK.search(i.get("body") or "")
        ]
    else:
        issues = [gh_issue(root, args.issue, fields)]
    stale = 0
    for issue in issues:
        try:
            change_id, reasons = stale_reasons(root, issue)
        except SddError as err:
            change_id, reasons = "?", [str(err)]
        stale += bool(reasons)
        verdict = "stale: " + "; ".join(reasons) if reasons else "still applies"
        print(f"#{issue['number']}  {change_id}  {verdict}")
    if args.all and not issues:
        print("no open issue carries an OpenSpec change")
    return 1 if stale else 0


def cmd_status(args: argparse.Namespace) -> int:
    root = args.root
    has_openspec = (root / "openspec").is_dir()
    on = on_branch(root)
    if args.brief and not has_openspec and not on:
        return 0
    lines = []
    if not has_openspec:
        lines.append("openspec/ is not set up: run sdd.py init")
    else:
        if not shutil.which("openspec"):
            lines.append(f"openspec CLI not found: {INSTALL}")
        config = root / "openspec" / "config.yaml"
        if config.is_file() and RULES_MARKER not in config.read_text():
            lines.append(
                "openspec/config.yaml lacks this layer's rules: run sdd.py init"
            )
    current = None
    if on:
        issue, current = on
        cdir = root / "openspec" / "changes" / current
        if (cdir / "tasks.md").is_file():
            tasks = all_tasks(parse_tasks((cdir / "tasks.md").read_text()))
            done = sum(task.done for task in tasks)
            parts = [f"#{issue} {current}", f"tasks {done}/{len(tasks)}"]
            following = next((task for task in tasks if not task.done), None)
            if following:
                text = (
                    following.text
                    if len(following.text) <= 70
                    else following.text[:69] + "…"
                )
                parts.append(f"next {following.number} {text}")
            verdict, rounds = review_state(cdir)
            if verdict:
                parts.append(f"review {verdict}, {rounds}/{MAX_ROUNDS} rounds")
            lines.append(" · ".join(parts))
            blocked = cdir / "BLOCKED.md"
            if blocked.is_file():
                reason = next(
                    (
                        line
                        for line in blocked.read_text().splitlines()
                        if line.strip() and not line.startswith("#")
                    ),
                    "",
                )
                lines.append(f"BLOCKED: {reason.strip()}")
            lines.append(f"resume with /implement-issue {issue}")
        elif change_path(root, current):
            lines.append(
                f"#{issue} {current} is archived on this branch: the PR carries it"
            )
        else:
            lines.append(
                f"#{issue} {current}: no mirror yet; start with /implement-issue {issue}"
            )
    changes = root / "openspec" / "changes"
    others = (
        sorted(
            p.name
            for p in changes.iterdir()
            if p.is_dir() and p.name not in ("archive", current)
        )
        if changes.is_dir()
        else []
    )
    if others:
        lines.append("other changes in openspec/changes/: " + ", ".join(others))
    for line in lines:
        print(f"SDD: {line}" if args.brief else line)
    if not args.brief and not lines:
        print("nothing in progress")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    on = on_branch(args.root)
    change_id = args.change or (on[1] if on else None)
    problems, notes = run_check(
        args.root, change_id, args.base, args.remote, args.issue
    )
    for line in problems + notes:
        print(line)
    print(f"check: {len(problems)} problem(s)" if problems else "check ok")
    return 1 if problems else 0


def cmd_stop_gate(args: argparse.Namespace) -> int:
    data: dict = {}
    if not sys.stdin.isatty():
        try:
            data = json.loads(sys.stdin.read() or "{}")
        except json.JSONDecodeError:
            data = {}
    if data.get("stop_hook_active"):
        return 0
    root = args.root
    on = on_branch(root)
    if not on:
        return 0
    issue, change_id = on
    cdir = root / "openspec" / "changes" / change_id
    if not (cdir / "tasks.md").is_file() or (cdir / "BLOCKED.md").is_file():
        return 0
    tasks = all_tasks(parse_tasks((cdir / "tasks.md").read_text()))
    verdict, _ = review_state(cdir)
    if any(not task.done for task in tasks) and verdict != "APPROVED":
        return 0
    failures = []
    try:
        problems, _ = run_check(root, change_id, default_branch(root))
    except SddError as err:
        problems = [str(err)]
    if problems:
        failures.append(
            "sdd.py check --base:\n" + "\n".join(f"  {p}" for p in problems[:15])
        )
    elif not shutil.which("uv"):
        print("stop-gate: uv not found, so the suite was not run", file=sys.stderr)
        return 0
    else:
        for cmd in (["uv", "run", "ruff", "check", "."], ["uv", "run", "pytest", "-q"]):
            try:
                done = run(cmd, root, timeout=540)
            except subprocess.TimeoutExpired:
                failures.append(f"{' '.join(cmd)} timed out")
                break
            if done.returncode:
                tail = (done.stdout + done.stderr).strip().splitlines()[-15:]
                failures.append(
                    f"{' '.join(cmd)} failed:\n" + "\n".join(f"  {t}" for t in tail)
                )
                break
    if not failures:
        return 0
    print(
        f"#{issue} {change_id} is marked as done but fails its checks:\n"
        + "\n".join(failures)
        + "\nFix it, or block it (BLOCKED.md, label and issue comment) before stopping.",
        file=sys.stderr,
    )
    return 2


COMMANDS = {
    "init": cmd_init,
    "body": cmd_body,
    "branch": cmd_branch,
    "skip-specs": cmd_skip_specs,
    "pull": cmd_pull,
    "diff": cmd_diff,
    "stale": cmd_stale,
    "status": cmd_status,
    "check": cmd_check,
    "stop-gate": cmd_stop_gate,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", type=Path, default=Path("."), help="the project root")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    body = sub.add_parser("body")
    body.add_argument("--change")
    body.add_argument("--out", type=Path)
    for name in ("branch", "pull", "diff"):
        sub.add_parser(name).add_argument("issue", type=int)
    skip_specs = sub.add_parser("skip-specs")
    skip_specs.add_argument("change")
    skip_specs.add_argument("--off", action="store_true")
    stale = sub.add_parser("stale")
    which = stale.add_mutually_exclusive_group(required=True)
    which.add_argument("issue", type=int, nargs="?")
    which.add_argument("--all", action="store_true")
    sub.add_parser("status").add_argument("--brief", action="store_true")
    check = sub.add_parser("check")
    check.add_argument("--change")
    check.add_argument("--base")
    check.add_argument("--remote", action="store_true")
    check.add_argument("--issue", type=int)
    sub.add_parser("stop-gate")
    args = parser.parse_args(argv)
    args.root = args.root.resolve()
    try:
        return COMMANDS[args.command](args)
    except SddError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""Tests that the layer's documents agree with its files: no role or skill named that does not
exist, none that exists left unnamed, and no count that drifted.

Run: uv run pytest .claude/skills/sdd/tests -q
They run only in the layer's own repository, whose README starts with its name.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
CLAUDE = ROOT / ".claude"
README = ROOT / "README.md"
WORDS = "zero one two three four five six seven eight nine ten eleven twelve".split()

pytestmark = pytest.mark.skipif(
    not README.is_file()
    or not README.read_text().startswith("# python-multiagent-system"),
    reason="not the layer's own repository",
)


def agents() -> list[str]:
    return sorted(path.stem for path in (CLAUDE / "agents").glob("*.md"))


def skills() -> list[str]:
    return sorted(path.parent.name for path in (CLAUDE / "skills").glob("*/SKILL.md"))


def frontmatter_list(path: Path, key: str) -> list[str]:
    head = path.read_text().split("---")[1]
    block = re.search(rf"(?m)^{key}:\n((?:  - .+\n)+)", head)
    return re.findall(r"  - (.+)", block[1]) if block else []


def test_every_skill_an_agent_loads_exists() -> None:
    for agent in agents():
        for skill in frontmatter_list(CLAUDE / "agents" / f"{agent}.md", "skills"):
            assert skill in skills(), f"{agent} loads {skill}, which does not exist"


def test_claude_md_names_every_role_and_skill() -> None:
    text = (ROOT / "CLAUDE.md").read_text()
    for name in agents() + skills():
        assert name in text, f"CLAUDE.md never names {name}"
    assert f"## {WORDS[len(agents())].capitalize()} roles" in text


def test_the_readme_skills_table_is_the_skills_on_disk() -> None:
    section = README.read_text().split("## Skills", 1)[1].split("\n## ", 1)[0]
    listed = {name.lstrip("/") for name in re.findall(r"(?m)^\| `([^`]+)` \|", section)}
    assert listed == set(skills())


def test_the_readme_counts_and_roles_match_the_files() -> None:
    text = README.read_text()
    assert f"The {WORDS[len(agents())]} roles" in text
    assert f"The {WORDS[len(skills())]} skills" in text
    for agent in agents():
        assert f"| `{agent}` |" in text, f"the README's roles table lacks {agent}"


def test_every_layer_path_the_documents_name_exists() -> None:
    for document in (ROOT / "CLAUDE.md", README):
        for path in re.findall(r"`(\.claude/[^`*<\s]+)`", document.read_text()):
            assert (ROOT / path).exists(), (
                f"{document.name} names {path}, which does not exist"
            )

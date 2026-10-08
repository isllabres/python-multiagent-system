"""Tests that the layer's documents agree with its files: no agent, command or skill named that
does not exist, none that exists left unnamed, and no count that drifted.

Run: uv run pytest .opencode/skills/sdd/tests -q
They run only in the layer's own repository, whose README starts with its name.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
OPENCODE = ROOT / ".opencode"
AGENTS_MD = ROOT / "AGENTS.md"
README = ROOT / "README.md"
WORDS = "zero one two three four five six seven eight nine ten eleven twelve".split()

pytestmark = pytest.mark.skipif(
    not README.is_file()
    or not README.read_text().startswith("# python-multiagent-system"),
    reason="not the layer's own repository",
)


def agents() -> list[str]:
    return sorted(path.stem for path in (OPENCODE / "agent").glob("*.md"))


def commands() -> list[str]:
    return sorted(path.stem for path in (OPENCODE / "command").glob("*.md"))


def skills() -> list[str]:
    return sorted(path.parent.name for path in (OPENCODE / "skills").glob("*/SKILL.md"))


def test_agents_md_names_every_agent_command_and_skill() -> None:
    text = AGENTS_MD.read_text()
    for name in agents() + commands() + skills():
        assert name in text, f"AGENTS.md never names {name}"
    assert f"## {WORDS[len(agents())].capitalize()} agents" in text


def table_names(section: str) -> set[str]:
    return {name.lstrip("/") for name in re.findall(r"(?m)^\| `([^`]+)` \|", section)}


def test_the_readme_command_and_skill_tables_are_what_is_on_disk() -> None:
    section = (
        README.read_text().split("## Commands and skills", 1)[1].split("\n## ", 1)[0]
    )
    before, after = section.split("| Skill |", 1)
    assert table_names(before) == set(commands())
    assert table_names("| Skill |" + after) == set(skills())


def test_the_readme_counts_and_agents_match_the_files() -> None:
    text = README.read_text()
    assert f"The {WORDS[len(agents())]} agents" in text
    assert f"{WORDS[len(agents())]} specialised agents" in text
    for agent in agents():
        assert f"| `{agent}` |" in text, f"the README's agents table lacks {agent}"


def test_every_opencode_path_the_documents_name_exists() -> None:
    for document in (AGENTS_MD, README):
        for path in re.findall(r"`(\.opencode/[^`*<\s]+)`", document.read_text()):
            assert (ROOT / path).exists(), (
                f"{document.name} names {path}, which does not exist"
            )


def test_no_agent_frontmatter_leftover_from_claude_code() -> None:
    for agent in agents():
        head = (OPENCODE / "agent" / f"{agent}.md").read_text().split("---")[1]
        assert "tools:" not in head, f"{agent}.md still has a Claude Code tools: field"
        assert "skills:" not in head, (
            f"{agent}.md still has a Claude Code skills: field"
        )

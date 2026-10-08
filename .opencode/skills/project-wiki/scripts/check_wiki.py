#!/usr/bin/env python3
"""Check that the project wiki is brief, connected and still points at real code.

    python3 .opencode/skills/project-wiki/scripts/check_wiki.py [--wiki wiki] [--root .]

Checks, each reported as one line; exit status 1 if there is any:
  structure   Home, _Sidebar, log and the six pages exist; the sidebar links all six
  size        pages at most 100 lines, changelog lines at most 100 characters,
              decisions and known issues at most 5 lines under their heading
  links       every relative link to a .md file resolves, a living spec included
  anchors     every `path.py` or `path.py:symbol` in a page names a file that exists and,
              if given, a def, class or assignment that is still in it
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PAGES = (
    "1.-Configuration-and-Environment.md",
    "2.-Architecture.md",
    "3.-Features-and-Behaviour.md",
    "4.-Testing-and-Evaluation.md",
    "5.-Decisions-and-Known-Issues.md",
    "6.-Production-and-Monitoring.md",
)
FRONT = ("Home.md", "_Sidebar.md", "log.md")
MAX_PAGE_LINES = 100
MAX_LOG_CHARS = 100
MAX_ENTRY_LINES = 6  # the heading plus five lines

LINK = re.compile(r"\]\(([^)#\s]+\.md)(?:#[^)]*)?\)")
ANCHOR = re.compile(r"`([\w./-]+\.py)(?:::?([A-Za-z_][\w.]*))?`")


def check_structure(wiki: Path) -> list[str]:
    problems = [
        f"missing: {name}" for name in (*FRONT, *PAGES) if not (wiki / name).is_file()
    ]
    sidebar = wiki / "_Sidebar.md"
    if sidebar.is_file():
        text = sidebar.read_text()
        problems += [
            f"_Sidebar.md does not link {page}" for page in PAGES if page not in text
        ]
    return problems


def check_sizes(wiki: Path) -> list[str]:
    problems = []
    for name in PAGES:
        path = wiki / name
        if (
            path.is_file()
            and (n := len(path.read_text().splitlines())) > MAX_PAGE_LINES
        ):
            problems.append(f"{name}: {n} lines, at most {MAX_PAGE_LINES}: condense it")
    log = wiki / "log.md"
    if log.is_file():
        for number, line in enumerate(log.read_text().splitlines(), 1):
            if line.startswith("- ") and len(line) > MAX_LOG_CHARS:
                problems.append(
                    f"log.md:{number}: {len(line)} characters, at most {MAX_LOG_CHARS}"
                )
            elif line.strip() and not line.startswith(("- ", "#")):
                problems.append(f"log.md:{number}: not a one-line entry")
    decisions = wiki / PAGES[4]
    if decisions.is_file():
        blocks = re.split(r"(?m)^(?=### )", decisions.read_text())
        for block in blocks[1:]:
            lines = block.rstrip().splitlines()
            if len(lines) > MAX_ENTRY_LINES:
                problems.append(
                    f"{PAGES[4]}: '{lines[0]}' is {len(lines)} lines, at most {MAX_ENTRY_LINES}"
                )
    return problems


def check_links(wiki: Path) -> list[str]:
    problems = []
    for page in sorted(wiki.glob("*.md")):
        for target in LINK.findall(page.read_text()):
            if (
                not target.startswith(("http:", "https:"))
                and not (wiki / target).is_file()
            ):
                problems.append(f"{page.name}: broken link to {target}")
    return problems


def symbol_defined(text: str, name: str) -> bool:
    pattern = rf"(?m)^\s*(?:(?:async\s+)?def|class)\s+{re.escape(name)}\b|^\s*{re.escape(name)}\s*[:=]"
    return re.search(pattern, text) is not None


def check_anchors(wiki: Path, root: Path) -> list[str]:
    problems = []
    for page in sorted(wiki.glob("*.md")):
        for path, symbol in sorted(set(ANCHOR.findall(page.read_text()))):
            source = root / path
            if not source.is_file():
                problems.append(f"{page.name}: stale anchor {path}: no such file")
            elif symbol and not symbol_defined(
                source.read_text(), symbol.split(".")[-1]
            ):
                problems.append(
                    f"{page.name}: stale anchor {path}:{symbol}: not defined there"
                )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--wiki", type=Path, default=Path("wiki"))
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args(argv)

    problems = check_structure(args.wiki)
    problems += check_sizes(args.wiki) + check_links(args.wiki)
    problems += check_anchors(args.wiki, args.root)
    for problem in problems:
        print(problem)
    print(f"wiki: {len(problems)} problem(s)" if problems else "wiki ok")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

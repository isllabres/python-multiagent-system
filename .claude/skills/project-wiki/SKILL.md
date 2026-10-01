---
name: project-wiki
description: How to use the project wiki (wiki/) as a map of the code — read it first, follow an entry's code anchors straight to the symbol, and read only that, instead of reading the code wholesale. Also the entry format the wiki-generator writes and the checker that keeps anchors honest. Not The Python Wiki.
---

The project wiki (`wiki/`) is a graph. Its entries are the nodes. The edges are the `See:` links
between entries and the `Code:` and `Tests:` anchors that point into the repository. It exists so
that nobody reads the whole code to find the part that matters.

## Reading it — before you read code

1. **Find the entry.** `grep -n '^### ' wiki/*.md` lists every entry, and the page tells its kind
   (2 modules, 3 features, 4 tests, 5 decisions and known issues). For a term:
   `grep -ril '<term>' wiki/`. If you know nothing yet, start at `wiki/Home.md`.
2. **Read that entry only.** Follow a `See:` link when the entry depends on another (a module it
   uses, a decision behind it), and no further than you need.
3. **Go straight to the anchor.** `grep -n 'def <symbol>\|class <symbol>' <file>`, then read that
   symbol, and its direct callers or callees only if your change reaches them. Read a whole file
   only when the entry's unit is the file.
4. **Verify before you change.** The wiki says where and why; the code says exactly what. Read the
   symbol itself before you edit it or state a fact about it.
5. **Report a gap in one line to `manager`**: `wiki gap: <what you looked for>` when there is no
   entry, `stale anchor: <anchor>` when it does not resolve. Carry on by searching the code;
   `manager` has `wiki-generator` repair it.

An empty wiki is normal on an existing project. Search the code as usual; `manager` has the area
surveyed before the work starts.

## The entry format

What `wiki-generator` writes, three or four lines per entry:

```
### Reject rows without customer_id
Rows with no id raise before load; batch jobs were silently dropping them.
Code: `src/loader.py:load_rows` · Tests: `tests/test_loader.py::test_rejects_row`
See: [Decision: fail fast](5.-Decisions-and-Known-Issues.md)
```

- **Code anchors** are `path:symbol` in backticks, dotted for methods (`src/loader.py:Loader.read`),
  never line numbers, which drift. A module entry may give only the file.
- **Tests** are pytest ids, or the runner of an eval (`evals/<slug>/run.py`); **See** links are
  relative `.md` links.
- An anchor outside backticks is invisible to the checker, so always use backticks.

## The checker

```bash
python3 .claude/skills/project-wiki/scripts/check_wiki.py --base <default-branch>
```

It prints one line per problem and exits 1 if there is any: a missing page or a sidebar that does
not link all six; a page over 100 lines, a changelog line over 100 characters, a decision over 5
lines; a broken link; an anchor whose file or symbol no longer exists; and, with `--base`, a commit
of the branch with no changelog line. `wiki-generator` runs it before every wiki commit, and
`/implement-issue` runs it at Step 6.

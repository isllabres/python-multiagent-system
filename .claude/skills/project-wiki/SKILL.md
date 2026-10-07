---
name: project-wiki
description: How to use the project wiki (wiki/) as a map of the code — read it first, follow an entry's code anchors straight to the symbol, and read only that, instead of reading the code wholesale. Also the entry format the wiki-generator writes and the checker that keeps anchors honest. What the system does lives in openspec/specs/, not here.
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
5. **Note a gap where your work is written down**: `wiki gap: <what you looked for>` when there
   is no entry, `stale anchor: <anchor>` when it does not resolve — under `## Wiki gaps` in
   `tasks.md` (implementer) or `review.md` (reviewer), or to the person (manager). Carry on by
   searching the code; `wiki-generator` repairs them once the change is approved.

An empty wiki is normal on an existing project. Search the code as usual; `manager` has an area
surveyed while the change that touches it is being written.

What the system does is not restated here: the living specs in `openspec/specs/` hold it. A
capability's entry points at its spec, its code and its tests.

## The entry format

What `wiki-generator` writes, three or four lines per entry:

```
### HTTP client: retries
Server errors are retried with backoff; batch jobs no longer fail on a transient 503.
Code: `src/client.py:HttpClient.get` · Tests: `tests/test_client.py::test_server_error_is_retried`
See: [http-client](../openspec/specs/http-client/spec.md)
```

- **Code anchors** are `path:symbol` in backticks, dotted for methods (`src/loader.py:Loader.read`),
  never line numbers, which drift. A module entry may give only the file.
- **Tests** are pytest ids; **See** links are relative `.md` links, to another page or to a
  capability's living spec.
- An anchor outside backticks is invisible to the checker, so always use backticks.

## The checker

```bash
python3 .claude/skills/project-wiki/scripts/check_wiki.py
```

It prints one line per problem and exits 1 if there is any: a missing page or a sidebar that does
not link all six; a page over 100 lines, a changelog line over 100 characters, a decision over 5
lines; a broken link; an anchor whose file or symbol no longer exists. `wiki-generator` runs it
before every wiki commit, and `/implement-issue` runs it before showing the local PR.

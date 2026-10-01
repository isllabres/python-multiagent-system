---
name: commit-messages
description: How commit messages are written in this project — short, descriptive, one idea each, with the red/green/wiki prefix per criterion. Carried by the tester, who makes the red commits, the developer, who makes the green ones, and the wiki-generator, who makes the wiki ones.
---

Someone reading `git log --oneline` should know what each commit does without opening it.

## Who commits what

| Commit | Made by | When |
|---|---|---|
| `red(#<issue>-<AC>): <the behaviour the test expects>` | `tester` | The test or eval exists and fails for the right reason. It goes in even though it fails |
| `green(#<issue>-<AC>): <the change that turns it green>` | `developer` | The criterion's test or eval passes |
| `wiki(#<issue>-<AC>): <what the wiki now says>` | `wiki-generator` | After every red or green commit. If it only logged the commit: `wiki(#<issue>-<AC>): log <hash>` |
| `wiki(#<issue>): survey <area>` or `wiki(#<issue>): repair <what>` | `wiki-generator` | An area the wiki did not cover yet, or anchors reported stale. No changelog line |

One commit per criterion per colour; each of them is followed by its own `wiki(...)` commit.
Never `git add -A`: stage the files you touched by name.

## The subject

- **One line, 72 characters at most, prefix included.** `red(#12-AC2): ` already takes 14, so what
  follows it is about 55 characters. No body unless the *why* is not obvious from the diff; then a
  blank line and at most three lines. Trailers the harness adds are fine.
- **Imperative, present tense, no trailing period**: "reject rows without customer_id", not
  "rejected", "rejecting" or "rejects".
- **Name the behaviour, not the activity**: what the code now does, in the spec's words. Never
  "add test", "update code", "fix", "wip", "changes" or "address feedback".
- **One commit, one criterion, one idea.** If you need "and" to describe it, it is two commits, or
  the criterion is too big: tell `manager`.
- Do not list files, paste the failure output (that goes in your report), repeat the issue title,
  or use emoji.

| | Vague, or doing two things | Short and descriptive |
|---|---|---|
| red | `red(#12-AC2): add test` | `red(#12-AC2): reject rows without customer_id` |
| green | `green(#12-AC2): fix schema stuff and update the loader so it works` | `green(#12-AC2): validate customer_id in load_rows` |

## Fix rounds

A commit made in a fix round keeps its colour's prefix and says what the change does ("reject empty
ids"), not that it answers a review. If a fix changes a test or eval, `tester` makes it, as a
`red(...)` commit; a `green(...)` commit never touches a test, an eval runner or a case file.

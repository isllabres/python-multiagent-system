# Design

## Context

`HttpClient.get` makes one attempt and raises `ServerError` on any 5xx response.

## Goals / Non-Goals

**Goals:** at most 3 attempts on a 5xx response, with exponential backoff between them.

**Non-Goals:** retrying 4xx responses or network timeouts.

## Files

- `src/client.py` — modify
- `tests/test_client.py` — new

## Decisions

- Retry inside `HttpClient.get` with a loop. Discarded: a retry decorator, because only one call site needs it and a decorator would hide the attempt count from the tests.
- The backoff sleeps through an injected `sleep` callable, so the tests run without waiting.

## Risks / Trade-offs

- A dead upstream now fails after about 3 seconds instead of at once.

## Open Questions

- None.

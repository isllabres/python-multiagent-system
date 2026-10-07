<!-- openspec:change add-retry-backoff -->

OpenSpec change `add-retry-backoff`. This issue is its source of truth: change it with `/update-issue`, never in the branch's mirror.

---

**`proposal.md`**

<!-- openspec:file proposal.md -->

# Proposal

## Why

Batch jobs fail as a whole when an upstream service returns a transient 5xx response, and a rerun costs hours.

## What Changes

The HTTP client retries a request that fails with a server error, with exponential backoff between attempts, before it gives up and raises.

## Capabilities

### New Capabilities
- `http-client`: how the HTTP client handles a failed request

### Modified Capabilities

## Impact

`src/client.py` (`HttpClient.get`). No new dependencies.

## Out of scope

- Retrying 4xx responses: they are the caller's error.
- Retrying network timeouts.

<!-- /openspec:file -->

---

**`specs/http-client/spec.md`**

<!-- openspec:file specs/http-client/spec.md -->

# Spec Delta

## Purpose
How the HTTP client reacts to a failed request and when it stops retrying it.

## ADDED Requirements

### Requirement: Retry server errors
The client SHALL make at most 3 attempts for a request that fails with a 5xx status.

#### Scenario: Server error is retried
- **WHEN** the first two attempts return 503 and the third returns 200
- **THEN** `get` returns the 200 response after exactly 3 attempts

#### Scenario: Retries are exhausted
- **WHEN** three consecutive attempts return 503
- **THEN** `get` raises `RetryExhausted` carrying status 503, after exactly 3 attempts

<!-- /openspec:file -->

---

**`design.md`**

<!-- openspec:file design.md -->

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

<!-- /openspec:file -->

---

**`tasks.md`**

<!-- openspec:file tasks.md -->

# Tasks

## 1. Requirement: Retry server errors

- [ ] 1.1 [test] `tests/test_client.py::test_server_error_is_retried` — Scenario: Server error is retried
- [ ] 1.2 [test] `tests/test_client.py::test_retries_are_exhausted` — Scenario: Retries are exhausted
- [ ] 1.3 [code] Retry 5xx responses in `HttpClient.get` with exponential backoff; both tests pass

<!-- /openspec:file -->

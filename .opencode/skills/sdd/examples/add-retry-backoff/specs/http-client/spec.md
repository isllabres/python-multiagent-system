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

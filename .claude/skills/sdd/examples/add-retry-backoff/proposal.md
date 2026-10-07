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

# Tasks

## 1. Requirement: Retry server errors

- [ ] 1.1 [test] `tests/test_client.py::test_server_error_is_retried` — Scenario: Server error is retried
- [ ] 1.2 [test] `tests/test_client.py::test_retries_are_exhausted` — Scenario: Retries are exhausted
- [ ] 1.3 [code] Retry 5xx responses in `HttpClient.get` with exponential backoff; both tests pass

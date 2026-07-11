# Provider Resilience

`scripts/provider_resilience.py` performs provider preflight, quota classification, backup provider selection, token/cost estimation, retry classification, and health report writing.

Supported provider statuses:

- `PROVIDER_OK`
- `PROVIDER_QUOTA_EXCEEDED`
- `PROVIDER_TRANSPORT_UNSTABLE`
- `PROVIDER_AUTH_FAILED`
- `PROVIDER_RATE_LIMITED`
- `PROVIDER_UNAVAILABLE`

Commercial rules:

- `PROVIDER_QUOTA_EXCEEDED` blocks live commercial generation.
- If an enabled backup provider reports `PROVIDER_OK`, it is selected automatically.
- If no backup is available, readiness becomes beta/provider-blocked or blocked depending on surrounding safety checks.
- Transport instability is retryable and must not be reported as semantic project failure.

Provider health reports are written under `examples/test_results/` and must not include API keys.

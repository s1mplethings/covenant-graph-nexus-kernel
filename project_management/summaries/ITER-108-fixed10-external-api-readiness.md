# ITER-108 — Fixed10 external API readiness

Outcome: `NEEDS_REWORK`.

The existing production facade and ProviderJob route now support an explicit
OpenAI-compatible external API profile for generation and affected-only repair.
Live transport is blocked until environment credentials, endpoint, model,
dependency source, and complete run budgets are explicit. Every live call is
reserved before transport in a privacy-safe process-safe ledger. Cache replay is
identified separately and cannot count as a new live generation.

The frozen Fixed10 manifest remained
`9B470B65970D6A3A33D45CDCAA4646B785F1F348C27F6121573F23E7D57974AF`.
No paid Provider call, Codex generation call, or Codex repair call occurred.
All ten projects remain `NOT_EVALUATED`; the smoke and revisions also remain
`NOT_EVALUATED`.

Focused verification passed 10 tests. The Provider-free regression and the
full_all profile each reached the 1800-second bound with failures already
visible in partial output. Both receipts are retained as `TIMEOUT`; neither is
claimed as PASS. Existing Pass 6 evidence was not modified or reinterpreted.

# ITER-016 — adaptive Provider evaluation

Phase 0 passed and ratcheted the source-bound gateway into
`BASELINE-PROVIDER-GATEWAY-001`. The bounded Phase 1 source increment added
task-specific benchmark contracts, the fixed eight-case micro suite, local
hidden evaluators, credential-free receipts, profile aggregation and cache,
reliability-first deterministic selection, and immutable pre-run routing.

Offline Micro, Fast, and Promotion scopes passed with 48/81/127 tests and two
platform-conditional skips in each applicable run. Compile, product direction,
kernel architecture, test architecture, and baseline ledger gates passed.

Live preflight stopped the iteration under condition A. Qwen and Grok vendor
credentials were rejected with HTTP 401. DeepSeek credentials could list
`deepseek-flash` and `deepseek-v4-pro`, but both models rejected the fixed
`json_schema` response format with HTTP 400. Seven bounded benchmark or
diagnostic transports produced zero accepted benchmark receipts, so no profile,
winner, or run routing snapshot was created. Unknown cost remains
`UNAVAILABLE`; it was not recorded as zero.

The iteration status is `PROVIDER_SELECTION_BLOCKED_ENVIRONMENT`. Repository
Codegen, Capability Builder, and Self-Growth V1 were not started. The current
baseline remains `BASELINE-PROVIDER-GATEWAY-001` with no removed guarantees.

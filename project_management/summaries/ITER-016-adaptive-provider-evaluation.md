# ITER-016 — adaptive Provider evaluation

Phase 0 passed and ratcheted the source-bound gateway into
`BASELINE-PROVIDER-GATEWAY-001`. The bounded Phase 1 source increment added
task-specific benchmark contracts, the fixed eight-case micro suite, local
hidden evaluators, credential-free receipts, profile aggregation and cache,
reliability-first deterministic selection, and immutable pre-run routing.

The connector-backed focused scope passed with 68 tests and two skips; the
promotion-like scope passed with 129 tests and two skips. Compile, product
direction, and kernel architecture gates passed. Kernel evidence was refreshed
after the connector source and test mappings were added.

The fixed live suite then completed 16 budget-controlled calls against
DeepSeek `deepseek-flash` and Grok `grok-4.7`: 15 succeeded and one Grok call
had a transport failure. The conservative estimated total cost was USD
0.061476, with zero unknown-cost calls and no persisted credentials. Both
Providers were eligible for `agent.composition`, `structured.output`, and
`worker.codegen`; DeepSeek won composition and code generation with HIGH
confidence under the deterministic policy.

`worker.repair` did not satisfy the two-eligible-Provider requirement.
DeepSeek passed one of two cases and failed the other with scope and interface
violations, making its repair profile ineligible. Grok passed one of two cases
and retained eligibility despite one transport failure, leaving only one
eligible repair candidate. A later isolated DeepSeek diagnostic succeeded, but
it did not replace the formal fixed-run receipt.

The iteration status is `PROVIDER_SELECTION_NEEDS_REWORK`. No immutable
routing snapshot or Provider selection baseline was created. Repository
Codegen, Capability Builder, and Self-Growth V1 were not started. The current
baseline remains `BASELINE-PROVIDER-GATEWAY-001` with no removed guarantees.

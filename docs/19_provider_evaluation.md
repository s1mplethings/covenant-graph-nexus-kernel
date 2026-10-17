# Provider evaluation and frozen routing

Provider evaluation is an application-layer decision service above the existing
`CompletionClient` transport boundary. It never owns project composition,
runtime scheduling, capability admission, or delivery.

The first policy evaluates providers per task class. Benchmark cases use the
same prompt facts, contracts, limits, retry policy, workspace, and acceptance
for every candidate. Receipts never contain credentials. Profiles become
ineligible when any fixed-suite sample violates schema, interface, scope, or
secret-safety requirements, and fewer than two samples is insufficient.

Selection is deterministic and reliability-first. Unknown cost is recorded as
`UNAVAILABLE` and its weight is removed instead of treating it as zero. Close
scores resolve by cost, token usage, latency, then provider ID. There is no
global provider rank.

Every project or growth run freezes a `RunProviderRoutingSnapshot` before its
first provider call. Its fallback policy is always `deny`; benchmark results
or failures recorded during a run can affect only a future run.

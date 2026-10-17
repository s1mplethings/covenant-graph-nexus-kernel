# Provider gateway integration — 2026-10-17

Iteration `ITER-015` closed `PASS_WITH_LIMITS` for backlog item `PB-021`.

The increment added a loopback-only `GatewayCompletionClient`, immutable
Qwen/DeepSeek/Grok role routing, credential-free run snapshots, schema and
truncation validation, and pre-transport reservations in the existing Provider
budget ledger. The existing OpenAI-compatible client remains the default and
no composition, execution, acceptance, packaging, or delivery authority moved
to API Lab.

Offline evidence includes the real Agent MVP CLI and the L6 seeded-repair
runtime over an HTTP mock gateway. Both observed `qwen`, `deepseek`, `qwen`
model routing and completed real pytest; the L6 case also produced a project
snapshot and passed external acceptance. Affected regression reported 194
passed and 1 skipped. The full repository run reported 2169 passed, 345
skipped, and four failures: coverage/evidence closure and iteration schema were
addressed in this increment; one generation lifecycle race is unrelated and
the direction gate is polluted by ignored local worktrees/benchmark folders.

The applied enterprise lessons were `EXP-MVP-003` (bounded worker context),
`EXP-MVP-004` (functional proof before scale), and `EXP-MVP-007` (repository
evidence is not product acceptance). The outcome supports those lessons for
loopback Provider integration but does not evaluate real vendor credentials,
model quality, billing, or interoperability.

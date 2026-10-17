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
snapshot and passed external acceptance. The final source-bound profiles
reported 362 passed and 1 skipped for both unit and full-core, 2183 passed and
350 skipped for the active repository, and `BLOCKED_ENVIRONMENT` for the live
Provider profile. Coverage reported 51.96% statements and 52.23% branches
overall; the new Provider modules individually satisfy the P0 thresholds. The
receipt, source freshness, architecture, test mapping, completeness, and clean
source product-direction gates all passed.

The applied enterprise lessons were `EXP-MVP-003` (bounded worker context),
`EXP-MVP-004` (functional proof before scale), and `EXP-MVP-007` (repository
evidence is not product acceptance). The outcome supports those lessons for
loopback Provider integration but does not evaluate real vendor credentials,
model quality, billing, or interoperability. The first full-run evidence was
discarded after C-drive temporary-space exhaustion caused cascading errors; a
clean rerun with adequate space passed and is the evidence retained here.

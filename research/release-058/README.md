# ITER-058 — CGNK Necessity Boundary

This directory contains the source-bound protocol and normalized evidence for
the CGNK necessity-boundary study and the Knowledge boundary decomposition.

The internal workload compares three routes on the same cheap model and the
same underlying facts: direct raw context (`B0`), a reasonable flat-state
control (`B1`), and current CGNK Knowledge localization (`B2`). The primary
unit is a five-episode scenario chain. Development contains 12 chains; the
frozen formal holdout contains 18 disjoint chains.

Raw Provider responses, ephemeral API Lab tokens, budget-ledger internals, and
temporary workspaces remain outside Git under ignored `artifacts/` paths. Only
normalized, secret-safe summaries and the release-asset index manifest are
committed.

Files:

- `preregistration.md`: frozen hypotheses, protocol, metrics, and exclusions.
- `architecture_before.json` / `architecture_after.json`: deterministic audit.
- `knowledge_boundary_audit.md`: exact SCC cause and safe decomposition.
- `development_summary.json`: development-only optimization evidence.
- `public_benchmark_preflight.json`: environment-only public benchmark checks.
- `formal_summary.json`: frozen aggregate results and usage.
- `statistical_analysis.json`: paired bootstrap/McNemar analysis by chain.
- `claim_ledger.json`: allowed and prohibited public claims.
- `formal_index_manifest.json`: hash/size identity for the release asset.
- `technical_report.md`: complete academic-style report.
- `failure_appendix.md`: the single formal episode failure.
- `security_audit.json`: current/history P0 gate and formal-index safety.
- `clean_clone_reproduction.json`: isolated install and focused reproduction.

Formal results bind Source Closure `a2c7720fb176ba8aa913016dd166e98221282afd`.
They were not used to tune the workload, evaluator, prompts, state projections,
or CGNK implementation.


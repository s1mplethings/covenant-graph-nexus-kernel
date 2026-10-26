# ITER-058 — CGNK Necessity Boundary

This directory contains the source-bound protocol and normalized evidence for
the CGNK necessity-boundary study and the Knowledge boundary decomposition.

The internal workload compares three routes on the same cheap model and the
same underlying facts: direct raw context (`B0`), a reasonable flat-state
control (`B1`), and current CGNK Knowledge localization (`B2`). The primary
unit is a five-episode scenario chain. Development contains 12 chains; the
frozen formal holdout contains 18 disjoint chains.

Raw Provider responses, ephemeral API Lab tokens, budget-ledger internals, and
temporary workspaces remain outside Git under `.service_scratch/release-058`.
Only normalized, secret-safe summaries are committed.

Files:

- `preregistration.md`: frozen hypotheses, protocol, metrics, and exclusions.
- `architecture_before.json` / `architecture_after.json`: deterministic audit.
- `knowledge_boundary_audit.md`: exact SCC cause and safe decomposition.
- `development_summary.json`: development-only optimization evidence.
- `public_benchmark_preflight.json`: environment-only public benchmark checks.

Formal results must bind the frozen Source Closure and must not be used to tune
the workload, evaluator, prompts, state projections, or CGNK implementation.


# CGKN current project management

Current project management follows the product authority in `PRODUCT_GOAL.md`, `MVP_SCOPE.md`, `governance/product_invariants.json`, and `governance/current_architecture.json`.

## Current status

The repository-reset cleanup is closed. Obsolete pre-MVP copies and
orphaned experiment families have been physically deleted from the working tree;
Git history is the archive.

This does not mean the new runtime is operational, and it does not establish
functional readiness.

The remaining compatibility runtime is intentionally retained:

- `scripts/codex_conversation.py`
- `scripts/run_codex_conversation_generation.py`
- `scripts/run_local_pipeline.py`
- `scripts/run_local_pipeline_impl.py`

Further cleanup inside that cluster now requires a working replacement path.

## Current feature increment

`ITER-ADAPTIVE-PROVIDER-CODE-GROWTH-016` first ratcheted the independent API
Lab gateway into `BASELINE-PROVIDER-GATEWAY-001`, then added the bounded
application-layer Provider evaluation substrate. Evaluation is task-specific,
reliability-first, credential-free, and separate from transport. Selection is
pre-run only and every routing snapshot continues to deny fallback.

The connector-backed focused and promotion-like scopes pass. A fixed real
benchmark completed 16 budgeted calls across DeepSeek `deepseek-flash` and
Grok `grok-4.7`, with 15 successful calls and one transport failure. Both
Providers are eligible for `agent.composition` and `worker.codegen`; DeepSeek
is the evidence-based HIGH-confidence winner for both task classes.

The overall result is `PROVIDER_SELECTION_NEEDS_REWORK` because
`worker.repair` has only one eligible Provider. DeepSeek failed one of two
repair cases with scope and interface violations, while Grok completed one of
two repair cases after one transport failure. The unsuccessful result is
retained without cherry-picking a later diagnostic. No routing snapshot or
selection baseline was created. Repository Codegen, Capability Builder, and
Self-Growth V1 remain blocked by explicit stop condition A.

## Roadmap after the active increment

1. complete CapabilityTree edit semantics;
2. complete Tree-to-DAG execution semantics;
3. add more bounded executor adapters;
4. persist project-level state and safe resume;
5. prove one real vertical slice;
6. add affected-subgraph repair;
7. add capability registry and validated self-growth;
8. add optional project-team views and later promotion capabilities.

## Management surfaces

- `backlog.json` — active and future MVP work;
- `risks.json` — current architecture and migration risks;
- `active_iteration.json` — the single active feature increment;
- `enterprise_experience.json` — reviewed reusable lessons;
- `governance/mvp_cleanup_boundary.json` — cleanup completion and migration boundary.

Management records cannot authorize functional success, formal evidence, packaging, or delivery.

## Verification

Local direction, focused, import, and collection checks pass. Full pytest
execution and GitHub Actions verification remain `NOT_EVALUATED` and cannot be
inferred from cleanup evidence.

# CGNK current project management

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

## Latest closed increment

`ITER-057` normalized public CGNK naming, made history-audit scope explicit,
and evaluated whether any architecture-admission Router was justified. The
paired ITER-056 oracle found no architecture-only successes, so Router
implementation stopped at the anti-overengineering gate.

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

Community Operator is `COMPLETE_WITH_ENVIRONMENT_LIMIT` on Source Closure
`0bc46cafb875c3f5da6baa2f7fe99b4e99dd38e1`: all frozen benchmarks, a 30-thread
real read-only scan, Top20 human review, Top10 draft review, compileall, Kernel
gates and profiles, 3,290-test collection, and the 2,933-pass full repository
run completed with zero failures or errors. No external write occurred. Offline
reply-adapter qualification does not authorize a real public reply; that remains
`BLOCKED_ENVIRONMENT_REAL_REPLY` until a controlled self-owned target, official
credentials, and exact approval are available together.

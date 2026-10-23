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

`ITER-CGNK-V2-RESOURCE-SAFE-SCALE-QUALIFICATION-047` attempted to qualify the
frozen production persistence-v2 source at 10k, 50k, 100k, and 250k without
changing storage or knowledge semantics.

The increment is closed `BLOCKED_ENVIRONMENT`. Every fixed local volume exceeded
the hard 75 percent pre-run utilization threshold, so no 10k worker was started.
Memory recovered below the threshold; disk remains decisive. Q: needs at least
31.117 GiB additional free space to cross the hard gate. Production v2 remains
explicit opt-in and v1 remains the new-pack default.

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

The frozen ITER-046 source-bound validation remains current: compileall, product
direction, kernel architecture, test architecture, kernel completeness, receipt
freshness, all eight deterministic Kernel profiles, 3112-test collection, and
full pytest (`2755 passed`, `357 skipped`, `0 failed`, `0 errors`). ITER-047
changed evidence only and started no benchmark worker.

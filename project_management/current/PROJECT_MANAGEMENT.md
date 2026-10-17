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

`ITER-015` integrated the independent API Lab gateway behind the existing
`CompletionClient`. The increment keeps the current composition, execution,
acceptance, packaging, and delivery authorities unchanged. It adds explicit
Qwen/DeepSeek/Grok role routing, immutable run snapshots, loopback-only
transport, and the existing Provider budget ledger at the transport boundary.

The offline acceptance target passed: one seeded repair used a Qwen-routed
Agent and DeepSeek-routed Worker before real pytest, snapshot, and external
acceptance. The increment is `PASS_WITH_LIMITS`: all paid Provider calls remain
`NOT_EVALUATED` until the user starts the API Lab launcher and explicitly
initiates a real test. The current desktop checkout also contains ignored
service worktrees and legacy benchmark directories that make the root-level
direction gate fail; committed-source verification is therefore run from a
clean snapshot.

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

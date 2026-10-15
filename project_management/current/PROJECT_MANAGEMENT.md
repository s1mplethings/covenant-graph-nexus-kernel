# CGKN current project management

Current project management follows the product authority in `PRODUCT_GOAL.md`, `MVP_SCOPE.md`, `governance/product_invariants.json`, and `governance/current_architecture.json`.

## Current status

The repository-reset cleanup has reached its deletion boundary and is recorded as `COMPLETE_UNVERIFIED` in `governance/mvp_cleanup_boundary.json`.

This means obsolete active authorities and standalone pre-MVP validation systems have been moved under `legacy/pre_mvp_reset/`. It does not mean the new runtime is operational, and it does not establish functional readiness.

The remaining compatibility runtime is intentionally retained:

- `scripts/codex_conversation.py`
- `scripts/run_codex_conversation_generation.py`
- `scripts/run_local_pipeline.py`
- `scripts/run_local_pipeline_impl.py`

Further cleanup inside that cluster now requires a working replacement path.

## Active increment

The single active increment is `MVP-002: Wire the common Block execution boundary`.

Execution order:

1. define canonical Block execution request and result contracts;
2. define one replaceable Executor protocol;
3. adapt deterministic local actions to the protocol;
4. execute ready `ExecutionDAG` nodes through a coordinator;
5. persist node results, failures, and provenance;
6. prove real node execution with focused tests.

After this works, the project can migrate one real vertical slice out of the compatibility runtime. Only then should deletion continue inside `codex_conversation.py` or `run_local_pipeline_impl.py`.

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

GitHub Actions on the isolated reset branch has reported startup failure. The product direction gate, focused tests, and full pytest suite remain `NOT_EVALUATED`. The branch must remain unmerged until executable verification exists.

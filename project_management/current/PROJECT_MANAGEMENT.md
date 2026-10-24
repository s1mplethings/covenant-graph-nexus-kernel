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

`ITER-CGNK-SELF-GROWTH-CAPABILITY-INTERNALIZATION-052` evaluates bounded
Self-Growth V1. It adds no production authority: every run starts from an
isolated deterministic registry clone, uses the existing capability builder and
Runtime boundaries, and leaves the production registry unchanged.

The increment first proves gap classification, search, reuse, parameterization,
ephemeral composition, proposal validation, sandbox implementation, hidden
qualification, and derived experience accounting offline. After full regression
and canonical Source Closure, G0/G1/G2/G3 will process the same frozen 100-task
stream. Production adoption remains proposal-only until the formal evidence
shows internalization rather than registry growth debt.

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

Source validation is in progress. Formal Self-Growth evidence is not valid
until one clean canonical Source Closure passes compileall, all Kernel gates and
profiles, collection, and full pytest. Discovery evidence cannot authorize
production admission.

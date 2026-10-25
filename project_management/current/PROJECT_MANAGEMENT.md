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

`ITER-054` adds a Community Operator application capability branch over the
existing Component, Registry, Runtime, Knowledge, Promotion validation, and
approval boundaries. It does not add a Community runtime, scheduler, planner,
Knowledge authority, or public-delivery route.

The active increment discovers bounded public discussions, normalizes thread
context, ranks opportunities with precision-first policy gates, drafts
claim-grounded replies, and keeps every external reply behind an exact-hash
`APPROVED_TO_REPLY` decision. Discovery and drafting may run automatically;
unknown rules, high spam risk, and every public write fail closed to human
review. Real dogfood is read-only unless a self-owned test target, official API,
credentials, and explicit approval are all present.

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

Community Operator evidence is not yet evaluated. Formal evidence will require
one clean canonical Source Closure, frozen policy/schema hashes, all benchmark
gates, a real read-only scan, compileall, Kernel gates and profiles, collection,
and full pytest. Offline reply-adapter qualification cannot authorize a real
public reply.

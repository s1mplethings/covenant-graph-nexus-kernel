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

## Completed feature increment

`ITER-CGNK-KNOWLEDGE-GROWTH-INTERNALIZATION-044` validates how the existing
`ProjectKnowledgePack` accepts new raw evidence, preserves provenance, records
relations, invalidates dependent abstractions, and refreshes derived knowledge
without introducing a second knowledge or retrieval authority.

The iteration uses a hybrid approach: stable raw-evidence, identity, safety,
Conversation, and authority constraints surround an adaptive local-lazy update
implementation and deterministic 100/1000/5000-entry maintenance comparison.

The increment is closed `PASS`. Exact duplicates use zero model calls, local
updates invalidate only actual dependent abstractions, stale derived nodes are
excluded from Conversation, and on-demand refresh recomputes only the selected
stale closure. The result is directional rather than statistically significant;
full-pack JSON serialization remains linear and is tracked as a P2 risk.

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

Source-bound validation passed: compileall, product direction, kernel
architecture, test architecture, kernel completeness, receipt freshness, all
eight deterministic Kernel profiles, 3041-test collection, and full pytest
(`2690 passed`, `351 skipped`, `0 failed`, `0 errors`). Provider network usage
was not required for this deterministic knowledge-maintenance increment.

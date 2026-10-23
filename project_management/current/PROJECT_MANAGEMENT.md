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

`ITER-CGNK-V2-RESOURCE-GATE-CALIBRATION-AND-SCALE-QUALIFICATION-048` replaced
the fixed 75 percent disk gate with a frozen empirical peak-and-reserve policy.
Real production-v2 probes at 1k and 5k calibrated the estimator, after which F:
passed on absolute disk and memory headroom despite being 82.904 percent used.

The frozen production v2 source passed formal 10k, 50k, 100k, and 250k scale,
checkpoint, compaction, semantic, mixed-workload, crash-recovery, and
restart-update-Conversation checks. However, the adoption gate remains closed:
250k checkpoint cold start took 45.472 seconds versus the 37.430-second S0
baseline, a 21.485 percent regression. No adoption commit was created; v1
remains the new-pack default and v2 remains explicit opt-in.

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

The frozen product source retains the ITER-046 source-bound full regression:
compileall, all deterministic Kernel profiles, 3112-test collection, and full
pytest (`2755 passed`, `357 skipped`, `0 failed`, `0 errors`). ITER-048 changed
only benchmark harness/tests and evidence. Its targeted verification is 70/70,
and product direction, kernel architecture, test architecture, kernel
completeness, and kernel test receipt gates all pass. Adoption-specific full
regression is not applicable because the failed cold-start gate prevented any
default change.

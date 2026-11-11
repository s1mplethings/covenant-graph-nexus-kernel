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

`ITER-121` / ACV4 completed the independently tested acceptance and metric
increment. I0-I7 passed 28 local controlled-fixture tests; affected regression
results and the root product direction gate are linked in
`F:/CGKN-ACV4-20261030-01/test-receipts.json` and `direction-receipt.json`.
The prior ITER-015 snapshot is preserved in this evidence directory's baseline.

Acceptance uses the existing FileRunStore authority. Metrics are read-only and
do not select models, promote knowledge or dispatch tasks. Joint experiments
were explicitly deferred. No Provider call was made this round. Earlier real
parallel witnesses remain historical evidence with their original limits;
two unresolved request charges remain in the original ledger. This increment
does not establish whole-repository readiness or arbitrary product delivery.

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

## V5 closeout

ITER-122 / PB-023 adds production provenance to the existing store and acceptance
authority. Final real counter candidate satisfies six frozen requirements; a
bounded Worker repaired a deliberately faulty isolated copy. Three Provider calls
include one evaluator-induced extra call. This is one logical task, with a
provisional score and no clean-protocol calibration claim. Full V5 scope remains
NOT_FULLY_VERIFIED for that sampling limitation. Previous work, two historical
UNKNOWN charges, and all failed evaluations are retained. See
`F:/CGKN-ACV5-20261030-01/report.txt` and `result.json`.

## V5.1 strict calibration attempt

ITER-123 / PB-024 closed with FAIL; PB-024 remains pending. Checker was qualified
and remained unchanged. The real job-state task failed R5; frozen repair-feedback
rendering then failed on hex observations. Engineering recovery and the sole
allowed business repair retained R5 failure. Two real calls, no third call; strict
calibration and U_model are NOT_QUALIFIED. Original candidates, failures, full
time, fees and historical unknown records remain intact. No follow-up experiment
starts automatically. Evidence: `F:/CGKN-ACV51-20261030-01/report.txt`.


## ITER-125 execution continuity
STRUCTURE_HARDENING_FAIL. Generic hardening implemented; 61 new/affected checks pass; frozen related regression 300 passed / 77 failed. PB-026 remains pending. 10 real Provider calls, known estimated CNY 0.6589, no host business patches. History retained. See F:/CGKN-ITER-125/execution-continuity-v1/FINAL_REPORT.md. No full Promotion or formal calibration authorized by this result.


Current iteration: ITER-127 / PB-028. Semantic IR simplification, strict canonical validation, historical replay and bounded corrections. Small project PASS is required before Promotion V2; formal calibration and public publishing remain disabled. Evidence: F:/CGKN-ITER-127/semantic-ir-to-promotion-v1.

ITER-130 active: adaptive harness and contract closure, V4 then conditional Promotion V2. Evidence: F:\CGKN-ITER-130\adaptive-harness-to-promotion-v1. Qualification pending; no publication or calibration.

ITER-131 active: adaptive harness and contract closure, V5 then conditional Promotion V2. Evidence: F:\CGKN-ITER-131\full-penetration-closure-v1. Qualification pending; no publication or calibration.

ITER-131 closed: V5 accepted; Promotion PRODUCT_NOT_READY. Formal calibration not started. Evidence: F:\CGKN-ITER-131\full-penetration-closure-v1\FINAL_REPORT.md.

ITER-132 active: production entry/authority convergence, cheap-first milestone compiler, new small dogfood, then Promotion product. Evidence: F:\CGKN-ITER-132\production-core-convergence-v1. Previous failures remain sealed.

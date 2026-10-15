# Project Decomposition Tree Mainline

`project_decomposition_tree.json` is the mandatory production index connecting ProjectSpec planning to generated source, independent failure evidence, exact ProviderJob repair, issue-level acceptance, and final evidence state.

The mainline is:

`User Goal -> ProjectSpec -> Project Decomposition Tree -> ProviderJob DAG -> BUILD_FIRST -> provisional candidate -> canonical probes/evaluator -> tree-bound Issue Ledger -> exact ProviderJob delta -> issue-level acceptance -> Evidence Tree update -> unchanged final gate -> local_packager`.

Plan Tree, Issue Tree, and Evidence Tree use the same node ids. A failure without a deterministic node mapping is recorded as `unmapped_failure`, is not Provider-repairable, and cannot widen to a component. The tree carries no formal evidence or release authority.

## Plan Tree

The goal is decomposed into capabilities, stages, components, files, and expected evidence before Provider generation. This is a stable routing index, not a second planner.

## Issue Tree

Probe, evaluator, semantic-review, and build-coherence failures map back to the closest existing node. A mapped repairable issue then binds the exact existing ProviderJob and its minimal owned files. No node means no Provider repair.

## Evidence Tree

Canonical probe/test/evaluator results and issue-level acceptance records update `current_evidence` and status on the same node. The update is support state only; final readiness still comes from the canonical final gate.

CASE01-style CSV projects declare static entry, upload, clean/preview, CSV export, and delivery-evidence capability nodes. CASE03-style local board projects additionally declare canonical `main`, canonical verifier, DOM alignment, CRUD, move/status, persistence, and export nodes. These are selected from the production GoalSpec domain and capabilities, never from benchmark case IDs or hidden acceptance.

For example, a CASE01-style `GET /` 404 maps to `capability.static_web_entry`, then to the ProviderJob that owns `app/main.py`; it never becomes a broad backend repair. A CASE03-style missing `main` maps to `semantic_contract.main_entry`, while a Selenium import in generated tests maps to `test_contract.canonical_verifier`.

Allowed repair flow is `mapped node -> issue ledger -> exact ProviderJob -> owned delta -> affected-behavior validation -> evidence update`. Unallowed flow includes direct candidate patching by the kernel, whole frontend/backend regeneration without a node, evidence-only Provider work, or any tree-derived release promotion.

Repairable semantic failures such as a missing expected Python `main` symbol or a generated test importing Selenium are retained as exact owned-source diagnostics and may materialize only when the candidate is otherwise complete and free of fatal fact blockers. Unsafe paths, malformed Provider output, fake artifacts, and missing required source remain blocking.

There is still one Provider scheduler: the existing production split-file leaf executor in `run_local_pipeline_impl.py`. `decomposition_tree.py`, `issue_ledger.py`, `provider_jobs.py`, and `repair_acceptance.py` are deterministic contracts/helpers and do not schedule work.

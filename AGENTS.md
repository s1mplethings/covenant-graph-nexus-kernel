# CGKN Agent Contract

## Product authority

Before non-trivial architecture work read PRODUCT_GOAL.md, MVP_SCOPE.md, governance/product_invariants.json, and governance/current_architecture.json. These outrank historical design notes, benchmark reports, and project-management summaries.

CGKN self-hosting uses the reviewed `skills/manage-pmp-agile-quality` method.

The reviewed Codex conversation generation route remains: API/provider project generation -> provider output validation -> post-build finalization -> local_packager -> public_delivery_gate -> delivery_manifest.json. Kernel work must not create a second public delivery route.

## Current MVP architecture

High-capability Agent -> CapabilityTree -> ExecutionDAG -> Component/Block -> replaceable Executor -> Result/Test -> Project State -> Agent checkpoint

The Agent owns project-level understanding and key decisions. Executors perform bounded work. Cheap APIs, local models, search, browser tools, scripts, test runners, and provider models are executors; they do not become the canonical project planner.

Tree structure represents composition. DAG structure represents executable dependencies.

## Non-negotiable rules

- Do not introduce a mandatory Product -> Design -> Build -> QA -> Delivery kernel sequence.
- Do not introduce mandatory virtual-team role stages.
- Roles are capability bundles/views only.
- Do not make a Provider or cheap model the canonical project-level planner.
- Do not create a second planner, scheduler, Component runtime, project-state authority, or execution graph.
- New executable capabilities must expose the common Component/Block input-output boundary.
- Prefer deterministic tools when model reasoning is unnecessary.
- Keep executor context bounded to the node and relevant dependencies.
- Failures should invalidate the smallest safely identifiable affected subgraph.
- Self-growth means validated capability acquisition/reuse, not unrestricted kernel self-modification.
- Do not restore Fixed10, role-driven validation ladders, stress, latency, or long-horizon tests as MVP readiness gates before repeated functional substrate success.

## Compatibility systems

The pre-reset Provider generation, formal evidence, packaging, public-delivery, and false-pass systems may remain in source while migration proceeds. They are compatibility/future systems, not product-definition authority. Do not expand them merely because they already exist.

## Repository changes

- Keep project-specific workflow logic out of the kernel.
- Add capabilities as reusable Components/Blocks.
- Keep team roles above the kernel.
- Run python scripts/product_direction_gate.py after architecture changes.
- Preserve guarded repository publishing and do not force push routine changes.

## Canonical repository publication

`scripts/canonical_repo_publish.py` is the sole staging, commit, normal-push,
and remote-SHA verification authority. Publication must use an explicit
ChangeManifest and current TestReceipt. Never use implicit bulk staging,
force push, automatic hard reset, or a successful push exit code as proof of
publication; the fetched remote branch SHA must match the committed SHA.

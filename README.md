# CGKN

CGKN is a composable autonomous project-team kernel.

The current MVP uses one high-capability Agent for project-level decisions, a Capability Tree for incremental composition, an Execution DAG for runtime dependencies, and replaceable executors for bounded work.

Mainline:

User Goal -> High-capability Agent -> Capability Tree -> Execution DAG -> Component/Block -> cheap model | local model | API | search | script | test tool -> Result/Test -> Project State -> Agent checkpoint

## What remains from the long-term vision

CGKN can grow into a project team with project management, coding, testing, research, release, promotion, and other capabilities. These are composed on the same substrate. Roles such as Developer, Tester, Researcher, or Marketing are capability bundles/views, not kernel stages.

## Current MVP priorities

1. Component/Block boundary
2. CapabilityTree
3. Tree-to-DAG compilation
4. executor assignment and bounded context
5. real tool/test execution
6. smallest-affected-subgraph repair
7. project state
8. capability reuse and later self-growth

Product authority lives in PRODUCT_GOAL.md, MVP_SCOPE.md, governance/product_invariants.json, and governance/current_architecture.json.

Run the direction gate with: python scripts/product_direction_gate.py

## Reusable foundation kept

- cgkn/component/: ComponentSpec, PortSpec, execution/result contracts
- cgkn/artifacts/: artifact identity/materialization
- cgkn/orchestration/: CapabilityTree and ExecutionDAG
- cgkn/runtime/: deterministic component/artifact runtime
- scripts/work_nodes.py: bounded work compatibility contract
- scripts/provider_jobs.py: Provider executor/PatchSet adapter
- scripts/real_test_execution.py: real test/runtime support
- scripts/canonical_repo_publish.py: guarded repository publication

The large pre-reset Provider project-generation and formal-delivery stack remains compatibility/future material. It is not the product-definition authority for the MVP.

Historical stress ladders, role-driven validation passes, Fixed10 launchers, and superseded fixed-flow architecture documents must not return as MVP readiness authorities.
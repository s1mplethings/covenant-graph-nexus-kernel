# CGNK Product Goal

CGNK is an autonomous project-team kernel built on a composable capability system.

The core rule is: a high-capability Agent owns project-level understanding and key decisions; CGNK exposes reusable capabilities through stable input/output boundaries, expands work as a Capability Tree, compiles executable dependencies into an Execution DAG, and delegates bounded execution to replaceable low-cost models, local models, APIs, tools, or deterministic programs.

For software-project generation, the coordinating Agent first designs and freezes one minimal `ProjectBlueprint`. It then delegates cohesive units through the existing CapabilityTree and ExecutionDAG. Repair preserves that blueprint, current workspace, observed interfaces, successful results, and project state, and reruns only the smallest affected unit and downstream checks.

CGNK is not a fixed Product -> Design -> Build -> QA pipeline, not a model router, and not a virtual-company simulator.

## Product layers

1. Project Team: maintains goals, state, changes, coding, testing, research, release, promotion, and other project work. Roles are capability bundles/views, never mandatory kernel stages.
2. Agent Decision Layer: the high-capability Agent understands the goal, expands or edits the capability structure, and handles decisions that bounded executors cannot safely make.
3. Composable Kernel: capabilities use a common Component/Block boundary; composition is represented as a tree; executable dependencies compile to one DAG; failures invalidate the smallest safely identifiable affected subgraph.
4. Executor Layer: cheap APIs, local models, provider models, search, browser tools, scripts, test runners, and deterministic tools are replaceable executors. Executors do not redefine project intent.

## Self-growth

Self-growth means capability growth, not unrestricted self-modification:

gap -> search existing library/API/tool -> bounded trial/integration -> validate common interface -> register/reuse

A learned capability must obey the same input/output, execution, testing, and governance rules as existing capabilities.

## Long-term project-team scope

The same substrate should support project management, coding, integration, automated testing, web/GitHub/package research, asset generation, repository/release operations, promotion/social publishing, feedback, and metrics collection.

These are capabilities built on one kernel, not separate hard-coded pipelines.

## Stable conceptual mainline

User Goal -> High-capability Agent -> Capability Tree -> Tree-to-DAG Compile -> Executor Assignment -> Block Execution -> Artifacts/Results/Tests -> Project State -> Agent Checkpoint -> Continue/Repair/Replace/Expand/Finish

All new product work must strengthen this mainline or add reusable capabilities to it.

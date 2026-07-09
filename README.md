# CovenantGraph Nexus Kernel

**Contract-governed autonomous project studio kernel for agent-planned, evidence-traced, and packageable project generation.**

CovenantGraph Nexus Kernel, or CGNK, is a machine-first design bundle for building an autonomous project production system. It defines how coding agents plan, generate, test, evidence, revise, and package modular projects under explicit contracts.

> 中文：CGNK 是一个面向自主项目生产的合约式 Agent 内核设计包，强调“目标输入 → 合约冻结 → 模块化生成 → 测试证据 → 可交付包”。

## Product goal

A user provides a goal, input expectation, output requirement, and constraints. CGNK then defines the system path for creating a virtual team, building a product story, freezing an output contract, composing a local pipeline, materializing a bounded generated project, producing test / visual evidence, and emitting a delivery bundle.

## Design principles

- **Agent-led** — agents can plan and generate, but must operate inside explicit contracts.
- **Contract-guarded** — product, kernel, module, policy, and flow boundaries are typed and validated.
- **Artifact-traced** — generated outputs, evidence, compile results, and delivery manifests are first-class artifacts.
- **Module-composed** — projects are built from modules with typed ports rather than uncontrolled cross-calls.
- **Evidence-delivered** — a project is not considered complete without test evidence, visual evidence where required, and packaging metadata.
- **User-revisable** — revision paths and known limits are part of the delivery model.

## Required Product Studio mainline

```text
customer_intent
  -> output_contract
  -> virtual_team_roster
  -> product_story
  -> mvp_scope
  -> technical_plan
  -> build_plan
  -> generated_project
  -> test_evidence
  -> delivery_bundle
```

A generated project must not be marked PASS unless the delivery contains a runnable project, startup instructions, test data, test report, required screenshots or visual evidence, a project package, known limits, and a revision entry.

## Source layout

```text
COVENANT_GRAPH_NEXUS_KERNEL_DESIGN.md     Main design document
PRODUCT_GOAL.md                           Product goal and generation rule
docs/                                     Kernel, product studio, agent, flow, evidence, and architecture contracts
schemas/                                  JSON Schemas for contract objects and compiled outputs
examples/                                 Example artifacts, modules, flows, policies, migrations, and compile results
scripts/                                  Validation, blueprint, context, pipeline, runtime, and preflight utilities
implementation_plan/                      Phased implementation plan
codex_prompts/                            Ready-to-use coding-agent prompts
```

Generated apps and runtime/test outputs are not source. They are written to `generated/`, `examples/runtime_runs/`, and `examples/test_results/` when commands run.

## Kernel architecture

```text
Telegram
  -> agent_session
  -> whiteboard/backend_dialogue
  -> pipeline_planner_agent
  -> pipeline_manifest
  -> dynamic_pipeline_runner
  -> local_agent_actions / local_agent_skills
  -> local_packager
  -> delivery_manifest
```

## Quick validation

```bash
python scripts/check_product_studio_contract.py
python scripts/check_product_studio_contract.py --json
pytest tests/test_product_studio_contract.py
python scripts/validate_bundle.py
python scripts/validate_bundle.py --json
python scripts/validate_bundle.py --schema
python scripts/validate_bundle.py --flow flow.project_generation@1
python scripts/validate_bundle.py --flow flow.project_refactor@1
python scripts/validate_bundle.py --flow flow.modular_project_generation@1
```

Boundary Guard sidecar preflight examples:

```bash
python scripts/cgnk_boundary_guard.py --intent examples/boundary/sample_intents.json --case allow_product_story --json
python scripts/cgnk_boundary_guard.py --intent examples/boundary/sample_intents.json --case block_product_agent_generated_path --json
```

## Status

Design baseline and prototype kernel specification for autonomous project studio systems.

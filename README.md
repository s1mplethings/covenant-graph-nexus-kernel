# CovenantGraph Nexus Kernel

**Contract-governed autonomous project studio kernel for agent-planned, evidence-traced, and packageable project generation.**

CovenantGraph Nexus Kernel, or CGKN, is a machine-first design bundle for building an autonomous project production system. It defines how coding agents plan, generate, test, evidence, revise, and package modular projects under explicit contracts.

CGKN is an Autonomous Project Studio Kernel. It is agent-led, contract-guarded, and governed by versioned delivery_manifest contracts.

> 中文：CGKN 是一个面向自主项目生产的合约式 Agent 内核设计包，强调“目标输入 → 合约冻结 → 模块化生成 → 测试证据 → 可交付包”。

`docs/01_contract_registry.md` is the authoritative registry for formal artifact kinds, schemas, producers, consumers, and canonical statuses.

## Product goal

A user provides a goal, input expectation, output requirement, and constraints. CGKN then defines the system path for creating a virtual team, building a product story, freezing an output contract, composing a local pipeline, materializing a bounded generated project, producing test / visual evidence, and emitting a delivery manifest.

## Design principles

- **Agent-led** — agents can plan and generate, but must operate inside explicit contracts.
- **Contract-guarded** — product, kernel, module, policy, and flow boundaries are typed and validated.
- **Artifact-traced** — generated outputs, evidence, compile results, and delivery manifests are first-class artifacts.
- **Module-composed** — projects are built from modules with typed ports rather than uncontrolled cross-calls.
- **Evidence-delivered** — a project is not considered complete without test evidence, visual evidence where required, and packaging metadata.
- **User-revisable** — revision paths and known limits are part of the delivery model.

Generated apps and runtime/test outputs are not source. They are written to `generated/`, `examples/runtime_runs/`, and `examples/test_results/` when commands run.

## Kernel architecture

```text
Telegram
  -> customer request
  -> agent_session
  -> whiteboard/backend_dialogue
  -> reviewed API/provider project generation
  -> provider output validation
  -> post-build finalization
  -> canonical test/runtime/visual evidence
  -> user review when required
  -> local_packager
  -> public delivery gate
  -> delivery receipt
  -> bind active project
  -> canonical final verdict
  -> delivery_manifest
```

`pipeline_planner_agent` + `pipeline_manifest` + `dynamic_pipeline_runner` remain the support/experimental planning lane. They do not replace the Telegram default provider route and cannot call the raw `run_local_pipeline.py` CLI as a second delivery mainline.

The project is generated inside a bounded workspace. Simulator mode is preflight-only and cannot produce a public PASS or delivery manifest.

## Product Studio Direction

```text
Do not ask the user to design the full project path.
Let the user provide goal, input, output, and constraints.
Create a virtual team before implementation.
Freeze the output contract before building.
Turn product story claims into acceptance implications.
Require factual project evidence for final PASS; allow honest warning/review delivery when non-factual quality evidence is incomplete.
```

## Core Direction

```text
Do not make every module call every other module.
Make every module expose typed ports.
Make FlowSpec connect ports.
Make the compiler validate graph compatibility, effect boundaries, policy, and migration invariants.
```

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
  -> delivery_manifest
```

A generated project must not be marked `PASS` unless the delivery contains a real runnable project, startup instructions, test data, canonical test/runtime/visual evidence, required screenshots or visual evidence, a project package, known limits, a revision entry, delivery receipt, and a final zip. Missing tests, previews, local models, or datasets may instead produce `PASS_WITH_LIMITS`, `NEEDS_REWORK`, `NOT_EVALUATED`, or a specific `BLOCKED_*` status; they are not automatic factual blocks.

Canonical final verdicts are written through `scripts/acceptance_verifier.py`. Legacy adaptive delivery judgment may remain as compatibility support, but it is not a second final truth source.

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

```text
REFS: OK errors=0
flow.modular_project_generation@1: OK errors=0
flow.project_generation@1: OK errors=0
flow.project_refactor@1: OK errors=0
```

## Generation Workflow

Telegram is the reviewed public generation front door. Its default route is:

```text
requirement analysis
-> provider project generation
-> provider output validation
-> generated project files
-> post-build finalization
-> canonical test/runtime/visual evidence
-> user review when required
-> local_packager
-> public delivery gate
-> delivery receipt
-> bind active project
-> canonical final verdict
-> delivery_manifest.json
-> Telegram attachment delivery
```

`scripts/run_local_pipeline.py` exposes the reviewed provider implementation for direct diagnostics and acceptance runs. API mode requires `--allow-network --allow-provider --use-api`. Without those flags it performs preflight only and returns a blocked result; it does not generate a fallback project.

Project-file generation is provider-backed by policy. The local composer reduces API context by splitting the project into component-scoped generation calls, then merging component file batches with conflict checks. The generated `pipeline_plan` includes a `component_pipeline` with component ids, dependencies, path hints, prompt budgets, and merge policy.

For blueprint-only inspection:

```bash
python scripts/requirement_blueprint.py --requirement "Build a requirement blueprint generator" --assume-defaults --outputs-dir generated/requirement_blueprint_outputs
```

For local context compression and prompt-pack inspection:

```bash
python scripts/context_prompt.py --requirement "Build a requirement blueprint generator" --max-chars 6000 --json
```

For durable long-context reduction and prompt-ready context packs:

```bash
python scripts/long_context_state.py append-turn --run-dir examples/runtime_runs/my-run --role user --content "Build a resumable generation flow"
python scripts/long_context_state.py reduce --run-dir examples/runtime_runs/my-run
python scripts/long_context_state.py context-pack --run-dir examples/runtime_runs/my-run --active-module module.project.generator@1 --purpose project_generation --prompt-max-chars 6000
```

For local pipeline composition:

```bash
python scripts/compose_local_pipeline.py --goal "Need customer intake, local librarian, local agent planning, project generation, test graph, and effect report" --no-network --no-provider
```

For an explicit provider-backed local acceptance run:

```bash
python scripts/run_local_pipeline.py --goal "Build a local task board" --allow-network --allow-provider --use-api
```

Local execution writes the standard runtime artifacts plus durable long-context artifacts under the run directory:
`conversation_state.json`, `decision_ledger.json`, `generation_checkpoint.json`, and `context_pack.json`.

Project-file generation uses the configured provider/API. Use `--no-api`, `--no-provider`, or `--no-network` only for preflight diagnostics that intentionally stop before project-file generation.

For a legacy compact Product Studio support artifact:

```bash
python scripts/run_product_studio.py --goal "Build a local GUI image rename tool" --input "image folder, prefix + index rule" --output "renamed images, report, README, test data, test report, screenshot evidence, delivery manifest" --out examples/product_studio/runs/demo
python scripts/check_product_studio_contract.py --run-file examples/product_studio/runs/demo/product_studio_run.json
python scripts/deliver_product_studio.py --run-file examples/product_studio/runs/minimal_gui_tool_run/product_studio_run.json --out examples/product_studio/runs/minimal_gui_tool_run
python scripts/check_product_studio_contract.py --run-file examples/product_studio/runs/minimal_gui_tool_run/product_studio_run.json --json
```

The compact Product Studio scripts are legacy/support diagnostics. They do not create formal delivery success; Telegram final delivery must use the provider route, canonical evidence, `local_packager`, public delivery gate, `CGKNDeliveryReceipt`, and canonical final verdict.

## Testing

```bash
python scripts/test_modular_modules.py
python scripts/compose_test_pipeline.py --goal "test CGKN contracts" --profile contracts
python scripts/run_test_pipeline.py --plan examples/test_results/test_pipeline_composition_result.json
python scripts/check_connectivity.py
```

`scripts/check_connectivity.py --live` performs a live OpenAI-compatible API probe when credentials are configured. Test pipeline composition defaults to configuration checks only; pass `--live-api` to `scripts/compose_test_pipeline.py` when a live probe is intended.

## Telegram Customer-Service Output

`scripts/telegram_live_bridge.py` is the single Telegram customer-service output. It handles normal replies, generation status, final delivery text, blocked/timeout replies, and reset commands through one guarded outbound path.

The bridge understands:

```text
/new             Archive only the current chat session and start fresh.
/reset           Archive the current chat session plus this chat's generated outputs, then start fresh.
/delete_history  Permanently delete the current chat session plus this chat's generated outputs.
/status          Show background generation status.
```

During generation the bridge starts one background job per chat, sends a waiting message, and only sends the final delivery after project generation, checks, and preview discovery finish. Delivery sends available videos and up to three preview images directly; if no real preview image exists, it tries to create a summary PNG fallback.

Set credentials in the shell that starts the listener:

```powershell
$env:TELEGRAM_BOT_TOKEN="your-bot-token"
python scripts/telegram_live_bridge.py --chat-id "123456789" --generation-timeout 900
```

`scripts/telegram_new_listener.py` is no longer a Telegram customer-service listener. Keep it only for local reset maintenance with `--dry-run-reset` or `--reset-now`; do not run it as a second Telegram output.

The reset archives matched history files under `generated/telegram_new_archives/<timestamp>/` by default instead of permanently deleting them. Set `"history_mode": "delete"` in the config only when permanent deletion is intended.

For local reset checks:

```bash
python scripts/telegram_new_listener.py --dry-run-reset
python scripts/telegram_new_listener.py --reset-now
```

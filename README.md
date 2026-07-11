# CovenantGraph Nexus Kernel Design Bundle

This repository is the CovenantGraph Nexus Kernel machine-first baseline for building an **Autonomous Project Studio Kernel**: a contract-governed project production system where coding agents plan, generate, test, evidence, and package modular projects safely.

CGNK is agent-led, contract-guarded, artifact-traced, module-composed, evidence-delivered, and user-revisable.

The product goal is one-sentence project delivery: a user gives a goal, input expectation, output requirement, and constraints; CGNK creates a virtual team, builds a product story, freezes an output contract, composes a local pipeline, materializes a bounded generated project, produces test/visual evidence, and emits a delivery bundle.

## Name

```text
Full name: CovenantGraph Nexus Kernel
Short name: CGNK
Product line: Autonomous Project Studio Kernel
Package/root name: covenant_graph_nexus_kernel_bundle
```

## Source Layout

```text
COVENANT_GRAPH_NEXUS_KERNEL_DESIGN.md   Main design document.
PRODUCT_GOAL.md                         Product goal and generation rule.
docs/00_product_studio_contract.md      Top-level Product Studio contract.
docs/00_kernel_contract.md              Stable Kernel Contract for Telegram, whiteboard, agent-generated pipeline, runner, and packager boundaries.
docs/01_virtual_team_contract.md        Virtual team role and artifact ownership contract.
docs/02_product_story_contract.md       Product story and MVP contract.
docs/03_execution_flow.md               Product Studio execution stage contract.
docs/04_acceptance_and_evidence.md      Delivery evidence contract.
docs/05_agent_operating_contract.md     Agent operating rules.
docs/06_agent_led_layered_architecture.md Agent-led layered architecture contract.
schemas/                                JSON Schemas for contract objects and compiled outputs.
examples/artifacts/                     ArtifactTypeSpec examples.
examples/modules/                       ModuleContract examples.
examples/flows/                         FlowSpec examples.
examples/proposals/                     GraphEditProposal examples.
examples/policies/                      PolicySpec examples.
examples/migrations/                    MigrationSpec examples.
examples/compile_results/               Expected CompileResult snapshots.
scripts/validate_bundle.py              Dependency-light semantic checker.
scripts/requirement_blueprint.py        Generic requirement blueprint generator.
scripts/context_prompt.py               Local context compression, key-point extraction, and prompt-pack generator.
scripts/compose_local_pipeline.py       Local pipeline composer.
scripts/run_local_pipeline.py           Generic local runtime executor.
scripts/compose_test_pipeline.py        Test pipeline composer.
scripts/run_test_pipeline.py            Test pipeline executor.
scripts/check_connectivity.py           OpenAI-compatible API connectivity checker.
implementation_plan/                    Phased implementation plan.
codex_prompts/                          Ready-to-use coding-agent prompts.
```

Generated apps and runtime/test outputs are not source. They are written to `generated/`, `examples/runtime_runs/`, and `examples/test_results/` when commands run.

## Kernel Architecture

```text
Telegram
  -> agent_session
  -> whiteboard/backend_dialogue
  -> reviewed API/provider project generation
  -> provider output validation and semantic review
  -> post-build tests and evidence collection
  -> local_packager
  -> delivery_fact_check
  -> agent_delivery_judgment
  -> delivery_manifest
```

`pipeline_planner_agent` + `pipeline_manifest` + `dynamic_pipeline_runner` remain the support/experimental planning lane. They do not replace the Telegram default provider route and cannot call the raw `run_local_pipeline.py` CLI as a second delivery mainline.

The project is generated inside a bounded workspace. Simulator mode is preflight-only and cannot produce a public PASS or delivery bundle.

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

## Required Product Studio Mainline

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

A generated project must never receive `PASS_FINAL` without a real runnable result and final zip. Missing tests, previews, local models, or datasets may instead produce `DELIVER_WITH_WARNINGS`, `NEEDS_REWORK`, or `ASK_USER_REVIEW`; they are not automatic factual blocks.

`agent_delivery_judgment` uses the bounded local judgment fallback by default. Set `CGNK_ADAPTIVE_DELIVERY_AGENT=provider` to request a provider-backed strict JSON judgment; factual blockers still override the returned verdict.

## Stable Baseline Guarantees

```text
1. Artifact refs are canonical: artifact.name@version.
2. Module refs are canonical: module.name@version.
3. SourceEndpoint and TargetEndpoint are direction-specific.
4. Flow gates use structured Predicate schema, not free strings.
5. GraphEditProposal uses op-specific schemas.
6. project_refactor uses contract-only planning and compiles under no-provider/no-network policy.
7. ContractPack, CompileResult, and CompiledContractBundle have schemas.
8. scripts/validate_bundle.py compiles project_generation, project_refactor, and modular_project_generation successfully.
9. Product Studio runs are governed by docs/00_product_studio_contract.md and related docs.
```

## Quick Validation

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

Expected result:

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
-> local validation and provider semantic review
-> generated project files
-> post-build tests and evidence
-> local_packager
-> delivery_fact_check
-> agent_delivery_judgment
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

For a compact Product Studio run artifact:

```bash
python scripts/run_product_studio.py --goal "Build a local GUI image rename tool" --input "image folder, prefix + index rule" --output "renamed images, report, README, test data, test report, screenshot evidence, delivery bundle" --out examples/product_studio/runs/demo
python scripts/check_product_studio_contract.py --run-file examples/product_studio/runs/demo/product_studio_run.json
python scripts/deliver_product_studio.py --run-file examples/product_studio/runs/minimal_gui_tool_run/product_studio_run.json --out examples/product_studio/runs/minimal_gui_tool_run
python scripts/check_product_studio_contract.py --run-file examples/product_studio/runs/minimal_gui_tool_run/product_studio_run.json --json
```

## Testing

```bash
python scripts/test_modular_modules.py
python scripts/compose_test_pipeline.py --goal "test CGNK contracts" --profile contracts
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

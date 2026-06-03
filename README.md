# CovenantGraph Nexus Kernel Design Bundle

This repository is the CovenantGraph Nexus Kernel machine-first baseline for evolving `cgnk-core-starter` into a contract compiler used by coding agents to plan and generate modular projects safely.

The product goal is one-sentence project generation: a user gives one requirement, CGNK builds a requirement blueprint, composes a local pipeline, materializes a bounded generated project, and emits test/effect artifacts.

## Name

```text
Full name: CovenantGraph Nexus Kernel
Short name: CGNK
Package/root name: covenant_graph_nexus_kernel_bundle
```

## Source Layout

```text
COVENANT_GRAPH_NEXUS_KERNEL_DESIGN.md   Main design document.
PRODUCT_GOAL.md                         Product goal and generation rule.
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

## Core Direction

```text
Do not make every module call every other module.
Make every module expose typed ports.
Make FlowSpec connect ports.
Make the compiler validate graph compatibility, effect boundaries, policy, and migration invariants.
```

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
```

## Quick Validation

```bash
python scripts/validate_bundle.py
python scripts/validate_bundle.py --json
python scripts/validate_bundle.py --schema
python scripts/validate_bundle.py --flow flow.project_generation@1
python scripts/validate_bundle.py --flow flow.project_refactor@1
python scripts/validate_bundle.py --flow flow.modular_project_generation@1
```

Expected result:

```text
REFS: OK errors=0
flow.modular_project_generation@1: OK errors=0
flow.project_generation@1: OK errors=0
flow.project_refactor@1: OK errors=0
```

## Generation Workflow

Use `scripts/generate_project.py` as the front door:

```bash
python scripts/generate_project.py --requirement "Build a local project that turns a requirement into blueprint artifacts"
```

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

For local execution:

```bash
python scripts/run_local_pipeline.py --goal "Generate a generic CGNK project" --no-provider
```

Local execution writes the standard runtime artifacts plus durable long-context artifacts under the run directory:
`conversation_state.json`, `decision_ledger.json`, `generation_checkpoint.json`, and `context_pack.json`.

Optional local-model route hints are disabled unless explicitly enabled with `--use-local-model`. Project-file generation uses the configured provider/API by default; use `--no-api`, `--no-provider`, or `--no-network` only when you intentionally want the provider-only generation policy to fail before writing files.

## Testing

```bash
python scripts/test_modular_modules.py
python scripts/compose_test_pipeline.py --goal "test CGNK contracts" --profile contracts
python scripts/run_test_pipeline.py --plan examples/test_results/test_pipeline_composition_result.json
python scripts/check_connectivity.py
```

`scripts/check_connectivity.py --live` performs a live OpenAI-compatible API probe when credentials are configured. Test pipeline composition defaults to configuration checks only; pass `--live-api` to `scripts/compose_test_pipeline.py` when a live probe is intended.

## Telegram `/new` Reset Listener

`scripts/telegram_new_listener.py` runs a long-polling Telegram listener. When an admin sends `/new`, it stops the configured frontend/backend processes, archives local conversation history, and starts the configured processes again.

The main Telegram bridge also understands:

```text
/new             Archive only the current chat session and start fresh.
/reset           Archive the current chat session plus this chat's generated outputs, then start fresh.
/delete_history  Permanently delete the current chat session plus this chat's generated outputs.
/status          Show background generation status.
```

During generation the bridge queues one background job per chat, sends a waiting message, and only sends the final delivery after project generation, checks, and preview discovery finish. Delivery sends available videos and up to three preview images directly; if no real preview image exists, it tries to create a summary PNG fallback.

Set credentials in the shell that starts the listener:

```powershell
$env:TELEGRAM_BOT_TOKEN="your-bot-token"
$env:TELEGRAM_ADMIN_IDS="123456789"
powershell -NoExit -File scripts/start_telegram_new_listener.ps1
```

Edit `scripts/telegram_new_config.example.json` to point `frontend` and `backend` at the real project directories and start commands. The default frontend entry restarts the latest generated static app on `127.0.0.1:8000`; the backend entry is disabled until a real command is configured.

The reset archives matched history files under `generated/telegram_new_archives/<timestamp>/` by default instead of permanently deleting them. Set `"history_mode": "delete"` in the config only when permanent deletion is intended.

For listener reset checks:

```bash
python scripts/telegram_new_listener.py --dry-run-reset
python scripts/telegram_new_listener.py --reset-now
```

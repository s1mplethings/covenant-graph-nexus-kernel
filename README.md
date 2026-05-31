# CovenantGraph Nexus Kernel Design Bundle

This bundle is the CovenantGraph Nexus Kernel machine-first baseline for evolving `cgnk-core-starter` into a contract compiler used by coding agents to refactor modular project-generation systems safely.

The product goal is one-sentence project generation: a user gives one requirement, customer service asks missing questions, CGNK generates a requirement blueprint, composes a local pipeline, generates the project, and returns test/effect artifacts.


## Name

```text
Full name: CovenantGraph Nexus Kernel
Short name: CGNK
Package/root name: covenant_graph_nexus_kernel_bundle
```

## Files

```text
COVENANT_GRAPH_NEXUS_KERNEL_DESIGN.md   Main design document, in Chinese.
PRODUCT_GOAL.md                                 Product goal and customer-service generation rule.
schemas/                                        JSON Schemas for contract objects and compiled outputs.
examples/artifacts/                             ArtifactTypeSpec examples.
examples/modules/                               ModuleContract examples.
examples/flows/                                 FlowSpec examples.
examples/proposals/                             GraphEditProposal examples.
examples/policies/                              PolicySpec examples.
examples/migrations/                            MigrationSpec examples.
examples/compile_results/                       Expected CompileResult snapshots.
examples/test_results/                          Local validation outputs.
examples/runtime_runs/                          Local smoke-run outputs.
scripts/validate_bundle.py                      Dependency-light reference semantic checker.
implementation_plan/                            Phased implementation plan.
codex_prompts/                                  Ready-to-use coding-agent prompts.
```

## Core direction

```text
Do not make every module call every other module.
Make every module expose typed ports.
Make FlowSpec connect ports.
Make the compiler validate graph compatibility, effect boundaries, policy, and migration invariants.
```

## Stable baseline guarantees in this bundle

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

## Quick validation

```bash
python scripts/validate_bundle.py
python scripts/validate_bundle.py --json
python scripts/validate_bundle.py --flow flow.project_generation@1
python scripts/validate_bundle.py --flow flow.project_refactor@1
python scripts/generate_project.py --requirement "给我做一个本地客户工单看板" --assume-defaults
python scripts/requirement_blueprint.py --requirement "做一个 AI 需求蓝图生成器" --assume-defaults --outputs-dir generated/requirement_blueprint_outputs
python scripts/validate_bundle.py --flow flow.local_pipeline_composition@1 --schema
python scripts/validate_bundle.py --flow flow.modular_project_generation@1 --schema
python scripts/compose_local_pipeline.py --goal "需要一个客服入口、本地 librarian、本地 agent、项目生成、测试图、效果报告，并接 API 和 Telegram"
python scripts/run_local_pipeline.py --plan examples/test_results/local_pipeline_composition_result.json
python scripts/run_local_pipeline.py --plan examples/test_results/local_pipeline_composition_result.json --use-api --allow-network --allow-provider
python scripts/compose_test_pipeline.py --goal "测试 CGNK 本地项目生成流程"
python scripts/run_test_pipeline.py --plan examples/test_results/test_pipeline_composition_result.json
python scripts/test_modular_modules.py
python scripts/check_connectivity.py
python scripts/check_connectivity.py --live
```

Expected result:

```text
REFS: OK errors=0
flow.modular_project_generation@1: OK errors=0
flow.project_generation@1: OK errors=0
flow.project_refactor@1: OK errors=0
```

## Recommended first target

For user-facing generation, start with `scripts/generate_project.py`. It is the front door for: requirement sentence, customer-service clarification, requirement blueprint generation, pipeline composition, local execution, test graph, and effect report.

For blueprint-only inspection, use `scripts/requirement_blueprint.py`. It produces the design-draft stages as structured local artifacts: `requirement_spec`, `io_contract`, `gap_analysis`, `feature_spec`, `capability_map`, `tech_candidates`, `tech_decisions`, `architecture.mmd`, `api.openapi.yaml`, `db_schema.sql`, `frontend_pages.json`, `task_backlog.csv`, `prd.md`, and `review_report.json`.

Start with `flow.project_generation@1` and the module contracts under `examples/modules/`.
For safe no-provider refactors, use `flow.project_refactor@1`, which uses `module.plan.generate.contract_only@1`.

For the modular customer-service/project-generation process, use `flow.modular_project_generation@1`. It keeps customer service, local librarian, local agent planning, online library sources, feature-library search, adversarial generation, project generation, test graph output, and effect reporting as separate module lines until `module.unified_control@1`.

For local project understanding and pipeline composition, use `flow.local_pipeline_composition@1` or run `scripts/compose_local_pipeline.py`. This uses a structured module catalog plus lightweight lexical retrieval by default. A large local model can be connected through `CGNK_LOCAL_MODEL_CMD` for re-ranking or synthesis, but the deterministic local catalog remains the authority for ports, effects, and policies.

For local execution, use `flow.local_pipeline_execution@1` or run `scripts/run_local_pipeline.py`. It materializes a composed pipeline into `generated/local_task_board/` and writes runtime artifacts under `examples/runtime_runs/`. Network and provider actions are disabled by default. API calls require `--use-api --allow-network --allow-provider`; Telegram sending requires `--send-telegram --allow-network --telegram-chat-id <id>`.

For modular testing, use `flow.modular_project_testing@1` or run `scripts/compose_test_pipeline.py`. Testing is split into:

```text
module.test.environment_selector@1      Chooses test environments.
module.test.method_selector@1           Chooses test methods.
module.test.pipeline_composer_agent@1   Binds environments and methods into a runnable matrix.
module.test.pipeline_executor@1         Runs local deterministic checks and emits reports.
```

The default safe runner does not perform live network/provider calls. It can combine contract validation, flow compilation, module smoke checks, generated static project inspection, declared browser smoke checks, industrial I/O fixture checks, runtime artifact inspection, and dry connectivity probes:

```bash
python scripts/compose_test_pipeline.py --goal "测试生成的主播高光项目" --project-dir generated/streamer_highlight_finder_industrial_io_v7 --profile full
python scripts/run_test_pipeline.py --plan examples/test_results/test_pipeline_composition_result.json
```

To run real local browser smoke checks, opt in explicitly. This starts a loopback static server for the generated project and calls the smoke-test functions exposed by the generated test files:

```bash
python scripts/compose_test_pipeline.py --goal "浏览器真实烟测" --project-dir generated/streamer_highlight_finder_industrial_io_v7 --profile generated-project --live-browser
python scripts/run_test_pipeline.py --plan examples/test_results/test_pipeline_composition_result.json
```

You can force a custom matrix with repeated selectors:

```bash
python scripts/compose_test_pipeline.py --goal "只测契约和模块烟测" --environment contract_catalog --environment module_smoke --method schema_validation --method contract_compile --method module_smoke
```

## Module tests and connectivity

`scripts/test_modular_modules.py` runs every module in `flow.modular_project_generation@1` with deterministic local fixtures and writes:

```text
examples/test_results/modular_project_generation_module_test_result.json
examples/runtime_runs/modular-project-generation-smoke/
```

`scripts/check_connectivity.py` checks external connectivity without persisting secrets. It supports the existing OpenAI-compatible and Telegram environment names used by the current local setup:

```text
OPENAI_API_KEY
OPENAI_BASE_URL
CTCP_OPENAI_API_KEY
CTCP_OPENAI_BASE_URL
CGNK_TELEGRAM_BOT_TOKEN
CTCP_TG_BOT_TOKEN
CTCP_TG_TOKEN
TELEGRAM_BOT_TOKEN
CTCP_TELEGRAM_BOT_TOKEN
```

If no Telegram token env var is set, it also checks:

```text
C:\Users\<user>\.ctcp\telegram_bot\bot_token.txt
```

Use `python scripts/check_connectivity.py --live` for a live API ping and Telegram `getMe` probe. The Telegram probe does not send messages.

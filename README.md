# CovenantGraph Nexus Kernel Design Bundle

This repository is the CovenantGraph Nexus Kernel machine-first baseline for building an **Autonomous Project Studio Kernel**: a contract-governed project production system where coding agents plan, generate, test, evidence, and package modular projects safely.

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
docs/01_virtual_team_contract.md        Virtual team role and artifact ownership contract.
docs/02_product_story_contract.md       Product story and MVP contract.
docs/03_execution_flow.md               Product Studio execution stage contract.
docs/04_acceptance_and_evidence.md      Delivery evidence contract.
docs/05_agent_operating_contract.md     Agent operating rules.
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

## Product Studio Direction

```text
Do not ask the user to design the full project path.
Let the user provide goal, input, output, and constraints.
Create a virtual team before implementation.
Freeze the output contract before building.
Turn product story claims into acceptance implications.
Require runnable project, test data, test report, visual evidence, and delivery bundle for PASS.
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

A generated project MUST NOT be marked PASS unless the delivery contains a runnable project, startup instructions, test data, test report, required screenshots or visual evidence, a project package, known limits, and a revision entry.

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
python scripts/generate_project.py --requirement "Build a local project that turns a requirement into blueprint artifacts" --no-network --no-provider --no-api
```

For blueprint-only inspection:

```bash
python scripts/requirement_blueprint.py --requirement "Build a requirement blueprint generator" --assume-defaults --outputs-dir generated/requirement_blueprint_outputs
```

For local context compression and prompt-pack inspection:

```bash
python scripts/context_prompt.py --requirement "Build a requirement blueprint generator" --max-chars 6000 --json
```

For local pipeline composition:

```bash
python scripts/compose_local_pipeline.py --goal "Need customer intake, local librarian, local agent planning, project generation, test graph, and effect report" --no-network --no-provider
```

For local execution:

```bash
python scripts/run_local_pipeline.py --goal "Generate a generic CGNK project" --no-provider
```

Network, provider, API, and optional local-model route hints are disabled unless explicitly enabled with runtime flags. Use `--allow-network`, `--allow-provider`, `--use-api`, and `--use-local-model` only when that run needs them.

## Testing

```bash
python scripts/test_modular_modules.py
python scripts/compose_test_pipeline.py --goal "test CGNK contracts" --profile contracts
python scripts/run_test_pipeline.py --plan examples/test_results/test_pipeline_composition_result.json
python scripts/check_connectivity.py
```

`scripts/check_connectivity.py --live` performs a live OpenAI-compatible API probe when credentials are configured. Test pipeline composition defaults to configuration checks only; pass `--live-api` to `scripts/compose_test_pipeline.py` when a live probe is intended.

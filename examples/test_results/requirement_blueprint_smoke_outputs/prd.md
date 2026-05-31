# Requirement Blueprint PRD

## Raw Requirement

我想做一个 AI 需求蓝图生成器

## Target Users

project_owner, developer

## Core Features

- Project intake: Create a project from a raw natural-language request.
- Requirement understanding: Extract business goal, users, scenarios, pain points, and boundaries.
- Input/output contract analysis: Identify input sources, process steps, outputs, formats, consumers, unknowns, and source types.
- Gap confirmation: Classify unknowns by Level 1/2/3 and block only unresolved Level 3 gaps.
- Feature decomposition: Convert confirmed requirement contracts into feature modules.
- Capability mapping: Map each feature to concrete implementation capabilities.
- Technology discovery: Find candidate libraries or local catalog options for each capability.
- Technology decision: Score candidates and choose library, custom, hybrid, or defer decisions.
- Blueprint generation: Emit architecture, API, database, frontend, workflow, deployment, risks, and PRD artifacts.
- Task backlog: Convert the blueprint into implementation tasks with dependencies and acceptance criteria.

## Technology Decisions

- project_state: custom CGNK rule (custom)
- text_input: custom CGNK rule (custom)
- local_artifact_storage: custom CGNK rule (custom)
- structured_ai_output: OpenAI Structured Outputs (hybrid)
- schema_validation: jsonschema (library)
- business_analysis: custom CGNK rule (custom)
- io_contract_modeling: custom CGNK rule (custom)
- source_attribution: custom CGNK rule (custom)
- confidence_scoring: custom CGNK rule (custom)
- gap_severity_rules: custom CGNK rule (custom)
- user_confirmation_gate: custom CGNK rule (custom)
- default_assumption_policy: custom CGNK rule (custom)

## Acceptance

- The blueprint includes requirement, I/O, feature, capability, technology, architecture, API, database, frontend, task, and review artifacts.
- Level 3 gaps must be resolved before treating the blueprint as final.
- External technology freshness checks require explicit network approval.

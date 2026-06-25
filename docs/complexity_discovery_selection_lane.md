# Discovery & Selection Lane

Discovery & Selection Lane is the neutral upstream lane for complex project requests. It exists to support Requirement Decision First: CGNK should determine the right requirement before treating code generation as success. It runs before Virtual Team Lane and Delivery Lane so CGNK does not turn a rough goal directly into code or collapse a complex request into a small demo.

## Standard Flow

```text
rough_user_goal
-> discovery_brief
-> candidate_directions
-> candidate_scorecard
-> selected_project_direction
-> rejected_options
-> complexity_project_contract
-> downstream planning / generation
```

## Relationship To Existing Lanes

Discovery & Selection Lane decides what complex project shape is worth building and why that requirement is preferable to rejected alternatives. Virtual Team Lane and Delivery Lane remain responsible for planning, implementation, evidence, packaging, and delivery. This lane does not replace provider generation, post-build finalization, `local_packager`, public delivery gate, or final truth checks.

## Input

The input is `rough_user_goal`: the user's coarse project request plus any already frozen intake context. The lane must not require the user to pre-design the full product.

## Output

Each complex project run writes stable artifacts under `run_dir/discovery/`:

- `discovery_brief.md`
- `candidate_directions.json`
- `candidate_scorecard.json`
- `selected_project_direction.json`
- `rejected_options.md`
- `complexity_project_contract.json`

These artifacts are requirement-decision evidence. They should make the selected direction, rejected directions, product scope, risk posture, constraints, and acceptance basis inspectable before implementation starts.

## Avoiding Small Demo Degradation

Candidate directions are rejected when they have low complexity, too few pipeline stages, no testable artifacts, no GUI/CLI shared-core potential, high demo degradation risk, or high fake-pass risk. The selected direction freezes a required complexity floor covering pages, modules, pipeline stages, stage artifacts, GUI, CLI, shared core, runtime evidence, final bundle, and screenshot.

## Avoiding External Dependency Traps

Candidates that depend on live external models, remote APIs, cloud accounts, or unavailable services are penalized. A high external dependency risk candidate cannot be selected unless it has an honest degraded mode that remains testable and deliverable locally.

## Choosing A Deliverable Complex Shape

Selection prefers candidates with:

- `complexity_score >= 75`
- `local_first_feasibility >= 70`
- `pipeline_clarity >= 70`
- `artifact_potential >= 70`
- `gui_cli_suitability >= 70`
- `delivery_feasibility >= 65`
- `testability_score >= 65`

Selection forbids low-complexity demos, high fake-pass risk, high demo degradation risk, missing pipeline stages, missing artifacts, and no GUI/CLI shared-core path.

## Complexity Project Contract

`complexity_project_contract.json` freezes the selected project direction and downstream obligations:

- required planning docs: `product_brief.md`, `technical_plan.md`, `interaction_design.md`, `acceptance_matrix.md`
- required core files: `orchestrator.py`, `stages.py`
- required interfaces: CLI and GUI
- GUI and CLI must share core orchestration/stage logic
- required pipeline stages and stage artifacts
- required artifact fields
- required delivery evidence
- honest degraded mode
- forbidden shortcuts

Downstream planning and generation must cite this contract. Provider generation must see both `selected_project_direction` and `complexity_project_contract`, not only the raw prompt. A generated project that ignores the selected requirement direction is rework, even if it runs.

## Entry Gate

Downstream generation may start only when:

- at least 3 candidate directions exist
- every candidate has structured scoring
- one eligible direction is selected
- rejected options are recorded
- `complexity_project_contract.json` exists and contains required stages, artifacts, evidence, and forbidden shortcuts

## NEEDS_REWORK

The lane must return `NEEDS_REWORK` when no candidate satisfies complexity, feasibility, artifact, GUI/CLI, delivery, testability, and risk thresholds. A `NEEDS_REWORK` discovery result must not be forced into implementation.

Final delivery remains strict. Discovery success alone cannot produce PASS, and missing zip, screenshot, run directory, core files, or required stage artifacts must still fail or require rework.

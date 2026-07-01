# Acceptance Matrix

Planning materialization status: deterministic_contract_planning, not implementation evidence.

## Requirement ID
local_video_material_workbench_requirement

## Acceptance Criteria
- Requirement decision artifacts exist and are internally consistent.
- Product planning docs cite their upstream contracts.
- Implementation structure and stage artifact schemas are present before implementation PASS.
- Delivery has final bundle, screenshot, run_dir, README, TEST_REPORT, and DELIVERY_NOTES before delivery PASS.

## Evidence Required
- requirement_decision: selected_requirement.json, mvp_scope.md, non_goals.md, acceptance_contract.json
- product_contract: product_brief.md, technical_plan.md, interaction_design.md, acceptance_matrix.md
- implementation: orchestrator.py, stages.py, CLI, GUI, shared core, stage artifact schema, upstream/downstream traceability
- delivery: README.md, TEST_REPORT.md, DELIVERY_NOTES.md, screenshot, final_project_bundle.zip, run_dir

## Layer Mapping
| Layer | Must pass only when | Evidence |
| --- | --- | --- |
| requirement_decision | customer need is selected and scoped | selected_requirement.json and acceptance_contract.json |
| product_contract | planning docs are complete and contract-driven | four planning docs with references |
| implementation | runnable structure and artifact schemas exist | shared orchestrator/stages, CLI, GUI, stage artifacts |
| delivery | strict final evidence exists | zip, screenshot, reports, run_dir |

## Must-Have vs Should-Have
- Must-have: independent layer gates, contract-driven planning docs, no fake PASS, strict delivery truth.
- Should-have: richer provider-authored prose when live provider succeeds, while deterministic planning remains acceptable for no-live product planning.

## Non-Goal Exclusions
- Cloud rendering farm
- Guaranteed real speech recognition without configured model
- Public media publishing

## Fake PASS Prevention Checks
- requirement_decision PASS must not make product_contract PASS.
- product_contract PASS must not make implementation PASS.
- implementation PASS must not make delivery PASS.
- Planning docs are not implementation evidence.
- Planning docs are not screenshot, run_dir, or final_project_bundle.zip evidence.

## References
- acceptance_contract.json
- selected_requirement.json
- complexity_project_contract.json

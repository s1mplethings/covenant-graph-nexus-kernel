# CGKN Continuous Verified Generation Loop

CGKN agents are not single-shot fixers. A CGKN agent is a continuous verified generation worker: it inspects the current system state, selects the highest-priority gap, defines a small acceptance contract, changes only what can be verified, runs focused checks, records evidence, and selects the next step.

Requirement Decision First remains the highest rule. Code generation is not the first success condition. CGKN must help the customer discover, compare, select, and freeze the right requirement before treating implementation as meaningful.

## Loop

1. Inspect
   - Read current acceptance artifacts, benchmark reports, test results, and known gaps.
   - Separate requirement decision, product contract, implementation, delivery, test infrastructure, provider transport, and naming consistency gaps.

2. Decide
   - Select one `selected_gap`.
   - Record `reason_for_priority`.
   - Prefer the gap that prevents reliable future verification over cosmetic improvements.

3. Plan
   - Write a small `micro_plan`.
   - Define `acceptance_criteria` before implementation.
   - Keep the plan small enough to verify in the current iteration.

4. Test Contract
   - If there is no test or benchmark for the gap, add one first.
   - Tests must preserve strict delivery truth.
   - Old tests that conflict with Requirement Decision First must update expectations instead of weakening the rule.

5. Implement
   - Make the smallest change that can satisfy the iteration acceptance.
   - Do not create a second formal generation path.
   - Do not hand-build a target project just to improve benchmark appearance.

6. Verify
   - Run the smallest relevant tests.
   - Run milestone benchmarks when the changed layer affects benchmark behavior.
   - Requirement decision PASS must not become delivery PASS.

7. Record Evidence
   - Append one record to `artifacts/continuous_generation_iterations.jsonl`.
   - The record must include selected gap, layer, plan, acceptance, files changed, commands, results, known gaps, and next action.
   - Failed or blocked iterations must be recorded.

8. Select Next Step
   - Choose the next highest-priority gap after verification.
   - If an external blocker exists, record it as an external blocker and stop without fake PASS.

## Status Model

The following states may coexist:

- `requirement_decision_status = PASS`
- `product_contract_status = PARTIAL`
- `implementation_status = FAIL`
- `delivery_status = NEEDS_REWORK`

This is valid and honest. A customer requirement can be clarified while implementation and delivery still need work. Program delivery failure cannot erase requirement success. Requirement success cannot become fake delivery success.

## Stop Conditions

An iteration may stop when:

- the current iteration acceptance is achieved;
- focused tests pass;
- Requirement Decision benchmark passes or a blocker is recorded;
- complexity scale benchmark can output layered status;
- no fake PASS is introduced;
- strict delivery truth remains unchanged;
- an external blocker is recorded with next action.

## Required Iteration Fields

Each iteration must record:

- `selected_gap`
- `reason_for_priority`
- `micro_plan`
- `acceptance_criteria`
- `files_changed`
- `tests_added_or_updated`
- `commands_run`
- `test_results`
- `benchmark_results`
- `known_gaps_after_iteration`
- `next_recommended_action`

## Naming Rule

CGKN is the only current formal project name in new docs, reports, benchmarks, tests, prompts, and artifacts. Historical compatibility markers may remain only as compatibility markers, not current branding.

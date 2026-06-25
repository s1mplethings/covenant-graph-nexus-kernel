# CGKN Agent Test-Integrated Behavior

CGKN agents must integrate testing into the work loop. A change is not complete because it sounds plausible; it is complete only when its acceptance criteria are checked or a blocker is recorded.

## Required Behavior

1. Locate the failing layer before changing code.
2. Write the iteration acceptance before implementation.
3. If no test exists for the behavior, add or update a focused test first.
4. Make only changes that can be proven by a test, checker, or benchmark.
5. Run the smallest relevant tests in every iteration.
6. Run benchmarks at layer milestones.
7. Never replace test evidence with prose.
8. If an old test conflicts with the current CGKN rules, update the test expectation instead of weakening the rule.
9. If a fake provider lacks zip, screenshot, run directory, or manifest evidence, the test must expect rework or the fake provider must produce real evidence.
10. Strict delivery truth must not be weakened to satisfy old tests.
11. New docs, reports, tests, prompts, benchmarks, and artifacts must use CGKN as the current formal project name.

## Requirement Decision First

Complex project generation must not bypass Requirement Decision. Before implementation, the run must have:

- `customer_goal_brief.md`
- `need_interpretations.json`
- `candidate_requirements.json`
- `requirement_scorecard.json`
- `selected_requirement.json`
- `rejected_requirements.md`
- `mvp_scope.md`
- `non_goals.md`
- `acceptance_contract.json`
- `customer_decision_summary.md`

Missing `selected_requirement.json` or `acceptance_contract.json` blocks implementation.

## Fake PASS Guard

The following cannot be accepted as PASS:

- README-only delivery;
- static preview as full project;
- delivery PASS without final zip;
- delivery PASS without screenshot;
- implementation PASS without orchestrator and stages for a complex contract;
- implementation PASS without shared GUI/CLI core when required;
- provider failure rewritten as success.

## Test Update Rule

When old tests expect incomplete artifacts to become ready delivery, fix the test fixture or expectation:

- If the test checks backend triggering, assert backend execution and `NEEDS_REWORK`.
- If the test checks completed delivery, make the fake provider produce screenshot, final zip, run directory, and manifest evidence.
- Do not change final delivery gates to satisfy the old test.

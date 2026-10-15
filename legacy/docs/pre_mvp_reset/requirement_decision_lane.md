# Requirement Decision Lane

Requirement Decision Lane is the first project lane for rough or complex customer goals. It turns ambiguous customer intent into an explicit selected requirement, MVP scope, non-goals, and acceptance contract before Product Design, Virtual Team planning, implementation, or Delivery Lane can treat the run as successful.

## Position

```text
customer raw goal
-> Requirement Decision Lane
-> customer_goal_brief
-> need_interpretations
-> candidate_requirements
-> requirement_scorecard
-> selected_requirement
-> rejected_requirements
-> mvp_scope
-> non_goals
-> acceptance_contract
-> Product Design Lane
-> Contract-Driven Materialization
-> Delivery Lane
```

The wrong flow is `customer raw goal -> direct code -> demo -> README-as-completion`.

## Inputs

- customer raw goal
- optional customer constraints
- optional prior context
- optional reference complexity target

## Outputs

Each run writes stable artifacts under `run_dir/requirement_decision/`:

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

These artifacts are first-class customer requirement evidence. They are not secondary notes.

## Selection Rules

The lane must generate at least three candidate requirements and score each one for customer value, clarity, complexity fit, local-first feasibility, delivery feasibility, testability, MVP focus, and risk control.

It must not select:

- a small static demo when the customer goal implies a complex or production-scale tool
- a direction with high demo degradation risk
- a direction with high fake-pass risk
- a high-risk implementation direction without non-goals, degraded mode, or MVP narrowing
- a direction with no core workflow
- a direction that cannot form acceptance criteria

If no direction is acceptable, the lane returns `NEEDS_REWORK` and downstream implementation must not start.

## Layered Success

Requirement decision success is separate from product implementation and delivery success:

- `requirement_decision_status`
- `product_contract_status`
- `implementation_status`
- `delivery_status`
- `overall_status`

`requirement_decision_status` may be `PASS` while `implementation_status` is `FAIL`. `delivery_status` must not pass just because the requirement was clarified. Missing `final_project_bundle.zip`, screenshot, or `run_dir` must keep delivery at `FAIL` or `NEEDS_REWORK`.

# Requirement Decision First

CGKN is not primarily a code generation tool. Its first responsibility is to help the customer determine the right requirement.

Customers usually start with rough goals, vague ideas, domain context, usage scenarios, constraints, and incomplete assumptions. CGKN must turn that input into a clear, comparable, executable, and acceptable product requirement before implementation is treated as success.

## Core Question

Every agent, pipeline, benchmark, acceptance check, and delivery gate should serve one question:

```text
Did we help the customer determine the right requirement?
```

If the requirement is not clearly defined, generated code is not a real success.

If the program is not fully generated yet, but CGKN has clarified the customer goal, candidate directions, scope, priorities, constraints, acceptance criteria, rejected options, and next steps, that is a valuable intermediate result.

## Required Upstream Behavior

For rough or complex goals, CGKN should:

1. Understand the customer's real target.
2. Explore multiple possible requirement directions.
3. Compare value, complexity, risk, feasibility, and deliverability.
4. Select the most suitable requirement definition.
5. State what should be built and what should not be built.
6. Freeze a requirement contract, product scope, and acceptance criteria.
7. Enter design, implementation, verification, and delivery only after the requirement is clear enough to evaluate.

Implementation must not start when the requirement is still unclear. The system should produce requirement-decision evidence first, including candidate requirements, selected requirement, MVP scope, non-goals, and an acceptance contract.

## Success Boundary

Requirement decision artifacts can be successful intermediate outputs when they are honest, traceable, and actionable. They do not replace final delivery, but they are not failures merely because code is not complete yet.

Generated code cannot override weak requirement definition. A runnable project that does not match a clear customer requirement must be treated as rework.

## Layered Success Model

CGKN reports success in layers:

- `requirement_decision_status`: whether CGKN clarified the customer goal, interpreted needs, compared multiple requirement directions, selected one, recorded rejected options, froze MVP scope, and wrote non-goals.
- `product_contract_status`: whether Product Design artifacts and contracts exist, including `product_brief.md`, `technical_plan.md`, `interaction_design.md`, `acceptance_matrix.md`, `acceptance_contract.json`, and applicable complexity contracts.
- `implementation_status`: whether the implementation satisfies the selected requirement and contract, including core files, shared GUI/CLI logic, workflows, and required artifacts.
- `delivery_status`: whether delivery evidence exists, including `README.md`, `TEST_REPORT.md`, `DELIVERY_NOTES.md`, `run_dir`, screenshot, and `final_project_bundle.zip` when final delivery is claimed.
- `overall_status`: the honest aggregate; it cannot be higher than the real delivery capability when final delivery is requested.

`requirement_decision_status` can be `PASS` while `implementation_status` is `FAIL`. That means CGKN helped the customer determine the right requirement, but did not finish implementation.

`delivery_status` cannot pass just because requirement decision passed. Missing `final_project_bundle.zip`, screenshot, or `run_dir` must keep `delivery_status` at `FAIL` or `NEEDS_REWORK`.

## Agent And Gate Alignment

All agents, pipeline steps, benchmarks, acceptance checks, and delivery gates must serve the same question: did CGKN help the customer determine the right requirement?

Benchmarks should not collapse all value to zero when implementation fails after requirement decision succeeds. Acceptance and delivery gates must still prevent fake PASS when implementation or delivery evidence is missing.

## Relationship To Existing Lanes

Discovery & Selection Lane is the upstream mechanism for finding and choosing a project direction. Product Studio and Virtual Team artifacts turn that direction into product scope and acceptance criteria. Provider generation is a downstream implementation capability, not the first objective.

Delivery gates must verify both product evidence and requirement alignment. They must not pass a project solely because code exists, files are packaged, or a demo runs.

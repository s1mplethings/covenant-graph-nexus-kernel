# ITER-106 bounded increment — role-driven autonomous validation MVP

This completed increment supports the still-active PB-084 ten-project quality
iteration. It does not close that larger iteration and does not change its
formal evidence status.

## Outcome

- Added a model-independent support CLI that derives four roles from public
  ORBIT-360 evidence and produces distinct CLI/Python API tasks.
- Kept tests, hidden acceptance, and prior defect answers outside the public
  role/scenario plan.
- Ran A and B from the same detached Git commit with separate worktrees and
  SQLite test databases. Both arms used four scenarios, ten business actions,
  zero model calls, and zero model cost.
- Generic validation found zero defects. Role-driven validation found one
  additional project-behavior issue and reproduced it in a fresh workspace:
  an accepted `--delta -1000` repair reports `-1000` while changing the weight
  from 63 to 1 (actual delta `-62`).
- The support report remains `NOT_EVALUATED`, has no release authority, and
  cannot authorize generation, packaging, delivery, or formal PASS.

## Review and quality evidence

- Review outcome: accepted with limits for the MVP scope.
- Schema validation: PASS.
- Repository tests: 60 passed for the new module, contract registry, and kernel
  contract suite.
- ORBIT-360 project tests: 8 passed from the project root.
- Kernel static contract check: PASS.
- Bundle reference/schema validation: PASS.
- Raw support evidence:
  `runs/role-driven-validation/orbit-360-mvp-20261014-r2/validation_report.json`.

## Limits and next experiment

One project cannot establish general defect recall. The next experiment is a
frozen multi-project corpus with independently known defects plus reviewed
HTTP and GUI adapters. Optional LLM semantic judgment must remain blinded and
separate from deterministic acceptance.

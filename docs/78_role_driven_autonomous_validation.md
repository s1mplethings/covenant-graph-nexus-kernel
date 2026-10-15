# Role-Driven Autonomous Validation MVP

This is an additive support lane for finding user-visible problems in an
existing project. It does not generate projects, repair customer code, produce
formal evidence, package, or deliver. The reviewed Provider route and
`local_packager` remain unchanged.

## Flow

```text
public project evidence
-> project understanding (tests and hidden answers excluded)
-> 3-5 evidence-backed roles
-> different real-use scenarios
-> CLI / Python API / GUI-capable channel selection
-> isolated Git worktree + isolated test database
-> real program execution
-> independent deterministic evaluation
-> reproduction of every finding
-> support report and A/B comparison
```

The public `scenario_plan.json` contains the project understanding, roles, and
tasks, but never the evaluator's hidden acceptance predicates. The evaluator
does not trust success fields emitted by the project. It checks process exit,
observable output, persisted artifacts, and independently calculated state.
Deterministic results and subjective LLM judgment are separate. The MVP makes
zero model calls and reports subjective judgment as `NOT_EVALUATED`.

## Run the bounded reference trial

From the repository root:

```powershell
python scripts/role_driven_validation.py `
  --project benchmarks/orbit_360_workbench `
  --out runs/role-driven-validation/orbit-360-mvp
```

ORBIT-360 exposes a CLI and Python API but no GUI, so the selector records GUI
as not selected rather than fabricating GUI evidence. Each A/B arm uses the
same detached commit, no model, a four-scenario budget, and a 12-action cap.
Each arm receives a separate SQLite database path and source worktree. The
worktrees are removed after the run; operation logs and actual scenario
workspaces remain under the output directory.

Outputs:

- `scenario_plan.json`: public role and scenario definitions.
- `baseline/operations.jsonl`: exact CLI operations, stdout, stderr, timing,
  hashes, produced artifacts, and evaluation.
- `role_driven/operations.jsonl`: the same evidence for role-driven scenarios.
- per-arm `test_database.sqlite3`: isolated validation-session state.
- `validation_report.json`: machine-readable results conforming to
  `schemas/role_driven_validation_report_v1.schema.json`.
- `validation_report.md`: human-readable independent report, reproduced
  findings, limitations, and next-stage recommendations.

## Adapter boundary

The MVP includes one reviewed `orbit360_v1` adapter. An adapter may only invoke
the project's normal CLI/API and may create test-only control code outside the
project source tree. It cannot call private storage to manufacture a business
success, bypass validation, modify production data, or attach to a running
service. Projects without a safe adapter fail closed.

Future HTTP or GUI adapters should reuse existing runtime and browser evidence
collectors where applicable, but their outputs remain support observations
until consumed by a registered formal evidence authority.

## Metrics and interpretation

The report compares independently reproduced valid findings, false-positive
rate, reproduction success, action count, model calls/cost, and wall time. A
single clean project cannot measure defect recall because the total number of
real defects is unknown. A general improvement claim therefore requires a
frozen multi-project corpus with independently seeded or previously confirmed
defects. Zero findings is allowed and must never be converted into an invented
problem or a formal PASS.

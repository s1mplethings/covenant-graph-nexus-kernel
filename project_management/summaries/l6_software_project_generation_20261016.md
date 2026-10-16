# L6 Software Project Generation — ITER-008

## Outcome

The adapter-only Software Project Generation bundle, scoped worker transaction,
deterministic snapshot, external acceptance harness, benchmark cases, and test
profiles were implemented. The increment stopped at condition B and remains
`PARTIAL` / `GENERATION_LEVEL_0` because the real-provider CLI Stage 1 did not
reach final project PASS within two Application Repair Rounds.

No generated candidate workspace was manually edited. Budgets remained fixed.
Stages 2–5 were not run after the bounded stop condition, so repeatability,
multitype generation, seeded repair, and the six-run frozen suite remain
`NOT_EVALUATED`.

## Exploratory real-provider evidence

The pre-closure Stage 1 run used `qwen3.8-max` for Agent decisions and
`qwen3.7-flash` for scoped file workers:

| Round | Agent | Worker | Deterministic | Provider | Internal test | Runtime | Hidden | Result | Wall time |
|---|---:|---:|---:|---:|---|---|---|---|---:|
| `cc096f216c12-r0` | 4 | 6 | 21 | 10 | FAIL | FAIL | NOT_EVALUATED | FAIL | 335296 ms |
| `e3ab7f137648-r1` | 4 | 8 | 21 | 12 | FAIL | PASS | NOT_EVALUATED | FAIL | 379744 ms |
| `cf020a763d34-r2` | 4 | 5 | 21 | 9 | FAIL | PASS | NOT_EVALUATED | FAIL | 373139 ms |

The final round failed public pytest after a scoped Provider repair regressed an
existing generated interface. This is a project-generation reliability blocker,
not a Kernel authority or environment blocker. Earlier exploratory evidence
showed that internal/runtime/hidden gates can execute, but no run lacking the
Agent's explicit final `FINISH` was promoted to PASS.

## Quality and regression evidence

- L6 unit: 10 passed.
- L6 local functional: 5 passed.
- Hidden acceptance harness: 3 passed.
- Pytest collection: 2372 collected, 0 errors.
- Kernel profiles: static, unit, boundary, fault, security, local-functional,
  full-core, and active-repository PASS; live-provider is
  `BLOCKED_ENVIRONMENT` because the selected case was skipped.
- Active repository: 2020 passed, 352 skipped, 0 failed, 0 errors.
- Core coverage run: 263 passed, 1 skipped; every manifest-bound L0–L5 file
  remains above its required threshold.
- Kernel receipt binds source commit
  `54a0bfd827413966ec232dc9e78f4558247c2126` and has verdict PASS.

## Next increment

Improve bounded Worker interface preservation and public-test repair fidelity
without increasing Agent, Worker, Provider, or Application Repair Round budgets.
Restart Stage 1 from independent empty workspaces; only after a real CLI PASS may
repeatability, multitype, repair, and final frozen validation resume.

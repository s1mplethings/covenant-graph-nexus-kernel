# ITER-106 — Real project generation quality pass

The frozen run `PGBV1_BASELINE_20261014_04` executed exactly ten projects, with two cases at each level L1 through L5, through the reviewed Codex conversation production route in `codex_surrogate` mode. Hidden acceptance remained evaluator-only. Provider scheduling, validation, post-build finalization, `local_packager`, and the public delivery gate retained their existing authority boundaries.

All ten production identities reached the terminal workflow state `REWORK_BLOCKED`. No terminal identity was restarted. The run recorded zero real Provider calls and zero network attempts. Existing Pass 6 24-hour evidence was not changed, deleted, or reinterpreted, and formal CGKN evidence remains `NOT_EVALUATED`.

Independent terminal evaluation used sealed Provider candidate snapshots rather than production verdicts. It reran candidate pytest suites with third-party plugin autoload disabled and exercised real API, file, persistence, repeatability, and fault-isolation scenarios where runnable code existed. API success was not substituted for browser evidence, and missing package or delivery receipts failed closed.

The honest result is `0/10` first-pass and `0/10` final-after-repair. All ten cases are `PROJECT_FAIL`; false-pass and false-negative are both zero. Root failures are four `CODE_GENERATION`, five `RUNTIME`, and one `DEPENDENCY`. Five candidates demonstrated goal-fidelity for their declared hard requirements, four demonstrated persistence, and five demonstrated integration, but none passed the complete runtime, visual, packaging, and delivery contract. The average independent score was 31.5 and requirement coverage was 0.5.

The four planned revisions remain `NOT_EVALUATED` because no base project was independently accepted. No separate post-evaluator repair adapter was invoked; the maximum of two repair rounds remained enforced and the observed benchmark repair count was zero.

Regression verification passed `85` tests with `35` environment/selection skips across `tests/test_project_generation_benchmark_v1.py`, `tests/test_kernel_contract.py`, and `tools/cgkn-agent-kit/tests/test_agent_kit.py`. Production contamination scanning passed.

The next increment is not another soak or a broadened compatibility path. It is a bounded generic correction for complete candidate materialization, usable frontend inclusion, dependency readiness, and semantic-review context size. Any such source change requires a fresh ten-case run under a new run id.

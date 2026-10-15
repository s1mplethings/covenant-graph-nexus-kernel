# ITER-111 — Qwen L1 framework closure

PB-088 closed with limits. The Provider API ledger now records the full request lifecycle and safely reconciles abandoned reservations and uncertain sent calls. Benchmark repair evidence now uses the canonical production `--repair-evidence` schema and entrypoint.

Scoped verification passed 51 tests plus Python and PowerShell preflights. The changed kernel guard passed; the full kernel test file retains one unrelated textual assertion failure around the pre-existing autonomous-acceptance wrapper.

The only paid CASE_01 execution used `qwen3.6-plus` through the existing live Qwen provider. One planning call succeeded at transport level (389 input, 1332 output, 1721 total tokens, 23.282 seconds) but its response used a `planning_proposal` wrapper rejected by the flat canonical schema. The one-planning-call cap blocked another planning request. No project generation or Qwen repair call occurred, no usable candidate was generated, and the independent evaluator returned `PROJECT_FAIL`. Both repair rounds reached the corrected entrypoint but failed closed because no ProviderJob scope existed.

Codex generation and repair calls were zero. Fixed10 was not started. Formal evidence remains `NEEDS_REWORK`.

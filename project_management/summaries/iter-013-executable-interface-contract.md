# ITER-013 — Executable Interface Contract

Status: `PASS_WITH_LIMITS`

The iteration compiled three canonical executable interface contracts from the CSV `ObligationSet`, attached them to WorkUnits, and added staged AST extraction plus a deterministic pre-commit guard. The public CLI is now fixed as `python -m csv_cleaner INPUT OUTPUT`; `-o` and `--output` are forbidden.

The fake correction path rejected a positional-to-optional proposal without mutating the workspace, then accepted the corrected second proposal. A shared recursive materializer fixed nested evidence JSON, and WU-DOCS now depends on the canonical CLI contract rather than WU-CORE implementation completion.

Verification completed with Micro/Fast/Promotion profiles, full-core, active repository (2141 passed, 350 skipped), application full (98 passed), and seeded live repair. Real qwen3.7-flash DAG single passed. Independent DAG repeat reached 2/3; Direct repeat reached 3/3. This authorizes `GENERATION_LEVEL_1` for the single CSV project, not MVP readiness.

Remaining limits: one DAG repeat failed after the fixed repair budget; Direct does not run the DAG pre-commit Interface Guard; a second distinct project is still required; semantic artifact winner remains `NONE`.

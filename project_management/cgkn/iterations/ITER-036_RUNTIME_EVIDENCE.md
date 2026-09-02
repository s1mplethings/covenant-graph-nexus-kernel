# ITER-036 runtime evidence

## Outcome

- Primary-intent correction: PASS. The unchanged YanTu Computer goal now produces `custom_local_application`, ten explicit workflows, and ten one-to-one acceptance behaviors. It no longer selects `productivity_timer` because Pomodoro is only one peer workflow.
- Codex advisory boundary: PASS. Ordinary guidance `with SQLite` no longer creates a required code symbol; only explicit `required code symbol Name` wording does. The sealed brief remained advisory-only with no candidate, evidence, packaging, or delivery authority.
- Chinese MCP transport: PASS. Real UTF-8 JSON-RPC input round-tripped the Chinese goal and gap without surrogate characters or request-hash failure.
- Reviewed Provider rerun: PASS_WITH_LIMITS. The reviewed route executed twice against the isolated project, but no candidate was accepted.
- Formal evidence: `NOT_EVALUATED`. No generated project, delivery manifest, package, or public delivery PASS exists.

## Root-cause evidence

1. The prior requirement lane returned the first fixed profile whose feature term appeared anywhere in the goal. The single Pomodoro clause therefore replaced study planning, knowledge, practice, wrong-answer, review, dashboard, search, and backup workflows.
2. The Codex plan-contract parser interpreted a capitalized word after natural-language `with` or `using` as a code symbol, turning `with SQLite` into a false structural blocker.
3. The Windows MCP stdio server did not explicitly select UTF-8, allowing valid Chinese input from the host transport to be decoded into surrogate characters before canonical hashing.

## Implemented decision rule

- Four or more explicit workflows are evaluated as a workflow set before a fixed profile can win.
- A fixed profile may replace the generic goal-derived product only when its own signals cover at least half of those explicit workflows.
- Otherwise every stated workflow is preserved in the canonical GoalSpec, project workstreams, and acceptance-test identities.
- Codex may add bounded, grounded guidance, acceptance checks, safety constraints, and repair targets. It cannot select a substitute product or become a second planner.

## Regression evidence

Command profile: targeted goal planning, Codex supervision, MCP plugin, kernel contract, requirement/discovery, goal acceptance, project management, and bundled skill tests with host pytest plugin autoload disabled.

Result: `130 passed, 7 skipped in 13.22s`.

Additional validation:

- CGKN plugin validation: PASS.
- Bundled `use-cgkn` skill validation: PASS.
- ITER-036 and enterprise-experience management validation: PASS before closure.
- Existing focused Pomodoro profile regression: PASS.

## Provider evidence

Isolated project: `D:\CGKN\workspaces\kaoyan-408-companion-retest-20260826`

First reviewed Provider execution:

- Foundation files passed.
- The backend plan contained all ten goal workflows and 22 leaves.
- Multiple API calls returned HTTP 504 and used recorded local-model fallback.
- Accepted checkpoints included foundation and early backend leaves.
- Final blocker: `backend/stages_part_04.py` called `ArtifactStore.get_study_plan()` without required `plan_id` after three attempts.
- Result: `BLOCKED`, `provider_fact_blocked`, `FACT_BLOCKED`; no candidate materialized.

One bounded resume execution:

- The command correctly included `--resume-run-dir`, but backend checkpoint identity changed from `19ee64b63b53db8801bcdb185020f9258043ef678274c451c416e62196bd3720` to `12dd22e4452b3a96cd9305c9c0285634b6ead5ad3c200420137ccfa802306817`.
- The cache scan therefore reported all 22 backend leaves as misses instead of reusing accepted leaves.
- Final blocker: `backend/stages_part_01.py` remained below the minimum implementation depth after three attempts.
- Result: `BLOCKED`, `provider_fact_blocked`, `FACT_BLOCKED`; no candidate materialized.

Across both executions the log recorded nine HTTP-504 fallbacks and ten local-model attempts. The controlled generated-project test tool then returned `No recorded generated-project directory exists`, which is the expected honest outcome when no candidate is accepted.

## Remaining limits

- Provider HTTP-504 stability and generated-leaf quality still block complete project materialization.
- Resume eligibility and actual checkpoint identity disagree; the backend spec hash drift prevents effective cross-invocation reuse and should be a separate backlog repair.
- The plugin source cachebuster was updated to `0.1.0+codex.20260826075935`, but automatic `codex plugin add cgkn@personal` was denied by the packaged WindowsApps executable. A fresh task after reinstall from a normal terminal is still required to pick up the new MCP server in the desktop app.

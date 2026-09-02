# ITER-028 Runtime Evidence

Date: 2026-08-20

Outcome: `PASS_WITH_LIMITS`

The replacement process-only Provider credential passed the live `gpt-4.1` smoke check through the configured OpenAI-compatible endpoint. The full credential was not persisted in the project, run artifacts, or this evidence record. The resumed formal run reused the sealed advisory capability brief and its existing hash-bound checkpoints, forced the reviewed Provider route to `api_only`, and retained Provider ownership of all generated-source replacements.

The Provider regenerated the four affected backend leaves and completed split component plus cross-component semantic review with no reported blocker. Post-build tests then exposed concrete runtime defects. The existing Provider post-build repair route reduced seven failures to three; a `gpt-5.5` repair transaction failed safely on retryable HTTP 504 without committing a partial repair. A bounded `gpt-4.1` Provider repair corrected the CLI argument contract and a second bounded Provider repair corrected the repeat-delete exit status. No generated source was manually edited.

Final functional evidence:

- The generated child project's complete pytest profile passed: `7 passed`.
- Canonical goal acceptance is `PASS` and the direct-CLI complexity contract check passed.
- A real CLI flow added two notes, listed them in stable order, searched `PYTHON` case-insensitively, deleted note 1, and returned stable JSON plus exit code 1 on repeat deletion.
- A corrupt JSON store returned stable JSON plus exit code 1 and the original corrupt bytes remained unchanged.
- The explicit no-Web-UI scope was preserved; an irrelevant second repair attempt that proposed `index.html` was interrupted before any file was committed.

Formal limitation:

The generic post-build review gate still treats a pure direct CLI as if visual UI evidence were applicable. It records `ui_status=skipped`, writes `screenshot_blocked.json`, and leaves candidate review at `needs_rework` despite passing pytest, canonical goal acceptance, complexity validation, and CLI runtime probes. The failed closure produced no real final bundle and did not authorize delivery. This is a CGKN applicability defect to address separately; the child project is functionally usable locally but is not represented as formally delivered.

Evidence references:

- `artifacts/agent_helped_notes_20260820/new_key_smoke.json`
- `artifacts/agent_helped_notes_20260820/result_v4_new_key_resume1.json`
- `artifacts/agent_helped_notes_20260820/run_v4/artifacts/candidate_post_build_finalize.json`
- `artifacts/agent_helped_notes_20260820/run_v4/artifacts/goal_acceptance.json`
- `artifacts/agent_helped_notes_20260820/closure_v4_new_key1.json`
- `generated/agent_helped_notes_v4_20260820/artifacts/final_cli_smoke_9355932c2d414e33bbe9434d89592da7/notes.json`
- `generated/agent_helped_notes_v4_20260820/artifacts/corrupt_smoke_edc98adc082047d0a9e80a208d1cd04f/notes.json`

Recommended improvement experiment: make visual evidence explicitly `NOT_EVALUATED` or non-applicable for `direct_cli_application` projects, and prove that this changes only CLI applicability without weakening browser-project screenshot and UI-smoke gates.

Extended black-box, packaging, Unicode, randomized, atomic-failure, and concurrency results are recorded in `artifacts/agent_helped_notes_20260820/EXTENDED_TEST_REPORT.md`. They preserve the `PASS_WITH_LIMITS` conclusion and add concrete single-process versus multi-process applicability boundaries.

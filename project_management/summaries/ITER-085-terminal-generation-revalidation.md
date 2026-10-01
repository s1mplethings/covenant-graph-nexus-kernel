# ITER-085 — Terminal generation revalidation

- Backlog: `PB-064` completed with Provider limits.
- Defect: `run_formal_generation_once` returned an obsolete `REWORK_BLOCKED` result whenever the same goal already had a terminal failed session, so an explicitly authorized revalidation never reached the reviewed route.
- Repair: terminal failed states now enter `start_generation_from_income` with a fresh production identity. Waiting surrogate/replan states remain same-run resumes and successful terminal states do not rerun.
- Zero-API evidence: 154 passed and 13 skipped; management validation and Python compilation passed.
- Canonical publish: repair commit `7ea2facd977b286eeed64752d3097106260475da` was pushed normally and fetched remote SHA matched.
- Runtime: fresh desktop host, fresh Codex host, fresh CGKN MCP processes, healthy `cgkn_status`, and valid unchanged brief `19f7fd7bc62b0a73b672da6ce5146af7f35b9c5ea9d0817e60369677b1cdf589`.
- Smoke: one Qwen/DashScope Chat Completions request succeeded with `qwen3.7-flash`, no fallback.
- Generation: fresh run `production-8ffc7f0800e34269a94c3c2589f654d4` bound the current commit and sealed brief. Run-local metrics recorded six Provider calls: five timeouts and one HTTP 200 response. The successful response was not accepted into the formal requirements-planning chain, and bounded retry exhaustion blocked candidate creation.
- Fail-closed outcome: candidate absent, production provenance absent, formal evidence `NEEDS_REWORK`, and resume remains unsafe. No additional Provider call was made after the bounded run ended.
- Observability limit: the outer formal result reports zero calls while canonical run-local metrics report six.

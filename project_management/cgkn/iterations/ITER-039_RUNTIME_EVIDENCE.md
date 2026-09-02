# ITER-039 Runtime Evidence

Recorded: 2026-08-28T03:31:35+08:00

## Scope and authority boundary

This iteration repairs Provider component-manifest routing, canonical path ownership, and bounded leaf expansion inside the existing reviewed generation route. It does not add a generation or delivery path, write a sealed candidate, package output, or authorize formal project delivery evidence. The generated YanTu project remains `NOT_EVALUATED` and undeliverable until the Provider blocker is resolved and all downstream gates pass.

## Live causal evidence

1. The first resumed YanTu run reproduced the backend manifest omission while the manifest call was routed as a small payload.
2. After adding the component-manifest capability route, the live pending plan selected `gpt-5.5` with `pending_model_capability_floor`; the saved `gpt-5.4-nano` retry could no longer downgrade it.
3. The next live run showed that the Provider returned `app/main.py` and the canonical `src/*.py` paths, but the generic directory table incorrectly labelled them as frontend and pruned them. Exact `canonical_goal_project_plan` ownership now outranks that fallback guess, including when a package hint is present.
4. The following run accepted the 15-leaf backend manifest and reached `src/domain_models.py`. The remote Provider returned HTTP 504, while the local fallback exposed that one eleven-symbol high-complexity leaf was too broad.
5. Automatic bounded children now inherit only a safe same-directory, same-suffix, parent-prefixed path. The resumed live run restored the exact pending identity, expanded `src/domain_models.py` into six independent parts, completed all six parts plus the compatibility facade, and completed `src/repository.py`. Independent receipts/checkpoints exist for each of those eight files.
6. The next exact pending target is `src/service.py`. Continuation stopped on a non-retryable Provider response: `HTTP 401: Balance is insufficient`. No candidate was materialized, post-build finalization did not start, and delivery remains forbidden.

## Verification evidence

- Python compilation passed for all changed runtime, planning, design, and MCP modules.
- Provider fallback, formal mainline, complexity, GoalPlan, kernel, and transport profiles: **420 passed**.
- Direct routing, capability-floor, canonical ownership, multi-file manifest, and resume checks: **7 passed**.
- Total current targeted passing checks: **427**.
- `git diff --check` reports no whitespace errors; only existing LF-to-CRLF conversion warnings are present.
- Management validation passed before closure.

## Review conclusion

The code-level causal fixes are accepted. The live run materially verified each repaired relationship through the repository leaf, but the complete YanTu project cannot be claimed as passing because the Provider account balance exhausted before `src/service.py`. Iteration evidence is therefore `PASS_WITH_LIMITS`; the project runtime blocker is Provider-owned and formal project evidence remains `NOT_EVALUATED`.

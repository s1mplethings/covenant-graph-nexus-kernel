# ITER-083 — Production provenance closure

- Backlog: `PB-062` remains `needs_rework` because the live chain could not create a candidate.
- Scoped repair: PASS. The reviewed run's resolved model policy now reaches requirements planning, and the Agent Kit's validated sealed brief reaches the sole formal Provider pipeline with resume drift rejection.
- Zero-API evidence: 151 passed and 13 skipped across requirement planning, production provenance, formal mainline acceptance, capability-brief validation, kernel contracts, and the Agent Kit plugin. Python compilation passed.
- Global evidence: three unrelated component-generation tests remain failing in `tests/test_formal_provider_fallback.py`; they concern split-leaf regeneration and JavaScript symbol contracts, not the provenance handoffs.
- Canonical publish: repair commit `98ecb9a80e4cc570150da690db6464f9158badb4` was pushed normally and fetched remote SHA matched local HEAD.
- Live evidence: exactly one reviewed attempt used the unchanged Attune brief `19f7fd7bc62b0a73b672da6ce5146af7f35b9c5ea9d0817e60369677b1cdf589`, selected `qwen3.7-flash`, and made one real DashScope transport attempt. It received non-retryable HTTP 403 `PERMISSION_DENIED` because free quota was exhausted.
- Fail-closed outcome: no Provider result, candidate, production provenance, formal evidence, or safe resume state was created. Attune implementation remains blocked.
- Improvement: the outer formal result reports zero calls when a pre-build Provider transport attempt fails, while the canonical provider metrics correctly report one; a later diagnostic increment should align this summary counter without retrying the Provider.

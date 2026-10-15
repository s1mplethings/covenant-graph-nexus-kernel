# ITER-112 — Qwen planning envelope canonicalization

PB-089 completed with limits. The formal requirements-planning boundary now passes a canonical flat object unchanged and unwraps exactly one `planning_proposal` envelope before the unchanged schema. Unknown, nested, ambiguous, malformed envelopes and malformed planning fail closed. Every attempt records raw and parsed identities, the explicit decision, canonical identity, semantic-mutation flag, and schema result.

Verification passed: 8 focused canonicalization tests, 110 requirement-compiler tests, 47 Provider/repair tests, 46 benchmark-framework tests, the changed kernel guard, and Python compilation.

The single live CASE_01 revalidation made one `qwen3.6-plus` planning call. The known envelope was correctly unwrapped, but the enclosed object was a different non-canonical proposal shape and failed the production schema. ProviderJob count and generation calls therefore remained zero. The independent evaluator ran, reported PROJECT_FAIL, and produced no false pass. Downstream empty repair scope remained fail-closed and was not modified.

Classification: `PLANNING_CONTRACT_FAIL`, not `FRAMEWORK_BLOCKER`, `GENERATION_FAIL`, `EVALUATOR_FAIL`, or `PROJECT_PASS`. Fixed10 was not started and formal evidence remains `NEEDS_REWORK`.

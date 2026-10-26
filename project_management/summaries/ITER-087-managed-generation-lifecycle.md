# ITER-087 — Managed generation lifecycle and plugin deployment identity

- Backlog: `PB-066` completed with downstream Provider-output limits.
- Deployment: CGKN plugin package `0.2.0-rc.2+codex.20261001183500` was installed through the canonical Codex plugin CLI; installed/source package digests matched and serving status exposed repository, package, and server identity.
- Zero-API evidence: P01–P08 plus MCP, managed lifecycle, and kernel regressions passed (`86 passed`).
- Runtime: `cgkn_generate` returned in 664 ms with run `production-7ba6c807edeb49689520b8ba771db94f`; the worker survived MCP request completion, status remained responsive, polling was read-only, and no duplicate job appeared.
- Provider accounting: canonical run-local metrics recorded seven starts, six completions, three timeouts, and three HTTP successes. One requirements-planning result was admitted and materialized.
- Limit: the canonical replan responses failed the unchanged strict schema (`necessary_inferences_contains_invalid_item` and invalid `source_grounding[*].target` values), so no candidate or production provenance was created and formal evidence remained `NEEDS_REWORK`.
- Safety: no retry-policy, Provider-route, schema, admission, provenance, or Attune source changes were made after the live outcome.

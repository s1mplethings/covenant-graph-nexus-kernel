# ITER-109 — Fixed10 Qwen L1 smoke

Outcome: `NEEDS_REWORK`.

The existing Qwen implementation and configured `qwen3.6-plus` model were
audited and reused. A one-call connectivity probe passed. The single requested
CASE_01 smoke entered the formal production facade and independent evaluator,
but made no benchmark Provider call because the external-only transport branch
treated the canonical internal planning alias `surrogate-stage` as a concrete
model id. Two official repair resumptions ran without an affected ProviderJob
and also made no Provider calls.

The routing boundary was corrected so internal planning aliases resolve through
the reviewed Provider policy while concrete generation and repair model ids stay
pinned. Three focused tests passed. No new Provider, Qwen client, generation
route, benchmark case, full Fixed10 run, Codex project-worker call, or Pass 6
change was introduced.

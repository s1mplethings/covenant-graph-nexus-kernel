# ITER-110 — Qwen L1 smoke revalidation

Outcome: `NEEDS_REWORK` with workflow result `FRAMEWORK_BLOCKER`.

The same CASE_01 and frozen Fixed10 catalog were reused with `qwen3.6-plus`.
The real Provider request proved the corrected alias binding: the internal
`surrogate-stage` request selected `qwen3.6-plus` for the HTTP payload. One call
was reserved and started, but the caller was interrupted before a response was
durably recorded. Resume left the call `RESERVED`, generated no candidate, and
did not re-enter the pending request.

Independent evaluation rejected the missing candidate. Both bounded repair
rounds then failed before Provider execution because the benchmark supplied an
unsupported `--observed-failure` argument to the formal generation entrypoint.
Qwen generation and repair quality remain unevaluated. Codex generation and
repair calls were zero, the four-call limit was respected, no candidate was
manually edited, and full Fixed10 was not started.

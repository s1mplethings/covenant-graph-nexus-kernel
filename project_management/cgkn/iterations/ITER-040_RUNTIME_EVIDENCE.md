# ITER-040 Runtime Evidence

Recorded: 2026-08-28T09:54:36+08:00

## Scope and authority boundary

This short iteration repairs only MCP failure-diagnosis consistency. It does not retry a known non-retryable Provider failure, modify the sealed generated candidate, authorize evidence, package output, or change the reviewed generation route.

## Observed defect and correction

- The live YanTu diagnosis reported `resume.safe=true` for the complete backend `resume_identity`, but selected `checkpoint_identity_drift` as the reason and recommended a fresh run because historical drift existed for foundation.
- Decision precedence now follows the current actionable checkpoint: a complete matching identity-bound pending plan determines the resume reason and safety; unrelated historical drift remains contributing evidence only.
- Recommended action now uses the same decision. Provider authentication, account availability, usage, or transport blockers must be resolved first; if the checkpoint is safe, it then recommends resuming that matching pending plan. Unsafe legacy drift still recommends a fresh reviewed run.

## Verification evidence

- The live Provider probe returned `authentication_failed` with non-retryable `HTTP 401: Balance is insufficient`; formal evidence remained `NOT_EVALUATED` and no generation was attempted.
- Plugin and kernel regression profile: **50 passed**.
- Python compilation and plugin validation passed.
- Plugin cachebuster advanced to `0.1.0+codex.20260828015416`; reinstall completed and the plugin is installed/enabled.
- Source and installed-cache MCP server SHA-256 values match: `4E13D33698CA2C0E37F2C1471B5060BF46541052BA4870E21405A23F2B89EDAC`.
- `git diff --check` found no whitespace errors; only existing LF-to-CRLF conversion warnings were emitted.

## Review conclusion

The diagnostic decision is internally consistent and covered for both identity-bound safe resume and legacy unsafe drift. The YanTu project itself remains blocked at `src/service.py` until Provider authentication/account availability is restored; its formal evidence status remains `NOT_EVALUATED`.

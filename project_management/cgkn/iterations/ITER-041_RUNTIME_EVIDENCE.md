# ITER-041 Runtime Evidence

Recorded: 2026-08-29T00:00:00+08:00

## Scope and authority boundary

This short iteration qualifies Alibaba Bailian Qwen3.8-Max through the existing
OpenAI-compatible Provider adapter and reviewed generation route. It does not
create a second generation path, bypass Provider output validation, package or
deliver a project directly, or promote a diagnostic probe to formal evidence
PASS.

## Acceptance baseline

- The pre-change live MCP probe reached the correct Beijing `/responses`
  endpoint but returned HTTP 400 because it requested 8 output Tokens while the
  Provider requires at least 16.
- A bounded direct compatibility request using 128 output Tokens and
  `reasoning.effort=none` completed in 3.813 seconds, returned strict JSON, and
  consumed 96 total Tokens with zero reasoning Tokens.
- The API key was resolved from the canonical Windows User environment and was
  not written to repository artifacts or passed as a tool argument.

## Verification evidence

- Static compilation passed for the changed connectivity adapter and Provider
  transport tests.
- Targeted Provider, plugin-boundary, kernel-contract, management, and skill
  regression profile completed with **73 passed**.
- Both the project management pack and ITER-041 validate with status `PASS`;
  these are management validation results, not formal delivery evidence.
- A fresh-process live connectivity call reached the Beijing `/responses`
  endpoint, returned `pong` in one attempt, and reported request ID
  `resp_06a3632f-74a5-92c6-9370-99d5e2571e7d`.
- After Codex restarted, the guarded `cgkn_probe_provider` call also completed
  in one attempt against the Beijing `/responses` endpoint and reported request
  ID `resp_3ef3ff3b-c31a-91e2-9f4d-557f1559363d`; its formal evidence posture
  remained `NOT_EVALUATED`.
- The first isolated generation fixture was rejected before any Provider call
  because its single-operation CLI goal did not project the advisory entrypoint
  and safety constraints into the deterministic plan. No guard was bypassed.
- A second fixture using the supported local-record CLI profile passed planning
  and capability binding. Its Provider component request then returned HTTP 400
  because the internal routing policy selected unsupported model
  `gpt-5.4-nano` instead of the requested `qwen3.8-max`.
- Windows User settings `CGNK_PROVIDER_SMALL_MODEL` and
  `CGNK_PROVIDER_LARGE_MODEL` are now both `qwen3.8-max`; no credential value
  was changed or exposed.
- A post-restart guarded resume still selected `gpt-5.4-nano`, proving that the
  desktop plugin process did not inherit the Windows User routing variables.
  The repeated request was stopped at the same Provider fact boundary and no
  incomplete candidate was materialized.
- The Agent Kit command builder now projects its selected `model` to the formal
  route's `--model`, `--small-model`, and `--large-model` arguments. Targeted
  Agent Kit, plugin, and kernel-contract verification completed with **61
  passed**.
- After plugin reload, the dry-run command contained `qwen3.8-max` in all three
  Provider model slots and contained no secret argument.
- The guarded generation progressed through real Qwen component calls, produced
  three validated leaf checkpoints, and preserved them for identity-bound
  resume. This demonstrates that authentication, endpoint selection, model
  selection, Responses transport, and structured component parsing all work
  beyond a minimal ping.
- The first full run exhausted its generation deadline. One safe checkpoint
  resume then failed on `qwen_probe_demo/model.py` after repeated Provider read
  timeouts; the recorded totals were three completed leaves, eight Provider
  transport failures, six rejected local-fallback results, and zero Provider
  response-parse failures.
- No complete candidate, supported project-test run, package, or delivery
  manifest was produced. The final project evidence therefore remains
  `NOT_EVALUATED`; the qualification outcome is accepted only with limits.

## Review conclusion

- Suitable for short OpenAI-compatible Responses requests and strict JSON
  outputs.
- Not yet demonstrated suitable for CGKN's sustained multi-file generation
  workload under the current Provider read-timeout budget; a complete project
  test cannot run until the Provider reliably completes the pending leaf.
- The matching identity-bound checkpoint remains safely resumable if Provider
  latency or timeout policy is addressed later.

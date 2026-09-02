# ITER-042 runtime evidence

## Outcome

The qualified Alibaba Model Studio Qwen3.8 component-file boundary now compiles a short deterministic `CGKNCompactProviderLeafRequest`, sets `reasoning.effort=none`, derives the output ceiling from the implementation-size contract, and enforces the configured request-character ceiling as a hard budget. Full project context, omitted contract detail, repair history, validation, checkpoint, packaging, and delivery authority remain local and unchanged.

Evidence status is `PASS_WITH_LIMITS`. Implementation and repository regression evidence passed, but the live Provider run did not create `generation_result.json`, a generated project, or a delivery manifest; formal delivery therefore remains `NOT_EVALUATED`.

## Deterministic verification

- `python -m pytest -q tests/test_provider_api_transport.py tests/test_kernel_contract.py tests/test_formal_provider_fallback.py -k "qwen or compact or kernel_contract or provider_text_uses_compact or retry_accumulates"`: 41 passed.
- `python -m pytest -q`: 1408 passed, 395 skipped, 21 subtests passed, 5 warnings, in 727.19 seconds.
- Oversized-contract coverage forces a 6000-character ceiling and verifies that target path, acceptance checks, direct dependency paths, required symbols, newest repair, response shape, and Provider authorship survive budget trimming.
- Transport tests verify that reasoning `none` is scoped to qualified Alibaba Qwen3.8 Responses generation and that other providers/models retain their previous payload shape.

## Live Provider observations

- A bounded Provider probe reached `qwen3.8-max` through the Beijing Alibaba Responses endpoint without credential disclosure.
- The first live generation produced 18 ordinary compact leaf events. Their average request size fell from 29,669 legacy characters to 6,954 effective characters, a 76.6% reduction.
- Three live complex leaves exposed the former soft-budget defect at 12,121-16,182 effective characters. That observation caused the compiler to be changed from a profile warning to a deterministic hard budget; the oversized regression fixture now prevents recurrence.
- The reviewed continuation reused 19 completed Provider leaf checkpoints and advanced through semantic review into real post-build execution and repair.
- The continuation recorded 17 Provider transport failures and 15 bounded local fallback attempts, then reached the 900-second MCP command limit during a second post-build repair round. A separate one-attempt post-change leaf smoke request failed before model output with TLS `UNEXPECTED_EOF_WHILE_READING`.
- Current CGKN status reports no generated project or delivery manifest, formal status `NOT_EVALUATED`, and unsafe resume because the accumulated run records checkpoint identity drift. No further API retry was made.

## Limits and follow-up

- This iteration validates compact component-file generation, not the older semantic-review or post-build `file_repair` envelopes. Those stages dominated the failed end-to-end duration and should be optimized as a separate governed backlog increment.
- `cgkn_test_generated` was not run because no complete generated-project directory was produced. The system correctly withheld packaging and delivery.
- Before another paid or free-quota acceptance run, start from a clean identity-bound run directory or implement a reviewed stale-run recovery path, and separately verify Alibaba endpoint/TLS stability.

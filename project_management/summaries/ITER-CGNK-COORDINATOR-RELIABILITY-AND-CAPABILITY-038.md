# ITER-CGNK-COORDINATOR-RELIABILITY-AND-CAPABILITY-038

## Outcome

- Source Closure: `f841f2666392240e52eeaa24a19c2acaa651a380`
- API Lab dependency: `7c15f2546ec007cc7e601fa62ae4d88b9ba12f80`
- Coordinator qualification: `PASS_5_OF_5`
- Coordinator Provider reliability: `QUALIFIED`
- CSV Single: `FAIL_GENERATED_TEST_CONTRACT_CONFLICT_WITHIN_FIXED_BUDGET`
- Stop status: `MINIMAL_BLUEPRINT_NEEDS_REWORK`

The Coordinator P0 was closed, but the project gate remains closed. Seeded Repair, CSV repeatability, efficiency experiments, formal server evaluation, and model capability evaluation were not started.

## Coordinator forensics and repair

The first historical schema failure was a Provider-completed response whose visible answer was not a valid Blueprint candidate; most of the 2,889 output tokens were reasoning. The second historical failure was a gateway/upstream 504 at about 90.5 seconds. Neither was a Worker or Incremental Materialization failure.

The Provider-facing contract was reduced to unit kind, purpose, owned paths, and public requirement IDs. Unit IDs, dependencies, checks, execution metadata, limits, and requirement ownership are assembled deterministically. Qwen thinking control was fixed in API Lab so `disabled` maps to the Provider's top-level `enable_thinking=false`. The final schema is 569 characters and the prompt is about 1,004 user characters plus a 518-character system prompt.

The final five frozen-source Coordinator probes all passed with one transport attempt, one schema-valid candidate, no reasoning tokens, three normalized Units, four deterministic checks, and one normalized responsibility-graph signature. Input tokens were 338 each; output tokens were 151–170; latency was 3.0–5.7 seconds.

## CSV call graph

The final fresh CSV run used seven of eight allowed logical calls:

1. Qwen Coordinator design — necessary, passed.
2. DeepSeek documentation generation — necessary, passed.
3. DeepSeek implementation generation — necessary, passed.
4. DeepSeek tests generation — necessary, passed structurally but encoded a contract-inconsistent preview expectation and brittle newline expectations.
5. DeepSeek tests repair — corrected public pytest failures caused by newline expectations.
6. DeepSeek implementation repair — hidden acceptance was reached; deterministic public-requirement attribution selected the implementation owner without exposing hidden source, and the implementation was aligned with the literal public preview contract.
7. DeepSeek tests repair — failed to reconcile generated tests with the normative public contract; pytest remained red.

Final nodes: `pytest=FAILED`; `runtime_smoke` and `external_acceptance` blocked. Manual edits were zero. There were no Provider transport or schema failures in this run.

## Root cause

The remaining blocker is no longer Coordinator reliability or the eight-call ceiling itself. It is cross-Unit contract coherence: the generated tests became a competing behavioral authority. After the implementation was corrected to the public contract, the test Unit continued asserting its prior interpretation. Owner-local repair preserved the Frozen Blueprint but oscillated between implementation and tests instead of deterministically re-grounding generated tests in the canonical public contract.

The next source iteration should make the public contract an explicit deterministic input to test generation and test repair, and reject generated tests whose asserted external behavior contradicts that contract before committing the tests Unit. This must be solved without exposing hidden acceptance or increasing the eight-call budget.

## Validation

- Targeted Project Loop/Blueprint tests: 67 passed.
- Application suite: 394 passed, 1 skipped.
- Kernel source-bound evidence retained: 4,071 passed, 356 skipped across formal profiles; active repository 2,583 passed, 351 skipped; 0 failed, 0 errors.
- Receipt freshness and Kernel completeness gates: PASS.
- API Lab: 69 passed; branch and remote SHA verified.

## Security

- Hidden source exposed to Provider: false.
- Secrets persisted: false.
- Manual generated-project edits: zero.
- Scope and Frozen Blueprint boundaries remained enforced.
- No force push and no pull request.

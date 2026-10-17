# ITER-017 Provider Connection Normalization

## 1. Git Identity

- Repository: `s1mplethings/covenant-graph-nexus-kernel`
- Work branch: `codex/provider-connectors-code-growth-20261017`
- Source closure: `b078927711070cf12f7e58c7fc31bb624046efcc`
- Source tree: `82d9b272c5513b2470e1eeca96415eaa3e94905d`

## 2. Protected MVP Baseline

`kernel_foundation=COMPLETE`, `functional_readiness=LEVEL_4`, `mvp_readiness=READY`, and `generation_readiness=GENERATION_LEVEL_2` remain protected. No second public-delivery path was introduced.

## 3. Provider Architecture

`QwenConnector`, `GrokConnector`, and `DeepSeekConnector` independently own vendor configuration, authentication, model probing, request translation, structured-output strategy, and error classification. The shared layer owns only canonical requests/completions, schema validation, budget integration, telemetry, and registry lookup. There is no vendor-branching request monolith.

## 4. Qwen Connection

- Region: `cn-beijing`
- Endpoint class: configuration
- Workspace configured: no
- Credential present: no
- Catalog/model/native-schema probes: not evaluated
- Requested model: `qwen3.8-max`
- Final: `QWEN_CONNECTION_BLOCKED_ENVIRONMENT`

## 5. Grok Connection

- Base URL class: xAI inference
- Models probe: PASS
- Requested/actual model: `grok-4.7`
- Backend: Responses API
- Structured output: native strict JSON Schema plus local validation, PASS
- Reasoning effort: medium
- Final: `GROK_CONNECTION_READY`

## 6. DeepSeek Connection

- Structured mode: prompt JSON plus canonical local schema validation
- Credential present: no
- Final: `DEEPSEEK_CONNECTION_BLOCKED_CREDENTIAL`

## 7. Credential Failure Classification

Qwen is classified `QWEN_WORKSPACE_NOT_FOUND` before any live request because no workspace-specific endpoint/credential is configured. DeepSeek is classified `DEEPSEEK_MISSING_AUTH`. No credential value, prefix, suffix, or fingerprint is persisted.

## 8. Canonical Structured Completion

All connectors return `ProviderCompletion` and pass the same Draft 2020-12 local schema validator. Qwen translates to Chat Completions native schema, Grok to Responses `text.format` strict schema, and DeepSeek to prompt JSON with bounded format-only repair.

## 9. Provider Benchmark

Adaptive benchmark selection was not run because only one Provider is eligible. Historical blocked evidence is preserved.

## 10. Task Winners

No adaptive winner is declared for `agent.composition`, `worker.codegen`, `worker.repair`, or `capability.build`. Grok is the sole eligible route used under frozen `SINGLE_PROVIDER_MODE`.

## 11. Single-provider State

`provider_selection=BLOCKED_ENVIRONMENT`; downstream code generation remains permitted and explicitly records single-provider operation with fallback denied.

## 12. Repository Codegen

BUG_FIX, MULTI_FILE_FEATURE, and REFACTOR all passed (3/3), with zero manual edits, unrelated edits, interface breaks, and whole-project replans.

## 13. Capability Builder

`text.slugify@1` and `markdown.links.extract@1` passed and were admitted/stored. `json.path.get@1` failed runtime verification and was neither admitted nor stored. Threshold: 2/3 PASS, zero manual edits.

## 14. Self-Growth

Both required capabilities completed Gap → Spec → Provider → Builder → Candidate → Sandbox → Admission → Store → Registry → Resume. Auto-admission remains limited to PURE and READ_ONLY_LOCAL.

## 15. Reuse

Second runs for both admitted capabilities directly reused the store with zero growth calls and zero builder calls.

## 16. Security

Credential-specific values remain outside committed profiles and receipts. Error material is sanitized before persistence; unknown Providers fail closed; routing fallback remains denied.

## 17. Budget

The final Growth ledger reconciles 3 completed Provider calls, 5,913 actual input tokens, 7,649 actual output tokens, complete actual usage, and an estimated USD 0.05772 under the recorded rate assumptions.

## 18. Regression

Kernel receipt: 3,470 passed, 0 failed, 0 errors, 356 skipped; live-provider profile is environment-blocked. Application suite: 138 passed, 0 failed, 0 errors, 1 skipped. Architecture, completeness, freshness, and product-direction gates pass.

## 19. Readiness

- provider_connection_qwen: BLOCKED_ENVIRONMENT
- provider_connection_grok: READY
- provider_connection_deepseek: BLOCKED_CREDENTIAL
- provider_selection: BLOCKED_ENVIRONMENT
- repository_codegen: COMPLETE (single-provider)
- capability_builder: COMPLETE (single-provider threshold)
- self_growth_v1: COMPLETE (BUILD path)
- mvp_readiness: READY
- kernel: COMPLETE

## 20. Remaining Blockers

Adaptive selection requires at least one additional eligible Provider. Qwen needs a workspace-recognized endpoint/credential; DeepSeek needs a credential. These blockers do not invalidate the completed single-provider codegen, builder, or BUILD-only self-growth evidence.

## 21. Commits

`dca4164`, `5602fe8`, `8ff7ff7`, `e7e7780`, `e301a6f`, `d75c3c9`, `56ba2a6`, `7530ed1`, `5683227`, `354c339`, `665b901`, `db2bf55`, `258b8ef`, and `b078927`; final evidence closure is published separately by the canonical repository publisher.

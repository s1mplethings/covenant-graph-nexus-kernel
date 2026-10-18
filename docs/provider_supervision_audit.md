# Provider supervision audit — ITER-029

## Authority and scope

The Agent, `ProjectProviderPlan`, CandidateRevisionStore, Action Policy, CapabilityTree/ExecutionDAG, FileRunStore, and `local_packager` remain the existing authorities. The supervisor owns only one in-flight Provider request. It neither selects a Provider nor validates or repairs a Candidate.

## Call chains observed before the change

### Micro benchmark

`ProviderBenchmarkCase` → `BenchmarkBudget` → `ProviderEvaluationService.run_case` → `ModelRoleConfig(timeout_seconds=case.timeout)` → `ConnectorCompletionClient` (when the connector route is selected) → vendor Connector → direct `urllib.request.urlopen`.

The benchmark timeout is local to provider evaluation. Production packages do not import `BenchmarkBudget`.

### Production domain

`ProjectProviderPlan` → `GenerationManifestCompiler` / bundle spec → `GreenfieldBundleProductionService` → `ProductionGenerationClient` → `ModelRoleConfig` → completion client → transport.

The previous ITER-028 validation runner instantiated `GatewayCompletionClient` and started `cgkn-provider-api-lab`. Although bundle generation replaced the outer `ModelRoleConfig` timeout with the bundle's 180-second value, the gateway's upstream Provider adapter independently read persisted `ProviderConfig.timeout_seconds=90` and called `request.urlopen(..., timeout=90)`. That upstream 90-second value caused the observed Candidate-none failures. It was not imported from `BenchmarkBudget`, but it had the same fixed benchmark-scale behavior in the production route.

ITER-029 removes the gateway adapter from production qualification. The lab is used only to resolve credential and endpoint metadata; the data request runs through `ConnectorCompletionClient` and `SupervisedHttpTransport`.

### Repository patch

`ChangeRequest` → `RepositoryCodegenService` → `ProductionGenerationClient` → task-stamped `ModelRoleConfig` → `ConnectorCompletionClient` → vendor Connector → `SupervisedHttpTransport`.

The repository patch Candidate and scope authorities are unchanged.

## Connector audit

- Qwen before: single legacy `timeout`, mandatory `list_models()` in completion, direct `urlopen`, full response read.
- DeepSeek before: same timeout/catalog/direct transport pattern; optional format repair remained vendor-local.
- Grok before: default/max timeout and pinned-model data plane already existed, but transport/supervision was private to the connector.

All three now share supervised HTTP lifecycle and keep separate endpoints, payloads, parsers, model binding, schema behavior, and error mapping. Qwen and DeepSeek accept legacy timeout only when it agrees with the new default. Production completion uses a profile-pinned allowlist and does not require Catalog.

Strict structured-output calls are currently non-streaming. They are therefore marked `DEADLINE_ONLY`; headers and bounded body chunks are recorded when they become observable, but no pre-header generation progress is claimed. Catalog operations remain chunk-aware.

## Cancellation and ledger

The transport performs the request synchronously, applies bounded socket timeouts, closes the response in the same call stack, and creates no worker thread or subprocess. A timeout therefore cannot leave a future or request worker running. The Windows test compares the live thread set before and after cancellation.

`ConnectorCompletionClient` retains exactly one reservation, one request-start, and one finalize per completion call. Deadline extensions are events within that request and never create ledger rows. Static configuration failures have no sent-request uncertainty; sent-request timeouts carry `outcome_unknown=true`.

## Real evidence

The supervised Patch canary completed after 146.391 seconds—past the old 90-second gateway cutoff—with schema, interface, existing tests, public acceptance, and hidden acceptance passing. Qwen Simple and Library produced no headers before their deterministic 206/216-second estimated deadlines. Grok Persistent returned a Candidate after 50.375 seconds, but functional acceptance rejected it. The 1/4 canary result correctly prevented the P01–P04 project phase.

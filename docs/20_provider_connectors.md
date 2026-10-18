# Provider connectors

CGKN uses one canonical structured-completion contract and a lookup-only
connector registry. Vendor-specific authentication, endpoints, probes, request
translation, structured-output strategy, response parsing, and error
classification live in separate `QwenConnector`, `GrokConnector`, and
`DeepSeekConnector` implementations.

`GatewayCompletionClient` remains a loopback transport only. It does not know
vendor credentials or vendor payloads. Connection readiness is independent of
quality selection: an eligible connector proves that the canonical contract is
callable, while benchmark receipts determine task-specific quality.

Qwen uses its workspace-scoped OpenAI-compatible Chat Completions path and
native JSON Schema. Grok uses the xAI Responses path and `text.format` JSON
Schema. DeepSeek uses JSON Object prompting followed by the same local Draft
2020-12 validator, with at most one format-only repair whose existing semantic
values may not change.

Credentials are read only from the connector-specific environment variables.
Connection snapshots store booleans and configuration hashes, never secret
values or credential fingerprints. Runtime fallback remains denied.

The bounded Provider suite can use these connectors explicitly with
`scripts/run_provider_benchmarks.py --transport connectors`. Provider IDs still
come from the active routing configuration, every completion is reserved in the
existing budget ledger with purpose `BENCHMARK`, and prices are supplied as
non-secret CLI metadata. Omitting price metadata records `UNAVAILABLE`; it never
means zero cost. Connector selection happens before the benchmark run and does
not add runtime fallback.

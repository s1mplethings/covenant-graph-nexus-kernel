# ITER-018 Runtime Evidence

No credential value is recorded in this artifact.

## Local Ollama

- Ollama `0.12.3` responded at `http://127.0.0.1:11434`.
- Installed code model: `qwen2.5-coder:7b`.
- Installed reasoning model: `qwen2.5:7b-instruct`.
- `local_model_router` strict-JSON code smoke: PASS in 6.702 seconds.
- Medium component manifest: PASS in 24.186 seconds.
- 21,668-character component-manifest prompt with 16k context and 1,024 prediction budget: PASS in 41.024 seconds, six bounded files, valid JSON.
- Reasoning-model strict-JSON support task: PASS in 7.399 seconds.

Measured safe configuration:

- routing profile: `hybrid_safe`
- code model: `qwen2.5-coder:7b`
- reasoning model: `qwen2.5:7b-instruct`
- component manifest prediction budget: `1024`
- context window: `8192` by default; the 16k diagnostic also passed
- local request timeout cap: `180` seconds
- Ollama auto-start: enabled

## API provider

- Base URL: `https://api.gptsapi.net/v1`.
- Model: `gpt-5.4-nano`.
- Selected method: `chat_completions`.
- TLS verification: enabled.
- Minimal strict-JSON smoke: PASS on first attempt in 2.332 seconds.
- Non-trivial structured component manifest through `provider_text`: PASS in 8.365 seconds, fourteen files and complete JSON.
- A deliberate 700-token output cap was rejected with `finish_reason=length`; increasing the diagnostic cap to 2,000 returned a complete contract-valid response.
- Persisted credential resolution selected `CGKN_OPENAI_API_KEY(User)` and `CGKN_OPENAI_BASE_URL(User)` without command-line injection.
- `provider_readiness`: `provider_ready=true` with no provider error.

## Routing conclusion

`hybrid_safe` keeps `api_provider` as formal generation owner. Ollama handles bounded dialogue, classification, planning-context and risk-support tasks; the existing registered fallback may handle code tasks only when the API route reports a classified failure. Local support cannot authorize formal delivery truth.

The currently running Codex process inherited an older credential value before the user-level environment was updated, so the process reports a credential conflict while still selecting the new user-level value. Restart Codex and any long-running Codex conversation bridge after this iteration to refresh their environment blocks.


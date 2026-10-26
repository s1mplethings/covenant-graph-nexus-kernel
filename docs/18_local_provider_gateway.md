# Local Provider gateway integration

CGNK can use the independent `cgkn-provider-api-lab` loopback gateway without
reading Qwen, DeepSeek, or Grok credentials. The existing
`OpenAICompatibleClient` remains the default. Gateway mode is selected only
when the legacy compatibility environment variable
`CGKN_PROVIDER_GATEWAY_ENABLED=1` is present in the CGNK process.

## Route configuration

The reviewed example is
`config/provider_profiles/gateway_model_routing.json`. It maps the Agent to
`qwen`, the Worker to `deepseek`, allows `grok` as an explicit replacement,
and denies fallback. Provider IDs are aliases; real vendor model IDs remain in
API Lab. Each run writes `model_routing_snapshot.json` before its first model
call.

## Safe live entrypoint

First configure provider model IDs and credentials in the API Lab GUI. Do not
put vendor keys or the local gateway token in arguments. The API Lab launcher
starts a loopback gateway, creates a temporary credential-free route file, and
injects the ephemeral gateway token only into the child process environment:

```powershell
Set-Location D:\cgkn-provider-api-lab
.\.venv\Scripts\cgkn-provider-lab.exe launch-agent-mvp-gateway `
  --agent qwen --worker deepseek `
  --cgkn-root <repository-root> --run-root <run-root> `
  --max-api-calls 4 --max-input-tokens 100000 --max-output-tokens 30000 `
  --max-estimated-cost 5 `
  --input-cost-per-million 1 --output-cost-per-million 2
```

Running that command is an explicit paid-test action. Price inputs are local
operator estimates based on current vendor pricing, not a hard vendor-billing
limit. Calls fail before transport when the ledger, call/token/cost limits, or
price estimates are missing.

## Offline verification

No credential or paid call is needed for the supported end-to-end checks:

```powershell
Set-Location <repository-root>
python -m pytest -q `
  tests\agent\test_agent_mvp_gateway_cli.py `
  tests\application\software_project\test_gateway_e2e.py `
  tests\providers\test_gateway_client.py
```

These tests execute the actual Agent MVP entrypoint and software-project
runtime through an HTTP mock gateway. The software-project case includes a
failing seed, Qwen-routed Agent decisions, a DeepSeek-routed bounded patch,
real pytest, project snapshot, and external acceptance. They do not assert
that any real vendor credential or model is usable.

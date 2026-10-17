# CGKN Provider API Lab

A local, isolated GUI extension for registering OpenAI-compatible API providers,
running the same prompt against several providers, and exporting comparable
results. It is an experiment surface only: it does not replace CGKN ProviderJob,
canonical evidence, `local_packager`, or the public delivery gate.

## Security contract

- Provider configuration stores metadata and a `secret_ref`, never a plaintext API key.
- A key may come from the current process memory, an environment variable, or the OS credential store.
- The key field is write-only and is cleared immediately after save.
- HTTP errors and adapter failures pass through credential redaction.
- Exported comparison JSON excludes secret backend and secret reference metadata.
- Non-local endpoints must use HTTPS. Plain HTTP is accepted only for localhost.
- Authentication header names and prefixes are selected from a small allowlist; arbitrary secret-bearing header metadata is not persisted.
- Session/keyring references are forced to the Provider ID so the reference field cannot be used as a hidden plaintext-key field.

No client can call a remote API without holding the credential briefly in process
memory and placing it in the TLS request header. The guarantee here is narrower
and testable: the credential is not persisted in the repository/config/results,
not rendered back into the GUI, and not intentionally emitted to logs or errors.

## Run on Windows

Python 3.11+ includes Tkinter in the standard Windows installer.

```powershell
cd extensions/provider_api_lab
python -m pip install -e ".[keyring]"
./run_provider_lab.ps1
```

Without `keyring`, use either:

- `session`: paste the key once; it disappears when the GUI closes.
- `environment`: save only an environment variable name, then launch the GUI from a shell where it is set.

Example:

```powershell
$env:DEEPSEEK_API_KEY = "<set-it-locally>"
$env:DASHSCOPE_API_KEY = "<set-it-locally>"
./run_provider_lab.ps1
```

Do not put those assignments in tracked scripts.

## Workflow

1. Open **供应商** and select a preset.
2. Confirm the editable Base URL and current model ID.
3. Choose `keyring`, `environment`, or `session` credential storage.
4. Save, then use **测试连接**.
5. Open **对比测试**, multi-select providers, enter one prompt, and run.
6. Inspect latency, token usage, reasoning (when returned), final text, and failures.
7. Export metadata/results as JSON for later evaluation.

Presets intentionally keep model IDs editable because provider catalogs change.
Qwen workspace-specific and regional endpoints should replace the shared Beijing
endpoint when applicable.

## Add another provider

For an OpenAI-compatible service, add a `ProviderPreset` in `presets.py`; no new
adapter is needed. For a different protocol, implement the `Adapter` protocol in
`adapters.py` and register it in `ADAPTERS`. Credentials must still be resolved
through `SecretManager` and failures must pass through `redact_text`.

## Tests

```powershell
$env:PYTHONPATH = "extensions/provider_api_lab/src"
python -m pytest extensions/provider_api_lab/tests -q
```

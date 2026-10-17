# Validation evidence

Scope: isolated Provider API Lab extension only. No real provider calls were made
and no credential was supplied during validation.

## Automated checks

```text
PYTHONPATH=extensions/provider_api_lab/src \
python -m pytest extensions/provider_api_lab/tests -q

20 passed
```

Covered contracts include:

- configuration serialization and duplicate detection;
- rejection of plaintext credential fields;
- HTTPS-only remote endpoints;
- environment, memory, and no-auth secret resolution;
- exact and pattern-based error redaction;
- OpenAI-compatible request/response behavior against a local HTTP fixture;
- deterministic multi-provider result ordering;
- result export without secret backend/reference metadata;
- export-time removal of a credential reflected into a prompt or error;
- safe allowlists for authentication metadata;
- refusal to use keyring/session references as hidden plaintext-key fields.

## Packaging and runtime checks

- `python -m compileall` passed for the extension source.
- A wheel was built and installed locally with `--no-build-isolation --no-deps`.
- `python -m cgkn_provider_lab list` returned metadata JSON from the installed package.
- All six built-in presets passed `ProviderConfig` validation.
- Tk 8.6 imported successfully.
- The 1180x760 GUI opened, rendered both tabs, processed one event loop cycle,
  switched to the comparison tab, and closed under Xvfb.
- A credential-literal scan found no likely live-key literals in the extension.

## Limits

- No paid or live provider endpoint was called.
- The GUI was smoke-rendered under a Linux virtual display, not manually operated
  on Windows.
- OS keyring behavior remains dependent on the user's installed `keyring` backend.
- This extension is not formal ProviderJob, benchmark, release, or delivery evidence.

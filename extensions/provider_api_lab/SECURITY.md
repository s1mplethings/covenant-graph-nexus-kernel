# Security notes

## Threats addressed

- Accidental API key commits.
- Plaintext keys in provider JSON.
- Keys copied into comparison result exports.
- Keys reflected in common HTTP/adapter error messages.
- Keys accidentally pasted into an authentication prefix or keyring reference field.
- A GUI that reads an existing key back into a visible field.
- Remote plaintext HTTP transport caused by a mistyped Base URL.

## Deliberate limits

- A compromised local process, Python runtime, OS account, TLS trust store, or
  provider endpoint can still access data available to that component.
- Prompt and model output are exported by design; do not place secrets in prompts.
- Environment variables can be inspected by sufficiently privileged local users.
- The optional `keyring` package delegates protection to the OS credential store.
- Certificate pinning is not implemented.

## Incident response

If a key may have appeared outside its intended backend, revoke it at the provider,
create a replacement, remove the old keyring/session/environment value, and inspect
repository history and exported result files. Redaction reduces accidental leaks;
it is not a substitute for credential rotation.

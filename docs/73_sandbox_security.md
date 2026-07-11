# Sandbox Security

`scripts/sandbox_security.py` statically scans generated projects before final promotion. It checks npm scripts, shell/Python/JavaScript scripts, secret leakage risks, network command risks, and execution path boundaries.

Blocked examples include `rm -rf`, `del /s`, `format`, `shutdown`, unknown `curl`/`wget`/`Invoke-WebRequest`, `scp`, `ssh`, `net user`, `reg delete`, and recursive PowerShell deletion.

Rules:

- Commands may execute only inside run, candidate, or final project directories.
- Generated project runtime receives a whitelist of environment variables only.
- API keys, tokens, secrets, and private keys must not be passed into generated runtime env.
- A failing security scan writes `security_blocked.json` and prevents final promotion.

Warnings may be allowed only when they are non-critical and do not expose secrets or unsafe write/delete behavior.

# ITER-049 Runtime Evidence

## Result

The active branch is `codex/cgkn-codex-edition`. Its distribution name is
`CGKN Codex Edition`; the formal kernel and schema namespace remain `CGKN`.

The canonical edition launcher is
`scripts/start_cgkn_codex_edition.ps1`. It uses
`generated/cgkn_editions/codex/` for sessions, logs, uploads, memory, and
Provider candidates, and `.cgkn/editions/codex/` for persistent supervisor
state. The superseded `start_cgkn_codex_supervised.ps1` launcher is absent.

## Verification

- Exact Git branch identity: PASS.
- Python compilation and PowerShell parser validation: PASS.
- Kernel contract guard, including edition launcher and one-shot Codex isolation: PASS.
- Kernel, runtime-supervisor, and document-consistency tests: 44 passed.
- Project-management pack and ITER-049 validation: PASS.
- Repository whitespace/error check: PASS; only existing Windows LF-to-CRLF notices were emitted.

## Limits

The branch was created with the repository's existing uncommitted working-tree
changes intact. No commit, remote branch push, live Telegram launch, Provider
generation, package, or public delivery was performed. This iteration record is
support evidence and does not authorize formal delivery PASS.

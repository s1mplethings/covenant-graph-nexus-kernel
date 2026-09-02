# CGKN Codex Edition

`CGKN Codex Edition` is the branch distribution that combines the formal CGKN
kernel with persistent Codex supervision and the reviewed Codex-facing tools,
skills, and plugin surfaces in this repository.

## Identity

- Product edition: `CGKN Codex Edition`
- Git branch: `codex/cgkn-codex-edition`
- Formal kernel and schema namespace: `CGKN`
- Primary launcher: `scripts/start_cgkn_codex_edition.ps1`
- Runtime data: `generated/cgkn_editions/codex/`
- Supervisor state: `.cgkn/editions/codex/`
- Local worktree: `D:\CGKN\.service_worktree\codex-edition`
- API-only sibling worktree: `D:\CGKN` on `codex/cgkn-api-only`

The edition name does not create another Provider author, evidence authority,
packager, or delivery path. Project generation still uses the registered
API/Provider mainline, and `local_packager` remains the only delivery exit.

## Separation from API-only

The API-only runtime never starts or invokes Codex. CGKN Codex Edition starts
one persistent, identity-bound Codex supervisor thread and forces the older
one-shot Codex design CLI off. The two profiles do not share sessions, logs,
uploads, project memory, candidate roots, or supervisor state.

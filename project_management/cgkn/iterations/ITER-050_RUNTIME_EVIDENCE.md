# ITER-050 Runtime Evidence

## Worktree split

- API-only directory: `D:\CGKN`
- API-only branch: `codex/cgkn-api-only`
- CGKN Codex Edition directory: `D:\CGKN\.service_worktree\codex-edition`
- CGKN Codex Edition branch: `codex/cgkn-codex-edition`
- Edition snapshot commit: `d86e9e2ecc356f8f960cf1831fa998da78695cd8`

The requested sibling directory `D:\CGKN-Codex-Edition` could not be created
because the host denied writes at the `D:\` root. The repository's existing,
ignored `.service_worktree` container was used instead. Git reports both
directories as distinct worktrees with distinct branch refs.

## Snapshot boundary

The edition commit includes source, tests, docs, schemas, skills, plugins,
tools, and project-management support records. It excludes `.cgkn`, examples
runtime/project-memory changes, `workspaces`, `benchmarks`, generated outputs,
artifacts, and run logs. Potential-secret pattern matches were inspected and
were limited to deliberate redaction test fixtures.

## Verification

- Worktree and exact branch identity checks: PASS.
- API-only source check: persistent Codex supervisor absent.
- Codex Edition kernel contract guard: PASS.
- Codex Edition kernel, runtime-supervisor, and documentation tests: 44 passed.
- Project-management pack and ITER-050 validation: PASS.

## Limits

No remote branch push, live Telegram launch, Provider generation, package, or
public delivery was performed. Existing API-directory example/runtime changes
were preserved and remain uncommitted. This support evidence does not authorize
formal delivery PASS.

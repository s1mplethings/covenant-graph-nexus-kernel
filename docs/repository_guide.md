# CGKN Repository Guide

This guide is the navigation and retention map for the repository. It does not replace the kernel contract or the formal artifact registry.

## Authority order

1. `AGENTS.md` defines repository change constraints.
2. `docs/00_kernel_contract.md` defines the stable kernel and route boundaries.
3. `docs/01_contract_registry.md` defines formal artifact kinds, schemas, producers, consumers, and evidence statuses.
4. This guide explains where work belongs; it cannot authorize generation, evidence, packaging, or delivery.

## Directory ownership

| Area | Purpose | Retention rule |
| --- | --- | --- |
| `src/`, `scripts/` | Kernel code and reviewed operational entrypoints | Track reviewed source. Kernel changes require the matching contract and guard updates. |
| `schemas/`, `contracts/` | Machine-readable and module contracts | Track reviewed contracts and their tests. |
| `tests/` | Unit, contract, integration, and regression checks | Track deterministic tests and small fixtures; write bulky output elsewhere. |
| `docs/` | Formal contracts, architecture, and contributor guidance | Track current documents. The numbered kernel and registry files remain authoritative. |
| `skills/` | Reviewed CGKN operating methods | Track only approved repository skills. A Skill is guidance, not a generation route. |
| `plugins/` | Installable Codex plugin bundles | Track plugin manifests, MCP servers, bundled guidance, and deterministic tests. |
| `tools/` | Portable user-facing companion tools | Track source, packaging metadata, and small tests. Do not store credentials. |
| `project_management/` | CGKN backlog, iterations, evidence summaries, and experience | Track structured records and concise evidence references. These are support artifacts, not formal delivery truth. |
| `examples/` | Reviewed static examples and fixtures | Track stable, reusable examples. Do not leave ad hoc runs, live `.cgkn` state, caches, or generated customer output here. |
| `benchmarks/` | Reproducible benchmark definitions | Track definitions and bounded fixtures; write executions to `artifacts/` or `runs/`. |
| `artifacts/` | Retained diagnostic or runtime evidence | Historical tracked evidence stays in place when referenced. New bulk output is ignored unless a review explicitly promotes a bounded evidence summary. |
| `generated/` | Generated customer projects and disposable generation output | Runtime-only and ignored. A generated project is not formal delivery merely because it exists. |
| `runs/` | Provider checkpoints, resumes, and local workspaces | Runtime-only and ignored. Preserve externally only when a referenced diagnostic requires it. |
| `legacy/` | Compatibility and historical code | Keep isolated. Do not reconnect it to the Codex conversation default mainline. |
| `.service_worktree/` | Service-owned nested worktree | Local-only. Never clean it as ordinary cache data. |

## Where new work goes

- New formal behavior: `src/` or the applicable reviewed `scripts/` module, with tests and contract updates when required.
- New reusable Codex integration: `plugins/<name>/`; portable CLI support belongs in `tools/<name>/`.
- New management increment: one `project_management/cgkn/iterations/ITER-NNN.json`, plus a concise runtime-evidence document only when needed.
- New reviewed fixture: a purpose-named directory under `examples/` or `benchmarks/`.
- New test or generation run: `artifacts/<purpose>_<date>/`, `generated/<purpose>_<date>/`, or `runs/<purpose>_<date>/`.
- Temporary debugging: the operating-system temporary directory. If a root `.tmp_*` directory is unavoidable, remove it before handoff.

## Retention decisions

Use this order before moving or deleting anything:

1. Check whether Git tracks the path.
2. Search `project_management/`, `docs/`, tests, and the enterprise-experience pack for references.
3. Preserve canonical artifacts and any evidence required to reproduce a reviewed claim.
4. Prefer a concise tracked evidence summary plus ignored bulky runtime output for future runs.
5. Delete only caches and reproducible temporary output whose exact path has been verified.

Do not bulk-clean `artifacts/`, `generated/`, `runs/`, or `.service_worktree/` as a convenience operation. Their delivery authority may be absent, but they can still contain diagnostic or referenced evidence.

## Routine checks

```powershell
python scripts/repository_hygiene.py
python scripts/repository_hygiene.py --json
git status --short
pytest -q tests/test_repository_hygiene.py
```

The hygiene check is read-only. It reports root caches, temporary directories, live CGKN support state under examples, missing ignore boundaries, and missing core navigation surfaces. It never deletes files and never emits a formal evidence status.

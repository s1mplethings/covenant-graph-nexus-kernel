# ITER-032 runtime evidence

## Scope

Repository organization only. Existing source modifications, tracked historical evidence, formal artifacts, generated projects, run checkpoints, and the service worktree were preserved.

## Changes

- Added `docs/repository_guide.md` as the navigation and retention map.
- Updated the README source layout and removed the stale claim that fallback media may satisfy missing preview evidence.
- Added explicit ignore boundaries for root `.tmp_*` directories and `runs/`.
- Added the read-only `scripts/repository_hygiene.py` check and deterministic tests.
- Moved the untracked small-scale plugin smoke project from `examples/plugin-small-scale-smoke/` to ignored runtime evidence at `artifacts/cgkn_plugin_small_scale_smoke_20260822/`.
- Removed six verified untracked and reproducible cache or temporary directories: root `__pycache__`, `.pytest_cache`, `.playwright-mcp`, `.vs`, `.tmp_fixture_debug`, and `.tmp_implementation_depth_probe_20260727`.

## Verification

- Repository hygiene report: `ok=true`, zero issues.
- Project-management pack validation: PASS.
- ITER-032 validation: PASS.
- Applicable hygiene, management, kernel, plugin, and Agent Kit regression profile: `67 passed`.
- Pre-clean checks confirmed every removed directory resolved under `D:\CGKN` and contained zero Git-tracked files.

## Limits

- Approximately 3,420 historical files under `artifacts/` are already tracked, and several are referenced by iteration or enterprise-experience evidence. They were not bulk-moved or deleted.
- The working tree already contained 22 modified files and many untracked implementation/evidence files from earlier increments. This iteration preserved them rather than attempting to infer ownership or split commits.
- This support evidence does not authorize formal project delivery PASS.

# Discovery Selection Repo Status

- Checked at: 2026-06-19
- Workspace: `D:\CGKN`
- Current branch: `codex/project-revision-execution-phase2`
- Current commit: `9fd5fa3a781362b3b22d3881ab59df82ed3cbade`
- `VERSION` file: not present
- Worktree status: dirty before this change

## Pre-Existing Worktree Notes

`git status --short` showed many modified and untracked files before Discovery & Selection work started, including:

- Modified kernel/docs/test files such as `docs/00_kernel_contract.md`, `scripts/run_local_pipeline.py`, `scripts/local_packager.py`, `scripts/telegram_live_bridge.py`, and multiple tests.
- Untracked acceptance/delivery modules such as `scripts/product_acceptance.py`, `scripts/provider_generation.py`, `scripts/final_delivery_truth.py`, `scripts/final_promotion.py`, `scripts/post_build_finalize.py`, and related tests/docs.
- Existing benchmark artifacts and scripts used legacy complexity-scale naming before this work.

This work must not revert unrelated user or generated changes.

## Confirmed Architecture Guardrails

- Telegram default generation must stay on provider/API project generation, provider output validation, post-build finalization, `local_packager`, public delivery gate, and `delivery_manifest.json`.
- `pipeline_manifest` and `dynamic_pipeline_runner` remain support/experimental planning lane infrastructure.
- `local_packager.package_project` remains the only formal delivery exit.
- `final_delivery_truth.py`, `final_promotion.py`, `artifact_integrity.py`, public delivery gate logic, and fake artifact checks are truth boundaries.

## Existing Complex-Scale Naming To Neutralize

Existing files included legacy benchmark names that must be neutralized:

- benchmark runner scripts
- benchmark tests
- benchmark spec
- benchmark reports under `artifacts/`

The requested replacement naming is `complexity_scale` / `complexity_project` / `discovery_selection`.

## Main Risk

The repo already has a large dirty worktree. Discovery & Selection changes should be scoped to new neutral modules, focused tests, and the narrow mainline integration points needed to pass the complexity contract into provider generation and acceptance.

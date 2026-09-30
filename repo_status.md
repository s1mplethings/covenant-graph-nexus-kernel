# Repo Status

Generated: 2026-06-18

## Git

- Current branch: `codex/project-revision-execution-phase2`
- Latest commit: `9fd5fa3a781362b3b22d3881ab59df82ed3cbade`
- `VERSION`: not present
- Working tree: dirty before this benchmark work started

## Pre-existing Uncommitted Changes

`git status --short` showed many modified and untracked files before this benchmark run, including kernel/docs/tests/script changes. Notable files already present before this work included:

- `scripts/run_complexity_scale_benchmark.py`
- `tests/test_complexity_scale_benchmark.py`
- `benchmarks/`
- `scripts/run_commercial_readiness.py`
- `scripts/product_acceptance.py`
- `scripts/provider_generation.py`
- `scripts/post_build_finalize.py`
- `scripts/local_packager.py` was modified
- `scripts/telegram_live_bridge.py` was modified
- `docs/00_kernel_contract.md` was modified
- `tests/test_kernel_contract.py` was modified

These existing changes are treated as user/workspace state and were not reverted.

## Existing Test Entrypoints

Detected from `README.md`, `scripts/`, and `tests/`:

- `python scripts/check_product_studio_contract.py`
- `python scripts/validate_bundle.py`
- `python scripts/run_test_pipeline.py`
- `python scripts/check_connectivity.py`
- `python -m pytest`
- `tests/test_complexity_scale_benchmark.py`
- `tests/test_commercial_readiness.py`
- `tests/test_product_acceptance.py`
- `tests/test_telegram_public_delivery_gate.py`
- `tests/test_kernel_contract.py`

## Existing Generation Entrypoints

Detected from `README.md`, `docs/00_kernel_contract.md`, `scripts/`, and `--help` output:

- `scripts/run_local_pipeline.py`
- `scripts/run_local_pipeline_impl.py`
- `scripts/provider_generation.py`
- `scripts/post_build_finalize.py`
- `scripts/local_packager.py`
- `scripts/telegram_live_bridge.py`
- The superseded compact generation CLI and Product Studio wrapper chain are removed from the active tree; Git history retains them.
- `scripts/pipeline_manifest.py` and `scripts/dynamic_pipeline_runner.py` exist as support/experimental planning lane.

## Requested Entrypoints Checked

- `scripts/ctcp_orchestrate.py`: not present
- `scripts/run_agent_league.py`: not present
- `scripts/run_commercial_readiness.py`: present
- `scripts/product_acceptance.py`: present
- `scripts/verify_repo.ps1`: not present
- `tests/` formal/regression coverage: present, including existing 用户参考项目 benchmark tests

## Environment Notes

- `CGKN_OPENAI_API_KEY` is set in the environment. The key value was not printed.
- Shell startup emits conda plugin warnings about `conda-libmamba-solver`; this warning is unrelated to CGKN but appears in command stderr.

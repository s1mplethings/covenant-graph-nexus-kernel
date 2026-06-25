# Detected Entrypoints

Generated: 2026-06-18

## Selected Benchmark Entrypoint

For this complexity-scale test, use:

```powershell
python scripts/run_local_pipeline.py --goal "<complexity-scale prompt>" --out-dir <generated project dir> --run-dir <run dir> --result <result json> --allow-network --allow-provider --use-api --video --json
```

Reason:

- `README.md` documents `scripts/run_local_pipeline.py` as the generic local runtime executor.
- `scripts/run_local_pipeline.py --help` exposes provider/API flags, `--out-dir`, `--run-dir`, `--result`, `--video`, and JSON output.
- `scripts/run_local_pipeline.py` is a thin compatibility orchestrator over bounded modules including candidate sanitizer/materializer, post-build finalize, visual evidence, and final delivery truth.
- The kernel contract preserves provider generation, post-build finalization, `local_packager`, public delivery gate, and `delivery_manifest.json` as the delivery route.

## Telegram Default Mainline

The stable Telegram route is documented as:

```text
Telegram
-> agent_session.jsonl
-> whiteboard / backend_dialogue_loop
-> API/provider project generation
-> provider output validation
-> provider project files written
-> post_build_finalize
-> tests, image/screenshot evidence, runtime artifacts
-> local_packager
-> delivery_manifest.json
```

This benchmark does not run Telegram intake. It tests the generation/delivery capability by calling the local pipeline CLI that exercises the provider/post-build/finalization modules.

## Existing Benchmark/Readiness Entrypoints

- `scripts/run_complexity_scale_benchmark.py`: present before this work, but its spec targets a generic media evidence pipeline, not the exact local video workbench prompt in this request.
- `tests/test_complexity_scale_benchmark.py`: present before this work and validates the existing benchmark spec/runner behavior.
- `scripts/run_commercial_readiness.py`: readiness assessment lane only; not a generation route.
- `scripts/product_acceptance.py`: acceptance assessment helper; not a generation route.

## Not Selected

- `scripts/generate_project.py`: not selected because the kernel contract says it must not be reconnected as Telegram mainline.
- `scripts/pipeline_manifest.py` + `scripts/dynamic_pipeline_runner.py`: not selected as default generation route because the kernel contract preserves these as support/experimental planning lane.
- `scripts/ctcp_orchestrate.py`: absent.
- `scripts/run_agent_league.py`: absent.
- `scripts/verify_repo.ps1`: absent.

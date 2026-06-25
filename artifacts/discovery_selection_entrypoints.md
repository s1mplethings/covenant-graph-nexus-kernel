# Discovery Selection Entrypoints

## Confirmed Main Entrypoints

- `README.md` documents `scripts/run_local_pipeline.py` as the generic local runtime executor.
- `scripts/run_local_pipeline.py` is a thin compatibility wrapper over `scripts/run_local_pipeline_impl.py`.
- `scripts/run_local_pipeline_impl.py` contains the local execution mainline and `execute(args)`.
- `scripts/provider_generation.py` is a replaceable module wrapper that calls the provider generation logic through the legacy-compatible `run_provider_semantic_review_with_repair` function.
- Telegram default generation calls provider-backed generation from `scripts/telegram_live_bridge.py`; the kernel contract forbids bypassing provider validation, post-build finalization, `local_packager`, public delivery gate, and `delivery_manifest.json`.

## Existing Design / Planning Lane

- `docs/01_virtual_team_contract.md` defines the Virtual Team lane before implementation.
- `README.md` currently lists `customer_intent -> output_contract -> virtual_team_roster -> product_story -> mvp_scope -> technical_plan -> build_plan -> generated_project -> test_evidence -> delivery_bundle`.
- `scripts/pipeline_manifest.py` and `scripts/dynamic_pipeline_runner.py` exist and are preserved as support/experimental planning lane components, not Telegram default delivery mainline.

## Existing Acceptance And Truth Modules

- `scripts/product_acceptance.py` evaluates generated project acceptance and has a `pipeline_mode` path.
- `scripts/final_delivery_truth.py` calls `telegram_live_bridge.evaluate_public_delivery_gate` and `artifact_integrity.validate_final_package`.
- `scripts/final_promotion.py` promotes only validated candidates and packages through `local_packager.package_project`.
- `scripts/local_packager.py` creates `final_project_bundle.zip` and `delivery_manifest.json`; it must remain the only formal delivery exit.

## Existing Benchmark / Formal / Gate Scripts

- `scripts/run_local_pipeline.py`
- `scripts/run_local_pipeline_impl.py`
- `scripts/provider_generation.py`
- `scripts/product_acceptance.py`
- `scripts/final_delivery_truth.py`
- `scripts/final_promotion.py`
- `scripts/local_packager.py`
- `scripts/post_build_finalize.py`
- `scripts/post_build_repair.py`
- `scripts/visual_evidence.py`
- Existing complex-scale benchmark scripts used legacy naming before this work and should be neutralized.

## Discovery & Selection Integration Point

The safest v1 integration point is immediately after `run_local_pipeline_impl.execute(args)` resolves the raw `user_goal` and writes run context, before requirement blueprint, online input collection, market research, component pipeline composition, and provider semantic generation.

At that point Discovery & Selection can write stable artifacts under `run_dir/discovery/`, freeze `complexity_project_contract.json`, and pass selected direction/contract context forward without replacing the provider generation mainline.

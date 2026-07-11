# Requirement Decision Entrypoints

## Main Flow Entrypoints

- `README.md` documents `scripts/run_local_pipeline.py` as the generic local runtime executor.
- `scripts/run_local_pipeline.py` is the public compatibility wrapper.
- `scripts/run_local_pipeline_impl.py` contains `execute(args)` and the provider-backed local pipeline mainline.
- Telegram generation is coordinated through `scripts/telegram_live_bridge.py`, which must continue to use provider generation, post-build finalization, `local_packager`, public delivery gate, and `delivery_manifest.json`.

## Requirement / Discovery Files

- `docs/requirement_decision_first.md`
- `docs/requirement_decision_lane.md`
- `docs/complexity_discovery_selection_lane.md`
- `scripts/requirement_decision_lane.py`
- `scripts/discovery_selection_lane.py`
- `scripts/complexity_project_contract_check.py`

## Acceptance / Truth Files

- `scripts/requirement_acceptance_check.py`
- `scripts/product_acceptance.py`
- `scripts/final_delivery_truth.py`
- `scripts/final_promotion.py`
- `scripts/local_packager.py`

## Benchmarks

- `scripts/run_requirement_decision_benchmark.py`
- `scripts/run_complexity_scale_benchmark.py`
- `scripts/run_complexity_scale_workbench_benchmark.py`
- `benchmarks/complexity_scale_pipeline_benchmark.json`

## Test Entrypoints

- `python -m pytest`
- Focused requirement tests:
  - `tests/test_requirement_decision_lane.py`
  - `tests/test_requirement_acceptance_layers.py`
  - `tests/test_requirement_decision_pipeline_integration.py`
- Existing complexity tests:
  - `tests/test_complexity_discovery_selection.py`
  - `tests/test_complexity_project_contract.py`
  - `tests/test_complexity_scale_benchmark.py`

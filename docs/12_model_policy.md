# Model Policy

`scripts/model_policy.py` centralizes model selection so bridge, connectivity, planning, generation, repair, and review tasks do not hardcode conflicting defaults.

## Profiles

`CGNK_MODEL_PROFILE` selects one profile:

- `cheap`
- `balanced`
- `quality`

The default is `balanced`.

## Tasks

Supported task names:

- `frontdesk`
- `classification`
- `planning`
- `provider_generation`
- `revision`
- `repair`
- `review`
- `connectivity`

## Overrides

Task-specific environment variables take priority:

- `CGNK_FRONTDESK_MODEL`
- `CGNK_CLASSIFICATION_MODEL`
- `CGNK_PLANNING_MODEL`
- `CGNK_PROVIDER_MODEL`
- `CGNK_REVISION_MODEL`
- `CGNK_REPAIR_MODEL`
- `CGNK_REVIEW_MODEL`
- `CGNK_CONNECTIVITY_MODEL`

After task overrides, the selected profile supplies the default. If no task profile value exists, `OPENAI_MODEL` is used, then `gpt-4.1-mini`.

## Compatibility

Telegram provider generation should use `select_model("provider_generation")`.

Connectivity checks should use `select_model("connectivity")`.

Repair and review may use stronger defaults under the `balanced` and `quality` profiles without changing the generation route.

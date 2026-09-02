# ITER-044 Runtime Evidence

Evidence status: `PASS_WITH_LIMITS`

## Accepted design evidence

- The requirement decision froze three side-effect-free feature contracts with distinct owned paths: `allocate_subject_hours`, `rank_review_topics`, and `build_revision_calendar`.
- `feature_parallel_batches` contains all three feature ids in the same dependency-ready batch.
- The first responsibility-route event for all three business leaves was recorded at `2026-08-30 22:34:10 +08:00`, demonstrating same-batch scheduling rather than a declared-only parallel plan.
- The package boundary and single stdin JSON CLI remain downstream of the independent business leaves; no persistence, network, framework, GUI, account, or content-database feature was introduced.

## Generated-project evidence

- Workspace `kaoyan-companion-parallel-20260830-06` was generated through the reviewed Qwen Provider route and materialized a complete candidate.
- The supported CGKN test profile reported `29 passed, 1 failed` in `0.52s`.
- The single failure was a deficient generated assertion that expected the CLI `result` to remain a string. The runtime correctly returned the already-parsed revision-calendar list required by the frozen CLI contract.
- No generated candidate was hand-edited. The failure was instead converted into a reusable generation boundary: test leaves now reject both `isinstance(response["result"], str)` and a second `json.loads(response["result"])`.

## Kernel verification evidence

- Targeted feature-unit, Provider fallback, capability-supervision, goal-plan, and kernel-contract regression: `382 passed`.
- The focused aggregate-feedback/cache-revalidation/kernel guard profile: `33 passed`.
- Full repository regression: `1430 passed, 395 skipped, 5 warnings` in `719.02s`; no failures.
- The feature-unit test contract is retained on leaf work graphs, revalidated on cached component reuse, and versioned in the test component checkpoint identity.
- A deficient repair now receives all observed test-contract violations in one bounded response, preventing serial fix-and-regress loops.

## Provider recovery

- A minimal live probe of `qwen3.8-max` returned HTTP 403 `PERMISSION_DENIED`: that model's free quota was exhausted while the account was configured for free-tier-only usage.
- The independent `qwen3.8-flash` quota returned a connected Provider probe and was selected for the reviewed safe resume.
- `qwen3.8-flash` completed the final Provider-authored repair, materialized workspace `kaoyan-companion-parallel-20260830-07`, and produced generation status `PASS`.
- The supported generated-project profile then reported `22 passed` in `0.44s` with no failures.
- Earlier local fallback attempts failed the frozen test contract and were rejected before materialization. They are retained only as contributing diagnostic history, not Provider or delivery evidence.

## Delivery boundary

- Generation planning, parallel scheduling, Provider generation, and supported generated-project test evidence are available.
- The supported generated-project profile fully passed.
- Packaging, public delivery gate, `delivery_manifest.json`, and formal delivery PASS are `NOT_EVALUATED`.
- The iteration is therefore `PASS_WITH_LIMITS`; packaging and public delivery require a separate authorized run through `local_packager` and the public delivery gate.

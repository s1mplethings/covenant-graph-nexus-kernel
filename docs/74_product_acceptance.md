# Product Acceptance

`scripts/product_acceptance.py` checks whether the generated project resembles a usable product, not merely whether evidence files exist.

Inputs may include the user goal, generated file manifest, README, TEST_REPORT, screenshot/video metadata, UI smoke result, feature list, known limits, and repair plan.

Commercial threshold:

- `product_score >= 75`
- `feature_coverage_score >= 80`
- `ux_score >= 60`
- no missing core features

If a project misses core features, it should be marked `NEEDS_REWORK`. If it is usable but below commercial threshold, it can be `DELIVER_WITH_WARNINGS` or `ASK_USER_REVIEW`. Product acceptance must write customer-visible limitations instead of faking PASS_FINAL.

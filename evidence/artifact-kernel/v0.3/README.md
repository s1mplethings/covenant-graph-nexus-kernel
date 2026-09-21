# Artifact-driven Pipeline Kernel v0.3 evidence

Claim: CGKN can execute a local typed Artifact → Module → Artifact flow with
deterministic provenance, cache fingerprints, dependency invalidation,
affected-only recompute, ref-only checkpoints, and stale-aware delivery
judgment while preserving existing Provider and delivery authorities.

Status: `PASS_WITH_LIMITS` for the scoped v0.3 verification. This curated
bundle is support evidence; it does not authorize packaging or public delivery.

Reproduce:

```text
python -m pytest tests/test_artifact_driven_kernel.py tests/test_kernel_contract.py tests/test_product_design_depth_rule_guard.py -q
python scripts/validate_bundle.py --root . --schema
python scripts/demo_artifact_recompute.py --run-dir runs/artifact-v03-demo --json
```

The demo writes all raw artifacts, manifests, checkpoints, cache entries, and
feed-forward reports beneath ignored `runs/` storage.

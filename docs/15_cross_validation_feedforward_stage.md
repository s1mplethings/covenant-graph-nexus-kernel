# CGKN Cross-Validation and Feedforward Stage

## Outcome

Cross-validation and feedforward is an executable project-generation quality
stage, not a diagram-only convention. Every newly generated or checkpoint-reused
component must pass it before that component becomes upstream input. The merged
project must pass an aggregate receipt before the existing post-build stage.

It remains inside the reviewed Provider route and creates no second planner,
generator, packager, or delivery exit.

## Position in the real project lifecycle

```text
frozen goal and component plan
  -> Provider component output
  -> semantic review
  -> deterministic component quality validation
  -> cross-validation receipt                    [new, veto-only]
  -> bounded passing feedforward projection      [new, next component input]
  -> next component
  -> assembled-project quality validation
  -> aggregate cross-validation receipt          [new, veto-only]
  -> post-build finalization
  -> canonical test/runtime/visual evidence
  -> production candidate provenance
  -> local_packager
  -> public_delivery_gate
  -> delivery_manifest.json
```

## Component checkpoint contract

The deterministic `CGKNCrossValidationFeedforwardReceipt` independently binds:

1. **Plan view** — every required component path exists in the current output.
2. **Quality view** — the component quality receipt is a hash-valid `pass` and
   its validated paths exactly match the current component files.
3. **Implementation view** — current paths exist in a hash-valid
   `CGKNProjectInterfaceRegistry` derived from actual merged source files.
4. **Dependency view** — every declared upstream component is complete and has
   a hash-valid passing cross-validation receipt projection.

A failure is recorded and blocks component publication. It is routed through the
existing component quality retry/repair behavior; it never creates a fallback
generation path. A checkpoint-reused component is revalidated under the current
plan, interfaces, and upstream state before reuse.

## Feedforward contract

Only a verified passing component receipt can produce a
`CGKNCrossValidationFeedforwardProjection`. The projection is deliberately small:

- component identity;
- receipt hash;
- validated project paths;
- component-quality receipt hash;
- implemented-interface-registry hash.

The next `CGKNIntegrationFeedforwardSnapshot` carries these projections alongside
the already bounded upstream interface catalog. Failure details, complete source,
formal evidence claims, packaging decisions, and delivery decisions are excluded.
The full receipt hash remains in the audit snapshot, but downstream checkpoint
identity omits only that audit hash while retaining validated paths, component
quality hash, and interface-registry hash. Transient repair narration therefore
cannot invalidate an otherwise unchanged downstream component.

## Aggregate project checkpoint

After merge and assembled-project quality validation, the project receipt binds:

- every component cross-validation receipt;
- the assembled-project quality receipt;
- the required final path inventory;
- the final implemented-interface registry.

This checkpoint answers only: “is the generated project internally consistent
enough to proceed to post-build?” It does not answer whether the project has passed
real tests, runtime checks, visual inspection, review, packaging, or delivery.

## Authority and failure rules

- Internal status is lower-case `pass` or `fail`, not `EvidenceStatus`.
- The receipt is veto-only and explicitly declares that it cannot assert formal
  evidence, package, or deliver.
- A failed component receipt cannot feed a downstream component.
- A failed aggregate receipt cannot enter post-build finalization.
- Canonical test, runtime, visual, review, packaging, and delivery gates remain
  independent and mandatory where applicable.
- `local_packager` remains the only delivery exit.

## Acceptance metrics

| Metric | Target | Evidence |
| --- | --- | --- |
| Component coverage | 100% of generated and reused components have a current receipt before publication | component artifacts and provider event log |
| Cross-binding | plan paths, quality paths/hashes, actual interface registry, and upstream receipts agree | deterministic positive and negative tests |
| Feedforward safety | only verified passing bounded projections enter downstream snapshots | projection and snapshot tests |
| Project convergence | one passing aggregate receipt exists before post-build | assembled-project artifact and integration test |
| Authority isolation | no receipt can assert formal PASS, package, or deliver | contract assertions and kernel guard |

## Deliberately deferred extensions

Post-build test/runtime/visual convergence already belongs to canonical evidence
producers and their registered inspectors. A later increment may add a read-only
cross-reference view over those artifacts, but it must not duplicate their
authority or turn this generation-stage receipt into a formal gate.

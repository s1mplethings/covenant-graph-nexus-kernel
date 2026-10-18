# Capability Build Lifecycle Contract

Capability building is an L6 application orchestration over the existing
CapabilityTree, ExecutionDAG, DAGRunner, and FileRunStore authorities. It does
not define another scheduler, retry engine, state authority, or event log.

The canonical flow is:

`Spec -> Frozen Route -> Provider Attempt -> Immutable Candidate Revision -> Validator DAG -> Failure Attribution -> Action Policy -> Admission -> Capability Store -> Original Task Resume`

The boundaries are mandatory:

- A Provider adapter may create a new candidate source tree. It cannot validate,
  admit, install, or overwrite a prior revision.
- A CandidateRevisionStore publishes a complete revision by atomic rename. A
  published revision is content-addressed and load-time verified. Repair always
  creates a child revision.
- Validators are deterministic executors. They produce immutable,
  source-bound ValidationReceipts and cannot import or call Provider APIs.
- CapabilityBuildActionPolicy is the sole repair authority. Framework defects
  select revalidation, external failures select wait, dependency drift selects
  dependency revalidation, and unknown failures fail closed to review.
- Admission evaluates a validated revision and cannot modify it. Installation
  copies the admitted content into CapabilityStore, whose existing admitted and
  hash-matched gate remains unchanged.
- External availability is separate from local correctness. A capability whose
  policy permits fixture-backed local admission may be `VALIDATED_LOCAL` while
  external readiness remains `BLOCKED_EXTERNAL`.

Validator suite identity binds validator sources, contract-test authority,
fixtures, policy version, and schema version. A suite hash change makes prior
validation evidence `STALE_VALIDATOR_CHANGED`; it does not invalidate or mutate
the candidate. Revalidation keeps the revision ID and source hash unchanged,
reruns only the validation/action subgraph through DAGRunner affected-only
invalidation, and performs zero Provider calls.

Provider failure before a valid candidate creates no revision. Provider failure
during repair preserves the parent revision and creates no child. A validation
failure alone never authorizes repair.

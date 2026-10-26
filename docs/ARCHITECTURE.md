# CGNK Architecture

CGNK is a composable capability kernel for evidence-grounded project work.
CGNK is the public project name. The current Python package namespace remains
`cgkn` for backward compatibility.
Its canonical execution path is:

```text
User goal
  -> high-capability Agent
  -> CapabilityTree
  -> ExecutionDAG
  -> Component / Block
  -> replaceable bounded Executor
  -> Result / Test / Artifact
  -> Project State
  -> Agent checkpoint
```

The Agent owns project-level intent, decomposition, and high-impact decisions.
Executors—including provider models, local models, tools, and scripts—perform
bounded node work. The tree expresses composition; the DAG expresses executable
dependencies. `FileRunStore` is the persisted run-state authority.

## Stable core

- typed Component and Block request/result boundaries;
- CapabilityTree and ExecutionDAG compilation;
- bounded executor registry and deterministic local executors;
- project/run state, checkpoints, retry, and affected-subgraph invalidation;
- localized knowledge retrieval with raw-evidence provenance;
- capability registry, search, qualification, reuse, and bounded composition;
- deterministic validation, repair evidence, and guarded repository publishing.

## Qualified application surfaces

Conversation, knowledge internalization, minimal software-project generation and
repair, Promotion Studio, Community Operator, and Project Digital Persona use
the same kernel authorities. Their qualification levels differ; they are not
additional runtimes or planners. Public writes remain approval-required.

## Experimental surfaces

Self-Growth admission remains bounded and experimental. Persona and Community
results are directional. Adaptive routing and Multi-Agent Runtime are not
release defaults. The release uses fixed routing.

## Project Corpus boundary

`cgkn/application/project_corpus/` observes application runs and preserves
versioned attempt and snapshot manifests over immutable SHA-256 objects. Its
SQLite catalog is disposable derived state. It can reconstruct a snapshot,
trace failure-to-repair lineage, and produce deterministic family-level samples,
but it cannot plan, schedule, execute, mutate project state, or internalize
Knowledge. Capture is best-effort and is disabled unless an external local root
is configured. Private evaluator packets use a separate non-searchable,
non-exportable namespace.

## Context and dependency boundaries

Executors receive only the node contract and relevant dependencies. Downstream
project workers receive stable semantic dependency facts—modified files,
interfaces, materialized-baseline state, and public test-authority receipts.
Timing, usage, result hashes, and other ledger-only metadata stay out of model
prompts. This preserves reproducibility and reduces non-actionable context.

## Public delivery and external services

The reviewed public delivery route remains provider output validation,
post-build finalization, `local_packager`, `public_delivery_gate`, and
`delivery_manifest.json`. `scripts/canonical_repo_publish.py` is the sole
repository commit/push authority. Postiz remains an independent AGPL-3.0
service across API/MCP/CLI transport boundaries; no Postiz implementation code
is vendored into this Apache-2.0 repository.

## Security properties

Effects, paths, file ownership, output schemas, and call budgets are enforced
deterministically. Hidden acceptance is never supplied to providers. Partial
unit materialization is staged until complete validation and atomic commit.
Secrets are opaque local references and are excluded from evidence artifacts.

For the product invariants and migration boundary, see `PRODUCT_GOAL.md`,
`MVP_SCOPE.md`, `governance/product_invariants.json`,
`governance/current_architecture.json`, and
`docs/MVP_RUNTIME_MIGRATION_BOUNDARY.md`.

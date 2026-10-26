# Artifact-driven pipeline migration

## Purpose

CGNK v0.3 adds an artifact-driven execution lane without breaking
`flow.project_generation@1`, `flow.project_refactor@1`, or
`flow.modular_project_generation@1`. Those flows may continue to use their
existing phase/checkpoint conventions while modules migrate incrementally.

The old shape primarily records progress:

```text
Phase -> PhaseCheckpoint -> Phase -> PhaseCheckpoint
```

The new shape carries validated knowledge and records execution separately:

```text
ArtifactInstance -> typed ModuleContract -> ArtifactInstance
                                  |
                                  +-> GenerationCheckpoint (status side channel)
```

## Definitions

- Feed-forward: a validated upstream output artifact becomes a downstream typed
  input artifact. Replaying full chat history is not feed-forward.
- Decomposition: a complex input is transformed through multiple typed
  intermediate artifacts, independent bounded modules, and an explicit DAG.
- Incremental recompute: a changed artifact hash invalidates only consuming
  nodes and their descendants; unrelated fresh artifacts are reused.

## Contract changes

Artifact instances live under `runs/<run-id>/artifacts/`, while
`artifact_index.json` stores refs, producer, hash, lifecycle status,
supersession, and consumers. `run_manifest.json` binds the flow, policy, run
inputs/outputs, and node checkpoint paths. Filesystem paths never replace
`ArtifactRef` at a module boundary.

Artifact-driven module contracts add:

```json
{
  "ports": {
    "input": {
      "snapshot": {
        "artifact_type": "artifact.project_snapshot@1",
        "required": true,
        "projection": ["modules", "boundaries", "importantFiles"]
      }
    }
  },
  "context": {
    "maxChars": 6000,
    "requiredArtifactPorts": ["snapshot"],
    "optionalArtifactPorts": [],
    "includeDecisionLedger": true,
    "recentConversationTurns": 0
  },
  "implementation": {
    "kind": "local_function",
    "entrypoint": "package.module:function",
    "promptVersion": "v1",
    "cacheable": true
  }
}
```

Top-level field projection is intentionally the only query mechanism in this
version. Implementation kinds are `local_function`, `provider`, `script`, and
`composite`. A Provider receives only declared artifact inputs, the module
prompt/context, and policy. Its JSON output is schema-validated and materialized
before the next node runs; one bounded schema repair is permitted.

## Migration steps

1. Register each business/analysis payload as an `ArtifactTypeSpec` with a real
   content schema.
2. Split a generic phase module only where input/output/effect/policy contracts
   materially differ. The old generic module may remain in compatibility or
   tooling flows.
3. Connect every required input port to one compatible producer and compile the
   DAG.
4. Declare the module-specific context budget and top-level projections.
5. Declare the runtime implementation and all effects, then add applicable
   effect-cardinality constraints to the policy.
6. Run once to materialize the artifact index, manifest, checkpoints, and
   feed-forward report.
7. Change one artifact, inspect `invalidate_artifact.py --dry-run`, and verify
   affected-only recompute plus unrelated cache reuse.
8. Keep artifact delivery judgment upstream of the existing canonical evidence,
   packaging, and public-delivery gates.

## CLI

```text
python scripts/run_artifact_flow.py --run-dir runs/demo --requirement "..." --project-json examples/artifact-driven/todo-refactor/todo_project.json
python scripts/invalidate_artifact.py --run-dir runs/demo --artifact ai.requirement-interpretation.002 --dry-run
python scripts/run_artifact_flow.py --run-dir runs/demo --from-artifact ai.requirement-interpretation.002
python scripts/artifact_lineage.py --run-dir runs/demo --artifact ai.delivery-judgment.002 --json
python scripts/explain_flow.py --flow flow.artifact_driven_project_refactor@1 --json
```

## Current limits

Storage and cache are local files. Projections support top-level fields only.
Diff is structural JSON. The runtime is single-machine and deterministic; it
does not add a queue, database, graph database, distributed scheduler, external
artifact store, or alternate delivery engine.

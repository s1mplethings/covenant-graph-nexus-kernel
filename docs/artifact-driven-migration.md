# Artifact-driven pipeline migration

## Purpose

CGKN v0.3 adds an artifact-driven execution lane without breaking
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


## Portable components and Skill transfer (code-only, not exercised)

These entries use `scripts/run_goal_driven.py --config <config>` and the existing
ProjectSession/FileRunStore/ExecutionAuthority. They do not use the historical
artifact-flow CLI above. Administrative commands return before Provider setup.

- `export-component --package <manifest> --output <new-file>` consumes a Block,
  exact `artifact_paths`, current `receipt_id`, `entrypoint`, `dependencies`,
  `applicability`, and optional `invocation`. Source exports require current
  receipt-bound artifact bytes. `import-component --package <envelope>` stores
  an unqualified candidate; import dependency packages first.
- Direct invocation requires `invocation` with exactly `protocol`,
  `input_semantics`, `error_semantics`; protocol is `python-json-stdio@1`.
  The selected `.py` entry receives UTF-8 JSON on stdin:
  `{"inputs":{"port_id":"value"},"dependencies":{"block_id":{"root":"relative package directory","entrypoint":"main.py"}}}`.
  It writes one JSON object mapping output port IDs to values to stdout; logs go
  to stderr. Nonzero exit, malformed output, mismatched input or changed content
  rejects the candidate. A timeout requires reconciliation, not automatic retry.
- The Agent proposes `local.component@1` with `goal`, `package_identity`,
  `inputs`, `bindings`, and `output_paths`. A binding is
  `{"input_port":{"node_id":"declared_dependency","port_id":"producer_output"}}`;
  the node must be in `depends_on`. Each output port has a distinct bounded
  destination. All values use the imported Port schemas; semantic requirements
  remain subject to independent acceptance. Evidence-policy Ports and remote
  effects require an explicit specialized adapter. v1 packages remain source
  inputs and cannot silently become executable.
- `register-skill --skill <json>` takes `manifest` and `receipt_ids`, registering
  a current-project candidate through existing source authorities.
  `export-skill --skill <json> --output <new-file>` takes `skill_id`, `version`
  and exports only a currently qualified, portable strategy.
  `import-skill --skill <envelope>` binds the candidate to the target project,
  discards source receipts as qualification and clears source metrics.
- Configure `skill_sources` as explicit objects with `store_root`, `project_id`,
  `run_id`. `store_root` is the actual FileRunStore directory (normally the
  source run root's `store` child). Source discovery never follows paths in a
  package. List source authorities during import and other target trial runs
  during requalification. Existing authority hashes and receipts are rechecked.
- Configure `skill_trial: {"skill_id":"...","version":"..."}` plus `skill_task`
  (`task_family`, `capability_id`, `inputs`, `outputs`, `dependency_versions`,
  `dependency_contract_hashes`, current `checker_identities` and
  `environment_identity`, applicable `context`, `requirement_refs`, and the
  current `capability_claim`). Public strategy steps pass through the ordinary
  GoalComposer compiler and admission. The Permit binds the exact strategy;
  an imported candidate is never selected as verified by SkillMatcher.
- Import the same strategy into the same target project in two distinct runs
  and obtain real independent execution/acceptance evidence. Then
  `requalify-skill --skill <json>` takes `skill_id`, `version`, `receipt_ids`.
  Existing promotion_check requires compatible target receipts and current
  passing gates; source-project success is insufficient. Normal sessions then
  consume the qualified strategy through the same compiler/admission path.
  Changed strategy/dependencies require an explicit new candidate version.

All six administrative commands use the existing session lock. No command here
has been executed as part of this code-only change, and no qualification is
claimed. Process effects retain the existing Host boundary, not an OS sandbox.

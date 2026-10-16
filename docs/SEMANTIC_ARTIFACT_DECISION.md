# Semantic Artifact Design Decision

## Decision

`ITER-SEMANTIC-ARTIFACT-DESIGN-009` has no production winner. Designs A, B, and C were exercised under the same Provider models, budgets, public contracts, hidden acceptance, independent workspaces, deterministic extractor/guard, and repair limits. Every design passed its schema and fake-provider suites and repaired the seeded project, but every design failed the real CSV CLI single run and all three repeat runs.

The predeclared production threshold required at least two successful CLI runs out of three. The highest numerical score therefore cannot be used to select a "least bad" design.

## Designs

| Design | Representation | Core types | Artifact kinds | Schemas | Score | Qualified |
|---|---|---:|---:|---:|---:|---|
| A | Fine-grained immutable typed artifacts | 11 | 10 | 10 | 69.25 | No |
| B | Generic immutable envelope plus strict schema registry | 2 | 10 | 10 | 73.25 | No |
| C | Contract/State/Evidence families plus strict payload schemas | 4 | 10 | 10 | 74.25 | No |

Design A provided a base typed artifact plus ten common semantic kinds. It did not implement the three separately named refinements `SourceArtifact`, `TestArtifact`, and `ExecutionEvidence` from the original A sketch; this is recorded as an additional design-completeness weakness rather than being hidden by the common ten-fact comparison.

## Results

| Design | CLI single | Seeded repair | CLI repeat | Accepted interface breaks | Whole replans | Manual edits |
|---|---|---|---|---:|---:|---:|
| A | FAIL | PASS | 0/3 | 0 | 0 | 0 |
| B | FAIL | PASS | 0/3 | 0 | 0 | 0 |
| C | FAIL | PASS | 0/3 | 0 | 0 | 0 |

The seeded repair result is meaningful: every design retained the original CapabilityTree/DAG identity, attributed the failure to the bounded owner, preserved the public interface, and reran only the affected subgraph. The CLI result is decisive: semantic envelope choice alone did not make the acceptance facts complete enough for reliable greenfield generation.

## Common failure

Post-experiment governance inspection found the same two acceptance gaps in representative generated projects:

1. Public tests imported `pytest`. The project contract asked for pytest tests and stdlib-only runtime behavior, but the hidden hygiene rule rejects imports that are neither stdlib nor project modules.
2. CSV parsing used the default permissive reader. A malformed quoted row consequently exited successfully instead of producing a clear non-zero error.

The workers received current source, extracted interfaces, direct semantic dependencies, structured failures, and bounded paths. What they did not receive was a canonical, machine-checkable mapping from each public acceptance claim to its exact generated-project dependency and executable obligation. This is the next design problem; adding another envelope without closing that mapping would not address the evidence.

## Consequence

Production L6 semantics remain unchanged. No experimental design is copied into `cgkn/application/software_project`, no Kernel authority is modified, and Web/API, production CLI repeat, production repair, and weak-worker robustness runs are not started. Status remains `semantic_artifact_interface = PARTIAL` and `generation_readiness = GENERATION_LEVEL_0`.

# Artifact-driven Todo refactor demonstration

This deterministic local reference run starts from:

> 给现有 Todo App 增加批量归档功能，但不能破坏现有单条归档。

It materializes RawRequirement, RequirementInterpretation, ProjectSnapshot,
ProblemAnalysis, ArchitectureDecision, RefactorPlan, ImplementationPatch,
TestEvidence, BoundaryReport, and DeliveryJudgment instances. The runtime then
supersedes only RequirementInterpretation with:

> 批量归档必须有确认。

The resulting invalidation closure excludes `n_project_snapshot`. On the second
scheduler pass, that node is a cache hit; ProblemAnalysis and every affected
descendant are cache misses and produce new immutable instances. The largest
module context is 2,640 characters versus the 12,000-character comparison
source, and the smallest measured module ratio is 0.0845.

`sample_run.json` and `incremental_recompute_evidence.json` are reproducible
support evidence with formal status `NOT_EVALUATED`; they do not authorize
packaging or delivery.

```text
python scripts/demo_artifact_recompute.py --run-dir runs/artifact-v03-demo --json
```

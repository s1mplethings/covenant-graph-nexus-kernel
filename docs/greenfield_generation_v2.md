# Greenfield Bundle Generation V2

`ITER-GREENFIELD-BUNDLE-GENERATION-027` replaces the Campaign-only, whole-project Provider response with a reusable Software Project Production capability.

## Audited old call graph

`ProjectCase -> MultiProjectCampaignService._CoreExecutor -> GenerationRequest -> ProductionGenerationClient -> Grok -> whole-project proposal -> ScopedFileTransaction -> compile/pytest/oracle/hidden -> core-generate rerun`

The old `_CoreExecutor`, project matrix, and result aggregation were Campaign-specific. `ProductionGenerationClient`, `CapabilityTree`, `DAGRunner`, `FileRunStore`, `CandidateRevisionStore`, `RepositoryCodegenService`, and `local_packager` remain canonical authorities. Historical whole-project generation remains compatibility code.

## V2 call graph

`Project Contract -> deterministic GenerationManifest -> frozen Bundle Interface Contracts -> CapabilityTree -> ExecutionDAG -> DOMAIN revision/validation -> CLI revision/validation -> atomic assembly -> compile/pytest/oracle/hidden/help -> RepositoryCodegenService bounded patch when needed -> local_packager`

Provider transport retries target only the failed bundle. A response-less attempt creates no revision. Candidate repair creates a child revision. CLI generation consumes the frozen Domain interface rather than Domain Provider output. Project assembly verifies exact target manifests and source hashes before replacing the workspace atomically.

## Current evidence

Targeted Real 4 passed 3/4 and the Existing Repo canary passed. The frozen Mini Campaign passed 3/8, including 1/2 holdout and a naturally grown `project.docs.api_reference.render@1` capability. The functional checkpoint is therefore not established; the permanent baseline remains `BASELINE-SELF-GROWN-LEAVES-001`.

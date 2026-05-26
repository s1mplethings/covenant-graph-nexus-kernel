# CovenantGraph Nexus Kernel Phased Implementation Plan

## Phase 0: Contract object freeze

Goal: introduce machine-first contract object names without breaking the existing starter repository.

Tasks:

```text
1. Add schemas for ArtifactTypeSpec, ModuleContract, FlowSpec, PolicySpec, GraphEditProposal, MigrationSpec, Diagnostic.
2. Add examples under contracts/examples or examples/contract_v2.
3. Keep old flowspec validation and tests working.
4. Add JSON load tests for every example file.
5. Add a simple id parser for refs like module.patch.emit@1.
```

Acceptance:

```text
python -m unittest discover -s tests -p "test_*.py" -v
python scripts/contract_check.py examples/flows/project_generation.flow.json
```

## Phase 1: Compiler skeleton

Goal: compile a flow into a resolved symbol table.

Tasks:

```text
1. Implement ContractBundle loader.
2. Implement ref resolver for artifact/module/policy/flow refs.
3. Build symbols.artifacts, symbols.modules, symbols.flows, symbols.nodes, symbols.ports.
4. Expand FlowNode uses into resolved input/output surfaces.
5. Emit canonical normalized JSON.
6. Return structured diagnostics instead of free text errors.
```

Acceptance:

```text
valid project_generation flow returns ok=true
missing module returns CGNK_MODULE_NOT_FOUND
missing artifact type returns CGNK_ARTIFACT_TYPE_NOT_FOUND
```

## Phase 2: Type, graph, and policy checks

Goal: make module movement and replacement safe.

Tasks:

```text
1. Type check PortEdge.
2. Detect unbound required inputs.
3. Detect multi-producer input ports unless multi=true.
4. Detect graph cycles.
5. Check effects against policy.
6. Check capabilities against policy.
7. Check structured predicates and gates.
```

Acceptance:

```text
wrong artifact edge returns CGNK_EDGE_TYPE_MISMATCH
cycle returns CGNK_GRAPH_CYCLE
risk > policy.max_risk returns CGNK_POLICY_RISK_EXCEEDED
network/provider denial returns CGNK_POLICY_EFFECT_DENIED
```

## Phase 3: GraphEditProposal preview

Goal: coding agent cannot directly mutate FlowSpec.

Tasks:

```text
1. Implement apply_graph_edits(flow, proposal) -> preview_flow.
2. Validate proposal edit permission against PolicySpec.agent_permissions.
3. Compile preview_flow.
4. Reject proposal if preview compile fails.
5. Add repair_hints for common edge and ref errors.
```

Acceptance:

```text
insert_extra_patch_validation proposal passes
replace_node must either keep same node id or provide explicit rewiring
preview failure returns CGNK_PROPOSAL_PREVIEW_INVALID
```

## Phase 4: MigrationSpec and Contract Pack

Goal: support legacy project-generation refactor with bounded agent context; CTCP can be the first pilot.

Tasks:

```text
1. Implement migration checker.
2. Implement preserve-rule skeleton for CLI/output schema/report/provider behavior.
3. Implement contract_pack generator.
4. Add codex prompt generator using ContractPack.
```

Acceptance:

```text
project_generation migration produces agent_context.project_generation.contract_pack.json
contract pack includes flow, modules, artifacts, policy, migration, allowed files, denied files, required checks
```

## Phase 5: Legacy project-generation pilot

Goal: use the contract layer to guide a real legacy-system refactor, with CTCP as an optional first target.

Target:

```text
tools/providers/project_generation_contracts.py
tests/concrete_project_benchmark/run_concrete_project_benchmark.py
```

Rules:

```text
1. No provider behavior change.
2. No CLI behavior change.
3. No benchmark summary schema change.
4. No report format removal.
5. All module splitting must map to ModuleContract ids.
6. Agent changes must produce PatchManifest or GraphEditProposal.
```


## Final baseline hardening included in this bundle

This final bundle tightens the design into a compiler-ready baseline:

```text
1. Artifact and module references are canonical `id@version` refs.
2. Flow endpoints are directional: SourceEndpoint cannot be flow_output, TargetEndpoint cannot be flow_input.
3. Gate predicates are structured through `predicate.schema.json`.
4. Graph edit proposals are op-specific; each op has required fields.
5. `flow.project_refactor@1` no longer uses provider/network planning; it uses `module.plan.generate.contract_only@1`.
6. `flow.project_generation@1` keeps provider planning through `module.plan.generate.provider@1` under a policy that allows it.
7. ContractPack, CompileResult, and CompiledContractBundle schemas are included.
8. `scripts/validate_bundle.py` is a dependency-light reference semantic checker for refs, types, policy effects, required inputs, output binding, cycles, and gate node refs.
```

Minimum acceptance for using this as the CovenantGraph Nexus Kernel base:

```text
python scripts/validate_bundle.py
# flow.project_generation@1: OK errors=0
# flow.project_refactor@1: OK errors=0
```

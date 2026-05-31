# Prompt: Phase 1 Contract Compiler Skeleton

Continue from Phase 0.

Goal:
Implement the first contract compiler pipeline for the CovenantGraph Nexus Kernel contract system.

Compiler pipeline:

```text
load bundle
schema/basic shape validation
normalize refs
resolve artifacts/modules/policies/flows
build symbol table
expand FlowNode surfaces from ModuleContract
check PortEdge source/target existence
check PortEdge artifact compatibility
emit compiled bundle and diagnostics
```

Required public API:

```python
compile_contract_bundle(bundle: ContractBundle) -> CompileResult
compile_flow(flow_ref: str, bundle: ContractBundle) -> CompileResult
```

CompileResult shape:

```json
{
  "ok": true,
  "compiled": {
    "symbols": {
      "artifacts": {},
      "modules": {},
      "flows": {},
      "nodes": {},
      "ports": {}
    },
    "graphs": {}
  },
  "diagnostics": []
}
```

Required diagnostics:

```text
CGNK_REF_NOT_FOUND
CGNK_MODULE_NOT_FOUND
CGNK_ARTIFACT_TYPE_NOT_FOUND
CGNK_PORT_NOT_FOUND
CGNK_EDGE_TYPE_MISMATCH
CGNK_INPUT_UNBOUND
```

Testing:

```text
1. Add a valid project_generation contract bundle test.
2. Add one test per required diagnostic.
3. Existing tests must remain passing.
```

Do not add runtime execution or provider calls.


## Final baseline requirements

- Use canonical refs (`artifact.*@version`, `module.*@version`).
- Do not mutate FlowSpec directly; submit GraphEditProposal.
- Run `python scripts/validate_bundle.py` before reporting success.
- `flow.project_refactor@1` must compile without provider/network effects.
- Keep customer/runtime code out of this contract kernel.

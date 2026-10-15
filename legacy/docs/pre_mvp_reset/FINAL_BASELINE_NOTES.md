# Final Baseline Notes

This bundle is intended to be used as a CovenantGraph Nexus Kernel base.

## What was hardened in the final pass

- Canonicalized artifact refs to `artifact.*@version`.
- Split provider planning and contract-only planning:
  - `module.plan.generate.provider@1`
  - `module.plan.generate.contract_only@1`
- Fixed `flow.project_refactor@1` so it compiles under `policy.safe_project_refactor@1` without network/provider effects.
- Split endpoint schemas into direction-specific `SourceEndpoint` and `TargetEndpoint`.
- Added `predicate.schema.json` for structured gates.
- Tightened `GraphEditProposal` into op-specific edit schemas.
- Added schemas for:
  - `ContractPack`
  - `CompileResult`
  - `CompiledContractBundle`
  - common refs/endpoints
- Added reference semantic checker:
  - `scripts/validate_bundle.py`
- Added expected compile result snapshots under `tests/fixtures/compile_results/`.

## Required baseline check

```bash
python scripts/validate_bundle.py
python scripts/validate_bundle.py --schema
```

Expected:

```text
flow.project_generation@1: OK errors=0
flow.project_refactor@1: OK errors=0
```

## Intended use

Use this bundle as a contract compiler starter, not as a runtime executor. The first real implementation target should be:

```text
1. load bundle
2. resolve refs
3. compile flow
4. preview graph edits
5. emit structured diagnostics
6. generate bounded ContractPack for coding agents
```

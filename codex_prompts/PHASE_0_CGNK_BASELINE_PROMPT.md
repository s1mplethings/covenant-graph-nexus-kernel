# Prompt: Phase 0 CovenantGraph Nexus Kernel Baseline

You are working on `cgnk-core-starter`.

Goal:
Introduce a machine-first contract compiler foundation. Do not add a runtime executor. Do not add provider calls. Do not add Telegram/frontend/product-layer code.

Current repository shape:

```text
src/cgnk_core/flowspec/
src/cgnk_core/refactor/
src/cgnk_core/runtime/
src/cgnk_core/cli/
examples/
tests/
```

Add the following contract objects:

```text
ArtifactTypeSpec
ModuleContract
FlowSpec
PolicySpec
GraphEditProposal
MigrationSpec
Diagnostic
```

Required implementation shape:

```text
src/cgnk_core/contracts/
  __init__.py
  ids.py
  diagnostics.py
  loader.py
  normalize.py
  resolver.py
  compiler.py
  graph_invariants.py
  compatibility.py
  proposals.py
  predicates.py

src/cgnk_core/specs/
  artifact.py
  module.py
  flow.py
  policy.py
  migration.py
  proposal.py
```

Phase 0 tasks:

```text
1. Add dataclasses or TypedDict-like structures for the contract objects.
2. Add stable ref parser for refs like module.patch.emit@1.
3. Add diagnostic object and stable error codes.
4. Add JSON example loader tests.
5. Keep all existing tests passing.
6. Do not remove old flowspec validator.
```

Important design rules:

```text
1. Modules do not call other modules.
2. Modules expose typed input/output ports.
3. FlowSpec connects ports.
4. GraphEditProposal is the only allowed graph mutation format.
5. Compiler returns ok/compiled/diagnostics JSON.
6. Diagnostics must include code, severity, path, message, expected, actual, repair_hints where relevant.
```

Validation commands:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p "test_*.py" -v
PYTHONPATH=src python scripts/flowspec_validate.py examples/project_normalization.flowspec.json
```

Do not:

```text
Do not add runtime execution.
Do not apply patches.
Do not write workspace files except explicit CLI output.
Do not make network calls.
Do not copy legacy application code into this kernel; keep project-specific code only in separate migration fixtures if a pilot needs it.
```


## Final baseline requirements

- Use canonical refs (`artifact.*@version`, `module.*@version`).
- Do not mutate FlowSpec directly; submit GraphEditProposal.
- Run `python scripts/validate_bundle.py` before reporting success.
- `flow.project_refactor@1` must compile without provider/network effects.
- Keep customer/runtime code out of this contract kernel.

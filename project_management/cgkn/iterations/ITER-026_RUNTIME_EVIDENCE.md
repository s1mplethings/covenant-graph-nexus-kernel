# ITER-026 Runtime Evidence

## Outcome

`NEEDS_REWORK`. The user-selected key works and CGKN produced real Provider
checkpoints, but no candidate materialized and the partial Backend contains
decisive semantic defects.

## Credential handling and usage

The selected credential was entered through hidden terminal input and injected
only into child-process environment `CGKN_OPENAI_API_KEY_OVERRIDE`. It was not
written into the repository or the Windows persistent credential store.

- TLS-verified minimal probe: connected, response `pong`.
- Minimal probe calls: 1.
- Phase-log requests: 26 cumulative.
- Earlier wrong-configured-credential requests: 3, all usage limited.
- Selected-key generation requests: 23.
- Selected-key generation prompt characters: 549,621.
- New selected-key fallbacks: 0.

The monitor observed 24 cumulative requests and interrupted the run. Two
already-in-flight requests subsequently entered the log, so the actual
cumulative count is 26. This is evidence that manual polling is not an atomic
request-budget control.

## What CGKN generated

- Foundation: completed; two unique checkpoints (`pyproject.toml` and
  `requirements.txt`).
- Backend graph: eighteen planned leaves.
- Backend: ten unique checkpoint files saved before stop.
- All ten saved Backend Python files pass AST syntax parsing.
- Domain contracts include `SourceManifest`, `ParserProof`, `NormalizedDemo`,
  and `InformationState`.
- Candidate directory: absent.
- Generated tests and real-Demo execution: not run.
- Packaging and delivery: not invoked.

## Decisive quality findings

1. `backend/demo_parser.py` never imports `demoparser2`; it decodes binary Demo
   bytes as UTF-8 JSON. It cannot parse a genuine CS2 Demo.
2. `load_catalog` returns a list, while acquisition requires a mapping and the
   parser calls `.values()`. These interfaces cannot execute together.
3. Required HTTP acquisition is explicitly disabled in the acquisition leaf.
4. `target_known` is inferred from the mere presence of positions and view
   angles; `line_of_sight_known` is inferred from the first position. This
   violates the unknown-information rule.
5. Alignment is computed from one absolute position relative to map origin,
   rather than a subject-to-target vector.
6. Four generic `stages_part` modules and an eighteen-leaf Backend graph remain,
   despite the compact-ownership guidance.

The result is more domain-shaped than the earlier unrelated/generic failures,
but it is not a usable CS2 anomaly detector. More generation should not resume
until deterministic goal-fidelity and atomic request-budget gates reject these
failure classes before downstream work.

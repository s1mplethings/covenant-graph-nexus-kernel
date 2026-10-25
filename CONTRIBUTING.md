# Contributing to CGKN

CGKN accepts changes that preserve the authority boundaries in
`PRODUCT_GOAL.md`, `MVP_SCOPE.md`, and `governance/product_invariants.json`.

## Development workflow

1. Create a topic branch with the `codex/` prefix when working through Codex.
2. Keep changes bounded and add tests for changed behavior.
3. Run `python scripts/product_direction_gate.py` after architecture changes.
4. Run targeted tests while developing and the documented release regression
   before publication.
5. Publish repository changes only through
   `python scripts/canonical_repo_publish.py` with an explicit change manifest
   and a current test receipt. Never force push routine changes.

## Licensing and provenance

Contributions are submitted under the Apache License 2.0 unless explicitly
marked otherwise. Do not copy code, benchmark data, model assets, fonts, media,
or fixtures without recording their origin and compatible license. An API,
MCP, or CLI bridge to separately licensed software does not relicense that
software.

Postiz remains an independent AGPL-3.0 service boundary. Do not copy Postiz
implementation code into this repository.

Do not commit credentials, private paths, private repository data, hidden test
answers, or benchmark material whose license forbids redistribution.

## Review expectations

Changes should explain their hypothesis, evidence, regressions, complexity
cost, and effect on public contracts. Experimental results must remain
separate from production authority and negative results must be retained.

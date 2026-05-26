# CovenantGraph Nexus Kernel

CovenantGraph Nexus Kernel (CGNK) is a contract-first graph compiler kernel for modular agentic project generation.

CGNK defines and validates machine-readable contracts for artifacts, modules, flows, policies, predicates, graph edit proposals, migration specs, compile results, contract packs, and compiled contract bundles. The core does not execute project generation directly. It compiles project-generation workflows into verified contract bundles that coding agents and downstream runtimes can consume.

CTCP is an optional migration source: old CTCP docs, configs, examples, behavior, and tests may inform migration adapters, but CGNK does not inherit CTCP runtime code. In particular, this repository must not copy the old orchestrator, support bot, progress fallback, Telegram path, generated output tree, database, or delivery artifacts.

All graph changes must go through `GraphEditProposal`. Coding agents must not directly edit a `FlowSpec` main graph; they submit proposals, preview them, compile the preview, and inspect diagnostics.

## Phase 0

This repository starts from the provided CGNK design bundle as the only design baseline. Phase 0 keeps the reference semantic checker dependency-light while moving reusable validation logic into `src/cgnk_core`.

Run:

```bash
python scripts/validate_bundle.py
python scripts/validate_bundle.py --schema
python -m unittest discover -v
```

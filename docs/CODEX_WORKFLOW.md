# Codex Workflow

Agents must work contract-first.

1. Validate schemas.
2. Compile the target flow.
3. Submit graph changes as `GraphEditProposal`.
4. Preview and compile the cloned flow.
5. Use diagnostics to repair contracts.
6. Run tests before moving to the next phase.

Agents must not directly edit FlowSpec main graphs, weaken schemas, copy CTCP runtime code, or commit generated outputs.

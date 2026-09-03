# ITER-023 Runtime Evidence

## Outcome

`PASS_WITH_LIMITS`. The Codex capability-supervisor support layer completed an offline replay of the preserved FocusForge generation failure. It did not call an external API, edit a sealed generated candidate, package, or claim delivery readiness.

## Audited handoff

- Librarian input: `ITER-023_LIBRARIAN_CONTEXT.json`, four selected items from 61 available/relevant run artifacts and 57 recorded exclusions.
- Failure evidence: the real Provider phase log and canonical `NEEDS_REWORK` delivery manifest.
- Bounded request: `ITER-023_CODEX_REQUEST.json`, 5,439 bytes.
- Sealed Codex response: `ITER-023_CODEX_RESPONSE.json`, 5,053 bytes.
- Validated support brief: `ITER-023_CODEX_CAPABILITY_BRIEF.json`, 4,273 bytes.
- Shared communication: `ITER-023_AGENT_SESSION.jsonl` records request, response, and brief events; `ITER-023_WHITEBOARD_PATCH.json` contains only bounded advisory support state.
- All three request/response/brief schemas validated with JSON Schema Draft 2020-12 and format checking.

The brief diagnosed the mismatch between explicit CRUD behavior and the generic import/export stage skeleton, the string-versus-callable CLI contradiction, and the 19-test-leaf/70-test-request amplification. It proposed deterministic domain-interface coverage, dependency-ordered generation, proportional manifest and request budgets, and executable CLI acceptance checks.

## Verification

- `python .../quick_validate.py skills/supervise-cgkn-capabilities` -> skill valid.
- `python .../manage_project.py validate --path project_management/cgkn/project_management.json` -> `PASS`.
- `python .../manage_project.py validate --path project_management/cgkn/iterations/ITER-023.json --project-pack project_management/cgkn/project_management.json` -> `PASS` before closure; final validation repeated after closure.
- `python .../manage_project.py validate --path project_management/enterprise_experience.json` -> `PASS`.
- Targeted supervisor, agent pipeline, kernel, rule-guard, management, and formal Provider suite -> `258 passed, 8 skipped`.
- Complexity, goal-driven plan, and Provider post-build finalization suite -> `20 passed, 9 skipped`.
- The direct-script subprocess regression proves `prepare` writes both a valid request and an `agent_session` event.

## Authority and limitations

- Codex conversation default generation remains the reviewed Provider route.
- Provider validation, post-build finalization, canonical evidence, `local_packager`, `public_delivery_gate`, and `delivery_manifest.json` remain unchanged authorities.
- An absent external Codex handoff fails explicitly; Provider and local models cannot impersonate the Codex supervisor.
- This increment does not automatically launch a new Codex task in the background. A future plugin or SDK adapter may automate that invocation while retaining this file and `agent_session` contract.
- No live Provider generation was rerun, so reduced Provider request/token usage is a future measured experiment rather than a current claim.

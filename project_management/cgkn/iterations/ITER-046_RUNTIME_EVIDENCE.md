# ITER-046 Runtime Evidence

Evidence status: `PASS`

## Scope accepted

- Added `docs/14_codex_cgkn_runtime_supervision_baseline.md` as the normative architecture baseline.
- The baseline makes CGKN the independently running system, Telegram Bot and Mini App CGKN-owned interfaces, and Codex the startup/attachment and persistent checkpoint supervisor.
- It defines startup and attachment, persisted supervisor/thread/process/checkpoint identity, mandatory checkpoints, allowed actions, bounded `repair_cgkn`, recovery behavior, customer flow, formal-route preservation, and implementation-conformance evidence.
- It explicitly rejects a fresh one-shot Codex process per Telegram message as the target architecture.
- It labels the current ephemeral read-only design adapter as a valid bounded specialist/transitional path, not the persistent supervisor.

## Authority preservation

- Codex may repair CGKN-owned source, configuration, documentation, and tests only within a diagnosed bounded change followed by proportionate regression.
- Provider remains the sealed generated-candidate author.
- Workflow/support state cannot authorize formal evidence.
- Whiteboard plus `agent_session` remain shared communication state.
- Provider validation, post-build finalization, canonical evidence, user review, `local_packager`, `public_delivery_gate`, delivery receipt, and canonical final verdict remain unchanged.

## Registration and enforcement

- `AGENTS.md` requires future agents to follow the baseline.
- `README.md` points operators to the baseline.
- `docs/00_kernel_contract.md` binds the runtime ownership and migration boundary into the kernel contract.
- `docs/01_contract_registry.md` registers the baseline and separates supervisor workflow state from formal evidence.
- `tests/test_document_contract_consistency.py` treats the baseline as a formal document.
- `tests/test_kernel_contract.py` guards ownership direction, persistent-thread supervision, repair authority, prohibited inversion, `NOT_EVALUATED` runtime posture, and the unchanged Provider/packager route.

## Verification

- JSON syntax validation passed for the management pack and ITER-046.
- The deterministic management helper validated the management pack: `PASS`, zero errors.
- The deterministic management helper validated ITER-046 against the management pack: `PASS`, zero errors.
- Documentation consistency, kernel contract, and adaptive project-management regression: `39 passed, 1 warning` in `7.44s`.
- The warning is the existing `jsonschema.RefResolver` deprecation warning; there were no test failures.

## Evidence boundary

- `PASS` applies to creating, registering, and guarding the architecture baseline requested by the user.
- The persistent supervisor host, same-thread runtime resume, checkpoint emitter, automatic bounded repair, restart behavior, and live Telegram supervision are not implemented by this documentation increment and remain `NOT_EVALUATED` until the baseline's conformance evidence exists.

# ITER-048 Runtime Evidence

## Scope

Separated CGKN runtime operation into two mutually exclusive public profiles:

- `API-only`: no Codex design invocation and no persistent runtime supervision.
- `Codex-supervised`: one persistent, identity-bound Codex supervisor thread; the historical one-shot Codex design CLI is forced off.

Both profiles retain the same reviewed API/Provider generation, canonical evidence, `local_packager`, public delivery gate, and delivery-manifest route. Sessions, logs, uploads, project memory, Provider candidate roots, and supervisor state use profile-specific directories.

## Verification

- Python compilation and both CLI help surfaces: PASS.
- PowerShell parser validation for both launchers: PASS.
- `scripts/kernel_contract_check.py`: PASS, including four runtime-profile isolation guards.
- Project-management pack and `ITER-048` deterministic validation: PASS.
- Direct API-only design probe: reached `awaiting_user_confirmation`, recorded `codex_used=false`, and created no Codex artifact.
- Persistent supervisor argv probe: forced `--codex-design-mode disabled` and a dedicated Provider-project root.
- Targeted kernel, runtime-supervisor, Telegram-design, customer-bridge, document-consistency, and dynamic-tree regression: 53 passed, 44 skipped.
- Formal generation, final acceptance, agent conversation, backend dialogue, Telegram generation E2E, and production-candidate provenance regression: 90 passed, 4 skipped.

## Review limits

No live Telegram token, Provider generation, public delivery, or long-running production daemon was exercised in this cleanup. Those remain separately evaluated runtime and delivery concerns; this iteration evidence is support evidence and does not authorize formal delivery PASS.

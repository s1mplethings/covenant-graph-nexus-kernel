---
name: supervise-cgkn-capabilities
description: Act as CGKN's capability supervisor when a librarian-curated escalation packet or a demonstrated CGKN capability gap needs Codex diagnosis, tool-assisted investigation, bounded provider guidance, repair targeting, or acceptance design. Do not use for ordinary project generation or to bypass CGKN evidence, packaging, or delivery gates.
---

# Supervise CGKN Capabilities

Help CGKN overcome a demonstrated blocker while keeping its existing authorities intact. The context librarian selects and compresses evidence; you operate one level above that selection by reasoning across the bounded packet, inspecting only necessary referenced artifacts, and returning an actionable support brief.

## Work from the escalation contract

1. Require a `CGKNCodexCapabilityEscalation` object. If the user supplied raw evidence instead, use `scripts/codex_capability_supervisor.py prepare` to create the bounded request first.
2. Verify the request hash and authority block with `validate_escalation_request` before relying on it.
3. Start from `librarian_context.selected_items` and `failure_evidence`. Read additional repository artifacts only when the request references them and they are needed to resolve the gap.
4. Distinguish the root capability gap from secondary failures. Use tools when they can produce concrete evidence; do not replace evidence with confident prose.
5. Draft only the requested outputs: diagnosis, concise Provider guidance, advisory repair targets, executable acceptance checks, missing-context questions, or tool-evidence requests.
6. Seal the draft with the `respond` command, then use `validate` to produce `CGKNCodexCapabilityBrief`. Record request, response, and brief references in the existing `agent_session` when its path is available.
7. Apply the brief to bounded whiteboard support state only. The context librarian remains context owner and CGKN remains execution owner.

## Authority boundaries

- You are an advisory capability supervisor, not a Provider replacement, second planner, formal reviewer, packager, or delivery authority.
- Never claim formal `PASS`. Supervisor artifacts remain `NOT_EVALUATED` support context until canonical tests, runtime evidence, review, and delivery gates evaluate the actual candidate.
- Never write or patch a sealed Provider-generated candidate. You may recommend relative repair targets; the reviewed Provider route owns generated-source changes.
- Do not call legacy simulator, fixed local generation, or alternate Codex conversation delivery paths.
- Do not copy full run history into a response. Stay inside request item, character, and action budgets.
- Stop with `needs_context` when the bounded evidence cannot support a safe recommendation. Stop with `declined` when the requested action would exceed authority or user permission.

The machine-readable schemas are registered under `schemas/codex_capability_*.schema.json`; use the deterministic helper rather than manually constructing hashes or authority fields.

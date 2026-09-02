# ITER-027 Runtime Evidence

Date: 2026-08-20

Outcome: `NEEDS_REWORK`

The reviewed Provider route consumed the sealed advisory brief `codex-escalation-1e9dd879e07ab793` with brief SHA-256 `31a116fd8ee658daa56429cb29630aa832d480f16612d5b277bccd306a98aa48`. The full brief was retained under each run and the bounded projection was carried into split-file Provider prompts. No Agent-authored generated source, alternate materializer, package shortcut, or delivery claim was used.

Implemented CGKN changes include fail-closed brief validation and resume identity binding, bounded split-leaf Agent guidance, explicit local record CLI requirement derivation, direct `backend/` planning and Provider path alignment, a fixed repository -> service -> CLI -> root-entry dependency and public-symbol contract, bounded librarian context, exact repair-target enforcement, and Python execution-safety checks for runtime annotation shadowing in generation and post-build repair.

Formal child-project runs were retained under `artifacts/agent_helped_notes_20260820/`. The best run is `run_v4`, with candidate `generated/agent_helped_notes_v4_20260820_candidate`. The complexity project contract passed and all seven canonical goal-test symbols were present, but the final real pytest run stopped during collection after Provider post-build repair introduced a repository annotation-shadowing error. Earlier V4 evidence reached one passing test and six failures before that repair; the remaining failures were concrete repository path handling, CLI/test signature, returned-ID shape, and corrupt-storage expectation mismatches.

The configured API endpoint returned HTTP 403 `Key usage limit exceeded`, so it could not take over from the local model. The local `qwen2.5-coder:7b` model materially improved after the Agent guidance and compact contracts, but repeated multi-file repair still regressed previously valid code. Therefore there is no final project bundle or delivery manifest, and the candidate must not be represented as usable or delivered.

Verification evidence:

- 72 relevant goal-planning, capability-supervisor, complexity, and kernel tests passed after the main integration changes.
- 42 focused direct-CLI, capability, and kernel tests passed after ownership and annotation-safety changes.
- The final consolidated regression profile passed all 255 selected CGKN tests; management validation and Python syntax checks also passed.
- New focused exact repair-target and annotation-shadowing tests passed.
- A fresh direct pytest replay of the V4 candidate reproduced two collection errors at `NoteRepository.search`: the earlier `list` method shadows Python's built-in `list`, so `list[Note]` is evaluated against a function. Formal verdict remains `NEEDS_REWORK`.

Recommended next increment: run the preserved contract against a working reviewed API/provider or a stronger local code model, and add cross-interface executable contract probes before post-build repair can rewrite a previously valid leaf.

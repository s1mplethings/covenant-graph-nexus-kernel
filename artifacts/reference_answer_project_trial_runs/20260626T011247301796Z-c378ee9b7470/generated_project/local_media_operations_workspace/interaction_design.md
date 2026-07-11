# Interaction Design

Planning materialization status: deterministic_contract_planning, not implementation evidence.

## Target User
Creators or operators who need repeatable local media processing.

## Primary User Journey
The user starts with a selected requirement, reviews the MVP scope, launches the same pipeline through GUI or CLI, watches stage progress, checks artifact evidence, and only treats the result as delivery-ready after strict delivery evidence exists.

## Required Pages/Views
- Import/source selection view
- Pipeline progress view
- Artifact/evidence review view
- Degraded mode and blocker view
- Export/readiness view

## Key Interactions
- Start or resume the shared pipeline through GUI or CLI.
- Inspect stage status, counts, input paths, output paths, and upstream artifacts.
- See blockers when provider, model, or media tooling is unavailable.
- Review known gaps before final delivery is attempted.

## GUI/CLI Relationship
GUI and CLI are two control surfaces over the same orchestrator.py and stages.py. Neither surface may contain a separate implementation path. Both must expose the same pipeline state and artifact locations.

## Pipeline Progress Visibility
Every stage should show stage name, status, count, input_path, output_path, created_at, and upstream_artifacts. Progress visibility is part of implementation acceptance, not delivery completion.

## Degraded/Blocker Visibility
Degraded mode must be visible as an honest status. Missing model access, missing ffmpeg, unavailable input files, or provider failure must block fake PASS claims and remain visible in user-facing status.

## References
- selected_requirement.json
- mvp_scope.md
- non_goals.md

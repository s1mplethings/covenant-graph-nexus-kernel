# Technical Plan

Planning materialization status: deterministic_contract_planning, not implementation evidence.

## Architecture Overview
The implementation should be local-first and contract-driven. Product planning artifacts are created from selected_requirement.json, acceptance_contract.json, and complexity_project_contract.json before implementation. Runtime code must later use one orchestrator and one stages module shared by GUI and CLI.

## Required Modules
- orchestrator.py as the single workflow coordinator
- stages.py as the shared implementation stage library
- CLI entrypoint calling the shared orchestrator
- GUI entrypoint calling the shared orchestrator
- artifact validators for stage outputs and traceability

## Data/Artifact Flow
Inputs move from customer goal and selected_requirement.json into product planning docs, then into implementation artifacts. Stage artifacts must flow downstream with upstream_artifacts references so later files can prove where their inputs came from.

Required stage artifacts:
- stage_plan.json
- media_manifest.json
- audio_chunk_manifest.json
- transcript_merged.json
- segment_analysis.json
- selected_segments.json
- clip_manifest.json
- export_results.json

## Pipeline Stages
- ingest_video
- extract_audio
- chunk_audio
- transcribe_audio
- analyze_segments
- select_segments
- render_clips
- export_results

## Local-First/Degraded Mode Strategy
When ffmpeg, provider models, or media dependencies are unavailable, the implementation must expose honest degraded mode. Degraded mode can write blockers and partial artifacts, but it must not claim real processing success, screenshot evidence, or final delivery completion.

## Implementation Risks
- Provider output may omit required modules or stage artifacts.
- GUI and CLI can drift if they do not share the same orchestrator and stages.
- External media tooling or model access may be unavailable and must be represented as honest degraded mode.
- Delivery evidence remains separate from product planning evidence.

## Verification Strategy
- requirement_decision, product_contract, implementation, and delivery statuses must be evaluated independently.
- Product planning can PASS while implementation remains FAIL.
- Implementation can PASS only after required structure and artifact schemas exist.
- Delivery can PASS only with final bundle, screenshot, run_dir, README, TEST_REPORT, and DELIVERY_NOTES.

## References
- acceptance_contract.json
- complexity_project_contract.json
- selected_requirement.json

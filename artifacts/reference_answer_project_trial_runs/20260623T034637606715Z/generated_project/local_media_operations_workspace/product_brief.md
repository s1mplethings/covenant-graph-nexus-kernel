# Product Brief

Planning materialization status: deterministic_contract_planning, not implementation evidence.

## Selected Requirement
- id: local_video_material_workbench_requirement
- name: Local video material processing workbench
- source: selected_requirement.json

## Interpreted Customer Need
A local-first workbench for ingesting video, extracting or simulating audio, chunking/transcribing, analyzing segments, selecting clips, and exporting reviewable artifacts.

## Target User
Creators or operators who need repeatable local media processing.

## Core Problem
The customer needs the broad request converted into a bounded product contract before implementation starts. The core problem is to preserve Requirement Decision First while preventing planning gaps from becoming fake implementation or delivery PASS results.

## Selected Product Shape
local_video_workbench

## MVP Scope
Source: mvp_scope.md

# MVP Scope

## Must Do This Round
- Local media import
- Pipeline run view
- Segment review
- Clip selection

## Should Do This Round
- Artifact export
- Honest degraded mode

## Not This Round
- Cloud rendering farm
- Guaranteed real speech recognition without configured model
- Public media publishing

## Later Versions
- Customer-specific integrations after the first requirement is validated.
- Larger automation or cloud workflows after credentials and acceptance evidence are agreed.

## Scope Rationale
This scope preserves the selected requirement while keeping the first version testable and deliverable.

## Non-Goals
Source: non_goals.md

# Non-Goals

## Cloud rendering farm

- Reason: outside the selected MVP or too risky for first delivery.
- Risk if forced now: larger dependency surface, weaker testing, and higher fake-pass risk.

## Guaranteed real speech recognition without configured model

- Reason: outside the selected MVP or too risky for first delivery.
- Risk if forced now: larger dependency surface, weaker testing, and higher fake-pass risk.

## Public media publishing

- Reason: outside the selected MVP or too risky for first delivery.
- Risk if forced now: larger dependency surface, weaker testing, and higher fake-pass risk.

## Success Definition
- The selected requirement is traceable to product scope, planning artifacts, implementation evidence, and delivery gates.

## Assumptions
- Provider output may be unavailable, so deterministic product planning can be used without claiming implementation completion.
- Planning artifacts are contractual evidence only; they are not code, screenshot, or final delivery evidence.

## References
- selected_requirement.json
- acceptance_contract.json
- mvp_scope.md
- non_goals.md

# Universal Capability Strategy Contract

This document defines the project-intake rule for every CGNK generation run. It is intentionally not tied to a project type, industry, media kind, or domain.

## Non-Negotiable Rule

CGNK must plan from underlying capabilities, not from project-type patches.

A domain label such as game, VN, CRM, image tool, video tool, admin system, chatbot, data dashboard, or automation app may help identify capabilities, but it must never create a special formal generation path.

## Required Intake Steps

For every project request, frontdesk, backend dialogue, CFO planning, and support agents must:

1. Identify the core capabilities that determine whether the project is actually useful.
2. Mark capabilities as critical when they affect acceptance, cost, privacy, runtime feasibility, user-visible quality, delivery evidence, or architecture.
3. For each critical capability, look for mature or high-quality methods before accepting a basic fallback.
4. Record advanced-method candidates in `capability_research_targets`.
5. Record obvious user-visible route differences in `critical_questions`.
6. Record fallback limits in `acceptance_criteria` so a fallback cannot be reported as satisfying the original capability.

## Capability Categories

The capability categories are universal and may combine freely:

- Content generation: text, code, image, video, audio, report, design, or other generated output.
- Model/service integration: local model, hosted model, external API, self-hosted service, credentialed provider, or offline engine.
- Structured workflow or relation modeling: timeline, graph, state machine, dependency map, approval flow, scenario tree, or task lifecycle.
- Data persistence: database, file store, cache, search index, history, audit log, or sync boundary.
- Runtime interaction: local web app, desktop app, CLI, Codex conversation interaction, browser automation, or mobile-facing UI.
- Evidence and verification: screenshot, generated artifact, video, test report, benchmark, sample dataset, replay, or acceptance manifest.
- Automation and execution: scheduler, scraper, browser driver, media processor, command runner, workflow engine, or background worker.
- Security and control: permissions, sandbox, credential handling, user data boundary, moderation, or destructive-action approval.
- Import/export and interoperability: file formats, archives, APIs, webhooks, document conversion, or schema compatibility.

This list is not a closed taxonomy. New capabilities may be added, but they must be expressed as capability categories rather than project-type branches.

## Advanced-Method Requirement

For each critical capability, the system must prefer a mature method when one exists:

- Proven library, framework, engine, model, or API.
- Configurable local or hosted backend with a capability probe.
- Structured data model instead of ad hoc strings.
- Runtime evidence instead of claims.
- Real artifact generation instead of placeholders.
- Explicit fallback with user-visible limits when the mature method is unavailable.

If no mature method is available, the agent must document why and make the fallback status visible.

## Critical Questions

Ask a critical question when the difference would materially change the product:

- Local/self-hosted capability versus external hosted API.
- Model, provider, engine, or library choice when quality or cost changes.
- Database versus file-based storage.
- Web UI versus desktop UI versus chat-only interaction.
- Real-time processing versus batch processing.
- Fully automated execution versus human confirmation.
- Linear flow versus graph/state-machine/branching structure.
- Strict acceptance output versus fallback preview.

These questions do not hard-gate the manifest/runner flow. They guide planning and acceptance. The system may continue building configuration, interfaces, tests, and fallback previews, but it must not mark the unresolved capability as satisfied.

## Prohibited Pattern

Do not add project-type-specific rules such as “if this is a VN project, do X” as kernel behavior.

Allowed: “This request needs content generation, structured workflow modeling, persistence, and runtime evidence; here are the best methods and decisions.”

Rejected: “This request is project type X, therefore use a special hardcoded flow for X.”

## Acceptance Rule

Delivery readiness must be judged against the requested capabilities. A fallback can be delivered as a warning or partial result, but it cannot be described as satisfying a mature method, configured model, external API, local service, automation engine, or runtime evidence requirement that was not actually met.

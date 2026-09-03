# ITER-020 Runtime Evidence

## Review outcome

`accepted_with_limits` / `PASS_WITH_LIMITS` for the CGKN mainline increment.

The generated CS2 candidate remains `NEEDS_REWORK`. This iteration does not claim a generated-project PASS, delivery readiness, or detection accuracy.

## Deterministic CGKN evidence

- Changed Python modules compiled successfully with `python -m py_compile`.
- Goal, discovery, complexity, interface, kernel, and project-management regression profile: `148 passed`.
- Complete formal Provider fallback/mainline profile: `179 passed`.
- Explicit marked checkpoint, manifest ownership, and post-build owner-repair profile: `7 passed`.
- The default slow test module profile reported `140 skipped`; the seven applicable marked cases were then executed explicitly and passed.
- New focused negative cases prove:
  - CLI plus JSON/HTML report goals do not gain an unrequested GUI.
  - code symbols and documentation/config anchors are type-specific;
  - stage result envelopes, annotated helper parameter method calls, property-vs-method use, and merged pytest fixtures are checked before component PASS;
  - component checkpoint reuse binds current required paths, runtime dependencies, capabilities, and executable-interface identity;
  - semantic review cannot promote excerpt truncation, missing visibility, cross-owner findings, or reducer invention into a hard blocker;
  - post-build pytest disables unrelated host plugin autoload;
  - Python traceback repair selects imported implementation owners and dependent tests as one bounded atomic repair set.

## Formal CS2 Provider probe

- Result: `NEEDS_REWORK`.
- Reason: `semantic_review_needs_rework_candidate_materialized`.
- Provider state: `candidate_materialized`.
- Semantic review state: `needs_rework`.
- Post-build state: `needs_rework`.
- `final_delivery_allowed`: `false`.
- Candidate: `D:\CGKN\generated\cs2_demo_anomaly_lab_formal_20260814_v3_candidate`.
- Result evidence: `D:\CGKN\artifacts\cs2_demo_anomaly_lab_formal_20260814\provider_result_v3_resume7.json`.
- No `delivery_manifest.json` or final project bundle was created.

The saved semantic review contained hard claims derived from truncated review excerpts and an out-of-scope Foundation summary. The mainline now downgrades those statements to review warnings while preserving deterministic runtime authority.

The original post-build pytest did not reach project collection because the host Python installation auto-loaded a broken global `pytest-qt`/Qt runtime. With plugin autoload isolated, the same candidate executed and reported `16 passed, 29 failed, 4 errors, 4 skipped`. Representative real failures included incompatible `ArtifactStore` method calls, calling `base_dir` as both property and method, missing `artifact_store` fixtures, CLI/report behavior contradictions, and test/implementation data-shape mismatches. The candidate therefore correctly remains non-PASS.

Revalidating the saved tests component with the new component gate rejected it before checkpoint PASS with six deterministic blockers: two imported `ArtifactStore` call-signature mismatches and four undefined pytest-fixture findings. This is prevention evidence, not a repair or delivery claim.

## Model and delivery truth

- The formal run contains recorded API Provider execution and bounded local-model fallback participation in its model ledger.
- No new API resume was started during final review because the current process had no Provider credential environment variable. No credential was written to source, command history, or project evidence.
- The reviewed API/provider route remains the only Codex conversation default generation route.
- `local_packager` remains the only delivery exit.
- Detection accuracy remains `NOT_EVALUATED`; an unlabeled public demo can prove pipeline execution only, not cheating or classifier accuracy.

## Retrospective

Worked: deriving negative contracts from an actual candidate moved goal drift, interface mismatch, fixture absence, stale checkpoint reuse, and host plugin pollution before expensive final execution.

Did not work: model semantic review treated bounded excerpts as complete source and the initial post-build test inherited unrelated host pytest plugins.

Experiment: re-run current deterministic component validation against the saved formal candidate. It identified actionable test-component blockers without another Provider call and without modifying the candidate.

# ITER-043 Runtime Evidence

## Scope

Implemented the feature-unit projection inside the existing reviewed Provider route. One explicit typed operation now freezes one public interface, one owned source leaf, its thin adapters, exact tests, and conflict-free dependency-ready batches without inventing persistence, services, repositories, frameworks, GUI, or generic workflows.

## Prevention and assurance

- Registered `CGKNFeatureContract`, `CGKNFeatureInterfaceFreeze`, and `CGKNFeatureUnitSemanticReviewRequest` in the formal registry.
- Updated the kernel contract and contract guards in the same change.
- Preserved Provider authorship, existing output validation, post-build finalization, `local_packager`, public delivery gate, and delivery manifest boundaries.
- Bound the same frozen feature validator to API-authored leaves before semantic review and write; undeclared public functions, signatures, errors, side effects, and invented CLI module paths are rejected.
- Limited project-local output cleaning to the exact resolved `.cgkn/agent-kit/generated-project` suffix.
- Skipped external input, market, and visual research for already-frozen nonvisual feature units while retaining small `not_applicable` audit manifests.

## Fresh reviewed Provider acceptance

Workspace: `workspaces/qwen-feature-unit-acceptance-20260830-04`

- Model: `qwen3.8-max` through the reviewed Provider route.
- Result: generation `pass`; workflow state `generation_completed`; formal evidence `NOT_EVALUATED`.
- Exact planned deliverables: 9/9; no frontend, persistence, service, repository, framework, or generic workflow files.
- API leaf boundary: one invalid `normalize_title.py` attempt was rejected for an undeclared error and the backend leaf alone was repaired.
- Provider transport failures: 0.
- Feature semantic review: `pass`; prompt 9,990 characters; output ceiling 1,800 tokens; reasoning effort `none`.
- Supported generated-project profile: `python -m pytest -q`; 5 passed in 0.19 seconds.
- Final source exposes only `normalize_title(value: str) -> str`, the package adapter, and the requested CLI behavior.
- No delivery manifest was requested or produced by the Agent Kit generation/test workflow; formal delivery remains `NOT_EVALUATED`.

## Regression evidence

- Relevant broad suite: 417 passed, 167 skipped in 21.74 seconds.
- Full repository suite: 1,423 passed, 395 skipped, 5 warnings in 666.98 seconds.

## Review

The smallest useful vertical increment is complete: short typed requests remain small, exact, independently repairable, and compatible with multiple conflict-free feature leaves. The live rejection-and-repair event demonstrates that interface freeze is enforced on the real API path rather than trusted to semantic self-review.

# Pipeline Module Agent Guide

## A. General Principles

`run_local_pipeline.py` is orchestration only.

run_local_pipeline.py is orchestration only; module logic belongs in bounded modules.

Do not put provider, repair, screenshot, video, package, or delivery truth logic back into `run_local_pipeline.py`.

All project changes are direct modification, generation, or deletion of bounded modules or generated candidate files. That is the underlying mutation model. An agent must identify the responsible module first, then modify only that module and its module-level tests.

When debugging or modifying generation/repair behavior, start from the decomposition tree: `failure -> tree node -> issue ledger -> ProviderJob -> evidence update`. Do not patch generated project files directly. Do not create broad repair jobs without a tree node.

## B. Module Responsibility Table

| Problem Type | Module To Modify | Modules Not To Modify |
| --- | --- | --- |
| provider transport / model routing / split generation | `provider_generation.py` | `final_delivery_truth.py` |
| candidate write / candidate marker / snapshot | `candidate_materializer.py` | `final_delivery_truth.py` |
| fake zip / fake manifest / fake screenshot claim | `candidate_sanitizer.py` or `artifact_integrity.py` | Do not bypass `final_delivery_truth.py` |
| npm test failure / vitest missing / Windows ESM import | `post_build_repair.py` | `run_local_pipeline.py` |
| plan/issue/evidence node mapping or tree evidence update | `decomposition_tree.py`, `issue_ledger.py`, `repair_acceptance.py` | Do not add a scheduler or change the final gate |
| startup failure / npm test / TEST_REPORT / known_limits | `post_build_finalize.py` | `final_delivery_truth.py` |
| screenshot blank / screenshot diagnostics / video blocked | `visual_evidence.py` | `run_local_pipeline.py` |
| ASK_USER_REVIEW candidate send | `candidate_review_delivery.py` | public final delivery gate |
| `final_project_bundle.zip` / `delivery_manifest.json` / public final gate | `final_delivery_truth.py`, only to maintain truth rules | Do not relax it to pass tests |

## C. Replaceable Modules And Truth Layer

Replaceable capability modules:

- `provider_generation`
- `post_build_repair`
- `visual_evidence`
- `candidate_review_delivery`

Truth and ownership modules are not freely replaceable:

- `final_delivery_truth`
- `artifact_integrity`
- path safety
- fake artifact scanner
- `local_packager` ownership
- public final delivery gate

Truth modules can be made stricter or clearer. They must not be weakened so a candidate, fake artifact, or review bundle can pass final delivery.

## D. Required Modification Flow

1. Determine `failure_stage`.
2. Route to the matching module.
3. Check `pipeline_contracts.py` for the input/output contract.
4. Map any repairable failure to one existing `project_decomposition_tree.json` node and exact ProviderJob; an unmapped failure is not a generic component-repair license.
5. Modify only the target module and directly related tests.
6. Add or update module-level tests.
7. Run the smallest pytest filter that covers the changed behavior.
8. Run the full focused pytest filter for pipeline, candidate, repair, visual, delivery, and kernel contracts.
9. Confirm `final_project_bundle.zip`, `delivery_manifest.json`, and `PASS_FINAL` were not faked.

## E. Prohibited Actions

- Do not treat `candidate_diagnostic_bundle.zip` as `final_project_bundle.zip`.
- Do not allow provider output to generate `final_project_bundle.zip`.
- Do not allow provider output to generate `delivery_manifest.json`.
- Do not fake screenshot or video evidence.
- Do not let `TEST_REPORT.md` claim tests that were not actually run.
- Do not let a candidate write `delivered`, `final_delivered`, or `PASS_FINAL`.
- Do not lower `final_delivery_truth.py` rules to make final delivery pass.
- Do not extract a review bundle over a runnable `candidate_project_dir` during normal generation.

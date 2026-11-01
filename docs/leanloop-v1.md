# LeanLoop V1: reviewed feedback and bounded reuse

This branch retains the tested local foundation at commit `0bd7134ade87cb6ece13f8f7868860cd2c3ba67c`, including earlier uncommitted runtime, Provider and acceptance corrections. It is not a replacement snapshot for the newer `main`; integration must preserve newer mainline features. Product readiness remains `PRODUCT_NOT_READY`.

LeanLoop observes existing Agent, DAG, artifact and formal Provider boundaries. Reports are derived artifacts. The existing Planner, DAGRunner, FileRunStore, ArtifactCache, Gateway budget and independent Oracle remain authoritative. Default is `OBSERVE`; `CGKN_LEAN_MODE=OFF` disables optional analysis while retaining a minimal report. No production Run launches an ablation or paid model call.

Explicit, source/environment/task-bound `AUTO_QUALIFIED` policies can reuse audited input-only deterministic Component results. Loaded code, source, contracts, environment, receipt, expiry and producer lineage must match. A native cache hit alone is not fresh execution proof. Necessary Oracle, budget, UNKNOWN, permission, delivery, evidence and recovery work cannot be cut. The prior CSV qualification executed the actual function twice versus once with the original Oracle; its measured whole-task cost increased, so no global AUTO rollout is recommended.

## Selfcheck subtraction

A report now performs one final JSON commit instead of two. Markdown or policy-revocation errors cannot suppress that final JSON attempt or repeat the original business call. Analysis and Markdown time are measured; final JSON persistence is explicitly excluded from self timing.

A two-node OBSERVE run now computes source identity twice instead of four times. The separate eligibility-time recheck remains in place, and the existing `artifact_identity` call signature remains compatible. Two redundant policy comparisons and redundant initial metric assignments were removed. No new scheduler, cache or state authority was introduced. This is a small reduction of repeated work, not evidence of broad architectural convergence or a new speedup claim.

The publishing classifier recognizes explicit root dependency declarations and the existing management summary. Python keyword attribute references are distinguished from literal credentials using AST nodes; quoted literals, secret files and unknown paths remain blocked. Local fixture tokens use explicit test prefixes.

## Verification and limits

The immediately preceding full regression was 3475 passed, 29 failed, 14 errors and 350 skipped, with 68 added tests and no new failure, missing test or skip against its fresh baseline. These are historical current-foundation results, not a claim that this repository is green. The watchdog root cause remains unresolved.

Current scoped publication verification covers LeanLoop, Markdown/revocation faults, UNKNOWN exactly-once behavior, artifact/DAG/project-loop boundaries, local domestic Gateway fixtures and the canonical publisher. `evidence/leanloop-v1/selfcheck.json` records real before/after operation counts, output hashes and unchanged independent Oracle outcomes. Publication additionally requires the canonical source-bound TestReceipt, version gate, exact staging set and fetched remote SHA verification. Runtime logs, local policy files and multi-gigabyte scratch fixtures are not publication inputs.

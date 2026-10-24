# CGKN current project management

Current project management follows `PRODUCT_GOAL.md`, `MVP_SCOPE.md`, `governance/product_invariants.json`, and `governance/current_architecture.json`.

## Current status

`ITER-CGNK-STRONG-ESCALATION-EVIDENCE-CLOSURE-051` is complete. Product source remains `a14b309ff5fcc9a27dabd2acff824e8919298884`; this iteration added only a bounded benchmark/evidence harness, tests, and evidence records.

The 28-call frozen routing receipt has 27 known usages and one unknown Qwen timeout. Historical recovery failed because the request produced no response headers or provider request ID. The single permitted replacement returned HTTP 502 without usage, so the original semantic result remains in place and both failures remain operational evidence.

## Decision

- `STRONG_ESCALATION_BENEFIT = DIRECTIONAL`
- `ADAPTIVE_DECISION_HIERARCHY_BENEFIT = NEUTRAL`
- Adaptive default: `NOT_YET`
- Strong role separation collapse: `NOT_YET`

D3 preserves D0 reliability, has 100% strong-call precision/recall, and lowers cost/success versus D0 under a shared-unknown proof. It cannot meet the 50% strong-total-token gate: even zero unknown usage yields only 42.32%. It also uses at least 31 more total model tokens per success than D0 and its cost lower bound per success exceeds D2's exact cost.

## Current recommendation

Keep fixed routing for the evaluated workload and retain adaptive routing as a non-default capability. Revisit only with naturally collected production workload composition and provider-side failure billing telemetry. Do not spend further calls trying to qualify the already-impossible frozen token gate.

## Management surfaces

- `backlog.json` — active and future MVP work;
- `active_iteration.json` — latest reviewed iteration;
- `strong_escalation_evidence_report.json` — PB-027 machine summary;
- `risks.json` — architecture and migration risks;
- `enterprise_experience.json` — reviewed reusable lessons.

Management records do not authorize functional success, formal evidence, packaging, or delivery.

## Verification

PB-027 targeted tests pass 12/12. Compileall, product direction, kernel architecture, test architecture, and kernel receipt freshness pass. The product full regression remains the source-bound ITER-050 result (`2828 passed`, `357 skipped`, `0 failed`, `0 errors`) because PB-027 did not change production code.

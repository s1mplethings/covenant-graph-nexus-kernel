# ITER-060 Preregistration

Status: DEVELOPMENT SPEC REVISION AFTER PUBLIC/HIDDEN CONTRACT AUDIT  
Title: *CGNK Project Complexity Frontier: When Does Agent Architecture Start to Help?*

## Research questions

The evaluation asks where Direct, flat-state Direct, Minimal CGNK, and Full CGNK first become useful, burdensome, or necessary as actual project complexity increases. Primary outcomes are family success, private acceptance, calls, tokens, cost, latency, rework, repair locality, state errors, context growth, and architecture-only discordance.

No route is presumed best. A negative or neutral Full-CGNK result is valid evidence.

## Frozen design

- 12 development families: four each at LOW, MEDIUM, and HIGH.
- 24 formal holdout families: eight each at LOW, MEDIUM, and HIGH.
- Eight project types, three formal families per type.
- Four baselines per family (`B0`, `B1`, `B2`, `B3`).
- Generated-original Python, standard library only, no project execution network.
- Provider route: API Lab raw-defer at `7c15f2546ec007cc7e601fa62ae4d88b9ba12f80`, requested Provider ID `deepseek`, expected qualified actual model `deepseek-flash`.
- Temperature 0; 6,000 maximum output tokens; 150-second request timeout; 180-second outer deadline.
- At most 20 logical Provider calls per family attempt and two public-repair calls per episode.
- No Provider fallback, no manual intervention, no hidden-failure repair, and no formal Corpus read.
- All development/formal attempts, including failures and aborts, are written to isolated Project Corpus attempts.

## Frozen hashes

- Full family manifest: `sha256:74d370b604bf0085dfb5b4ad0fd4f0dbead6a3c6043249ff973e17130ad3f2c1`
- Development family manifest: `sha256:dcc1ef804ec3a4975607e2e787c2902be8f3a5878ed00efab1af5cf7ef49f7b2`
- Formal family manifest: `sha256:8147e3682f2aec26820ae283bd1bdbc6a81264e38a24108913ffc5ed456cf256`
- Evaluation policy: `sha256:3dd0ae8ad579f267d9f1f935540f2d423721e064ac954980091eded528a67c67`
- System prompt: `sha256:1db387a8cf8341f78b1fc778b368665d41f5dbf5f2ae6750b95433378a1a854d`
- Dynamic FileBundle schema template: `sha256:6f2a0c090b3e817965bfeb588b991250ff76e1768006cb0a3265f0f9d737f16f`

The formal freeze receipt binds these hashes to the final Source Closure and Git tree outside the repository under the local-only evaluation root.

The first four development smoke attempts exposed a public/hidden contract defect: empty numeric input was accepted by the private oracle but not specified publicly. Those negative attempts remain in the local Corpus. Before formal freeze, every operation was updated with explicit semantic and boundary rules; no private example or expected output was disclosed.

## Family and evaluator isolation

Every baseline receives the same family public contract in an independent sandbox. B0/B1/B2/B3 never see sibling output. Public tests and private acceptance share a canonical operation oracle but use distinct examples. The Provider packet omits private cases, private hashes, hidden assertions, hidden outputs, and hidden failure details. Private failure produces only a local opaque hash and is terminal.

Formal holdout families are write-only with respect to the Project Corpus. Corpus search and retrieval are disabled for all four primary conditions.

## Architecture boundaries

B2 is a thin adapter over existing FileRunStore/evidence concepts and does not define a runtime. B3 uses the existing frozen ProjectBlueprint and CapabilityTree-to-ExecutionDAG-to-DAGRunner path. The deterministic family specification is the Agent-owned project decision for this controlled study; no Provider is promoted to canonical planner. Multi-Agent and Architecture Router remain disabled.

## Analysis rules

Analysis is family paired and stratified by raw complexity and project type. Success differences take precedence; cost, calls, tokens, latency, context growth, repair/rework, and state errors break ties. Infrastructure failures are reported separately from task failures. Three-run or small-cell findings are directional and are not called statistically significant.

Allowed verdicts are `PROVEN`, `PROVEN_DIRECTIONALLY`, `NEUTRAL`, `HARMFUL`, `NOT_NEEDED_AT_TESTED_SCALE`, and `INSUFFICIENT_EVIDENCE`.

Development may repair only general harness defects. Once the final Source Closure and formal freeze receipt exist, any prompt, schema, evaluator, spec, budget, baseline, or generation-code change invalidates all formal results.

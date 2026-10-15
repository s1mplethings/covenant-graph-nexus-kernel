# Adaptive Autonomous Validation Integration

## Scope and authority

`scripts/adaptive_autonomous_validation.py` integrates the Pass 1–3 research
lane. It is a support-only validator. It cannot generate or repair a customer
project, grant formal evidence, package, publish, or deliver. Every report uses
formal status `NOT_EVALUATED` and `release_authority: false`.

The integration reuses the existing Pass 3 project adapters, independent
oracles, immutable snapshot copies, Git worktree isolation, raw evidence shape,
and fresh-workspace reproduction. It does not add another CGKN generation or
acceptance path.

## Default flow

1. Read only public goals, usage documents, channels, and operation contracts.
2. Derive the existing deterministic business-boundary plan.
3. Make one model-neutral OpenAI-compatible semantic planning call.
4. Validate every proposed operation against a per-operation JSON Schema before
   queueing it. Unknown or invalid proposals become `unsupported`; they are
   never renamed, auto-mapped, or executed.
5. Execute the real CLI, Python API, and file-state interfaces in an isolated
   workspace.
6. Save full raw observations and create a compact model-facing projection that
   preserves operation id, return code/result, state change, error text,
   artifact references, evidence references, and all independent issues.
7. Run a loss audit between raw and compressed evidence.
8. Permit one follow-up model call only for a goal conflict, unexplained
   anomaly, ambiguous result, or execution-revealed important coverage gap.
9. Reproduce every candidate issue from a clean workspace with the same action
   prefix and count only independently confirmed issues.

The default recommendation is deterministic plus one-shot semantic validation.
Conditional escalation remains disabled unless a study demonstrates an
additional independently reproduced issue.

## Budgets and comparison meaning

The four research arms intentionally have different coverage budgets:

- A: six deterministic operations per project, no model call.
- B: up to six semantic operations and one model call per project.
- C: A plus B, up to twelve discovery operations and one model call.
- D: C plus at most two follow-up operations and one additional model call,
  subject to an observed 20,000-token per-project cap and a conservative
  pre-dispatch estimate.

Because these budgets differ, more findings in C or D are coverage observations,
not proof that the strategy is intrinsically superior. Escalation replays are
reported as actual execution overhead rather than hidden.

## Reproducible command

```powershell
python scripts/adaptive_autonomous_validation.py `
  --repo . `
  --out runs/adaptive-autonomous-validation/integration-20261014-r4 `
  --model qwen3.5-flash `
  --input-price-per-million 0.029 `
  --output-price-per-million 0.287 `
  --pricing-source "Alibaba Cloud Model Studio official pricing, China mainland, qwen3.5-flash, <=128K input, accessed 2026-10-14"
```

Provider credentials are resolved through the existing reviewed connectivity
configuration and are never written to prompts or evidence. A compatible local
model can be selected with `--model` and the existing compatible base URL.

## Integration experiment result

The final auditable run is
`runs/adaptive-autonomous-validation/integration-20261014-r4`.

- A found two reproduced deterministic issues: restart state loss in Knowledge
  Studio and repair-report/persisted-state mismatch in ORBIT-360.
- B found one different reproduced semantic issue: Knowledge Studio reports
  omitted all imported source content.
- C preserved all three findings in one combined run.
- D also found the same three. Its two evidence-gated follow-ups added no new
  reproduced issue, so its nonproductive escalation ratio was 100% and the
  default stays off.
- Two schema-invalid proposals were recorded across B/C; zero invalid operations
  entered execution and zero proposals were auto-mapped.
- All findings reproduced, false-positive rate was zero, compression loss audit
  passed, and the new Task Ledger project completed all four arms without an
  unnecessary escalation.

The result supports continued investment in the reusable contract gate,
compression audit, combined deterministic/one-shot flow, and reproduction
engine. It does not support default multi-round exploration. HTTP and GUI
adapters should be added only for a project whose primary public workflow cannot
be observed through the current CLI/API/file channels; this study provides no
evidence that a generic GUI/HTTP framework should be built now.


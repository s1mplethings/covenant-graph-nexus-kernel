# ITER-106 — Adaptive Autonomous Validation Integration

- Workflow state: completed
- Evidence status: `NOT_EVALUATED`
- Scope: research support only; no formal acceptance or delivery authority

## Increment

Integrated Pass 1–3 isolation, adapters, deterministic oracles, evidence, and
reproduction into one adaptive runner. Added strict operation JSON Schemas,
unsupported-proposal accounting, raw-to-compressed evidence loss audits,
evidence-gated follow-up, per-project model budgets, and a third previously
unused CGKN-generated Task Ledger project.

## Quality result

- 20 focused Pass 1–3 and integration tests passed before the final experiment.
- Final A/B/C/D run: A=2, B=1, C=3, D=3 independently reproduced findings.
- False positives: 0; reproduction: 100% for every arm with findings.
- Invalid proposed operations executed: 0; automatic operation mappings: 0.
- Compression loss of important failure evidence: 0.
- New Task Ledger project ran in all arms and did not trigger D escalation.
- D made two justified follow-up calls but added zero findings; nonproductive
  escalation ratio was 100%, so conditional escalation remains default-off.

## Evidence

- `scripts/adaptive_autonomous_validation.py`
- `schemas/adaptive_autonomous_validation_report_v1.schema.json`
- `tests/test_adaptive_autonomous_validation.py`
- `runs/adaptive-autonomous-validation/integration-20261014-r4/validation_report.json`
- `runs/adaptive-autonomous-validation/integration-20261014-r4/validation_report.md`

## Retrospective

The useful gain came from combining independent test families, not from adding
more model rounds. Contract validation and loss-audited compression are reusable
across projects. The next increment should keep one-shot semantic exploration,
measure more project types, and add a channel adapter only when a real primary
path requires it.

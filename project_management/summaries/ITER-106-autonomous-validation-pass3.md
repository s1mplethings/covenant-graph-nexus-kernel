# ITER-106 bounded increment — autonomous validation Pass 3

This completed research increment supports the still-active PB-084 iteration.
It does not close the larger iteration or alter formal acceptance, packaging,
delivery, or publication state.

## Outcome

- Added a model-neutral Goal-Driven Explorer over allowlisted public project
  operations, without creating a generation or repair route.
- Compared A (one-shot ordinary model plan), C (deterministic boundaries), and
  D (three feedback rounds) on ORBIT-360 and the CGKN-generated Local AI
  Knowledge Studio. No defect was injected.
- Used the same source identity, public materials, adapter permissions,
  six-operation maximum, deterministic oracles, and independent fresh-workspace
  reproduction for every arm.
- D used six real `qwen3.5-flash` calls, 22,989 tokens, and an estimated
  $0.001616. It changed later operations based on real observation IDs in both
  projects.
- D found and reproduced a report-generation problem missed by C: a report
  built from an imported document returned only counts and section names, with
  none of the source material. Ordinary A found the same issue with two calls,
  5,323 tokens, and an estimated $0.000754.
- C found and reproduced two different issues: restart loses knowledge state,
  and ORBIT repair reports a delta inconsistent with persisted state.

## Decision

The model lane is useful as a complementary workflow-hypothesis generator, but
this run does not justify making multi-round D the default. D adapted correctly
and found a C-missed issue, yet did not outperform one-shot A and cost 2.14x as
much. Keep C as the default, add low-cost one-shot model exploration where
business workflow coverage matters, and reserve D for ambiguous observations
or anomaly confirmation. Compact large feedback before the next experiment.

Durable references:

- `scripts/autonomous_validation_pass3.py`
- `schemas/autonomous_validation_pass3_report_v1.schema.json`
- `tests/test_autonomous_validation_pass3.py`
- `docs/80_autonomous_validation_pass3.md`

Local raw evidence:
`runs/autonomous-validation/pass3-real-projects-20261014-r2/validation_report.json`.

# Customer-Agent Long Journey Trial

This trial is a black-box customer acceptance layer for CGKN. It does not create a new formal generation path and does not let the customer agent edit CGKN code or generate target project code.

CGKN is the current product name used in customer-facing trial summaries. Historical naming references may exist in legacy compatibility code or older kernel notes, but they are not the current release-candidate product name.

The customer agent can only:

- state a vague goal
- answer clarifying questions
- challenge claims
- inspect evidence
- request rework
- retest
- score the result

The underlying evidence must come from CGKN's existing requirement decision, product contract, implementation materialization, delivery evidence, local packaging, capability manifest, and commercial readiness reports.

Outputs:

- `artifacts/customer_agent_long_journey_trial.json`
- `artifacts/customer_agent_long_journey_summary.md`
- `artifacts/customer_agent_dialogue.jsonl`
- `artifacts/customer_agent_scorecard.json`
- `artifacts/customer_agent_gap_report.md`
- `artifacts/customer_agent_rework_report.md`

Customer acceptance is intentionally separate from commercial readiness. A scoped customer can accept a useful local-first beta delivery while `commercial_ready` remains `false` because production media coverage, production ASR evidence, repeat reliability runs, human review, and release operations are still missing.

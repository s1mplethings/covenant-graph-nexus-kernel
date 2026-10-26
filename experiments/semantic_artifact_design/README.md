# Canonical Semantic Artifact Design Experiment

This directory is a bounded non-production comparison of three representations
for the same ten semantic facts. Designs A, B, and C share payload schemas,
cases, Provider roles and budgets, interface extraction and compatibility,
failure attribution, hidden acceptance, metrics, and qualification rules.

- A uses one immutable Python type per semantic kind.
- B uses one generic envelope plus a strict schema registry.
- C uses Contract, State, and Evidence envelopes plus strict typed payloads.

No design is eligible for production merely because deterministic tests pass.
The evaluator requires CLI success in at least two of three independent runs,
seeded repair PASS, no accepted interface regression, no whole-project repair
replan, no hidden leakage, and zero manual candidate edits.

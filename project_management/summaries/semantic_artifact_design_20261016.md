# Semantic Artifact Design Experiment — 2026-10-16

The iteration compared three semantic artifact representations under one frozen experiment protocol. Deterministic schema tests passed 19/19 and fake-provider integration passed 6/6. Real seeded repair passed for A, B, and C with affected-only rerun, no whole-project replan, no accepted interface break, and no manual candidate edit.

Real greenfield CSV CLI generation failed for all three designs in the initial run and in all nine repeat runs. The fixed production threshold was not met, so the iteration closed with `winner = NONE`, evidence status `NEEDS_REWORK`, and no production integration.

The useful learning is that stable artifacts, deterministic manifests, and repair continuity are necessary but not sufficient. The next increment must make public acceptance obligations complete and executable before Provider generation, including dependency-policy semantics and strict malformed-input behavior. It should not begin by inventing a fourth envelope.

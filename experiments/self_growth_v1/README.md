# Self-Growth V1 evaluation

This evaluation tests whether CGKN accumulates reusable capability value under
the existing Capability Registry and Runtime authorities. It never writes to
the production registry.

The frozen 100-task stream is shared by four independent groups:

- G0 freezes the registry.
- G1 grows task-specific capabilities after exact-reuse checks.
- G2 searches, parameterizes, composes, then creates a general capability.
- G3 adds a strong-model decision only for ambiguous abstraction boundaries.

Every group starts from a deterministic clone of the production registry and
has its own candidate store and derived experience ledger. Candidate code is
implemented through the existing bounded capability builder, validated in its
immutable sandbox lifecycle, and admitted to the experimental clone only after
hidden generalization cases pass. Hidden cases and expected benchmark labels
are evaluator-only data and are never included in Provider prompts.

Run discovery before freezing source:

```text
python scripts/run_self_growth_benchmarks.py --profile growth-discovery --output-root <outside-worktree> --count 20
```

After canonical publication, each formal profile requires the exact clean
Source Closure commit through `--expected-source-commit`. `growth-final` accepts
one `--receipt` argument per group and rejects mixed source or task-stream
identities.

The pricing fixture records source URLs and currency conversion provenance. A
model mismatch or missing usage makes cost unknown; it is never treated as
zero. Reasoning tokens are recorded but not double-counted because official
output-token billing includes them.

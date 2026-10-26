# ITER-058 Failure Appendix

The only formal episode failure occurred in `FOR-W4-33`, baseline
`B1_DIRECT_CHEAP_WITH_FLAT_STATE`, episode `E5`. The answer correctly described
the converged behavior and preserved interface but omitted the required
provenance reference for the second repair receipt. It was classified
`PROVENANCE_ERROR`, not transport, schema, state, or action failure.

B0 and B2 both passed this chain. Therefore the case is evidence against the
particular flat-state projection, but it is not evidence that full CGNK is
necessary relative to fair Direct Cheap. There were no transport failures,
unknown-usage calls, retries, hidden-gold exposures, direct-only cases, or
both-fail cases in the formal holdout.

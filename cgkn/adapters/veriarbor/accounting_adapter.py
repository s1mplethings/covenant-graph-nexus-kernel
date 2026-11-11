"""Annotate calls; the existing ledger alone writes accounting entries."""


def call_context(*, node_id, obligation, strategy, expected_delta, actual_delta, reason):
    return {'veriarbor_node': node_id, 'obligation': obligation, 'strategy': strategy,
            'expected_frontier_delta': expected_delta, 'actual_frontier_delta': actual_delta,
            'allocation_reason': reason}

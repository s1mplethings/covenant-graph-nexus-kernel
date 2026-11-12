"""Only host-authenticated GoalAcceptance rows may enter this adapter."""
from veriarbor.verification import reduce_obligations


def obligation_rollup(requirements, rows):
    observations = {ref: [g['verdict'] for g in rows if ref in g['requirement_refs']]
                    for ref in requirements}
    return reduce_obligations(requirements, observations)

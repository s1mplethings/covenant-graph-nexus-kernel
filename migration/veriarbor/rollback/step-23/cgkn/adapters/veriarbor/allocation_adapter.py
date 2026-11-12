"""Bounded slot allocation over admitted tasks; budget ledger remains host-owned."""
from veriarbor.search import Candidate, allocate


def allocate_slots(configs):
    # An admitted executable leaf is a bounded probe unless observed strategy
    # statistics say otherwise. No model tier escalation is authorized here.
    candidates = []
    for key, config in configs.items():
        stats = config.get('strategy_statistics', {})
        candidates.append(Candidate(key, 1, 1, 1, 0, 0, 1,
                                    samples=stats.get('samples', 0), reward=stats.get('reward', 0)))
    return allocate(candidates, budget=len(candidates))

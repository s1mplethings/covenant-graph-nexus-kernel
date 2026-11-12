"""Deterministic admission order; experimental bandit/Pareto is opt-in only.

The runtime already owns capacity/budget admission. This adapter neither
escalates models nor allocates a second resource budget.
"""
def allocate_slots(configs):
    return [{'id': key, 'allocated': 1} for key in sorted(configs)]

"""Trusted host resource names are normalized by executors before this port."""
from collections.abc import Mapping
from dataclasses import replace
from veriarbor.scheduling import ResourceClaim, conflicts, parallel_batch


def resource_claim(node_id, config):
    resources = config.get('resources', {})
    if not isinstance(resources, Mapping) or any(v not in {'read', 'write'} for v in resources.values()):
        raise ValueError('resources must map identity to read/write')
    return ResourceClaim(node_id,
                         frozenset(k for k, v in resources.items() if v == 'read'),
                         frozenset(k for k, v in resources.items() if v == 'write'),
                         frozenset(config.get('side_effect_set', ())),
                         frozenset(config.get('contract_set', ())),
                         bool(config.get('parallel_safe')))


def compatible(left, right):
    # Preserve pre-existing validation order for non-opt-in configurations.
    if not left.get('parallel_safe') or not right.get('parallel_safe'):
        return False
    return not conflicts(resource_claim('left', left), resource_claim('right', right))


def select_batch(configs, *, slots, running=()):
    from .allocation_adapter import allocate_slots
    allocated = allocate_slots(configs)
    return parallel_batch([replace(resource_claim(row['id'], configs[row['id']]), weight=len(allocated) - index)
                           for index, row in enumerate(allocated)],
                          slots=slots, running=[resource_claim(key, config) for key, config in running])

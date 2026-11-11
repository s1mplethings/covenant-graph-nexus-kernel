"""Temporary qualification candidates; promoted only after shared tests."""
from collections import deque
from graphlib import CycleError, TopologicalSorter
from heapq import heappop, heappush
from cgkn.component.spec import _freeze as freeze, _thaw as thaw


def ordered_nodes(predecessors, *, fifo=False):
    sorter = TopologicalSorter(predecessors)
    try:
        sorter.prepare()
    except CycleError:
        pass  # Drain the acyclic portion to preserve complete blocked-node diagnostics.
    ready = deque() if fifo else []
    result = []
    while sorter.is_active():
        for node in sorted(sorter.get_ready()):
            ready.append(node) if fifo else heappush(ready, node)
        node = ready.popleft() if fifo else heappop(ready)
        result.append(node)
        sorter.done(node)
    return result

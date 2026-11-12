"""Host composition of existing execution validation and goal acceptance.

No second state owner: this returns the existing GoalAcceptance instance.
"""
from cgkn.state.acceptance import GoalAcceptance
from .node_authority import ExecutionAuthority

def open_goal_acceptance(store, project_id, run_id, requirements, checkers, *, execution_mode='GOVERNED'):
    authority = ExecutionAuthority(store, project_id, run_id) if execution_mode == 'GOVERNED' else None
    return GoalAcceptance(store, project_id, run_id, requirements, checkers,
                          execution_mode=execution_mode, execution_authority=authority)

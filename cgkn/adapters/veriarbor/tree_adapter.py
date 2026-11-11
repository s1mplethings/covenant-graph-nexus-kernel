"""Goal rows to generic identity/dependency inputs; no stored second tree."""
from veriarbor.verification import ready_frontier, verified_lineage


def _inputs(goals, blocked_paths):
    blocked_paths = set(blocked_paths)
    return ([g['id'] for g in goals], {g['id']: g.get('verdict') for g in goals},
            {g['id']: g.get('milestone_contract', {}).get('dependency_goal_ids', []) for g in goals},
            {g['id'] for g in goals if blocked_paths.intersection(g.get('subject_refs', []))})


def dependency_ready_goals(goals, blocked_paths=()):
    ready = set(ready_frontier(*_inputs(goals, blocked_paths)))
    return [g for g in goals if g['id'] in ready]


def task_readiness_projection(goals, identities, blocked_paths=()):
    args = _inputs(goals, blocked_paths)
    ready = set(ready_frontier(*args))
    lineage = verified_lineage(*args)
    rows = []
    for g in goals:
        refs = g.get('subject_refs', [])
        exists = bool(refs) and all(identities.get(p) for p in refs)
        verified = lineage[g['id']]
        state = ('VERIFIED' if verified else 'INVALIDATED' if g.get('verdict') == 'VERIFIED'
                 else 'BLOCKED' if g['id'] not in ready else 'FAILED' if g.get('verdict') == 'FAILED'
                 else 'IMPLEMENTED_UNVERIFIED' if exists else 'READY')
        rows.append({'goal_id': g['id'], 'state': state, 'artifact_exists': exists,
                     'acceptance_verified': verified, 'task_ready': g['id'] in ready,
                     'authority': 'projection of canonical GoalAcceptance and current execution effects'})
    return rows

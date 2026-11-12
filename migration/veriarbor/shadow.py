"""Offline old/new comparisons; no provider, acceptance writes or execution."""
from pathlib import Path
import itertools
import json
import hashlib
import sys

H = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(H))
from cgkn.protocol.context_pack import dependency_ready_goals as old_ready, task_readiness_projection as old_projection
from cgkn.protocol.progress import strategy_fingerprint as old_fingerprint
from cgkn.runtime.dag_runner import DAGRunner
from cgkn.adapters.veriarbor.tree_adapter import dependency_ready_goals, task_readiness_projection
from cgkn.adapters.veriarbor.dag_adapter import compatible
from cgkn.adapters.veriarbor.acceptance_adapter import obligation_rollup
from cgkn.state import FileRunStore
from cgkn.state.acceptance import GoalAcceptance
from veriarbor.learning import strategy_fingerprint


def run():
    count = 0
    for statuses in itertools.product(('VERIFIED', 'FAILED', 'INSUFFICIENT_EVIDENCE', 'UNKNOWN'), repeat=3):
        for blocked in ((), ('a.py',), ('b.py',), ('c.py',)):
            goals = [{'id': key, 'subject_refs': [key + '.py'], 'verdict': status,
                      'milestone_contract': {'dependency_goal_ids': deps}}
                     for key, status, deps in zip('abc', statuses, ([], ['a'], ['b']))]
            assert dependency_ready_goals(goals, blocked) == old_ready(goals, blocked)
            assert task_readiness_projection(goals, {'a.py': 'hash'}, blocked) == old_projection(goals, {'a.py': 'hash'}, blocked)
            count += 1
    for a, b in itertools.product(({}, {'x': 'read'}, {'x': 'write'}, {'y': 'write'}), repeat=2):
        for left_safe, right_safe in itertools.product((False, True), repeat=2):
            left, right = {'resources': a, 'parallel_safe': left_safe}, {'resources': b, 'parallel_safe': right_safe}
            assert compatible(left, right) == DAGRunner._compatible(left, right)
            count += 1
    for mechanism in ('atomic', 'LOCKED ', '  other  mechanism '):
        value = {'problem': 'shared file', 'write': mechanism, 'lock': True}
        assert strategy_fingerprint(value) == old_fingerprint(value)
        count += 1
    promotion = Path(r'F:\CGKN-ITER-132\production-core-convergence-v1\promotion\run-05')
    profile = json.loads((promotion / 'profile.json').read_text(encoding='utf-8'))
    state = promotion / 'state' / profile['project_id'] / profile['run_id']
    data = json.loads((state / 'goal_acceptance.json').read_text(encoding='utf-8'))
    before = hashlib.sha256((state / 'goal_acceptance.json').read_bytes()).hexdigest()
    acceptance = GoalAcceptance(FileRunStore(promotion / 'state'), profile['project_id'], profile['run_id'], data['requirements'], data['checker_bindings'])
    view = acceptance.view()
    rollup = obligation_rollup(data['requirements'], view['goals'])
    for key in ('obligations', 'hard_verdict', 'completion', 'evidence_coverage'):
        assert rollup[key] == view[key], key
    assert dependency_ready_goals(view['goals']) == old_ready(view['goals'])
    assert hashlib.sha256((state / 'goal_acceptance.json').read_bytes()).hexdigest() == before
    out = H / 'migration/veriarbor'
    result = {'status': 'PASS', 'synthetic_comparisons': count, 'current_goal_count': len(view['goals']),
              'current_obligations': view['obligations'], 'old_new_differences': 0,
              'provider_calls': 0, 'current_acceptance_sha256': before,
              'scope': ['compatibility obligation rollup', 'readiness', 'resource compatibility', 'strategy fingerprint'],
              'limitations': ['New certificate/backtracking/allocation policies have library tests only; not live host authority yet'],
              'frontier': [g['id'] for g in dependency_ready_goals(view['goals'])]}
    with (out / 'SHADOW_RESULTS.json').open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    with (out / 'CURRENT_ACCEPTANCE_SNAPSHOT.json').open('x', encoding='utf-8') as stream:
        json.dump(view, stream, indent=2)
    print(json.dumps(result))


if __name__ == '__main__':
    run()

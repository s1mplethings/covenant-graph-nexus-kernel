"""Read-only migration projection; original acceptance and corpus untouched."""
from pathlib import Path
import json
import sys
from dataclasses import asdict

H = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(H))
from cgkn.adapters.veriarbor.certificate_adapter import certificates
from cgkn.state import FileRunStore
from cgkn.state.acceptance import GoalAcceptance
from veriarbor.model import Node, NodeKind, stable_hash


def reconstruct():
    p = Path(r'F:\CGKN-ITER-132\production-core-convergence-v1\promotion\run-05')
    profile = json.loads((p / 'profile.json').read_text(encoding='utf-8'))
    data = json.loads((p / 'state' / profile['project_id'] / profile['run_id'] / 'goal_acceptance.json').read_text(encoding='utf-8'))
    view = GoalAcceptance(FileRunStore(p / 'state'), profile['project_id'], profile['run_id'], data['requirements'], data['checker_bindings']).view()
    certs = certificates(view)
    return {key: cert.as_dict() for key, cert in certs.items()}, view


if __name__ == '__main__':
    first, view = reconstruct()
    second, _ = reconstruct()
    assert first == second
    milestones = {}
    for ref in ('M1', 'M2', 'M3', 'M4', 'M5', 'M6'):
        ids = [g['id'] for g in view['goals'] if ref in g['requirement_refs']]
        assert ids and all(key in first for key in ids)
        milestones[ref] = ids
    out = H / 'migration/veriarbor'
    with (out / 'CAPABILITY_CERTIFICATES.json').open('x', encoding='utf-8') as stream:
        json.dump({'certificates': first, 'milestones': milestones,
                   'rebuild_hashes': [stable_hash(first), stable_hash(second)],
                   'scope': 'Current authenticated frozen predicates; no product acceptance upgrade'}, stream, indent=2)
    children = ('Backend Publish', 'Receipt Persistence', 'Idempotency', 'GUI Integration', 'Vertical Slice')
    graph = [Node('M7', NodeKind.OBLIGATION_AND, children)]
    for child in children[:3]:
        # Backend-specific witnesses are separate, not inferred from a failed
        # whole-milestone receipt. They remain unbound until independently checked.
        graph.append(Node(child, NodeKind.CERTIFICATE_REF))
    gui = ('DOM Closure', 'Event Binding', 'Content State', 'Review State', 'Approval State', 'Publish State', 'Receipt Display')
    graph.extend([Node('GUI Integration', NodeKind.OBLIGATION_AND, gui), Node('Vertical Slice', NodeKind.OBLIGATION_AND)])
    graph.extend(Node(key, NodeKind.EXECUTION_LEAF) for key in gui)
    with (out / 'M7_GRAPH.json').open('x', encoding='utf-8') as stream:
        json.dump({'nodes': [asdict(n) for n in graph], 'verdict': view['obligations']['M7']['verdict'],
                   'certificate_refs_status': 'BACKEND_WITNESS_BINDING_PENDING', 'execution_owner': 'existing CGKN DAGRunner'}, stream, indent=2)
    print(json.dumps({'certificate_count': len(first), 'milestones': list(milestones), 'identical_rebuilds': True}))

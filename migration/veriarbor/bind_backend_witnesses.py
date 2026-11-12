"""Bind existing successful backend witnesses to unchanged current artifacts."""
from pathlib import Path
import hashlib
import json
import sys

H = Path(__file__).resolve().parents[2]
P = Path(r'F:\CGKN-ITER-132\production-core-convergence-v1')
from veriarbor.lifecycle import CapabilityCertificate


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    candidate = P / 'promotion/run-05/candidate'
    bound = []
    for label, names in [('systemic-m7-idempotency488', ('Backend Publish', 'Receipt Persistence', 'Idempotency')),
                         ('systemic-m7-platform487', ('Local Platform',))]:
        observation_path = P / 'tests' / label / 'observation.json'
        receipt_path = P / 'audit' / label / 'receipt.json'
        observation = json.loads(observation_path.read_text(encoding='utf-8'))
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        assert observation['status'] == 'PASS' and receipt['exit_code'] == 0
        assert sha(Path(receipt['log'])) == receipt['log_sha256']
        assert all(sha(candidate / rel) == digest for rel, digest in observation['source_hashes'].items())
        for name in names:
            cert = CapabilityCertificate(
                'M7:' + name, name, {'historical_probe': label}, {'historical_probe_status': 'PASS'}, (), (),
                (label,), observation['source_hashes'], {'witness-binding-checker': sha(Path(__file__))},
                ('Reuses existing probe evidence without rerun; not full M7 GUI acceptance.',
                 'Checker version identifies this current binding verification, not an invented historical checker hash.'),
                ('sha256:' + sha(observation_path),), ('sha256:' + sha(receipt_path),),
                0, None, ('artifact_changed', 'witness_revoked'))
            bound.append(cert.as_dict())
    out = H / 'migration/veriarbor'
    with (out / 'M7_BACKEND_CERTIFICATES.json').open('x', encoding='utf-8') as stream:
        json.dump({'certificates': bound, 'backend_reexecuted': False, 'M7_verified': False}, stream, indent=2)
    graph = json.loads((out / 'M7_GRAPH.json').read_text())
    graph['certificate_refs_status'] = 'BOUND_TO_UNCHANGED_HISTORICAL_BACKEND_WITNESSES'
    graph['certificate_refs'] = {row['semantic_name']: row['capability_id'] for row in bound}
    (out / 'M7_GRAPH.json').write_text(json.dumps(graph, indent=2), encoding='utf-8')
    print(json.dumps({'bound_backend_certificates': len(bound), 'M7_verified': False}))


if __name__ == '__main__':
    main()

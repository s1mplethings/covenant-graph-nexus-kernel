"""Qualified checker versions in the existing run store, never new acceptance authority."""
import hashlib
import json
from pathlib import Path


def _qualification(gate, ref, previous, current):
    from .provenance import ProvenanceError
    proof = gate.resolve(ref, 'CheckerRevisionQualification')
    controls = proof.get('controls', [])
    if (proof.get('status') != 'QUALIFIED'
            or proof.get('previous_checker_hash') != previous
            or proof.get('checker_hash') != current
            or proof.get('requirement_policy') != 'UNCHANGED'
            or proof.get('historical_evidence_policy') != 'RETAIN_ORIGINAL_VERDICTS'
            or not isinstance(controls, list)
            or not {'positive', 'negative', 'mutation'} <= {c.get('kind') for c in controls if isinstance(c, dict)}
            or any(not isinstance(c, dict) or c.get('passed') is not True or not c.get('evidence_ref') for c in controls)):
        raise ProvenanceError('INVALID_PROVENANCE', 'checker revision is not independently qualified')
    for control in controls:
        gate.resolve(control['evidence_ref'])
    return proof


def load_checker_revisions(gate, binding):
    from .provenance import ProvenanceError, reference
    templates = binding.get('incremental_checker_bindings', {})
    current = {k: dict(v) for k, v in templates.items()}
    versions = {}
    for sequence, path in enumerate(sorted((gate.root/'checker_revisions').glob('*.json')), 1):
        row = json.loads(path.read_text(encoding='utf8'))
        key = row.get('checker_key')
        required = {'kind', 'sequence', 'checker_key', 'previous_checker_hash', 'checker_hash',
                    'checker_version', 'source_ref', 'qualification_ref', 'reason'}
        if (set(row) != required or row['kind'] != 'QualifiedCheckerRevision'
                or path.name != f'{sequence:06d}.json' or row['sequence'] != sequence
                or key not in current or not isinstance(row['reason'], str) or not row['reason'].strip()
                or row['previous_checker_hash'] != current[key]['checker_hash']
                or row['checker_version'] != f'qualified-revision-{sequence}'
                or row['checker_hash'] == row['previous_checker_hash']):
            raise ProvenanceError('INVALID_PROVENANCE', 'broken checker revision lineage')
        source = gate.resolve(row['source_ref'])
        if hashlib.sha256(source).hexdigest() != row['checker_hash']:
            raise ProvenanceError('INVALID_PROVENANCE', 'checker revision source mismatch')
        _qualification(gate, row['qualification_ref'], row['previous_checker_hash'], row['checker_hash'])
        sealed = {**row, 'revision_ref': reference(gate.store.root, path)}
        versions.setdefault(key, {})[row['checker_version']] = sealed
        current[key] = {**current[key], **sealed}
    return versions, current


def bind_checker_revision(store, project_id, run_id, checker_key, original, decision=None):
    """Controller-only explicit qualification; profile and original receipts stay immutable."""
    from .provenance import ProvenanceGate, reference
    gate = ProvenanceGate(store, project_id, run_id)
    base_path = gate.root/'provenance_contract.json'
    if not base_path.exists():
        if decision:
            raise ValueError('checker revision requires an existing frozen provenance contract')
        return None
    with store.exclusive_file(gate.root/'checker_revision.lock'):
        base = json.loads(base_path.read_text(encoding='utf8'))
        versions, current = load_checker_revisions(gate, base)
        if base['incremental_checker_bindings'][checker_key]['checker_hash'] != original['sha256']:
            raise ValueError('original consumer differs from frozen checker policy')
        if decision:
            required = {'checker_key', 'previous_checker_hash', 'source_path', 'source_sha256',
                        'qualification_ref', 'reason'}
            if not isinstance(decision, dict) or set(decision) != required or decision['checker_key'] != checker_key:
                raise ValueError('invalid explicit checker revision')
            active = current[checker_key]
            if decision['source_sha256'] == active['checker_hash']:
                if (decision['previous_checker_hash'] != active.get('previous_checker_hash')
                        or decision['qualification_ref'] != active.get('qualification_ref')
                        or decision['reason'] != active.get('reason')):
                    raise ValueError('conflicting checker revision decision')
            else:
                if decision['previous_checker_hash'] != active['checker_hash']:
                    raise ValueError('stale checker revision decision')
                supplied = Path(decision['source_path']).absolute()
                source = supplied.resolve()
                if (source.is_relative_to(Path(base['workspace_root']).resolve())
                        or any(p.is_symlink() for p in (supplied, *supplied.parents))):
                    raise ValueError('revised checker must remain outside candidate workspace')
                raw = source.read_bytes()
                if hashlib.sha256(raw).hexdigest() != decision['source_sha256']:
                    raise ValueError('revised checker source hash mismatch')
                _qualification(gate, decision['qualification_ref'], active['checker_hash'], decision['source_sha256'])
                if not isinstance(decision['reason'], str) or not decision['reason'].strip():
                    raise ValueError('checker revision reason required')
                sequence = sum(len(v) for v in versions.values()) + 1
                target = gate.root/'private_checker'/(decision['source_sha256']+'.py')
                store.immutable_blob(target, raw)
                row = {'kind': 'QualifiedCheckerRevision', 'sequence': sequence, 'checker_key': checker_key,
                       'previous_checker_hash': active['checker_hash'], 'checker_hash': decision['source_sha256'],
                       'checker_version': f'qualified-revision-{sequence}', 'source_ref': reference(store.root, target),
                       'qualification_ref': decision['qualification_ref'], 'reason': decision['reason']}
                store.immutable_json(gate.root/'checker_revisions'/f'{sequence:06d}.json', row)
                versions, current = load_checker_revisions(gate, base)
        active = current[checker_key]
        return versions[checker_key][active['checker_version']] if 'revision_ref' in active else None

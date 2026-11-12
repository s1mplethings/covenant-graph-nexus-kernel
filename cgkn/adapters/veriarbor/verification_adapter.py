"""Dedup projections from the original authenticated GoalAcceptance view."""
from veriarbor.dedup import VerificationKey, verification_disposition
from veriarbor.model import stable_hash


def goal_verification_keys(view):
    result = []
    if view.get('evidence_mode') != 'production_provenance':
        return result
    for goal in view.get('goals', ()):
        contract = goal.get('milestone_contract') or {}
        evidence = goal.get('evidence') or {}
        provenance = evidence.get('provenance') or {}
        checker = provenance.get('chain', {}).get('checker', {})
        required_version = view.get('required_checker_versions', {}).get(goal['id'])
        if required_version and checker.get('version') != required_version:
            continue  # New scoped qualification is a new VerificationKey.
        subjects = {p: view.get('subject_identities', {}).get(p) for p in goal.get('subject_refs', ())}
        evidenced_subjects = evidence.get('effective_subjects') if evidence.get('certified_substitutions') else evidence.get('subjects')
        if (not contract or not subjects or not all(subjects.values()) or
                evidenced_subjects != subjects or provenance.get('status') != 'TRUSTED' or
                not evidence.get('receipt_hash') or not checker.get('hash') or
                goal.get('verdict') not in {'VERIFIED', 'FAILED'}):
            continue
        # Legacy aggregate contracts remain opaque and exact. They are usable
        # for check dedup, NOT a typed-port substitution certificate.
        key = VerificationKey(goal['id'], stable_hash(subjects),
            stable_hash(contract.get('registry', {})), stable_hash(goal['acceptance']),
            stable_hash({'opaque_contract': contract}), goal['id'], checker['hash'], (), tuple(subjects.items()))
        status = 'PASS' if goal['verdict'] == 'VERIFIED' else 'FAIL'
        disposition = verification_disposition(key, [{'key': key.fingerprint, 'status': status, 'authenticated': True}])
        result.append({'goal_id': goal['id'], 'key': key.fingerprint, 'disposition': disposition,
                       'existing_node_id': evidence['node_id'], 'receipt_hash': evidence['receipt_hash'],
                       'subject_hash': stable_hash(subjects), 'authority': 'current authenticated acceptance view'})
    return result


def reject_duplicate_measurement(document, *, goal_id=None, node_id=None):
    from cgkn.protocol.normalization import ContractError
    for row in document.get('verification_dedup', ()):
        if ((goal_id and row['goal_id'] == goal_id) or
                (node_id and row['existing_node_id'] == node_id)):
            raise ContractError('NO_NOVEL_DELTA', fields=('action', 'target'), repair_class='R6',
                vector_key='semantic_contradictions', details={
                    'existing_measurements': [row], 'verification_key': row['key'],
                    'instruction': 'Reuse the existing current measurement. PASS remains reusable; FAIL requires a new artifact, contract, variant or qualified checker delta before another measurement. Repair the observed failure in its original owner or choose another unfinished capability. No duplicate observer is admitted.'})

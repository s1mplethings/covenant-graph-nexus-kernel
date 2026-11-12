"""Rebuild certificates from current, host-authenticated acceptance views."""
from veriarbor.lifecycle import CapabilityCertificate
from veriarbor.model import stable_hash


def certificates(view):
    result = {}
    if view.get('evidence_mode') != 'production_provenance':
        return result
    for goal in view.get('goals', []):
        evidence = goal.get('evidence') or {}
        provenance = evidence.get('provenance') or {}
        chain = provenance.get('chain') or {}
        checker = chain.get('checker') or {}
        subjects = evidence.get('subjects') or {}
        if (goal.get('verdict') != 'VERIFIED' or provenance.get('status') != 'TRUSTED'
                or not evidence.get('receipt_hash') or not checker.get('hash') or not subjects
                or any(view.get('subject_identities', {}).get(k) != v for k, v in subjects.items())):
            continue
        cert = CapabilityCertificate(
            goal['id'], goal['acceptance'],
            {'condition_hash': evidence['condition_hash'], 'requirements': chain.get('requirements', {})},
            {'verdict': 'VERIFIED'},
            tuple(goal.get('milestone_contract', {}).get('dependency_goal_ids', ())), (),
            (goal['id'],), subjects, {goal['id'] + ':' + checker['ref']: checker['hash']},
            ('Only the frozen acceptance predicate and bound versions are certified.',),
            ('sha256:' + evidence['receipt_hash'],), ('sha256:' + stable_hash(provenance),),
            0, None, ('artifact_changed', 'checker_changed', 'contract_changed', 'evidence_revoked'))
        if cert.valid(artifacts=view['subject_identities'], checkers=cert.checker_versions, now=0):
            result[goal['id']] = cert
    return result

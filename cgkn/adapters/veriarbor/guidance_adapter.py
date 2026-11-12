"""Retire explicitly state-bound operational guidance without changing authority."""
from copy import deepcopy
from veriarbor.model import stable_hash


def project_continuation(continuation, goal_state):
    result = deepcopy(continuation)
    diagnosis = result.get('fresh_runtime_diagnosis')
    if not isinstance(diagnosis, dict) or 'applicability' not in diagnosis:
        return result
    binding = diagnosis['applicability']
    reasons = []
    if (not isinstance(binding, dict) or not binding
            or set(binding) - {'artifact_hashes', 'goal_receipts'}
            or not all(isinstance(v, dict) for v in binding.values())):
        reasons.append('MALFORMED_GUIDANCE_BINDING')
    else:
        subjects = goal_state.get('subject_identities', {})
        goals = {g['id']: g for g in goal_state.get('goals', [])}
        for path, expected in binding.get('artifact_hashes', {}).items():
            if not isinstance(expected, str) or subjects.get(path) != expected:
                reasons.append('ARTIFACT_CHANGED:' + str(path))
        for key, expected in binding.get('goal_receipts', {}).items():
            if key not in goals or (goals[key].get('evidence') or {}).get('receipt_hash') != expected:
                reasons.append('GOAL_EVIDENCE_CHANGED:' + str(key))
    if reasons:
        result['fresh_runtime_diagnosis'] = {
            'status': 'GUIDANCE_NOT_APPLICABLE', 'reasons': reasons,
            'original_guidance_hash': stable_hash(diagnosis),
            'history_policy': 'Original guidance retained in bound raw context and continuation receipt.',
            'instruction': 'Use current canonical goal observations and artifact identities. This expired guidance selects no action.'}
    else:
        result['fresh_runtime_diagnosis']['status'] = 'GUIDANCE_APPLICABLE'
    return result

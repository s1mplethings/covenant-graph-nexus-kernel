"""Evidence validity is distinct from the product verdict; no model voting."""
import hashlib
import json
import math


def predicate(observed, contract):
    """Deterministic predicates over independently supplied, versioned expectations."""
    op, expected = contract['operator'], contract['expected']
    if op == 'equal':
        return type(observed) is type(expected) and observed == expected
    if op == 'set_equal':
        return set(observed) == set(expected)
    if op == 'within':
        tolerance = contract['tolerance']
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x)
               for x in (observed, expected, tolerance)) or tolerance < 0:
            raise ValueError('invalid numeric observation or tolerance')
        return abs(observed-expected) <= tolerance
    raise ValueError('unsupported predicate')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def evaluate(record, *, artifact_hash, requirement_version, environment_hash):
    required = ('requirement_ref', 'requirement_version', 'artifact_hash',
                'checker', 'check_version', 'environment_hash', 'expected',
                'observed', 'evidence_ref', 'check_execution', 'verdict')
    if any(k not in record for k in required):
        return {'verdict': 'INSUFFICIENT_EVIDENCE', 'next_action': 'ADD_EVIDENCE', 'reason': 'missing fields'}
    if record['check_execution'] != 'VALID':
        return {'verdict': 'INSUFFICIENT_EVIDENCE', 'next_action': 'ADD_EVIDENCE', 'reason': 'check not validly executed'}
    if (record['artifact_hash'], record['requirement_version'], record['environment_hash']) != (artifact_hash, requirement_version, environment_hash):
        return {'verdict': 'INSUFFICIENT_EVIDENCE', 'next_action': 'ADD_EVIDENCE', 'reason': 'conditions changed'}
    verdict = record['verdict']
    if verdict not in {'VERIFIED', 'FAILED', 'INSUFFICIENT_EVIDENCE'}:
        verdict = 'INSUFFICIENT_EVIDENCE'
    return {'verdict': verdict, 'next_action': {'VERIFIED': 'CONTINUE', 'FAILED': 'REPAIR', 'INSUFFICIENT_EVIDENCE': 'ADD_EVIDENCE'}[verdict]}


class StagnationGuard:
    """Only compare bound assertion/artifact evidence, not timestamps or prose."""
    def __init__(self):
        self.failures = {}

    def observe(self, *, issue, artifact_hash, assertion, evidence_hash, strategy):
        key = digest([issue, artifact_hash, assertion])
        signature = digest([evidence_hash, strategy])
        prior = self.failures.get(key, {})
        count = prior.get('count', 0) + 1 if prior.get('signature') == signature else 1
        self.failures[key] = {'signature': signature, 'count': count}
        return 'BLOCK_REPETITION' if count >= 3 else 'CHANGE_STRATEGY' if count == 2 else 'CONTINUE'

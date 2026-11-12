"""Read exact Host-authenticated attempts; mutable latest views are not evidence."""
import hashlib
import json
from collections.abc import Mapping

from cgkn.execution import BlockExecutionResult


class RunEvidenceStore:
    def __init__(self, store, project_id, run_id, *, authority=None):
        self.store, self.project_id, self.run_id = store, project_id, run_id
        self.authority = authority

    def evidence(self, ref):
        if not isinstance(ref, Mapping) or set(ref) != {'node_id', 'attempt_id', 'sha256', 'receipt_id'}:
            raise ValueError('EXACT_EVIDENCE_IDENTITY_REQUIRED')
        authority = self.authority
        if authority is None or authority.store is not self.store or (
                authority.project_id, authority.run_id) != (self.project_id, self.run_id):
            raise ValueError('HOST_AUTHORITY_REQUIRED')
        for key in ('node_id', 'attempt_id'):
            self.store._validate_segment(ref[key])
        root = self.store.run_dir(self.project_id, self.run_id)
        path = root/'attempts'/ref['node_id']/(ref['attempt_id']+'.json')
        if not path.resolve().is_relative_to(root.resolve()) or any(
                item.is_symlink() for item in [path, *path.parents] if item.is_relative_to(self.store.root)):
            raise ValueError('EVIDENCE_PATH_REJECTED')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != ref['sha256']:
            raise ValueError('EVIDENCE_HASH_MISMATCH')
        result = BlockExecutionResult.from_dict(json.loads(raw))
        if (result.project_id, result.run_id, result.node_id, result.attempt_id) != (
                self.project_id, self.run_id, ref['node_id'], ref['attempt_id']):
            raise ValueError('EVIDENCE_IDENTITY_MISMATCH')
        key = 'node_commit_receipt_id' if result.succeeded else 'node_failure_receipt_id'
        if not ref['receipt_id'] or result.metadata.get(key) != ref['receipt_id']:
            raise ValueError('EVIDENCE_RECEIPT_MISMATCH')
        if result.succeeded:
            authority.validate_execution_result(result)
        else:
            authority.validate_failed_execution(result)
        return result.as_dict()

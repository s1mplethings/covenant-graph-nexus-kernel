"""Read-only verification of FileRunStore facts, not a second acceptance authority.

The trusted coordinator freezes bindings before execution. Candidate/model code
must not have write access to the run store. Hashes detect changed references;
they are not signatures against an attacker with host filesystem privileges.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

from cgkn.execution.check_evidence import predicate
from .acceptance import identity


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def reference(root, path):
    path = Path(path).resolve()
    return {'path':path.relative_to(Path(root).resolve()).as_posix(), 'sha256':file_hash(path)}


def put_evidence(store, project_id, run_id, value):
    """Idempotent typed immutable documents inside the existing run store."""
    path = store.run_dir(project_id, run_id)/'evidence'/(identity(value)+'.json')
    store.immutable_json(path, value)
    return reference(store.root, path)


class ProvenanceError(ValueError):
    def __init__(self, status, reason):
        self.status, self.reason = status, reason
        super().__init__(status+': '+reason)


class ProvenanceGate:
    def __init__(self, store, project_id, run_id):
        self.store, self.project_id, self.run_id = store, project_id, run_id
        self.root = store.run_dir(project_id, run_id)

    def resolve(self, ref, kind=None):
        if not isinstance(ref, dict) or not ref.get('path') or not ref.get('sha256'):
            raise ProvenanceError('INSUFFICIENT_EVIDENCE', 'missing reference identity')
        relative = Path(ref['path'])
        path = self.store.root / relative
        if relative.is_absolute() or '..' in relative.parts or not path.resolve().is_relative_to(self.store.root):
            raise ProvenanceError('INVALID_PROVENANCE', 'reference outside this run')
        if not path.resolve().is_relative_to(self.root):
            binding=self.binding()
            if ref not in binding.get('authorized_imports',[]):
                raise ProvenanceError('INVALID_PROVENANCE','cross-run reference is not explicitly frozen for this logical task')
        if any(p.is_symlink() for p in [path, *path.parents] if p.is_relative_to(self.store.root)):
            raise ProvenanceError('INVALID_PROVENANCE', 'symlink evidence')
        if not path.is_file():
            raise ProvenanceError('INSUFFICIENT_EVIDENCE', 'referenced object missing: '+relative.as_posix())
        if file_hash(path) != ref['sha256']:
            raise ProvenanceError('INVALID_PROVENANCE', 'object hash mismatch: '+relative.as_posix())
        if kind is None:
            return path.read_bytes()
        try:
            obj = json.loads(path.read_text(encoding='utf-8'))
        except (ValueError, UnicodeError) as exc:
            raise ProvenanceError('INVALID_PROVENANCE', 'invalid JSON object') from exc
        if not isinstance(obj, dict) or obj.get('kind') != kind:
            raise ProvenanceError('INVALID_PROVENANCE', 'object type mismatch: '+kind)
        return obj

    def binding(self):
        path = self.root/'provenance_contract.json'
        if not path.exists():
            raise ProvenanceError('INSUFFICIENT_EVIDENCE','no coordinator-frozen provenance contract')
        obj = json.loads(path.read_text(encoding='utf-8'))
        if obj.get('kind') != 'ProvenanceContract':
            raise ProvenanceError('INVALID_PROVENANCE','invalid provenance contract type')
        return obj

    def verify_check(self, result, goal, subjects):
        """Used by GoalAcceptance before accepting and when rebuilding a check."""
        try:
            binding = self.binding()
            check = result.as_dict()['outputs'].get('goal_check', {})
            witness = self.resolve(check.get('provenance_ref'), 'CheckWitness')
            contract = binding['goals'][goal['id']]
            requirement_hashes = {k:identity(binding['requirements'][k]) for k in goal['requirement_refs']}
            for field, wanted in [('goal_id',goal['id']),('logical_task_id',binding['logical_task_id']),
                                  ('requirement_hashes',requirement_hashes),('input_ref',binding['input_ref']),
                                  ('environment_ref',binding['environment_ref']),('checker_ref',contract['checker_ref'])]:
                if witness.get(field) != wanted:
                    raise ProvenanceError('INVALID_PROVENANCE', field+' binding mismatch')
            if contract['condition_hash'] != identity(goal['acceptance']):
                raise ProvenanceError('INVALID_PROVENANCE','condition changed')
            source = self.resolve(witness['checker_source_ref'])
            if hashlib.sha256(source).hexdigest() != contract['checker_hash'] or witness.get('checker_version') != contract['checker_version']:
                raise ProvenanceError('STALE','checker identity/version mismatch')
            if result.executor_ref != contract['checker_ref'] or check.get('checker_version') != contract['checker_version']:
                raise ProvenanceError('INVALID_PROVENANCE','executor is not bound checker')
            if (result.project_id,result.run_id,result.attempt_id) != (self.project_id,self.run_id,witness.get('attempt_id')):
                raise ProvenanceError('INVALID_PROVENANCE','execution attempt mismatch')
            execution = self.root/'attempts'/result.node_id/(result.attempt_id+'.json')
            if not execution.exists() or json.loads(execution.read_text(encoding='utf-8')) != result.as_dict():
                raise ProvenanceError('INVALID_PROVENANCE','execution receipt not stored unchanged')
            self.resolve(witness['input_ref'],'PublicInput')
            self.resolve(witness['environment_ref'],'ToolEnvironment')
            candidate = self.resolve(witness['candidate_ref'],'CandidateIdentity')
            if not candidate.get('candidate_id') or not candidate.get('version') or not candidate.get('created_at'):
                raise ProvenanceError('INVALID_PROVENANCE','candidate identity incomplete')
            if dict(result.metadata.get('bound_candidate',{})) != {'id':candidate['candidate_id'],'version':candidate['version']}:
                raise ProvenanceError('INVALID_PROVENANCE','candidate version differs from executed binding')
            if candidate['subjects'] != check.get('subjects') or candidate['subjects'] != subjects:
                raise ProvenanceError('STALE','candidate subject binding mismatch')
            for subject, ref in candidate['artifacts'].items():
                self.resolve(ref)
                if candidate['subjects'].get(subject) != ref['sha256']:
                    raise ProvenanceError('INVALID_PROVENANCE','artifact subject hash mismatch')
            if set(candidate['subjects']) != set(candidate['artifacts']):
                raise ProvenanceError('INVALID_PROVENANCE','artifact coverage mismatch')
            raw = self.resolve(witness['observation_ref'],'RawObservation')
            if not raw.get('created_at') or raw.get('observed') in (None,{},[],''):
                raise ProvenanceError('INSUFFICIENT_EVIDENCE','empty raw observation')
            if raw.get('subjects') != subjects or raw.get('checker_hash') != contract['checker_hash'] or raw.get('input_ref') != witness['input_ref']:
                raise ProvenanceError('INVALID_PROVENANCE','observation binding mismatch')
            if check.get('observed') != raw['observed'] or check.get('condition_hash') != contract['condition_hash']:
                raise ProvenanceError('INVALID_PROVENANCE','observation/condition differs from receipt')
            if result.status.value != 'SUCCEEDED':
                # A successful measurement can be rejected by the deliverable
                # gate. Authenticate its original receipt only for a negative
                # business verdict; never grant success from a failed attempt.
                metadata = result.as_dict()['metadata']
                ref = metadata.get('raw_execution_receipt_ref')
                expected_path = self.root/'execution_receipts'/result.node_id/(result.attempt_id+'.json')
                if (result.status.value != 'FAILED' or check.get('verdict') != 'FAILED'
                        or metadata.get('execution_status') != 'EXECUTION_SUCCESS'
                        or metadata.get('deliverable_verdict') != 'FAILED'
                        or not isinstance(ref, dict)
                        or ref.get('path') != expected_path.relative_to(self.store.root).as_posix()):
                    raise ProvenanceError('INSUFFICIENT_EVIDENCE','no authenticated negative measurement')
                original = json.loads(self.resolve(ref))
                final = result.as_dict()
                if (original.get('status') != 'SUCCEEDED' or original.get('error')
                        or any(original.get(k) != final.get(k) for k in
                               ('project_id','run_id','node_id','attempt_id','executor_ref'))
                        or original.get('outputs',{}).get('goal_check') != check
                        or original.get('metadata',{}).get('bound_candidate') != metadata.get('bound_candidate')):
                    raise ProvenanceError('INVALID_PROVENANCE','negative measurement receipt mismatch')
            if check.get('execution') != 'VALID' or raw.get('execution') != 'VALID':
                raise ProvenanceError('INSUFFICIENT_EVIDENCE','checker did not execute successfully')
            actual = 'VERIFIED' if predicate(raw['observed']['value'],contract['predicate']) else 'FAILED'
            if actual != check.get('verdict'):
                raise ProvenanceError('CONFLICT','verdict differs from observed predicate')
            return {'status':'TRUSTED','chain':{'requirements':requirement_hashes,'candidate':witness['candidate_ref'],
                    'checker':{'ref':contract['checker_ref'],'version':contract['checker_version'],'hash':contract['checker_hash']},
                    'observation':witness['observation_ref'],'verdict':actual,'logical_task_id':binding['logical_task_id'],
                    'attempt_id':result.attempt_id,'execution_receipt':reference(self.store.root,execution),'witness':check['provenance_ref']}}
        except ProvenanceError as exc:
            return {'status':exc.status,'reason':exc.reason}
        except (OSError,ValueError,KeyError,TypeError) as exc:
            return {'status':'INVALID_PROVENANCE','reason':type(exc).__name__+': '+str(exc)}

    def current(self, acceptance):
        """Resolve the same authoritative acceptance records; never grant a verdict."""
        view = acceptance.view()
        binding = self.binding()
        if binding['requirements'] != acceptance.requirements:
            raise ProvenanceError('INVALID_PROVENANCE','original requirements differ')
        chains=[]
        for goal in view['goals']:
            evidence=goal.get('evidence')
            if not evidence:
                raise ProvenanceError('INSUFFICIENT_EVIDENCE','goal has no current execution')
            path=self.root/'attempts'/evidence['node_id']/(evidence['attempt_id']+'.json')
            from cgkn.execution import BlockExecutionResult
            if not path.exists():raise ProvenanceError('INSUFFICIENT_EVIDENCE','missing attempt receipt')
            value=json.loads(path.read_text(encoding='utf-8'))
            if identity(value)!=evidence['receipt_hash']:
                raise ProvenanceError('INVALID_PROVENANCE','acceptance receipt hash mismatch')
            result=BlockExecutionResult.from_dict(value)
            report=self.verify_check(result,goal,{k:view['subject_identities'][k] for k in goal['subject_refs']})
            if report['status']!='TRUSTED':raise ProvenanceError(report['status'],report['reason'])
            chains.append(report['chain'])
        if not chains:raise ProvenanceError('INSUFFICIENT_EVIDENCE','no current checks')
        return {'status':'TRUSTED','acceptance':view,'chains':chains}

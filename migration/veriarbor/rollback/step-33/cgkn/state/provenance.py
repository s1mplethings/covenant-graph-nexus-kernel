"""Read-only verification of FileRunStore facts, not a second acceptance authority.

The trusted coordinator freezes bindings before execution. Candidate/model code
must not have write access to the run store. Hashes detect changed references;
they are not signatures against an attacker with host filesystem privileges.
"""
from __future__ import annotations
import hashlib
from contextlib import contextmanager
from copy import deepcopy
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


def freeze_goal_bindings(store, project_id, run_id, plan):
    """Append bindings for admitted goals under a pre-frozen checker policy.

    Existing fixed-goal contracts are unchanged. These documents are evidence
    in FileRunStore, not a second plan or acceptance authority.
    """
    root=store.run_dir(project_id,run_id)
    path=root/'provenance_contract.json'
    if not path.exists(): return
    base=json.loads(path.read_text(encoding='utf-8'))
    templates=base.get('incremental_checker_bindings')
    if templates is None: return
    for goal in plan['goals']:
        if goal['checker'] not in templates:
            raise ValueError('goal checker is outside frozen provenance policy')
        if any(r not in base['requirements'] for r in goal['requirement_refs']):
            raise ValueError('goal requirements are outside frozen provenance policy')
        row={'kind':'IncrementalGoalBinding','goal_id':goal['id'],
             'requirement_refs':goal['requirement_refs'],'subject_refs':goal['subject_refs'],
             'checker_key':goal['checker'],'contract':{**templates[goal['checker']],
                 'condition_hash':identity(goal['acceptance'])}}
        store.immutable_json(root/'provenance_goals'/(identity(goal['id'])+'.json'),row)


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

    @contextmanager
    def read_binding_snapshot(self):
        """One read operation, no cache across views or evidence verification.

        Revalidate the full binding before returning any projected verdict.
        Individual receipts, referenced objects and current bytes remain checked.
        """
        if getattr(self, '_binding_snapshot', None) is not None:
            raise ProvenanceError('INVALID_PROVENANCE', 'nested binding snapshot')
        try:
            before = self._load_binding()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ProvenanceError('INVALID_PROVENANCE', 'binding snapshot unavailable') from exc
        self._binding_snapshot = before
        try:
            yield self
            try:
                after = self._load_binding()
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise ProvenanceError('INVALID_PROVENANCE', 'binding changed during read') from exc
            if after != before:
                raise ProvenanceError('INVALID_PROVENANCE', 'binding changed during read')
        finally:
            self._binding_snapshot = None

    def binding(self):
        snapshot = getattr(self, '_binding_snapshot', None)
        return deepcopy(snapshot) if snapshot is not None else self._load_binding()

    def _load_binding(self):
        path = self.root/'provenance_contract.json'
        if not path.exists():
            raise ProvenanceError('INSUFFICIENT_EVIDENCE','no coordinator-frozen provenance contract')
        obj = json.loads(path.read_text(encoding='utf-8'))
        if obj.get('kind') != 'ProvenanceContract':
            raise ProvenanceError('INVALID_PROVENANCE','invalid provenance contract type')
        if 'incremental_checker_bindings' in obj:
            obj['goals']=dict(obj['goals'])
            obj['current_artifacts']=dict(obj.get('current_artifacts',{}))
            workspace=Path(obj['workspace_root']).resolve()
            for path in sorted((self.root/'provenance_goals').glob('*.json')):
                row=json.loads(path.read_text(encoding='utf-8'))
                if (row.get('kind')!='IncrementalGoalBinding'
                        or path.stem!=identity(row['goal_id'])
                        or row['goal_id'] in obj['goals']
                        or any(r not in obj['requirements'] for r in row['requirement_refs'])):
                    raise ProvenanceError('INVALID_PROVENANCE','invalid incremental goal identity')
                template=obj['incremental_checker_bindings'][row['checker_key']]
                if {k:v for k,v in row['contract'].items() if k!='condition_hash'}!=template:
                    raise ProvenanceError('INVALID_PROVENANCE','incremental checker policy changed')
                obj['goals'][row['goal_id']]=row['contract']
                for subject in row['subject_refs']:
                    candidate=(workspace/subject).resolve()
                    if not candidate.is_relative_to(workspace):
                        raise ProvenanceError('INVALID_PROVENANCE','incremental artifact escape')
                    obj['current_artifacts'][subject]=str(candidate)
        from .checker_revision import load_checker_revisions
        revisions, _ = load_checker_revisions(self, obj)
        if revisions:
            obj['checker_revisions'] = revisions
        return obj

    def verify_check(self, result, goal, subjects):
        """Used by GoalAcceptance before accepting and when rebuilding a check."""
        try:
            binding = self.binding()
            check = result.as_dict()['outputs'].get('goal_check', {})
            witness = self.resolve(check.get('provenance_ref'), 'CheckWitness')
            contract = binding['goals'][goal['id']]
            if 'incremental_checker_bindings' in binding:
                row=self.resolve(witness.get('goal_binding_ref'),'IncrementalGoalBinding')
                expected_path=self.root/'provenance_goals'/(identity(goal['id'])+'.json')
                if (witness['goal_binding_ref']!=reference(self.store.root,expected_path)
                        or row['goal_id']!=goal['id'] or row['requirement_refs']!=goal['requirement_refs']
                        or row['subject_refs']!=goal['subject_refs'] or row['checker_key']!=goal['checker']
                        or row['contract']!=contract):
                    raise ProvenanceError('INVALID_PROVENANCE','incremental goal binding mismatch')
            if witness.get('checker_version') != contract['checker_version']:
                revision = binding.get('checker_revisions', {}).get(goal['checker'], {}).get(witness.get('checker_version'))
                if not revision or witness.get('checker_revision_ref') != revision['revision_ref']:
                    raise ProvenanceError('INVALID_PROVENANCE', 'checker version lacks qualified revision binding')
                contract = {**contract, 'checker_hash': revision['checker_hash'],
                            'checker_version': revision['checker_version']}
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
            if 'incremental_checker_bindings' in binding:
                from cgkn.execution.observations import Observations
                observations=Observations(self.store,self.project_id,self.run_id)
                if not raw.get('typed_observation_refs') or not raw.get('consumer_request_ref'):
                    raise ProvenanceError('INSUFFICIENT_EVIDENCE','consumer raw evidence missing')
                for ref in raw['typed_observation_refs']: observations.resolve(ref)
                consumed=self.resolve(raw['consumer_request_ref'],'IndependentMilestoneRequest')
                if (consumed.get('goal_id')!=goal['id'] or consumed.get('subjects')!=subjects
                        or consumed.get('acceptance')!=goal['acceptance']):
                    raise ProvenanceError('INVALID_PROVENANCE','consumer request binding mismatch')
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

    def register_worker_import(self, source_gate, receipt_ref, artifact, workspace, *, reason):
        """Freeze exact historical Worker authorship, never historical acceptance.

        Trusted controller operation while this run is idle. Model executors do
        not have access to FileRunStore. Evidence copies keep their byte hashes;
        they are not new Provider calls, receipts, charges, or execution nodes.
        """
        if not isinstance(reason,str) or not reason.strip():
            raise ProvenanceError('INVALID_PROVENANCE','explicit import reason required')
        with self.store.exclusive_file(self.root/'project_session.lock'):
            original=source_gate.resolve(receipt_ref)
            receipt=json.loads(original)
            if (receipt.get('project_id')!=source_gate.project_id or receipt.get('run_id')!=source_gate.run_id
                    or receipt_ref['path']!=reference(source_gate.store.root,
                        source_gate.root/'attempts'/receipt['node_id']/(receipt['attempt_id']+'.json'))['path']):
                raise ProvenanceError('INVALID_PROVENANCE','source attempt identity mismatch')
            def copy(raw):
                path=self.root/'import_objects'/hashlib.sha256(raw).hexdigest()
                self.store.immutable_blob(path,raw)
                return reference(self.store.root,path)
            metadata=receipt.get('metadata',{});proof=metadata.get('deliverable_check',{})
            staged=Path(proof.get('verified_artifacts',{}).get(artifact,{}).get('path','')).resolve()
            expected=(source_gate.root/'candidates'/receipt['node_id']/receipt['attempt_id']).resolve()
            if (not staged.is_relative_to(expected) or not staged.is_file()
                    or any(p.is_symlink() for p in [staged,*staged.parents] if p.is_relative_to(expected))):
                raise ProvenanceError('INVALID_PROVENANCE','source candidate outside bounded attempt')
            raw_ref=metadata.get('raw_execution_receipt_ref')
            raw=source_gate.resolve(raw_ref)
            responses={}
            for path in (source_gate.root/'provider_calls').glob('*/response.json'):
                value=json.loads(path.read_text(encoding='utf8'))
                responses.setdefault(value.get('request_id'),[]).append(path)
            ids={r.get('request_id') for r in receipt.get('usage',{}).get('completion_calls',[]) if r.get('request_id')}
            if receipt.get('usage',{}).get('request_id'):ids.add(receipt['usage']['request_id'])
            calls=[]
            for request_id in sorted(ids):
                found=responses.get(request_id,[])
                if len(found)!=1:raise ProvenanceError('INSUFFICIENT_EVIDENCE','source Worker response missing or ambiguous')
                path=found[0];request=path.with_name('request.json')
                calls.append({'request_id':request_id,'request_ref':copy(request.read_bytes()),
                              'response_ref':copy(path.read_bytes())})
            doc={'kind':'ImportedWorkerSource','artifact':artifact,'sha256':proof.get('subjects',{}).get(artifact),
                 'destination_logical_task':self.binding()['logical_task_id'],
                 'source_logical_task':source_gate.binding()['logical_task_id'],
                 'source_project_id':source_gate.project_id,'source_run_id':source_gate.run_id,
                 'source_store_root':str(source_gate.store.root),'original_receipt_ref':receipt_ref,
                 'receipt_ref':copy(original),'raw_execution_ref':copy(raw),
                 'candidate_ref':copy(staged.read_bytes()),'provider_calls':calls,'reason':reason}
            self._worker_import_origin(doc,workspace,doc['sha256'])
            path=self.root/'source_imports'/(identity(doc)+'.json')
            self.store.immutable_json(path,doc)
            return reference(self.store.root,path)

    def _worker_import_origin(self, doc, workspace, digest):
        """Validate copied provenance without requiring the old filesystem."""
        if (doc.get('kind')!='ImportedWorkerSource' or not doc.get('reason')
                or doc.get('destination_logical_task')!=self.binding()['logical_task_id']
                or not digest or doc.get('sha256')!=digest):
            raise ProvenanceError('INVALID_PROVENANCE','import binding mismatch')
        workspace=Path(workspace).resolve();relative=Path(doc['artifact']);candidate=(workspace/relative).resolve()
        if (relative.is_absolute() or '..' in relative.parts or not candidate.is_relative_to(workspace)
                or not candidate.is_file() or file_hash(candidate)!=digest):
            raise ProvenanceError('INVALID_PROVENANCE','imported current artifact mismatch')
        receipt=json.loads(self.resolve(doc['receipt_ref']));metadata=receipt.get('metadata',{})
        proof=metadata.get('deliverable_check',{})
        original=doc.get('original_receipt_ref',{})
        if (receipt.get('project_id')!=doc['source_project_id'] or receipt.get('run_id')!=doc['source_run_id']
                or receipt.get('status')!='SUCCEEDED' or receipt.get('error')
                or receipt.get('executor_ref')!='llm.cheap@1'
                or metadata.get('deliverable_verdict')!='VERIFIED' or proof.get('verdict')!='VERIFIED'
                or proof.get('subjects',{}).get(doc['artifact'])!=digest
                or proof.get('verified_artifacts',{}).get(doc['artifact'],{}).get('sha256')!=digest
                or original.get('sha256')!=doc['receipt_ref']['sha256']):
            raise ProvenanceError('INVALID_PROVENANCE','import lacks verified bounded Worker receipt')
        raw=json.loads(self.resolve(doc['raw_execution_ref']))
        if (metadata.get('raw_execution_receipt_ref',{}).get('sha256')!=doc['raw_execution_ref']['sha256']
                or raw.get('status')!='SUCCEEDED' or raw.get('error')
                or any(raw.get(k)!=receipt.get(k) for k in ('project_id','run_id','node_id','attempt_id','executor_ref'))
                or hashlib.sha256(self.resolve(doc['candidate_ref'])).hexdigest()!=digest):
            raise ProvenanceError('INVALID_PROVENANCE','import execution or candidate mismatch')
        ids={r.get('request_id') for r in receipt.get('usage',{}).get('completion_calls',[]) if r.get('request_id')}
        if receipt.get('usage',{}).get('request_id'):ids.add(receipt['usage']['request_id'])
        calls=doc.get('provider_calls',[])
        if not ids or len(calls)!=len(ids) or {r.get('request_id') for r in calls}!=ids:
            raise ProvenanceError('INVALID_PROVENANCE','import Provider call set mismatch')
        verified=[]
        for call in calls:
            request=json.loads(self.resolve(call['request_ref']));response=json.loads(self.resolve(call['response_ref']))
            config=request.get('config',{});route=response.get('routing',{})
            if (config.get('role')!='worker' or not request.get('identity')
                    or request['identity']!=response.get('identity') or response.get('request_id')!=call['request_id']):
                raise ProvenanceError('INVALID_PROVENANCE','import Worker call identity mismatch')
            real=bool(request.get('transport_kind')=='recorded_gateway' and response.get('model')
                and config.get('model_id') and route.get('identity_status')=='MATCH'
                and route.get('provider_id')==config.get('model') and route.get('actual_model')==response['model']
                and route.get('bound_model')==config['model_id'] and route.get('requested_model')==config['model_id'])
            if request.get('transport_kind')=='recorded_gateway' and not real:
                raise ProvenanceError('INVALID_PROVENANCE','import recorded model binding mismatch')
            verified.append({**call,'actual_model':response.get('model'),'real_provider_identity_bound':real})
        return {'sha256':digest,'node_id':receipt['node_id'],'attempt_id':receipt['attempt_id'],
                'source_project_id':doc['source_project_id'],'source_run_id':doc['source_run_id'],
                'receipt_ref':doc['receipt_ref'],'candidate_ref':doc['candidate_ref'],
                'provider_calls':verified,'imported':True,'old_acceptance_imported':False}

    def delivery_sources(self, acceptance, workspace, manifest):
        """Read-only source-origin projection for the existing delivery gate.

        A trusted observation is not proof of a paid Provider call. Keep that
        distinction explicit, and require every delivered source byte to have
        a bounded Worker receipt matching current bytes before finalization.
        Registered imports preserve original authorship, never old acceptance.
        """
        trusted=self.current(acceptance)
        if not trusted['acceptance']['complete'] or not manifest:
            raise ProvenanceError('INSUFFICIENT_EVIDENCE','project is not independently accepted')
        workspace=Path(workspace).resolve()
        manifest={name:value.removeprefix('sha256:') for name,value in manifest.items()}
        from cgkn.orchestration.capability_tree import CapabilityTree
        tree=CapabilityTree.from_dict(json.loads((self.root/'capability_tree.json').read_text(encoding='utf-8')))
        responses={}
        for path in (self.root/'provider_calls').glob('*/response.json'):
            response=json.loads(path.read_text(encoding='utf-8'))
            responses.setdefault(response.get('request_id'),[]).append((path,response))
        origins={}
        for node in tree.nodes:
            if not node.executable: continue
            from .store import StateStoreError
            try: result=self.store.load_result(self.project_id,self.run_id,node.id)
            except StateStoreError: continue
            if result.executor_ref!='llm.cheap@1' or not result.succeeded: continue
            raw=result.as_dict();metadata=raw['metadata'];proof=metadata.get('deliverable_check',{})
            if metadata.get('deliverable_verdict')!='VERIFIED' or proof.get('verdict')!='VERIFIED': continue
            request_ids={c.get('request_id') for c in raw['usage'].get('completion_calls',[]) if c.get('request_id')}
            if raw['usage'].get('request_id'): request_ids.add(raw['usage']['request_id'])
            if not request_ids: continue
            calls=[]
            for request_id in sorted(request_ids):
                matches=responses.get(request_id,[])
                if len(matches)!=1:
                    raise ProvenanceError('INSUFFICIENT_EVIDENCE','Worker Provider response is missing or ambiguous')
                response_path,response=matches[0];request_path=response_path.with_name('request.json')
                request=json.loads(request_path.read_text(encoding='utf-8'))
                if request['config']['role']!='worker' or request['identity']!=response['identity']:
                    raise ProvenanceError('INVALID_PROVENANCE','Worker call identity mismatch')
                route=response.get('routing',{})
                real=bool(request.get('transport_kind')=='recorded_gateway' and response.get('model')
                    and request['config'].get('model_id') and route.get('identity_status')=='MATCH'
                    and route.get('provider_id')==request['config']['model']
                    and route.get('actual_model')==response['model']
                    and route.get('bound_model')==request['config'].get('model_id')
                    and route.get('requested_model')==request['config'].get('model_id'))
                calls.append({'request_ref':reference(self.store.root,request_path),
                    'response_ref':reference(self.store.root,response_path),'actual_model':response['model'],
                    'request_id':request_id,'real_provider_identity_bound':real})
            self.resolve(metadata.get('raw_execution_receipt_ref'))
            for name,digest in proof.get('subjects',{}).items():
                if manifest.get(name)!=digest: continue
                candidate=(workspace/name).resolve()
                staged=proof.get('verified_artifacts',{}).get(name,{})
                staged_path=Path(staged.get('path','')).resolve()
                expected=self.root/'candidates'/node.id/result.attempt_id
                if (not candidate.is_relative_to(workspace) or not candidate.is_file() or file_hash(candidate)!=digest
                        or not staged_path.is_relative_to(expected.resolve()) or not staged_path.is_file()
                        or staged.get('sha256')!=digest or file_hash(staged_path)!=digest):
                    raise ProvenanceError('INVALID_PROVENANCE','delivered source differs from verified Worker candidate')
                origins.setdefault(name,[]).append({'sha256':digest,'node_id':node.id,'attempt_id':result.attempt_id,
                    'receipt_ref':reference(self.store.root,self.root/'attempts'/node.id/(result.attempt_id+'.json')),
                    'candidate_ref':reference(self.store.root,staged_path),'provider_calls':calls})
        for path in sorted((self.root/'source_imports').glob('*.json')):
            doc=json.loads(path.read_text(encoding='utf8'))
            if path.stem!=identity(doc):raise ProvenanceError('INVALID_PROVENANCE','source import manifest changed')
            name=doc.get('artifact')
            if name in origins or name not in manifest or doc.get('sha256')!=manifest[name]:continue
            origin=self._worker_import_origin(doc,workspace,manifest[name])
            origin['import_ref']=reference(self.store.root,path)
            origins.setdefault(name,[]).append(origin)
        if set(origins)!=set(manifest):
            raise ProvenanceError('INSUFFICIENT_EVIDENCE','delivered source lacks bounded Worker origin: '+','.join(sorted(set(manifest)-set(origins))))
        return {'status':'TRUSTED','source_origins':origins,'acceptance_chains':trusted['chains'],
            'real_provider_backed':all(c['real_provider_identity_bound'] for rows in origins.values() for row in rows for c in row['provider_calls']),
            'delivery_authorized':False}

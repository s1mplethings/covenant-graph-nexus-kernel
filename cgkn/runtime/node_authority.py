"""EA-2 authority over FileRunStore. Events are truth; views are disposable.

This is a trusted host service, not an OS sandbox. Workers receive permit data,
never this service or its store handle. No worker-supplied receipt is trusted.
"""
from dataclasses import asdict, replace
from pathlib import Path
import hashlib
import json
import math
import os
import uuid

from veriarbor.capability import CapabilityContract, CapabilityGateState
from veriarbor.model import stable_hash
from veriarbor.governance import (GovernanceError, InputBinding, EvaluationScope,
    independence_summary, ClaimEvidenceRelation)
from veriarbor.execution_authority import (
    NodeExecutionPermit, NodeExecutionResult, NodeCommitReceipt, DecisionRecord,
    CriticalCheckRegistry, NodeRuntimeRecord, EFFECT_OPERATIONS, utc_now)


def file_hash(path):
    p = Path(path)
    if not p.is_file() or p.is_symlink():
        raise ValueError('OUTPUT_BINDING_REJECT: missing file or symlink')
    return hashlib.sha256(p.read_bytes()).hexdigest()


class ExecutionAuthority:
    def __init__(self, store, project_id, run_id, *, registry=None):
        self.store, self.project_id, self.run_id = store, project_id, run_id
        self.root = store.run_dir(project_id, run_id) / 'NODE_RUNTIME'
        self.root.mkdir(parents=True, exist_ok=True)
        self.registry = registry or CriticalCheckRegistry()
        self.authority_id = 'host:' + stable_hash(str(store.root.resolve()))

    def _lock(self):
        return self.store.exclusive_file(self.root / 'authority.lock', wait_seconds=5)

    def events(self):
        try:
            return self._validated_events()
        except (ValueError,KeyError,TypeError) as exc:
            raise GovernanceError('AUTHORITY_INTEGRITY_FAILURE',str(exc)) from exc

    def _validated_events(self):
        p = self.root / 'events.jsonl'
        rows = [json.loads(line) for line in p.read_text(encoding='utf-8').splitlines()] if p.exists() else []
        previous = ''
        for i, row in enumerate(rows):
            if row['sequence'] != i or row['previous_hash'] != previous:
                raise ValueError('AUTHORITY_EVENT_CHAIN_REJECT')
            previous = row['event_hash']
            if stable_hash({k:v for k,v in row.items() if k != 'event_hash'}) != previous:
                raise ValueError('AUTHORITY_EVENT_HASH_REJECT')
            if row.get('schema_version')=='2' and (not row.get('event_id')
                    or row.get('payload_hash')!=stable_hash(row['data'])
                    or row.get('previous_event_hash')!=row['previous_hash']):
                raise ValueError('AUTHORITY_PAYLOAD_REJECT')
        return rows

    def _append(self, kind, node_id='', **data):
        events = self.events()
        row = dict(sequence=len(events), previous_hash=events[-1]['event_hash'] if events else '',
                   event_type=kind, node_id=node_id, project_id=self.project_id,
                   run_id=self.run_id, timestamp=utc_now(), data=data)
        row.update(schema_version='2',event_id='event-'+uuid.uuid4().hex,
                   previous_event_hash=row['previous_hash'],payload_hash=stable_hash(data))
        row['event_hash'] = stable_hash(row)
        with (self.root/'events.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False) + '\n'); f.flush(); os.fsync(f.fileno())
        if node_id:
            self.store._validate_segment(node_id)
            self.store.atomic_json(self.root/'nodes'/(node_id+'.json'), self.node_view(node_id))
        return row

    def _find(self, kind, key, value):
        return next((e['data'] for e in reversed(self.events())
                     if e['event_type'] == kind and e['data'].get(key) == value), None)

    def committed_tree(self):
        return next((e['data'] for e in reversed(self.events()) if e['event_type']=='TREE_COMMITTED'), None)

    def chain_checkpoint(self):
        events=self.events()
        return dict(kind='AuthorityChainCheckpoint',schema_version='1',scope='node_authority_checkpoint',
            project_id=self.project_id,run_id=self.run_id,authority_id=self.authority_id,
            sequence=len(events)-1,event_hash=events[-1]['event_hash'] if events else '')

    def verify_checkpoint(self,document,*,anchor=None,require_signature=False):
        if require_signature or 'signature' in document:
            from cgkn.state.release_authorization import verify_authority_checkpoint_signature
            try:verify_authority_checkpoint_signature(document,anchor or {})
            except ValueError as exc:raise GovernanceError('AUTHORITY_INTEGRITY_FAILURE',str(exc)) from exc
        if any(document.get(k)!=v for k,v in self.chain_checkpoint().items() if k not in {'sequence','event_hash'}):
            raise GovernanceError('AUTHORITY_INTEGRITY_FAILURE','checkpoint identity')
        events=self.events();position=document.get('sequence')
        if (not isinstance(position,int) or position<0 or position>=len(events)
                or events[position]['event_hash']!=document.get('event_hash')):
            raise GovernanceError('AUTHORITY_INTEGRITY_FAILURE','checkpoint chain prefix')
        return True

    def admit(self, tree, version, proposal, *, known_capabilities, catalog, policy):
        """Call real Admission, persist its result, never accept an admitted=True claim."""
        from cgkn.agent.project_agent import admit_proposal
        with self._lock():
            if proposal.project_id != self.project_id:
                raise ValueError('PROJECT_SCOPE_REJECT')
            current = self.committed_tree()
            if current and (current['tree'] != tree.as_dict() or current['tree_version'] != version):
                raise ValueError('UNMANAGED_TREE_MUTATION')
            if not current and any(n.executable for n in tree.nodes):
                raise ValueError('UNMANAGED_TREE_MUTATION: initial executable tree needs import, not adoption')
            result = admit_proposal(tree, version, proposal, known_capabilities=known_capabilities,
                                    catalog=catalog, policy=policy)
            if result.valid:
                from cgkn.agent.project_agent import REMOTE_EFFECTS, AdmissionResult
                for n in result.preview.nodes:
                    if not n.executable:continue
                    domains=set(n.config.get('leaf_contract',{}).get('effect_domains',()))
                    allowed=(set(policy.allowed_effect_domains)-set(REMOTE_EFFECTS)) | (set(REMOTE_EFFECTS) if policy.allow_remote_effects else set())
                    if not domains<=allowed:
                        result=AdmissionResult(False,'UNAUTHORIZED_EFFECT','updated node exceeds policy');break
            if result.valid:
                from cgkn.runtime.dag_runner import GraphEditRejected
                try:
                    self.validate_recovery_tree(result.preview, retry_nodes={op['node_id']
                        for op in proposal.proposed_operations if op['operation'] in {'retry_node','update_config'}})
                except GraphEditRejected as exc:
                    result=AdmissionResult(False,str(exc).split(':',1)[0],str(exc))
            aid = 'admission-' + uuid.uuid4().hex
            authorized_nodes={op['node_id'] for op in proposal.proposed_operations}
            if result.valid:
                from cgkn.orchestration.execution_dag import compile_tree
                from cgkn.orchestration.invalidation import downstream_closure
                invalidated={op['node_id'] for op in proposal.proposed_operations
                             if op['operation'] in {'retry_node','update_config'}}
                if invalidated:
                    authorized_nodes.update(downstream_closure(compile_tree(result.preview),invalidated))
            self._append('PROPOSAL_ADMITTED' if result.valid else 'PROPOSAL_REJECTED',
                         admission_id=aid, proposal_id=proposal.proposal_id,
                         valid=result.valid, code=result.code, base_version=version,
                         base_tree=tree.as_dict(), tree=result.preview.as_dict() if result.preview else None,
                         contracts=dict(policy.capability_contracts),
                         budget_scope=dict(policy.execution_budget) if policy.budget_state=='OK' else {},
                         authorized_nodes=sorted(authorized_nodes))
            return aid, result

    def validate_recovery_tree(self, tree, *, retry_nodes=()):
        """Reject unresolved reexecution before committing a proposed graph.

        Inspect the canonical run's outcomes and declared resources. A new
        node name or a config edit cannot authorize replay of an UNKNOWN effect.
        """
        from cgkn.state import StateStoreError
        from cgkn.orchestration.execution_dag import ExecutionDAG, compile_tree
        from cgkn.orchestration.invalidation import downstream_closure
        from .dag_runner import GraphEditRejected
        from cgkn.orchestration.leaf_contract import WRITING
        try:state=self.store.load_run(self.project_id,self.run_id)
        except StateStoreError:return
        if not state.execution_dag:return
        proposed=compile_tree(tree);original=ExecutionDAG.from_dict(state.execution_dag)
        retries={n for root in retry_nodes for n in downstream_closure(proposed,{root})}
        for old in original.nodes:
            record=state.nodes[old.id]
            if not record.latest_result_ref:continue
            result=self.store.load_result(self.project_id,self.run_id,old.id)
            if not (result.error and result.error.details.get('outcome_unknown')):continue
            if old.id in retries:
                raise GraphEditRejected('UNRESOLVED_OUTCOME: reconcile original attempt before retrying '+old.id)
            operation=old.config.get('operation_id')
            old_resources=old.config.get('resources',{})
            for node in proposed.nodes:
                if node.id in state.nodes:continue
                new_resources=node.config.get('resources',{})
                shared_write=any(old_resources[k]=='write' or new_resources[k]=='write'
                    for k in old_resources.keys() & new_resources.keys())
                old_leaf=old.config['leaf_contract'];new_leaf=node.config['leaf_contract']
                shared_write=shared_write or (bool(set(old_leaf['target_scope']) & set(new_leaf['target_scope']))
                    and (old_leaf['task_kind'] in WRITING or new_leaf['task_kind'] in WRITING))
                if (shared_write or (operation and node.config.get('operation_id')==operation)
                        or (not operation and node.capability_ref==old.capability_ref)):
                    raise GraphEditRejected('UNRESOLVED_OPERATION: reconcile unknown effect before replacement node '+node.id)

    def commit_tree(self, admission_id):
        from cgkn.orchestration.capability_tree import CapabilityTree
        with self._lock():
            admitted = self._find('PROPOSAL_ADMITTED', 'admission_id', admission_id)
            if not admitted:
                raise ValueError('ADMISSION_REQUIRED')
            current = self.committed_tree()
            if current and (current['tree_version'] != admitted['base_version'] or current['tree'] != admitted['base_tree']):
                raise ValueError('STALE_BASE_TREE_VERSION')
            tree = admitted['tree']
            self._append('TREE_COMMITTED', admission_id=admission_id,
                         tree_version=admitted['base_version']+1, tree=tree)
            self.store.save_definition(self.project_id, self.run_id, 'capability_tree.json', tree)
            for node in tree['nodes']:
                if node['id'] in admitted['authorized_nodes']:
                    self._append('NODE_ADMITTED',node['id'],admission_id=admission_id,
                                 tree_version=admitted['base_version']+1,
                                 capability_id=node['config'].get('capability_contract_id',node['capability_ref']))
            return CapabilityTree.from_dict(tree)

    def validate_tree(self, tree):
        current = self.committed_tree()
        if not current or current['tree'] != tree.as_dict():
            raise ValueError('UNMANAGED_TREE_MUTATION')
        path = self.store.run_dir(self.project_id,self.run_id)/'capability_tree.json'
        # Canonical store layout is checked through committed data as well as by callers.
        if path.exists() and json.loads(path.read_text(encoding='utf-8')) != current['tree']:
            raise ValueError('UNMANAGED_TREE_MUTATION')
        return current

    def issue_permit(self, *, node_id, contract, input_bindings=None, input_hashes=None,
                     allowed_effects=None, budget_scope=None, executor_identity=None,
                     parent_permit_id=None, expires_at=None, output_paths=(), input_manifest=None,
                     resource_decision_id=None, previous_permit_id=None):
        with self._lock():
            current = self.committed_tree()
            if not current:
                raise ValueError('TREE_COMMIT_REQUIRED')
            from cgkn.orchestration.capability_tree import CapabilityTree
            self.validate_tree(CapabilityTree.from_dict(current['tree']))
            admitted = self._find('PROPOSAL_ADMITTED','admission_id',current['admission_id'])
            node = next((n for n in current['tree']['nodes'] if n['id']==node_id), None)
            if not node or node_id not in admitted['authorized_nodes']:
                raise ValueError('NODE_NOT_ADMITTED')
            raw = admitted['contracts'].get(contract.capability_id)
            if not raw or CapabilityContract(**raw).fingerprint != contract.fingerprint:
                raise ValueError('CONTRACT_BINDING_REJECT')
            cfg = node['config']
            bound = cfg.get('capability_contract_id', node['capability_ref'])
            if bound != contract.capability_id:
                raise ValueError('CAPABILITY_BINDING_REJECT')
            effects = tuple(cfg.get('leaf_contract',{}).get('effect_domains', ()))
            allowed_effects = effects if allowed_effects is None else tuple(allowed_effects)
            if not set(allowed_effects) <= set(effects):
                raise ValueError('UNAUTHORIZED_EFFECT')
            budget_scope = admitted['budget_scope'] if budget_scope is None else budget_scope
            self._budget(budget_scope, admitted['budget_scope'])
            executor = cfg.get('executor_ref')
            if executor_identity is not None and executor_identity != executor:
                raise ValueError('EXECUTOR_BINDING_REJECT')
            if parent_permit_id:
                parent = self.validate_permit(parent_permit_id)
                if not set(allowed_effects)<=set(parent.allowed_effects):raise ValueError('UNAUTHORIZED_EFFECT')
                self._budget(budget_scope,parent.budget_scope)
            previous = [e['data']['permit'] for e in self.events() if e['event_type']=='NODE_PERMIT_ISSUED' and e['node_id']==node_id]
            if previous and self._permit(previous[-1]['permit_id']).status=='ACTIVE':
                raise ValueError('ACTIVE_ATTEMPT_EXISTS')
            bindings = dict(input_bindings or {})
            bindings['_output_paths'] = [str(Path(path).resolve()) for path in output_paths]
            bindings['_output_baseline'] = {path:file_hash(path) if Path(path).exists() else None
                                            for path in bindings['_output_paths']}
            hashes = dict(input_hashes or {})
            if input_manifest is not None:
                entries=[InputBinding(**r) if isinstance(r,dict) else r for r in input_manifest]
                manifest_hashes={r.path:r.sha256 for r in entries}
                if hashes and hashes!=manifest_hashes:raise ValueError('INPUT_BINDING_REJECT')
                hashes=manifest_hashes
                bindings['producer_receipts']={r.path:r.producer_receipt_id for r in entries if r.producer_receipt_id}
            else:
                # Compatibility normalization of an explicit hash manifest. No
                # undeclared filesystem inputs are discovered or silently adopted.
                entries=[InputBinding(path,path,h,node_id,
                    context=dict(bindings.get('contexts',{}).get(path,{})),
                    producer_receipt_id=bindings.get('producer_receipts',{}).get(path),
                    execution_mode='GOVERNED' if bindings.get('producer_receipts',{}).get(path) else 'IMPORTED_UNMANAGED')
                    for path,h in hashes.items()]
            if len({r.artifact_ref for r in entries})!=len(entries):raise ValueError('INPUT_BINDING_REJECT: duplicate artifact')
            for entry in entries:
                if entry.consumer!=node_id:raise ValueError('INPUT_BINDING_REJECT: consumer')
                if any(entry.context.get(k)!=v for k,v in entry.requirements.get('context',{}).items()):
                    raise ValueError('INPUT_BINDING_REJECT: context')
                if entry.producer_receipt_id:
                    self.validate_receipt(entry.producer_receipt_id,output_path=entry.path,output_hash=entry.sha256,
                                          **entry.requirements.get('producer',{}))
            bindings['manifest']=[r.as_dict() for r in entries]
            imported=[]
            for path,h in hashes.items():
                if file_hash(path)!=h:raise ValueError('INPUT_BINDING_REJECT')
                rid=bindings.get('producer_receipts',{}).get(path)
                if rid:
                    self.validate_receipt(rid,output_path=path,output_hash=h)
                elif contract.evidence_requirements.get('allow_imported_unmanaged') is True:
                    imported.append(path)
                else:raise ValueError('COMMIT_RECEIPT_REQUIRED: input '+path)
            bindings['imported_unmanaged_inputs']=imported
            checker_ids={check.checker_id:self.registry.identity(check.checker_id).as_dict()
                         for check in contract.critical_checks if check.checker_id in self.registry.identities()}
            resource_decision_id=resource_decision_id or 'resource-'+uuid.uuid4().hex
            if self._find('NODE_RESOURCE_DECISION','resource_decision_id',resource_decision_id):
                raise ValueError('PERMIT_MISMATCH: resource identity reused')
            if previous_permit_id:
                prior=self._permit(previous_permit_id)
                if prior.status not in {'REVOKED','EXPIRED'} or prior.node_id!=node_id:
                    raise ValueError('PERMIT_MISMATCH: repair predecessor must be failed attempt of same node')
                if prior.admission_id==current['admission_id']:
                    raise ValueError('ADMISSION_REQUIRED: repair requires a new admitted proposal')
            permit = NodeExecutionPermit('permit-'+uuid.uuid4().hex,self.run_id,self.project_id,node_id,
                contract.capability_id,current['admission_id'],current['tree_version'],contract.fingerprint,
                bindings,hashes,allowed_effects,dict(budget_scope),executor,len(previous)+1,
                parent_permit_id=parent_permit_id,expires_at=expires_at,
                resource_decision_id=resource_decision_id,previous_permit_id=previous_permit_id,
                checker_identities=checker_ids)
            self._append('NODE_PERMIT_ISSUED', node_id, permit=permit.as_dict(), permit_id=permit.permit_id,
                         contract=asdict(contract), goal=contract.semantic_goal)
            self._resource_update(permit,'OPEN',{})
            return permit

    @staticmethod
    def _budget(usage, limits):
        for k,v in usage.items():
            if (isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v)
                    or v<0 or k not in limits or v>limits[k]):
                raise ValueError('BUDGET_SCOPE_REJECT')

    def _permit(self, permit_id):
        event = self._find('NODE_PERMIT_ISSUED','permit_id',permit_id)
        if event is None:raise ValueError('PERMIT_NOT_ISSUED')
        p = NodeExecutionPermit(**event['permit'])
        for e in self.events():
            if e['data'].get('permit_id')!=permit_id:continue
            if e['event_type']=='NODE_COMMITTED':p=replace(p,status='CONSUMED')
            if e['event_type']=='NODE_PERMIT_REVOKED':p=replace(p,status='REVOKED')
        if p.status=='ACTIVE' and p.expires_at and utc_now()>=p.expires_at:p=replace(p,status='EXPIRED')
        return p

    def validate_permit(self, permit_id, **expected):
        if not isinstance(permit_id,str):raise ValueError('PERMIT_ID_REQUIRED')
        p = self._permit(permit_id)
        if p.status!='ACTIVE':raise ValueError('PERMIT_'+p.status)
        current = self.committed_tree()
        if not current or current['tree_version']!=p.tree_version:raise ValueError('TREE_VERSION_REJECT')
        from cgkn.orchestration.capability_tree import CapabilityTree
        self.validate_tree(CapabilityTree.from_dict(current['tree']))
        for k,v in expected.items():
            if getattr(p,k)!=v:raise ValueError('PERMIT_BINDING_REJECT:'+k)
        for path,h in p.input_hashes.items():
            if file_hash(path)!=h:raise ValueError('INPUT_BINDING_REJECT')
            rid=p.input_bindings.get('producer_receipts',{}).get(path)
            if rid:self.validate_receipt(rid,output_path=path,output_hash=h)
        return p

    def permit(self, permit_id):
        """Public immutable lifecycle view, including consumed/revoked permits."""
        return self._permit(permit_id)

    def audit_receipt(self, receipt_id):
        row=self._find('NODE_COMMITTED','receipt_id',receipt_id)
        if not row:raise ValueError('COMMIT_RECEIPT_REQUIRED')
        r=NodeCommitReceipt(**row['receipt'])
        return dict(schema_status=r.schema_status,receipt=r.as_dict(),
            checker_audit=self.registry.audit_identities(r.checker_identities),integrity='VALID')

    def begin_node_execution(self, permit_id):
        with self._lock():
            p=self.validate_permit(permit_id)
            if self._find('NODE_EXECUTION_STARTED','permit_id',permit_id):raise ValueError('PERMIT_ALREADY_STARTED')
            self._append('NODE_EXECUTION_STARTED',p.node_id,permit_id=permit_id)
        return p

    def staging_dir(self, permit_id):
        p=self.validate_permit(permit_id)
        path=self.root/'staging'/p.permit_id
        path.mkdir(parents=True,exist_ok=True)
        return path

    def use_effect(self, permit_id, operation, *, domain=None, resource_usage=None):
        """Call BEFORE transport/write/export. READ and COMPUTE need no operation call."""
        with self._lock():
            p=self.validate_permit(permit_id)
            if not self._find('NODE_EXECUTION_STARTED','permit_id',permit_id):raise ValueError('EXECUTION_NOT_STARTED')
            required=EFFECT_OPERATIONS.get(operation)
            if required is None or required=='receipt_authority' or (domain is not None and domain!=required) or required not in p.allowed_effects:
                self._append('NODE_BLOCKED',p.node_id,permit_id=permit_id,violation='UNAUTHORIZED_EFFECT')
                self._append('NODE_PERMIT_REVOKED',p.node_id,permit_id=permit_id,reason='UNAUTHORIZED_EFFECT')
                self._resource_update(p,'BLOCKED',{'failure_category':'UNAUTHORIZED_EFFECT'})
                raise ValueError('UNAUTHORIZED_EFFECT')
            used={}
            for e in self.events():
                if e['event_type']=='NODE_EFFECT_USED' and e['data'].get('permit_id')==permit_id:
                    for k,v in e['data']['resource_usage'].items():used[k]=used.get(k,0)+v
            for k,v in (resource_usage or {}).items():used[k]=used.get(k,0)+v
            try:self._budget(used,p.budget_scope)
            except ValueError:
                self._append('NODE_BLOCKED',p.node_id,permit_id=permit_id,violation='BUDGET_EXCEEDED',requested_usage=used)
                self._append('NODE_PERMIT_REVOKED',p.node_id,permit_id=permit_id,reason='BUDGET_EXCEEDED')
                self._resource_update(p,'BLOCKED',{'failure_category':'BUDGET_EXCEEDED'})
                raise
            self._append('NODE_EFFECT_USED',p.node_id,permit_id=permit_id,operation=operation,
                         domain=required,resource_usage=dict(resource_usage or {}))

    def perform_effect(self, permit_id, operation, callback, *, resource_usage=None):
        import time
        self.use_effect(permit_id,operation,resource_usage=resource_usage)
        started=time.monotonic()
        try:
            value=callback();outcome='SUCCEEDED';return value
        except Exception:
            outcome='FAILED';raise
        finally:
            self.finish_effect(permit_id,operation,duration_seconds=time.monotonic()-started,
                               cost=(resource_usage or {}).get('cost'),outcome=outcome)

    def finish_effect(self,permit_id,operation,*,duration_seconds,cost,outcome):
        with self._lock():
            p=self._permit(permit_id)
            self._append('NODE_EFFECT_FINISHED',p.node_id,permit_id=permit_id,operation=str(operation),
                         duration_seconds=duration_seconds,cost=cost,outcome=outcome)

    def run_subprocess(self, permit_id, argv, *, timeout=30, cwd=None):
        """Bounded local transport. Child receives data, Host alone can commit.

        Child writes NodeExecutionResult JSON to NODE_EXECUTION_RESULT. All child
        outputs must be in the permit staging directory or predeclared paths.
        """
        import subprocess
        p=self.begin_node_execution(permit_id)
        directory=self.staging_dir(permit_id)
        permit_path=directory/'permit.json';result_path=directory/'result.json'
        self.store.immutable_json(permit_path,p.as_dict())
        env={**os.environ,'NODE_EXECUTION_PERMIT':str(permit_path),
             'NODE_EXECUTION_RESULT':str(result_path)}
        try:
            self.perform_effect(permit_id,'EXTERNAL_SUBPROCESS',
                lambda:subprocess.run(list(argv),cwd=cwd,env=env,timeout=timeout,check=True,capture_output=True))
            result=NodeExecutionResult(**json.loads(result_path.read_text(encoding='utf-8')))
            if result.permit_id!=permit_id:raise ValueError('PERMIT_BINDING_REJECT')
            self.submit_node_result(result)
            return result
        except Exception:
            if self._permit(permit_id).status=='ACTIVE':self.revoke_permit(permit_id,'SUBPROCESS_FAILED')
            raise

    def validate_skill_lineage(self, validation):
        """Host callback for existing Skill promotion; claimed gates aren't enough."""
        if (validation.project_id,validation.run_id)!=(self.project_id,self.run_id):return False
        receipt=self.validate_receipt(validation.commit_receipt_id)
        if (validation.contract_hash!=receipt.contract_hash or
                validation.checker_identities!=receipt.checker_identities):return False
        permit=self._permit(receipt.permit_id)
        if permit.input_bindings.get('strategy_hash')!=validation.strategy_hash:return False
        from cgkn.adapters.veriarbor.capability_adapter import load
        row=load(self.store,self.project_id,self.run_id)['nodes'].get(receipt.node_id,{})
        accepted=self._find('NODE_ACCEPTANCE_RECORDED','receipt_id',receipt.receipt_id)
        return (row.get('commit_receipt_id')==receipt.receipt_id and row.get('execution_mode')=='GOVERNED'
                and row.get('gates')==validation.gates.as_dict() and accepted is not None
                and accepted['gate_status']==validation.gates.as_dict())

    def _resource_update(self, permit, outcome, details):
        from cgkn.adapters.veriarbor.capability_adapter import load
        path=self.store.run_dir(self.project_id,self.run_id)/'capability_governance.json'
        with self.store.exclusive_file(path.with_suffix('.lock'),wait_seconds=5):
            state=load(self.store,self.project_id,self.run_id)
            row=next((r for r in state['resource_decisions'] if r['id']==permit.resource_decision_id),None)
            if row is None:
                row=dict(id=permit.resource_decision_id,capability_id=permit.capability_id,
                    node_id=permit.node_id,permit_id=permit.permit_id,budget_scope=dict(permit.budget_scope),
                    expected_executor=permit.executor_identity,status='PLANNED',schema_version='2')
                state['resource_decisions'].append(row)
            if row['permit_id']!=permit.permit_id:raise ValueError('PERMIT_MISMATCH: resource decision reused')
            duration=sum(e['data'].get('duration_seconds',0) for e in self.events()
                         if e['event_type']=='NODE_EFFECT_FINISHED' and e['data'].get('permit_id')==permit.permit_id)
            costs=[e['data'].get('cost') for e in self.events()
                   if e['event_type']=='NODE_EFFECT_FINISHED' and e['data'].get('permit_id')==permit.permit_id
                   and e['data']['operation'] in {'PROVIDER_CALL','EXTERNAL_SUBPROCESS','EXTERNAL_SUBPROCESS_EFFECT'}]
            cost=None if any(c is None for c in costs) else sum(costs)
            usage=dict(details.get('usage',row.get('actual_usage',{})))
            measured={}
            for event in self.events():
                if event['event_type']=='NODE_EFFECT_USED' and event['data'].get('permit_id')==permit.permit_id:
                    for key,value in event['data']['resource_usage'].items():measured[key]=measured.get(key,0)+value
            for key,value in measured.items():usage[key]=max(usage.get(key,0),value)
            row.update(closure_state='OPEN' if outcome=='OPEN' else 'CLOSED',actual_outcome=outcome,
                actual_usage=usage,actual_duration=duration,actual_cost=cost,
                acceptance_status=details.get('gates',{}).get('semantic_status','NOT_TESTED'),
                utility_status=details.get('gates',{}).get('utility_status','NOT_TESTED'),
                failure_category=details.get('failure_category'),repair_link=permit.previous_permit_id)
            if outcome=='BLOCKED':row['status']='FAILED'
            elif outcome=='COMMITTED':
                row['status']='ACCEPTED' if row['acceptance_status']==row['utility_status']=='PASS' else 'EXECUTED_PENDING_ACCEPTANCE'
            if permit.previous_permit_id:
                trace=next((r for r in state['failure_repair_traces'] if r['id']=='repair-'+permit.permit_id),None)
                if trace is None:
                    trace=dict(id='repair-'+permit.permit_id,capability_id=permit.capability_id,
                        failed_permit=permit.previous_permit_id,failed_receipt_state='NO_COMMIT_RECEIPT',
                        repair_proposal=self._find('PROPOSAL_ADMITTED','admission_id',permit.admission_id)['proposal_id'],
                        new_permit=permit.permit_id,status='OPEN')
                    state['failure_repair_traces'].append(trace)
                previous=next((r for r in state['resource_decisions'] if r.get('permit_id')==permit.previous_permit_id),{})
                delta=details.get('acceptance_delta') or {'semantic_before':previous.get('acceptance_status','NOT_RECORDED'),
                    'semantic_after':row['acceptance_status'],'utility_before':previous.get('utility_status','NOT_RECORDED'),
                    'utility_after':row['utility_status']}
                trace.update(artifact_after=details.get('artifact_after',trace.get('artifact_after')),acceptance_delta=delta,
                             closure_state=row['closure_state'],actual_outcome=outcome,status=row['closure_state'])
            self.store.atomic_json(path,state)
        self._append('NODE_RESOURCE_DECISION',permit.node_id,permit_id=permit.permit_id,resource_decision=dict(row),
                     resource_decision_id=permit.resource_decision_id,repair_lineage=dict(trace) if permit.previous_permit_id else {})

    def assert_resources_closed(self, permit_id):
        p=self._permit(permit_id)
        if p.resource_decision_id is None:return  # Explicit old receipt schema, not fabricated history.
        from cgkn.adapters.veriarbor.capability_adapter import load
        row=next((r for r in load(self.store,self.project_id,self.run_id)['resource_decisions']
                  if r['id']==p.resource_decision_id),None)
        event=self._find('NODE_RESOURCE_DECISION','permit_id',permit_id)
        if not row or row.get('closure_state')!='CLOSED' or not event or event['resource_decision'].get('closure_state')!='CLOSED':
            raise GovernanceError('RESOURCE_DECISION_UNCLOSED')
        return row

    def evaluate_outcome(self, receipt_id, checker_id, *, evaluation_scope, context=None):
        """Execute an independent registered evaluator; never qualify Worker booleans."""
        receipt=self.validate_receipt(receipt_id)
        identity=self.registry.identity(checker_id).as_dict()
        if checker_id==self._permit(receipt.permit_id).executor_identity:
            raise ValueError('CHECKER_IDENTITY_MISMATCH: executor cannot qualify its outcome')
        scope=EvaluationScope(**{**evaluation_scope,'evaluator_identity':identity})
        if file_hash(scope.sample_ref)!=scope.sample_hash:raise ValueError('EVALUATION_SCOPE_VIOLATION: sample hash')
        if scope.population_hash and file_hash(scope.population_ref)!=scope.population_hash:
            raise ValueError('EVALUATION_SCOPE_VIOLATION: population hash')
        result=self.registry.invoke(checker_id,(),dict(receipt=receipt.as_dict(),evaluation_scope=scope.as_dict(),
                                                     context=context or {}),role='OUTCOME')
        if not isinstance(result,dict) or not isinstance(result.get('observations'),dict):
            raise ValueError('invalid outcome evaluator result')
        with self._lock():
            oid='outcome-'+uuid.uuid4().hex
            self._append('NODE_OUTCOME_EVALUATED',receipt.node_id,permit_id=receipt.permit_id,
                receipt_id=receipt_id,outcome_id=oid,checker_identity=identity,
                evaluation_scope=scope.as_dict(),observations=result['observations'])
        return oid

    def acceptance_observations(self, receipt_id, outcome_ids):
        from veriarbor.capability import Observation
        from veriarbor.model import Evidence
        receipt=self.validate_receipt(receipt_id);observations={};versions={};checkers={};scopes={}
        def observation(key,value,identity,evidence_refs,context=None):
            version=stable_hash(identity);checkers[identity['checker_id']]=version
            versions[receipt.receipt_id]=stable_hash(receipt.as_dict())
            return Observation(value,Evidence('VERIFIED',dict(versions),{identity['checker_id']:version},tuple(evidence_refs),qualified=True,
                scope={'PROJECT':self.project_id,'CAPABILITY':receipt.capability_id},
                context={'contract_hash':receipt.contract_hash,**(context or {})}))
        host={'checker_id':'host.node.commit','implementation_hash':'receipt-validation-v2','policy_hash':'commit'}
        for key in ('implemented','executed'):observations[key]=observation(key,True,host,(receipt_id,))
        for oid in outcome_ids:
            event=self._find('NODE_OUTCOME_EVALUATED','outcome_id',oid)
            if not event or event['receipt_id']!=receipt_id:raise ValueError('RECEIPT_INVALID: outcome')
            scope=EvaluationScope(**event['evaluation_scope'])
            if file_hash(scope.sample_ref)!=scope.sample_hash:raise ValueError('EVALUATION_SCOPE_VIOLATION: changed sample')
            if scope.population_hash and file_hash(scope.population_ref)!=scope.population_hash:
                raise ValueError('EVALUATION_SCOPE_VIOLATION: changed population')
            for key,row in event['observations'].items():
                if not isinstance(row,dict) or 'actual' not in row or 'conclusion_scope' not in row:
                    raise ValueError('EVALUATION_SCOPE_VIOLATION: observation scope missing')
                observations[key]=observation(key,row['actual'],event['checker_identity'],(scope.sample_ref,oid),
                    {'evaluation_id':scope.evaluation_id,'sample_hash':scope.sample_hash,
                     'population_hash':scope.population_hash,'generalization_target':scope.generalization_target})
                scopes[key]=(scope,row['conclusion_scope'])
        return observations,versions,checkers,scopes

    def record_acceptance_event(self, receipt_id, gates, *, acceptance_delta=None):
        receipt=self.validate_receipt(receipt_id)
        with self._lock():
            self._append('NODE_ACCEPTANCE_RECORDED',receipt.node_id,permit_id=receipt.permit_id,
                         receipt_id=receipt_id,operation='ACCEPTANCE_WRITE',gate_status=gates.as_dict())
            self._resource_update(self._permit(receipt.permit_id),'COMMITTED',
                dict(gates=gates.as_dict(),artifact_after=dict(receipt.output_hashes),acceptance_delta=acceptance_delta))

    def record_skill_lineage(self, receipt_id, manifest):
        receipt=self.validate_receipt(receipt_id)
        if receipt_id not in manifest.source_receipts or manifest.source_capability!=receipt.capability_id:
            raise ValueError('RECEIPT_INVALID: skill source')
        with self._lock():
            self._append('NODE_SKILL_LINEAGE',receipt.node_id,permit_id=receipt.permit_id,
                receipt_id=receipt_id,operation='SKILL_PROMOTION',skill_state=manifest.as_dict())

    def submit_node_result(self, result):
        if not isinstance(result,NodeExecutionResult):raise ValueError('NODE_RESULT_REQUIRED')
        with self._lock():
            p=self._permit(result.permit_id)
            if p.status!='ACTIVE':raise ValueError('PERMIT_'+p.status)
            if not self._find('NODE_EXECUTION_STARTED','permit_id',p.permit_id):raise ValueError('EXECUTION_NOT_STARTED')
            if self._find('NODE_RESULT_SUBMITTED','permit_id',p.permit_id):raise ValueError('RESULT_ALREADY_SUBMITTED')
            self._append('NODE_RESULT_SUBMITTED',p.node_id,permit_id=p.permit_id,result=result.as_dict())
            for raw in result.decision_records:
                d=DecisionRecord(**raw) if isinstance(raw,dict) else raw
                self._append('NODE_DECISION_RECORDED',p.node_id,permit_id=p.permit_id,decision=d.as_dict())

    def commit_node_execution(self, permit_id):
        with self._lock():
            p=self._permit(permit_id)
            if p.status!='ACTIVE':raise ValueError('PERMIT_'+p.status)
            event=self._find('NODE_RESULT_SUBMITTED','permit_id',permit_id)
            if not event:raise ValueError('RESULT_REQUIRED')
            result=NodeExecutionResult(**event['result'])
            spec=self._find('NODE_PERMIT_ISSUED','permit_id',permit_id)
            contract=CapabilityContract(**spec['contract'])
            checks=[]; violations=[]
            relations=[];derivations=[];independence={}
            effects=set(result.effects_used)
            used=dict(result.resource_usage)
            reservations={}
            for e in self.events():
                if e['event_type']=='NODE_EFFECT_USED' and e['data'].get('permit_id')==permit_id:
                    effects.add(e['data']['domain'])
                    for k,v in e['data']['resource_usage'].items():reservations[k]=reservations.get(k,0)+v
            try:
                self.validate_permit(permit_id)
                observed=list(result.consumed_inputs) if result.consumed_inputs else list(p.input_bindings.get('manifest',()))
                if observed!=list(p.input_bindings.get('manifest',())):
                    raise ValueError('INPUT_BINDING_REJECT: consumed input manifest differs')
                if result.input_hashes!=p.input_hashes:raise ValueError('INPUT_BINDING_REJECT')
                if not effects<=set(p.allowed_effects):raise ValueError('UNAUTHORIZED_EFFECT')
                self._budget(result.resource_usage,p.budget_scope)
                used={k:max(used.get(k,0),v) for k,v in reservations.items()} | {k:v for k,v in used.items() if k not in reservations}
                self._budget(used,p.budget_scope)
                for path,h in result.output_hashes.items():
                    resolved=Path(path).resolve()
                    staging=(self.root/'staging'/permit_id).resolve()
                    declared=p.input_bindings.get('_output_paths',())
                    if not resolved.is_relative_to(staging) and str(resolved) not in declared:
                        raise ValueError('OUTPUT_SCOPE_REJECT')
                    if p.input_bindings.get('_output_baseline',{}).get(str(resolved))==h:
                        raise ValueError('POST_HOC_OUTPUT_REJECT')
                    if file_hash(path)!=h:raise ValueError('OUTPUT_BINDING_REJECT')
            except ValueError as exc:violations.append(str(exc))
            decisions=tuple(DecisionRecord(**d) if isinstance(d,dict) else d for d in result.decision_records)
            for check in contract.critical_checks:
                checked=self.registry.evaluate(check,decisions,dict(permit=p.as_dict(),result=result.as_dict()))
                if checked.checker_identity and checked.checker_identity!=p.checker_identities.get(check.checker_id):
                    checked=replace(checked,status='UNKNOWN',reason='CHECKER_IDENTITY_MISMATCH')
                checks.append(checked.as_dict())
                relations.extend(checked.claim_relations);derivations.extend(checked.derivations)
                self._append('NODE_CRITICAL_CHECK_RESULT',p.node_id,permit_id=permit_id,check=checked.as_dict())
                if check.required and (checked.status=='FAIL' or checked.reason in {'CHECKER_MISSING','CHECKER_IDENTITY_MISMATCH'}
                        or (checked.status=='UNKNOWN' and check.unknown_policy=='BLOCK')):
                    violations.append('CRITICAL_CHECK_BLOCKED:'+check.check_id)
                elif checked.status=='UNKNOWN':
                    self._append('NODE_WARNING',p.node_id,permit_id=permit_id,
                                 warning='SEMANTIC_UNKNOWN_ALLOWED:'+check.check_id)
            required_claims=set(result.claim_refs) or {d.claim_ref or d.decision_id for d in decisions if d.output_claim}
            if not contract.conflict_collection and any(r['relation']=='CONTRADICTS' for r in relations):
                violations.append('CLAIM_CONTRADICTED')
            if contract.requires_claim_support:
                if not required_claims:violations.append('CLAIM_SUPPORT_REQUIRED')
                for claim in required_claims:
                    matching=[r for r in relations if r['claim_ref']==claim
                              and r['scope'].get('node_id')==p.node_id
                              and r['scope'].get('project_id')==p.project_id
                              and r['scope'].get('run_id')==p.run_id
                              and r['evidence_refs'] and set(r['evidence_refs'])<=set(p.input_hashes)]
                    if any(r['relation']=='CONTRADICTS' for r in matching) and not contract.conflict_collection:
                        violations.append('CLAIM_CONTRADICTED')
                    elif not any(r['relation']=='SUPPORTS' or (contract.conflict_collection and r['relation']=='CONTRADICTS') for r in matching):
                        if contract.claim_unknown_policy=='BLOCK':violations.append('CLAIM_SUPPORT_REQUIRED')
                        else:
                            checks.append(dict(check_id='claim-support',checker_id='host.relation.policy',status='UNKNOWN'))
                            self._append('NODE_WARNING',p.node_id,permit_id=permit_id,warning='CLAIM_SUPPORT_REQUIRED')
            if contract.independence_policy:
                try:
                    independence=independence_summary(derivations,dict(contract.independence_policy))
                    if independence['independent_count']<contract.independence_policy.get('minimum_count',0):
                        raise ValueError('INDEPENDENCE_POLICY_VIOLATION: insufficient independent events')
                except ValueError as exc:violations.append(str(exc))
            self._append('NODE_SEMANTICS_RECORDED',p.node_id,permit_id=permit_id,
                         claim_relations=relations,derivation_summary=independence)
            semantic=('FAIL' if any(c['status']=='FAIL' for c in checks) else
                      'UNKNOWN' if any(c['status']=='UNKNOWN' for c in checks) else
                      'PASS' if checks else 'NOT_TESTED')
            if semantic=='PASS' and (contract.semantic_invariants or contract.positive_controls
                    or contract.negative_controls or contract.failure_conditions or contract.forbidden_substitutes
                    or any(m.stage=='SEMANTIC_VERIFIED' for m in contract.acceptance_metrics)):
                semantic='NOT_TESTED'  # Existing semantic obligations still need their observations.
            if violations and semantic=='PASS':semantic='BLOCKED'
            gates=CapabilityGateState('PASS','PASS',semantic).as_dict()
            if violations:
                self._append('NODE_QUARANTINED',p.node_id,permit_id=permit_id,
                             output_hashes=dict(result.output_hashes),violations=violations,gate_status=gates)
                self._append('NODE_BLOCKED',p.node_id,permit_id=permit_id,violations=violations,gate_status=gates)
                self._append('NODE_PERMIT_REVOKED',p.node_id,permit_id=permit_id,reason='COMMIT_REJECTED')
                self._resource_update(p,'BLOCKED',dict(usage=used,gates=gates,failure_category=violations[0]))
                raise ValueError(';'.join(violations))
            self._resource_update(p,'COMMITTED',dict(usage=used,gates=gates,artifact_after=dict(result.output_hashes)))
            self.assert_resources_closed(p.permit_id)
            events=self.events()
            receipt=NodeCommitReceipt('receipt-'+uuid.uuid4().hex,permit_id,self.run_id,self.project_id,
                p.node_id,p.capability_id,p.tree_version,p.contract_hash,dict(p.input_hashes),
                dict(result.output_hashes),tuple(sorted(effects)),tuple(checks),result.evidence_refs,gates,
                p.execution_epoch,self.authority_id,checker_identities=dict(p.checker_identities),
                claim_relations=tuple(relations),derivation_summary=independence,
                input_manifest=tuple(p.input_bindings.get('manifest',())),resource_decision_id=p.resource_decision_id,
                authority_checkpoint={'sequence':len(events),'previous_event_hash':events[-1]['event_hash'] if events else ''},schema_version='2')
            # One durable event atomically consumes the permit AND creates the receipt.
            self._append('NODE_COMMITTED',p.node_id,permit_id=permit_id,receipt_id=receipt.receipt_id,
                         receipt=receipt.as_dict(),budget_used=used)
            return receipt

    def consume_permit(self, permit_id):
        return self.commit_node_execution(permit_id)

    def revoke_permit(self, permit_id, reason='HOST_REVOKED'):
        with self._lock():
            p=self._permit(permit_id)
            if p.status=='CONSUMED':raise ValueError('PERMIT_CONSUMED')
            self._append('NODE_PERMIT_REVOKED',p.node_id,permit_id=permit_id,reason=reason)
            self._resource_update(p,'BLOCKED',{'failure_category':reason})

    def validate_receipt(self, receipt_id, *, output_path=None, output_hash=None, **expected):
        return self._validate_receipt(receipt_id,output_path=output_path,output_hash=output_hash,
                                      require_current_epoch=True,**expected)

    def _validate_receipt(self, receipt_id, *, output_path=None, output_hash=None, require_current_epoch=True, **expected):
        if not isinstance(receipt_id,str):raise ValueError('RECEIPT_ID_REQUIRED')
        row=self._find('NODE_COMMITTED','receipt_id',receipt_id)
        if not row:raise ValueError('COMMIT_RECEIPT_REQUIRED')
        r=NodeCommitReceipt(**row['receipt']);p=self._permit(r.permit_id)
        if r.schema_version=='2':
            event=next(e for e in self.events() if e['event_type']=='NODE_COMMITTED' and e['data'].get('receipt_id')==receipt_id)
            if r.authority_checkpoint!={'sequence':event['sequence'],'previous_event_hash':event['previous_hash']}:
                raise GovernanceError('AUTHORITY_INTEGRITY_FAILURE','receipt checkpoint mismatch')
            self.assert_resources_closed(p.permit_id)
        if p.status!='CONSUMED' or r.authority_id!=self.authority_id:raise ValueError('RECEIPT_AUTHORITY_REJECT')
        latest=next(e['data']['permit'] for e in reversed(self.events())
                    if e['event_type']=='NODE_PERMIT_ISSUED' and e['node_id']==r.node_id)
        if require_current_epoch and latest['execution_epoch']!=r.execution_epoch:raise ValueError('STALE_EXECUTION_EPOCH')
        for k in ('project_id','run_id','node_id','capability_id','tree_version','contract_hash','input_hashes','execution_epoch'):
            if getattr(r,k)!=getattr(p,k):raise ValueError('RECEIPT_BINDING_REJECT:'+k)
        for k,v in expected.items():
            if getattr(r,k)!=v:raise ValueError('RECEIPT_BINDING_REJECT:'+k)
        if not set(r.effects_used)<=set(p.allowed_effects):raise ValueError('UNAUTHORIZED_EFFECT')
        contract=CapabilityContract(**self._find('NODE_PERMIT_ISSUED','permit_id',r.permit_id)['contract'])
        checks={c['check_id']:c for c in r.critical_check_results}
        for spec in contract.critical_checks:
            c=checks.get(spec.check_id)
            if spec.required and (not c or c['checker_id']!=spec.checker_id or c['status']=='FAIL'
                    or c['reason']=='CHECKER_MISSING' or (c['status']!='PASS' and spec.unknown_policy=='BLOCK')):
                raise ValueError('CRITICAL_CHECK_BLOCKED')
        for path,h in r.output_hashes.items():
            if file_hash(path)!=h:raise ValueError('OUTPUT_BINDING_REJECT')
        if output_path is not None and (output_path not in r.output_hashes or r.output_hashes[output_path]!=output_hash):
            raise ValueError('OUTPUT_BINDING_REJECT')
        return r

    def validate_execution_result(self,result):
        """Bind legacy-shaped BlockExecutionResult to its committed output packet."""
        return self._validate_execution_result(result,require_current_epoch=True)

    def record_failed_execution(self,permit_id,result):
        """Seal a failed attempt as failure evidence, never an artifact commit."""
        from cgkn.state.task_feedback import digest
        p=self._permit(permit_id)
        if p.status not in {'REVOKED','EXPIRED'} or result.succeeded:
            raise ValueError('FAILED_EXECUTION_REQUIRED')
        if (result.project_id,result.run_id,result.node_id,result.executor_ref)!=(p.project_id,p.run_id,p.node_id,p.executor_identity):
            raise ValueError('RESULT_BINDING_REJECT')
        failure_id='failure-'+uuid.uuid4().hex
        with self._lock():
            self._append('NODE_EXECUTION_FAILED',p.node_id,failure_id=failure_id,permit_id=permit_id,
                execution_epoch=p.execution_epoch,result_hash=digest(result.as_dict()))
        return replace(result,metadata={**result.metadata,'node_failure_receipt_id':failure_id})

    def validate_failed_execution(self,result):
        from cgkn.state.task_feedback import digest
        fid=result.metadata.get('node_failure_receipt_id')
        event=self._find('NODE_EXECUTION_FAILED','failure_id',fid) if isinstance(fid,str) else None
        if not event or result.succeeded:raise ValueError('FAILED_EXECUTION_RECEIPT_REQUIRED')
        p=self._permit(event['permit_id'])
        latest=[e['data']['permit'] for e in self.events() if e['event_type']=='NODE_PERMIT_ISSUED' and e['node_id']==p.node_id][-1]
        if latest['execution_epoch']!=p.execution_epoch:raise ValueError('STALE_EXECUTION_EPOCH')
        original=replace(result,metadata={k:v for k,v in result.metadata.items() if k!='node_failure_receipt_id'})
        if (p.status not in {'REVOKED','EXPIRED'} or digest(original.as_dict())!=event['result_hash']
            or (result.project_id,result.run_id,result.node_id,result.executor_ref)!=(p.project_id,p.run_id,p.node_id,p.executor_identity)):
            raise ValueError('RESULT_BINDING_REJECT')
        self.assert_resources_closed(p.permit_id)
        return fid

    def _validate_historical_execution_result(self,result):
        """Authenticate a past publication, never grant current artifact reuse.

        The runner's complete successor-chain check and read-only historical
        metric snapshots use this evidence.
        Public receipt/result validation still requires the latest epoch.
        """
        return self._validate_execution_result(result,require_current_epoch=False)

    def _validate_execution_result(self,result,*,require_current_epoch):
        r=self._validate_receipt(result.metadata.get('node_commit_receipt_id'),node_id=result.node_id,
                                 require_current_epoch=require_current_epoch)
        p=self._permit(r.permit_id)
        if (result.project_id,result.run_id,result.executor_ref)!=(p.project_id,p.run_id,p.executor_identity):
            raise ValueError('RESULT_BINDING_REJECT')
        packet=result.metadata.get('node_output_packet')
        if not packet or packet not in r.output_hashes:
            raise ValueError('OUTPUT_BINDING_REJECT: missing committed packet')
        if json.loads(Path(packet).read_text(encoding='utf-8'))!=result.as_dict()['outputs']:
            raise ValueError('OUTPUT_BINDING_REJECT: result differs from committed packet')
        return r

    def import_unmanaged(self,node_id,output_hashes,evidence_refs=()):
        with self._lock():
            self._append('NODE_IMPORTED_UNMANAGED',node_id,execution_mode='IMPORTED_UNMANAGED',
                         governed_execution=False,output_hashes=output_hashes,evidence_refs=list(evidence_refs))

    def node_view(self,node_id):
        v=dict(project_id=self.project_id,run_id=self.run_id,node_id=node_id,capability_id=None,
               tree_version=None,execution_mode='GOVERNED',admission_id=None,permit_id=None,state='ADMITTED',
               inputs={},input_hashes={},executor=None,effects_authorized=[],effects_used=[],
               budget_authorized={},budget_used={},decision_records=[],critical_check_results=[],
               evidence_refs=[],gate_status=CapabilityGateState().as_dict(),violations=[],output_refs={},
               commit_receipt_id=None,started_at=None,finished_at=None,output_state='UNCOMMITTED',warnings=[],
               checker_identities={},claim_relations=[],input_manifest=[],derivation_summary={},
               evaluation_scope_refs=[],resource_decision={},repair_lineage={},skill_state={},authority_integrity_state='VALID',effect_operations=[])
        for e in self.events():
            if e['node_id']!=node_id:continue
            d=e['data'];kind=e['event_type']
            if kind=='NODE_ADMITTED':v.update(state='ADMITTED',admission_id=d['admission_id'],
                tree_version=d['tree_version'],capability_id=d['capability_id'])
            elif kind=='NODE_PERMIT_ISSUED':
                p=d['permit'];v.update(capability_id=p['capability_id'],tree_version=p['tree_version'],
                    admission_id=p['admission_id'],permit_id=p['permit_id'],state='PERMITTED',goal=d['goal'],
                    inputs=p['input_bindings'],input_hashes=p['input_hashes'],executor=p['executor_identity'],
                    effects_authorized=p['allowed_effects'],budget_authorized=p['budget_scope'],
                    decision_records=[],critical_check_results=[],violations=[],effects_used=[],warnings=[],
                    output_refs={},commit_receipt_id=None,gate_status=CapabilityGateState().as_dict(),
                    output_state='UNCOMMITTED',execution_epoch=p['execution_epoch'],execution_mode='GOVERNED',
                    started_at=None,finished_at=None,budget_used={},evidence_refs=[],governed_execution=True,permit_status='ACTIVE')
                v.update(checker_identities=p.get('checker_identities',{}),input_manifest=p['input_bindings'].get('manifest',[]),
                         claim_relations=[],derivation_summary={},evaluation_scope_refs=[],effect_operations=[])
            elif kind=='NODE_EXECUTION_STARTED':v.update(state='EXECUTING',started_at=e['timestamp'])
            elif kind=='NODE_EFFECT_USED':
                v['effects_used'].append(d['domain'])
                v['effect_operations'].append({'operation':d['operation'],'domain':d['domain'],
                    'resource_usage':d['resource_usage'],'event_id':e.get('event_id'),'timestamp':e['timestamp']})
            elif kind=='NODE_DECISION_RECORDED':v['decision_records'].append(d['decision'])
            elif kind=='NODE_CRITICAL_CHECK_RESULT':v['critical_check_results'].append(d['check'])
            elif kind=='NODE_WARNING':v['warnings'].append(d['warning'])
            elif kind=='NODE_ACCEPTANCE_RECORDED':v['gate_status']=d['gate_status']
            elif kind=='NODE_SEMANTICS_RECORDED':v.update(claim_relations=d['claim_relations'],derivation_summary=d['derivation_summary'])
            elif kind=='NODE_RESOURCE_DECISION':v.update(resource_decision=d['resource_decision'],repair_lineage=d['repair_lineage'])
            elif kind=='NODE_OUTCOME_EVALUATED':v['evaluation_scope_refs'].append(d['evaluation_scope'])
            elif kind=='NODE_SKILL_LINEAGE':v['skill_state']=d['skill_state']
            elif kind=='NODE_RESULT_SUBMITTED':
                r=d['result'];v.update(state='CHECKING',output_refs=r['output_hashes'],
                    evidence_refs=r['evidence_refs'],budget_used=r['resource_usage'],
                    effects_used=sorted(set(v['effects_used'])|set(r['effects_used'])))
            elif kind in {'NODE_BLOCKED','NODE_QUARANTINED'}:
                v.update(state='BLOCKED' if kind=='NODE_BLOCKED' else 'QUARANTINED',output_state='QUARANTINED',finished_at=e['timestamp'])
                for item in d.get('violations',[d['violation']] if 'violation' in d else []):
                    if item not in v['violations']:
                        v['violations'].append(item)
                v['gate_status']=d.get('gate_status',v['gate_status'])
            elif kind=='NODE_COMMITTED':v.update(state='COMMITTED',commit_receipt_id=d['receipt_id'],
                gate_status=d['receipt']['gate_snapshot'],finished_at=e['timestamp'],output_state='COMMITTED',
                budget_used=d.get('budget_used',v['budget_used']),effects_used=d['receipt']['effects_used'],permit_status='CONSUMED')
            elif kind=='NODE_IMPORTED_UNMANAGED':v.update(execution_mode='IMPORTED_UNMANAGED',state='QUARANTINED',
                governed_execution=False,output_refs=d['output_hashes'],evidence_refs=d['evidence_refs'],output_state='AUDIT_ONLY')
            elif kind=='NODE_PERMIT_REVOKED':
                v['permit_status']='REVOKED'
        return v

    def node_runtime_record(self,node_id):
        return NodeRuntimeRecord(**self.node_view(node_id))

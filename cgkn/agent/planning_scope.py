"""Trusted Host bridge for bounded planning on the same committed root/tree.

No Worker Permit, new authority protocol, alternate graph, or planner ledger.
The application supplies an existing AdmissionPolicy from explicit project
authorization. GatewayCompletionClient retains its shared provider budget.
"""
from dataclasses import asdict, replace
from types import SimpleNamespace
from cgkn.agent.project_agent import ProjectProposal
from cgkn.orchestration import CapabilityTree
from cgkn.orchestration.leaf_contract import build_leaf_contract
from cgkn.execution.node_effects import execution_scope
from cgkn.providers.recording import recorded_execution
from cgkn.runtime.node_authority import file_hash
from veriarbor.capability import CapabilityContract
from veriarbor.execution_authority import NodeExecutionResult

def assemble_execution_authorities(project_id, run_id, store, authorization):
    """Bind explicit JSON authorization to the existing immutable run owner."""
    import json
    from cgkn.agent.project_agent import AdmissionPolicy
    if not isinstance(authorization,dict) or set(authorization)!={
            'admission_policy','max_planning_decisions','calls_per_decision'}:
        raise ValueError('EXPLICIT_EXECUTION_AUTHORIZATION_REQUIRED')
    raw=json.loads(json.dumps(authorization))
    policy=AdmissionPolicy(**raw['admission_policy'])
    if policy.project_id!=project_id:raise ValueError('PROJECT_SCOPE_REJECT')
    planning=HostPlanningScope(policy,max_decisions=raw['max_planning_decisions'],
                               calls_per_decision=raw['calls_per_decision'])
    store.immutable_json(store.run_dir(project_id,run_id)/'execution_authorization.json',raw)
    return policy,planning

class HostPlanningScope:
    root_id = '__host_planning_root__'
    capability_id = 'host.planning@1'
    executor_id = 'host.project-agent@1'

    def __init__(self, policy, *, max_decisions, calls_per_decision=1):
        if type(max_decisions) is not int or not 1<=max_decisions<=100:
            raise ValueError('bounded planning decisions required')
        if type(calls_per_decision) is not int or not 1<=calls_per_decision<=4:
            raise ValueError('bounded planning calls required')
        self.policy=policy;self.max_decisions=max_decisions;self.calls=calls_per_decision
        self.contract=CapabilityContract(self.capability_id,'Produce a bounded public proposal for the authorized root goal',
            critical=False,positive_controls=('public-proposal-captured',),
            evidence_requirements={'allow_imported_unmanaged':True})
        declared=policy.capability_contracts.get(self.capability_id)
        if not isinstance(declared,dict) or CapabilityContract(**declared).fingerprint!=self.contract.fingerprint:
            raise ValueError('trusted project policy must explicitly include planning contract')

    def decide(self, session, context):
        if hasattr(session.composer,'prepare_context'):
            # A local pause/preparation failure occurs before changing the
            # committed tree or issuing a planning Permit.
            context=session.composer.prepare_context(context)
        authority=session.runner._authority(context.project_id,context.run_id)
        events=authority.events()
        prior=[e for e in events if e['event_type']=='NODE_PERMIT_ISSUED' and e['node_id']==self.root_id]
        if len(prior)>=self.max_decisions:
            raise RuntimeError('PROVIDER_BUDGET_EXHAUSTED: planning decision bound')
        if self.policy.budget_state!='OK' or not self.policy.allow_remote_effects:
            raise RuntimeError('PROVIDER_BUDGET_EXHAUSTED: planning not authorized')
        for row in prior:
            previous=authority.permit(row['data']['permit_id'])
            if previous.status=='ACTIVE':
                # Reconcile only an exact recorded, definitely-not-submitted
                # Gateway failure. Unknown calls remain active and blocked.
                import json
                call_root=session.store.run_dir(context.project_id,context.run_id)/'provider_calls'
                proofs=[]
                for error_path in call_root.glob('*/error.json'):
                    error=json.loads(error_path.read_text(encoding='utf-8'))
                    req=json.loads((error_path.parent/'request.json').read_text(encoding='utf-8'))
                    if (req.get('execution_identity')==dict(project_id=context.project_id,run_id=context.run_id,
                        node_id=self.root_id,attempt_id='planning-'+str(previous.execution_epoch)) and
                        error.get('category')=='provider_request_rejected_before_send' and error.get('outcome_unknown') is False):
                        proofs.append((str(error_path),file_hash(error_path)))
                if len(proofs)==1:
                    authority.revoke_permit(previous.permit_id,'PLANNER_NOT_SUBMITTED:'+proofs[0][1])
                    continue
                raise RuntimeError('PLANNER_OUTCOME_UNKNOWN: existing active planning permit')
        committed=authority.committed_tree()
        tree=CapabilityTree.from_dict(committed['tree']) if committed else context.tree
        version=committed['tree_version'] if committed else session.tree_version
        leaf=build_leaf_contract(goal=self.contract.semantic_goal,kind='INSPECTION',scope=['public-proposal'],
            acceptance=['proposal-envelope'],checker='host-proposal',output_identity='public-proposal',
            effect_domains=['external_network'],executor=self.executor_id,subject='authorized-root',
            expected_observation='public bounded proposal, never execution authority',pass_fail_rule='capture public response; normal Admission validates proposal')
        cfg={'executor_ref':self.executor_id,'capability_contract_id':self.capability_id,'leaf_contract':leaf,'required':False}
        if self.root_id in tree.by_id:
            if tree.by_id[self.root_id].executable or tree.by_id[self.root_id].as_dict()['config']!=cfg:
                raise ValueError('PLANNING_ROOT_CHANGED')
            operation={'operation':'move_node','node_id':self.root_id,'parent_id':''}
        else:
            operation={'operation':'add_node','node_id':self.root_id,'capability_ref':'','config':cfg}
        proposal=ProjectProposal('host-plan-'+str(len(prior)+1),context.project_id,version,context.goal,(),(operation,),
            reason_summary='Host renews bounded root planning scope under existing project policy',
            target_capability_id=self.capability_id,strategy_capabilities=(self.capability_id,),
            exploration_reason='bounded planning',exploration_budget=self.calls,exploration_measure='public proposal admitted separately')
        effective=replace(self.policy,capability_contracts={**session.admission_policy.capability_contracts,
                                                           self.capability_id:asdict(self.contract)})
        aid,result=authority.admit(tree,version,proposal,known_capabilities=session.known_capabilities,
            catalog=session.capability_catalog,policy=effective)
        if not result.valid:raise ValueError(result.code)
        tree=authority.commit_tree(aid);session.tree_version=authority.committed_tree()['tree_version']
        # The Host-owned planning root is not a model-editable capability or
        # an executable dependency. Keep it in the authority tree only.
        public_tree=CapabilityTree(tree.goal,tuple(n for n in tree.nodes if n.id!=self.root_id))
        context=replace(context,tree=public_tree)
        root=session.store.run_dir(context.project_id,context.run_id)
        path=root/'agent'/('planning-context-'+str(context.decision_number)+'.json')
        session.store.immutable_json(path,context.as_dict())
        permit=authority.issue_permit(node_id=self.root_id,contract=self.contract,
            input_hashes={str(path):file_hash(path)},executor_identity=self.executor_id,budget_scope={'calls':self.calls})
        authority.begin_node_execution(permit.permit_id)
        request=SimpleNamespace(project_id=context.project_id,run_id=context.run_id,node_id=self.root_id,
                                attempt_id='planning-'+str(permit.execution_epoch))
        try:
            with execution_scope(authority,permit.permit_id),recorded_execution(request):
                decision=session.composer.decide(context)
            # Host control response packet, as in DAGRunner; not business Utility.
            packet=authority.staging_dir(permit.permit_id)/'proposal.json'
            session.store.immutable_json(packet,decision.as_dict())
            authority.submit_node_result(NodeExecutionResult(permit.permit_id,{str(packet):file_hash(packet)},
                input_hashes=permit.input_hashes,consumed_inputs=permit.input_bindings['manifest']))
            authority.commit_node_execution(permit.permit_id)
        except Exception as exc:
            from cgkn.agent.composer import AgentDecisionValidationError
            if isinstance(exc,AgentDecisionValidationError):
                # A completed response with a local schema/contract error is
                # known, retained feedback, not ambiguous remote execution.
                authority.revoke_permit(permit.permit_id,'PLANNER_RESPONSE_REJECTED')
            # Do not turn ambiguous remote execution into a retryable failure.
            # Existing request records, active Permit and context survive restart.
            raise
        if any(e.node_id==self.root_id for e in decision.edits):
            raise ValueError('PLANNER_CANNOT_EDIT_HOST_SCOPE')
        return decision,tree

"""Public thin facade over ExecutionAuthority; no alternate permit or gate logic."""
from dataclasses import asdict
from pathlib import Path
from veriarbor.execution_authority import DecisionRecord, NodeExecutionResult
from .node_authority import ExecutionAuthority, file_hash


class GovernedNodeSession:
    def __init__(self, authority, *, tree, tree_version, proposal, node_id, contract,
                 known_capabilities, catalog, policy, input_manifest=(), **permit_options):
        self.authority=authority;self.decisions=[];self.receipt=None;self.result=None
        aid,admitted=authority.admit(tree,tree_version,proposal,known_capabilities=known_capabilities,
                                     catalog=catalog,policy=policy)
        if not admitted.valid:raise ValueError(admitted.code)
        self.tree=authority.commit_tree(aid)
        self.permit=authority.issue_permit(node_id=node_id,contract=contract,input_manifest=input_manifest,**permit_options)
        self.permit_id=self.permit.permit_id;self.node_id=node_id
        self.tree_version=self.permit.tree_version;self.execution_epoch=self.permit.execution_epoch

    def __enter__(self):
        self.authority.begin_node_execution(self.permit_id)
        return self

    def use_effect(self,operation,callback,*,resource_usage=None):
        return self.authority.perform_effect(self.permit_id,operation,callback,resource_usage=resource_usage)

    def write_json(self,name,value,*,operation='PERSISTENT_ARTIFACT_WRITE'):
        return self.authority.store.publish_business_json(self.authority,self.permit_id,name,value,operation=operation)

    def record_decision(self,decision):
        self.decisions.append(DecisionRecord(**decision) if isinstance(decision,dict) else decision)

    def provider_result(self,callback,*,resource_usage):
        """Host captures the transport response, as DAGRunner captures outputs.json.

        This is the immutable result envelope, not a business publication API.
        """
        value=self.use_effect('PROVIDER_CALL',callback,resource_usage=resource_usage)
        path=self.authority.staging_dir(self.permit_id)/'provider-response.json'
        self.authority.store.immutable_json(path,value)
        return path

    def submit_result(self,outputs,*,evidence_refs=(),resource_usage=None,consumed_inputs=None,claim_refs=()):
        self.result=NodeExecutionResult(self.permit_id,{str(p):file_hash(p) for p in outputs},
            decision_records=tuple(self.decisions),evidence_refs=tuple(evidence_refs),
            resource_usage=resource_usage or {},input_hashes=dict(self.permit.input_hashes),
            consumed_inputs=tuple(consumed_inputs if consumed_inputs is not None else self.permit.input_bindings['manifest']),
            claim_refs=tuple(claim_refs))
        self.authority.submit_node_result(self.result)

    def __exit__(self,exc_type,exc,tb):
        if exc_type or self.result is None:
            self.authority.revoke_permit(self.permit_id,'UNSUBMITTED_RESULT' if exc is None else str(exc))
            if exc is None:raise ValueError('RESULT_REQUIRED')
            return False
        self.receipt=self.authority.commit_node_execution(self.permit_id)
        return False


def governed_node(authority,**kwargs):
    return GovernedNodeSession(authority,**kwargs)


def admit_declared_tree(authority, tree, *, policy, proposal_id, reason, retry_node=None):
    """Thin admission adapter for an explicitly authorized, declared graph.

    The caller supplies the policy; this function cannot invent effects,
    budgets, contracts or a model decision. Execution still uses DAGRunner.
    """
    from cgkn.orchestration.admission import ProjectProposal
    from cgkn.orchestration.capability_tree import CapabilityTree
    current=authority.committed_tree()
    if current:
        authority.validate_tree(tree)
        if retry_node is None:return tree
        base=tree;version=current['tree_version']
        operations=({'operation':'retry_node','node_id':retry_node},)
    else:
        if retry_node is not None:raise ValueError('RETRY_REQUIRES_COMMITTED_TREE')
        base=CapabilityTree(tree.goal,tuple(n for n in tree.nodes if not n.executable));version=1
        operations=tuple({'operation':'add_node','node_id':n.id,'parent_id':n.parent_id,
            'capability_ref':n.capability_ref,'depends_on':list(n.depends_on),'config':n.as_dict()['config']}
            for n in tree.nodes if n.executable)
    capabilities=tuple(dict.fromkeys(n.capability_ref for n in tree.nodes if n.executable))
    if not capabilities:raise ValueError('DECLARED_EXECUTABLE_TREE_REQUIRED')
    proposal=ProjectProposal(proposal_id,authority.project_id,version,tree.goal,(),operations,
        reason_summary=reason,target_capability_id=capabilities[0],strategy_capabilities=capabilities,
        exploration_reason=reason,exploration_budget=1,
        exploration_measure='Existing independently registered deliverable checks')
    aid,result=authority.admit(base,version,proposal,known_capabilities=set(capabilities),catalog={},policy=policy)
    if not result.valid:raise ValueError(result.code+': '+result.message)
    return authority.commit_tree(aid)

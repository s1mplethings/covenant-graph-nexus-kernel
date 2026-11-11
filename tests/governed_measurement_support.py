"""Explicit pre-execution Admission for old measurement calibration fixtures."""
from dataclasses import asdict,replace
from cgkn.agent.project_agent import AdmissionPolicy,ProjectProposal
from cgkn.orchestration.capability_tree import CapabilityTree,CapabilityNode
from cgkn.orchestration.leaf_contract import build_leaf_contract
from cgkn.runtime.node_authority import ExecutionAuthority,file_hash
from cgkn.runtime.governed import governed_node
from veriarbor.capability import CapabilityContract
from veriarbor.governance import InputBinding


def admit_fixture_tree(store,tree,*,operations=None):
    """Explicit bounded batch policy for scheduler fixtures, not Session defaults."""
    a=ExecutionAuthority(store,'p','r');current=a.committed_tree()
    base=CapabilityTree.from_dict(current['tree']) if current else CapabilityTree(tree.goal,tuple(n for n in tree.nodes if not n.executable))
    version=current['tree_version'] if current else 1
    contracts={n.capability_ref:asdict(CapabilityContract(n.capability_ref,'Bounded scheduler fixture',critical=False,
        positive_controls=('independent-observation',))) for n in tree.nodes if n.executable}
    ops=operations or tuple({'operation':'add_node','node_id':n.id,'capability_ref':n.capability_ref,
        'parent_id':n.parent_id,'depends_on':list(n.depends_on),'config':n.as_dict()['config']} for n in tree.nodes if n.executable)
    cap=next(iter(contracts))
    proposal=ProjectProposal('fixture-tree-'+str(version),'p',version,tree.goal,(),tuple(ops),reason_summary='explicit bounded test graph',
        target_capability_id=cap,strategy_capabilities=(cap,),exploration_reason='scheduler calibration',exploration_budget=1,
        exploration_measure='independent deliverable observation')
    domains={d for n in tree.nodes if n.executable for d in n.config['leaf_contract']['effect_domains']}
    policy=AdmissionPolicy(project_id='p',capability_contracts=contracts,incremental_mode=False,
        max_new_nodes=len(tree.nodes),allowed_effect_domains=frozenset(domains),allow_remote_effects=True,execution_budget={'calls':20})
    aid,result=a.admit(base,version,proposal,known_capabilities=set(contracts),catalog={},policy=policy)
    if not result.valid:
        from cgkn.runtime.dag_runner import GraphEditRejected
        raise GraphEditRejected(result.code+':'+result.message)
    return a.commit_tree(aid)


def admit_file_fixture(store, tree):
    """Declare actual file/model effects before a pre-authority repair fixture."""
    nodes=[]
    for node in tree.nodes:
        if not node.executable:nodes.append(node);continue
        config=node.as_dict()['config']
        if config['executor_ref']!='llm.cheap@1':raise ValueError('file fixture requires bounded worker')
        config['leaf_contract']['effect_domains']=['filesystem','external_network']
        nodes.append(replace(node,config=config))
    return admit_fixture_tree(store,replace(tree,nodes=tuple(nodes)))


def execute_external_measurement(executor,request):
    return execute_measurement(executor.session_acceptance.store,request,
        executor.project_root/'module.py',lambda:executor.execute(request))


def execute_measurement(store,request,artifact,callback):
    a=ExecutionAuthority(store,request.project_id,request.run_id)
    with store.exclusive_file(store.run_dir(request.project_id,request.run_id)/'fixture-admission.lock',wait_seconds=5):
        current=a.committed_tree()
        tree=CapabilityTree.from_dict(current['tree']) if current else CapabilityTree('ROOT',(CapabilityNode('ROOT'),))
        version=current['tree_version'] if current else 1
        capability=request.component_ref
        c=CapabilityContract(capability,'Produce independently checked measurement',critical=False,
                             positive_controls=('goal-observation',),evidence_requirements={'allow_imported_unmanaged':True})
        leaf=build_leaf_contract(goal='Measure local fixture',kind='INSPECTION',scope=['measurement'],
            acceptance=['goal-observation'],checker='fixture.measurement',output_identity='measurement',
            effect_domains=['local_process'] if request.executor_ref=='project.acceptance@1' else ['filesystem'],executor=request.executor_ref,dependencies=[],subject='measurement',
            expected_observation='independent value predicate',pass_fail_rule='existing provenance and GoalAcceptance')
        operation={'operation':'retry_node','node_id':request.node_id} if request.node_id in tree.by_id else {
            'operation':'add_node','node_id':request.node_id,'parent_id':'ROOT','capability_ref':capability}
        proposal=ProjectProposal('fixture-'+request.node_id+'-'+str(version),request.project_id,version,'ROOT',(),(operation,),
            reason_summary='offline calibration',target_capability_id=capability,strategy_capabilities=(capability,),
            exploration_reason='measure public predicate',exploration_budget=1,exploration_measure='goal observation')
        policy=AdmissionPolicy(project_id=request.project_id,capability_contracts={capability:asdict(c)})
        binding=InputBinding(str(artifact),str(artifact),file_hash(artifact),request.node_id,execution_mode='IMPORTED_UNMANAGED')
        session=governed_node(a,tree=tree,tree_version=version,proposal=proposal,node_id=request.node_id,contract=c,
            known_capabilities={capability},catalog={capability:{'executor_ref':request.executor_ref,'config':{'leaf_contract':leaf}}},
            policy=policy,input_manifest=(binding,))
        # Tree revisions invalidate active permits. Keep this test-operator
        # admission transaction through commit, as ProjectSession does; result
        # publication/acceptance below remains independently concurrent.
        node=session.__enter__()
        try:
            from cgkn.execution.node_effects import execution_scope
            with execution_scope(a,node.permit_id):result=callback()
            if not result.succeeded:
                a.revoke_permit(node.permit_id,'MEASUREMENT_FAILED_NO_PUBLICATION')
                return result
            packet=a.staging_dir(node.permit_id)/'outputs.json'
            store.immutable_json(packet,result.as_dict()['outputs'])
            node.submit_result((packet,))
            session.__exit__(None,None,None)
        except BaseException:
            if a.permit(node.permit_id).status=='ACTIVE':
                a.revoke_permit(node.permit_id,'MEASUREMENT_EXCEPTION')
            raise
    return replace(result,metadata={**result.metadata,'node_commit_receipt_id':node.receipt.receipt_id,
                                   'node_output_packet':str(packet),'execution_mode':'GOVERNED'})

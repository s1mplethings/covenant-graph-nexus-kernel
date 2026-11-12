"""Explicit test-operator admission before exercising the canonical scheduler.

This fixture does not execute or commit results. All scheduling, effects,
independent checks, version validation and recovery remain in DAGRunner.
Only the test's explicit accept_edits/retry flags authorize new proposals.
"""
from dataclasses import asdict
from cgkn.agent.project_agent import AdmissionPolicy, ProjectProposal
from cgkn.orchestration import CapabilityTree, compile_tree
from cgkn.runtime.node_authority import ExecutionAuthority
from cgkn.state import StateStoreError
from veriarbor.capability import CapabilityContract


def run_calibration(runner, *, project_id, run_id, tree, dag, model_calls=0, **kwargs):
    if runner.execution_mode!='GOVERNED':raise ValueError('Calibration requires real governed execution')
    if compile_tree(tree).as_dict()!=dag.as_dict():raise ValueError('execution DAG does not match executable CapabilityTree nodes')
    authority=ExecutionAuthority(runner.store,project_id,run_id)
    current=authority.committed_tree()
    try:state=runner.store.load_run(project_id,run_id)
    except StateStoreError:state=None
    if state and (kwargs.get('resume') or kwargs.get('retry_node')):
        runner._bind_graph(state,dag,accept_edits=kwargs.get('accept_edits',False),
            retry_node=kwargs.get('retry_node'),validate_only=True)
    base=CapabilityTree.from_dict(current['tree']) if current else CapabilityTree(tree.goal,tuple(n for n in tree.nodes if not n.executable))
    version=current['tree_version'] if current else 1
    operations=[]
    if current and tree.as_dict()!=base.as_dict() and not kwargs.get('accept_edits'):
        raise ValueError('explicit edit commit required')
    for node in tree.nodes:
        if not node.executable:continue
        old=base.by_id.get(node.id)
        if old is None:
            operations.append(dict(operation='add_node',node_id=node.id,parent_id=node.parent_id,
                capability_ref=node.capability_ref,depends_on=list(node.depends_on),config=node.as_dict()['config']))
        elif old.as_dict()!=node.as_dict():
            if old.depends_on!=node.depends_on:raise ValueError('Calibration dependency edits require an explicit dedicated proposal')
            operations.append(dict(operation='update_config',node_id=node.id,config=node.as_dict()['config']))
    for node in reversed(base.nodes):
        if node.id not in tree.by_id:operations.append(dict(operation='remove_node',node_id=node.id))
    if kwargs.get('retry_node'):operations.append(dict(operation='retry_node',node_id=kwargs['retry_node']))
    if operations:
        contracts={n.capability_ref:asdict(CapabilityContract(n.capability_ref,'Bounded scheduler observation',
            critical=False,positive_controls=('independent fixture observation',))) for n in (*base.nodes,*tree.nodes) if n.executable}
        domains={d for n in tree.nodes if n.executable for d in n.config['leaf_contract']['effect_domains']}
        policy=AdmissionPolicy(project_id=project_id,capability_contracts=contracts,incremental_mode=False,
            max_new_nodes=len(tree.nodes),allowed_effect_domains=frozenset(domains),
            allow_remote_effects=model_calls>0,execution_budget={'calls':model_calls})
        cap=next(iter(contracts))
        proposal=ProjectProposal('calibration-'+str(version),project_id,version,tree.goal,(),tuple(operations),
            reason_summary='Explicit scheduler test operation',target_capability_id=cap,strategy_capabilities=tuple(contracts),
            exploration_reason='Bounded independent scheduler calibration',exploration_budget=1,
            exploration_measure='Original test assertions and registered deliverable checks')
        aid,result=authority.admit(base,version,proposal,known_capabilities=set(contracts),catalog={},policy=policy)
        if not result.valid:
            from cgkn.runtime.dag_runner import GraphEditRejected
            raise GraphEditRejected(result.code+': '+result.message)
        committed=authority.commit_tree(aid)
        assert committed.as_dict()==tree.as_dict(),'Fixture admission changed the requested graph'
    return runner.run(project_id=project_id,run_id=run_id,tree=tree,dag=dag,**kwargs)

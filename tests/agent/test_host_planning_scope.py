from dataclasses import asdict,replace
from tests.agent.test_goal_acceptance_integration import setup,action,PLAN
from cgkn.agent.planning_scope import HostPlanningScope
from cgkn.execution.node_effects import require_provider_context,perform_scoped_effect
from veriarbor.capability import CapabilityContract

def prepare(tmp_path,authorized=True):
    session,a,client=setup(tmp_path,[action('plan',PLAN),action('execute',{},'check@1')],continuous=True)
    contract=CapabilityContract('host.planning@1','Produce a bounded public proposal for the authorized root goal',
        critical=False,positive_controls=('public-proposal-captured',),evidence_requirements={'allow_imported_unmanaged':True})
    policy=replace(session.admission_policy,capability_contracts={**session.admission_policy.capability_contracts,'host.planning@1':asdict(contract)},
        allow_remote_effects=authorized,execution_budget={'calls':1})
    planning=HostPlanningScope(policy,max_decisions=3)
    original=client.complete;permits=[]
    def complete(**kw):
        authority,pid=require_provider_context();permits.append(authority.permit(pid))
        return perform_scoped_effect('PROVIDER_CALL',lambda:original(**kw),resource_usage={'calls':1})
    client.complete=complete
    return session,a,client,planning,permits

def test_planning_is_root_scope_same_tree_not_worker_permit(tmp_path):
    s,a,c,p,permits=prepare(tmp_path)
    result=s.run(project_id='p',run_id='r',goal='g',planning=p,finish_when_verified=True)
    assert result.status=='GOALS_VERIFIED'
    assert len(permits)==2 and all(x.node_id==p.root_id and x.executor_identity==p.executor_id for x in permits)
    authority=s.runner._authority('p','r')
    assert all(authority.permit(x.permit_id).status=='CONSUMED' for x in permits)
    assert all(authority.assert_resources_closed(x.permit_id)['closure_state']=='CLOSED' for x in permits)
    assert len([n for n in result.tree.nodes if n.executable])==1
    assert not result.tree.by_id[p.root_id].executable

def test_missing_planning_scope_blocks_before_provider(tmp_path):
    s,a,c,p,permits=prepare(tmp_path,False)
    result=s.run(project_id='p',run_id='r',goal='g',planning=p)
    assert result.status=='BLOCKED' and not c.contexts and not permits

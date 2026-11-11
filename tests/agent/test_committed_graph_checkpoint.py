import base64
import json
import pytest
from tests.runtime.test_graph_commit import setup, tree, run
from tests.agent.test_project_loop_boundaries import Composer, decision,policy
from cgkn.agent.project_loop import AgentProjectLoop

pytestmark=[pytest.mark.boundary,pytest.mark.negative]

@pytest.mark.parametrize('mode',['committed-ahead','mirror-tampered','divergent','intent-ahead','unknown-committed-ahead'])
def test_canonical_committed_nodes_survive_missing_next_decision(tmp_path,mode):
    executor,runner=setup(tmp_path/'state');store=runner.store
    first=run(runner,tree('a'))
    run(runner,tree('a','b'),resume=True,accept_edits=True)
    folder=store.run_dir('p','r');checkpoint=folder/'agent_checkpoint.json'
    planned=tree('a','uncommitted') if mode=='divergent' else tree('a','b','planned') if mode=='intent-ahead' else tree('a')
    store.atomic_json(checkpoint,{'goal':'goal','tree':planned.as_dict(),'summary':first.as_dict(),
        'failure_details':{},'execution_results':{},'worker_calls':0,'next_decision':2,'composer_state':{}})
    if mode=='unknown-committed-ahead':
        state=store.load_run('p','r');state.nodes['b'].status='RUNNING';state.nodes['b'].latest_result_ref=None;store.save_run(state)
    before=checkpoint.read_bytes();calls=list(executor.calls);state_before=(folder/'run_state.json').read_bytes()
    attempts={str(p.relative_to(folder)):p.read_bytes() for p in (folder/'attempts').rglob('*.json')}
    if mode=='mirror-tampered':store.save_definition('p','r','capability_tree.json',tree('a','b','forged').as_dict())
    seen=[]
    class Observe(Composer):
        def decide(self,context):
            seen.append(context)
            return decision(escalation=True)
    loop=AgentProjectLoop(Observe([]),runner,store,known_capabilities={'c@1'},worker_model='worker',continuous=True,admission_policy=policy())
    assert not (folder/'agent/decision-02.json').exists()
    if mode in {'mirror-tampered','divergent'}:
        with pytest.raises(RuntimeError,match='RECOVERY_GRAPH_'):
            loop.run(project_id='p',run_id='r',goal='goal')
        assert not seen and checkpoint.read_bytes()==before
        assert (folder/'run_state.json').read_bytes()==state_before
    elif mode=='unknown-committed-ahead':
        result=loop.run(project_id='p',run_id='r',goal='goal')
        assert result.status=='BLOCKED' and 'EXECUTION_OUTCOME_UNKNOWN' in result.escalation_reason
        assert not seen
        assert store.load_result('p','r','b').error.details['outcome_unknown'] is True
        snapshot=next((folder/'recovery').glob('agent-checkpoint-*.json'))
        assert base64.b64decode(json.loads(snapshot.read_text())['content'])==before
    else:
        result=loop.run(project_id='p',run_id='r',goal='goal')
        assert result.status=='BLOCKED'  # explicit fixture escalation, no false pass
        assert set(seen[0].tree.by_id)==({'a','b','planned'} if mode=='intent-ahead' else {'a','b'})
        snapshots=list((folder/'recovery').glob('agent-checkpoint-*.json'))
        if mode=='committed-ahead':
            assert len(snapshots)==1
            assert base64.b64decode(json.loads(snapshots[0].read_text())['content'])==before
            event=next(e for e in store.load_events('p','r') if e.event_type=='AGENT_COMMITTED_GRAPH_RECONCILED')
            assert list(event.data['adopted_committed_nodes'])==['b'] and event.data['automatic_replay'] is False
        else:assert snapshots==[]
    assert executor.calls==calls
    assert all((folder/p).read_bytes()==content for p,content in attempts.items())

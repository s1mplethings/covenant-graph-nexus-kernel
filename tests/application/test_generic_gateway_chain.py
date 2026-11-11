"""Domain-neutral real Host/Gateway/ledger integration, synthetic wire only."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pytest
from cgkn.application.goal_driven import build_session
from cgkn.providers import GatewayCompletionClient
from cgkn.protocol.adaptive_context import ContextPacker
from tests.application.test_goal_driven import configuration
from tests.providers.stream_fixtures import send_gateway


def answer(payload, *, first_wrong):
    context=ContextPacker.restore(json.loads(payload['input'][1]['content']))
    schema=payload['text']['format']['name']
    if schema=='cgkn_worker_proposal':
        repair=context['config'].get('goal','').startswith('Repair')
        return {'schema_version':'1.0','node_id':context['node_id'],'summary':'wire fixture',
            'actions':[{'action':'write_file','path':'answer.txt','content':'wrong' if first_wrong and not repair else 'hello'}],
            'expected_outputs':['answer.txt'],'confidence':1,'needs_escalation':False,'escalation_reason':''}, False
    nodes=context['tree']['nodes'];produced=any(n['id']=='make-greeting' for n in nodes)
    observed=any(n['id']=='observe-result' for n in nodes)
    cfg={'executor_ref':'goal.acceptance@1' if produced else 'llm.cheap@1',
         'goal':'Check promised hello file' if produced else 'Create promised hello file'}
    if not produced:cfg.update(target_paths=['answer.txt'],read_paths=[])
    node='observe-result' if produced else 'make-greeting'
    edits=[{'edit_id':'e-'+node,'operation':'add_node','node_id':node,'payload':{
        'capability_ref':'project.rootcheck@1' if produced else 'project.greeting@1','parent_id':'',
        'depends_on':['make-greeting'] if produced else [],'config':cfg},'provenance':{'fixture':'terminal-wire'}}]
    if observed:
        assert context['goal_acceptance']['goals'][0]['verdict']=='FAILED'
        edits=[{'edit_id':'repair-config','operation':'update_config','node_id':'make-greeting',
            'payload':{'config':{'goal':'Repair hello file from independent failed byte observation',
                'verified_artifact_change_reason':'Root exact-byte checker FAILED'}},'provenance':{}},
            {'edit_id':'repair-retry','operation':'retry_node','node_id':'make-greeting','payload':{},'provenance':{}}]
    return {'schema_version':'1.0','decision_id':'d-'+node+('-repair' if observed else ''),
        'summary':'Bounded fixture proposal','reason':'R1 remains unverified','edits':edits,'request_run':True,
        'finish':False,'needs_escalation':False,'escalation_reason':'','decision_audit':{
            'requirement_refs':['R1'],'alternatives_considered':['inspect','repair'],
            'expected_outcome':'Independent checker observes exact hello bytes'}}, observed


@pytest.mark.parametrize('first_wrong',[False,True])
def test_gateway_chain_feedback_budget_and_no_dispatch_on_resume(tmp_path,monkeypatch,first_wrong):
    profile=tmp_path/'network.json';profile.write_text('{"mode":"legacy"}')
    monkeypatch.setenv('CGKN_APPLICATION_PROFILE',str(profile))
    monkeypatch.setenv('CGKN_PROVIDER_CACHE_MODE','off')
    ledger=tmp_path/'ledger.json'
    for key,value in {'BUDGET_LEDGER':str(ledger),'MAX_API_CALLS':8,'MAX_INPUT_TOKENS':800000,
        'MAX_OUTPUT_TOKENS':100000,'MAX_ESTIMATED_COST':10,'INPUT_COST_PER_MILLION':1,'OUTPUT_COST_PER_MILLION':1}.items():
        monkeypatch.setenv('CGKN_PROVIDER_'+key,str(value))
    calls=[];feedback=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            value,used_feedback=answer(payload,first_wrong=first_wrong)
            calls.append(payload);feedback.append(used_feedback)
            send_gateway(self,payload,{'id':'wire-'+str(len(calls)),'status':'completed',
                'model':payload['cgkn_model_id'],'output_text':json.dumps(value),
                'usage':{'input_tokens':20,'output_tokens':10,'total_tokens':30}})
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        cfg=configuration(tmp_path)
        client=GatewayCompletionClient(f'http://127.0.0.1:{server.server_port}/v1','fixture-only',
            run_id=cfg['run_id'],case_id=cfg['project_id'],authorization_reference='ISOLATED_TEST_NO_PRODUCTION_AUTHORIZATION')
        session,scope=build_session(cfg,tmp_path/'run',client)
        result=session.run(project_id=cfg['project_id'],run_id=cfg['run_id'],goal=cfg['root_goal'],planning=scope,finish_when_verified=True)
        assert result.status=='GOALS_VERIFIED',result.as_dict()
        assert Path(cfg['inputs_and_workspace']['workspace'],'answer.txt').read_text()=='hello'
        assert any(feedback)==first_wrong
        assert [c['verdict'] for c in session.acceptance.data['checks']]==(['FAILED','VERIFIED'] if first_wrong else ['VERIFIED'])
        count=len(calls);assert count==(5 if first_wrong else 3)
        state=json.loads(ledger.read_text())
        assert state['totals']['api_calls']==count and state['totals']['unknown_calls']==0
        assert state['totals']['actual_input_tokens']==20*count
        for path in (session.store.run_dir(cfg['project_id'],cfg['run_id'])/'provider_calls').glob('*/response.json'):
            response=json.loads(path.read_text())
            assert response['routing']['request_packing']['final_wire']['within_ceiling']
            assert path.with_name('packing.json').is_file()
        resumed,resume_scope=build_session(cfg,tmp_path/'run',client)
        outcome=resumed.run(project_id=cfg['project_id'],run_id=cfg['run_id'],goal=cfg['root_goal'],planning=resume_scope,resume=True,finish_when_verified=True)
        assert outcome.status=='GOALS_VERIFIED' and len(calls)==count
        assert json.loads(ledger.read_text())==state
    finally:
        server.shutdown();server.server_close();thread.join(timeout=3)

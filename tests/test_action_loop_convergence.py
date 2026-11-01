"""Public compatibility entries retain their policy while sharing turn ownership."""
import asyncio
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import agent_conversation_loop as conversation
import dynamic_pipeline_runner as dynamic
from tests.providers.test_domestic_repair import isolated, fake_gateway, admit


def step(tmp_path, agent, *, allowed=('write_file',), turns=2):
    executor=conversation.local_agent_actions.LocalAgentActionExecutor(tmp_path/'project')
    return dynamic._run_agent_turn(session_file=tmp_path/'session.jsonl', executor=executor,
        manifest={'roles':[{'id':'worker'}]}, step={'id':'build','role':'worker','allowed_actions':list(allowed)},
        model='offline',timeout=1,max_turns=turns,agent=agent)


@pytest.mark.parametrize('mode',['conversation','step'])
def test_cancelled_provider_never_dispatches_actions_or_retries(tmp_path, mode):
    calls=[]
    def cancelled(*args):
        calls.append(1)
        raise asyncio.CancelledError('cancelled')
    with pytest.raises(asyncio.CancelledError):
        if mode=='step':
            step(tmp_path,cancelled)
        else:
            conversation.run_agent_loop(session_path=tmp_path/'session.jsonl',project_dir=tmp_path/'project',agent=cancelled)
    assert len(calls)==1
    assert not list((tmp_path/'project').glob('*'))


def test_manifest_repair_preserves_permission_and_feedback(tmp_path):
    histories=[]
    def agent(events,*args):
        histories.append(events)
        if len(histories)==1:
            return {'actions':[{'type':'run_command','command':'echo forbidden'}]}
        assert any('not allowed' in e.get('result',{}).get('error','') for e in events)
        return {'actions':[{'type':'write_file','path':'result.txt','content':'bounded'}]}
    result=step(tmp_path,agent)
    assert result['status']=='ok'
    assert (tmp_path/'project/result.txt').read_text()=='bounded'
    events=conversation.read_session(tmp_path/'session.jsonl')
    assert all(e.get('step_id')=='build' for e in events)
    assert not any(e.get('manifest') for e in events)


@pytest.mark.parametrize('mode',['conversation','step'])
def test_saved_history_survives_a_fresh_entry_without_replaying_side_effects(tmp_path, mode):
    session=tmp_path/'session.jsonl'
    conversation.append_event(session,{'kind':'tool_result','turn':1,'action':{'type':'write_file','path':'prior.txt'},'result':{'ok':True}})
    project=tmp_path/'project';project.mkdir();(project/'prior.txt').write_text('retained')
    def agent(events,*args):
        assert any(e.get('action',{}).get('path')=='prior.txt' for e in events)
        return {'actions':[{'type':'write_file','path':'next.txt','content':'new'}]}
    if mode=='step':
        result=step(tmp_path,agent,turns=1)
    else:
        result=conversation.run_agent_loop(session_path=session,project_dir=project,agent=agent,max_turns=1)
    assert (project/'prior.txt').read_text()=='retained'
    assert (project/'next.txt').read_text()=='new'
    assert result['status'] not in ('PASS','DELIVERED','SUCCEEDED','ready')
    assert len([e for e in conversation.read_session(session) if e.get('kind')=='action'])==1


def test_manifest_falsey_agent_uses_existing_default_policy(tmp_path,monkeypatch):
    class Falsey:
        def __bool__(self):return False
        def __call__(self,*args):pytest.fail('falsey callback was historically not selected')
    calls=[]
    def default(*args,**kwargs):
        calls.append(1)
        return {'actions':[{'type':'write_file','path':'ok.txt','content':'ok'}]}
    monkeypatch.setattr(dynamic,'_call_step_agent',default)
    assert step(tmp_path,Falsey())['status']=='ok'
    assert calls==[1]


def test_manifest_non_integer_turn_limit_is_rejected_before_provider(tmp_path):
    with pytest.raises(TypeError):
        step(tmp_path,lambda *args:pytest.fail('invalid limit must not call model'),turns=1.5)


@pytest.mark.parametrize('entry',['step','pipeline'])
def test_unknown_submission_stops_turns_and_outer_fallback(fake_gateway,isolated,monkeypatch,tmp_path,entry):
    state,_=isolated
    base=json.loads((state/'session.json').read_text())['base_url']
    monkeypatch.setattr(conversation.check_connectivity,'_resolve_api_credentials',lambda:{'api_key':'offline','base_url':base})
    monkeypatch.setattr(dynamic.local_model_router,'call_text_task',lambda *a,**k:{'ok':False})
    monkeypatch.setattr(dynamic,'_fallback_to_agent_loop',lambda **k:pytest.fail('UNKNOWN must not start fallback'))
    admit(monkeypatch,tmp_path,CGKN_PROVIDER_MAX_OUTPUT_TOKENS='100000',CGKN_PROVIDER_MAX_INPUT_TOKENS='1000000')
    fake_gateway[1]['mode']='unknown'
    session=tmp_path/'session.jsonl';project=tmp_path/'project'
    if entry=='step':
        result=dynamic._run_agent_turn(session_file=session,executor=conversation.local_agent_actions.LocalAgentActionExecutor(project),
            manifest={'roles':[{'id':'worker'}]},step={'id':'work','role':'worker','allowed_actions':['write_file']},
            model='qwen',timeout=2,max_turns=3,agent=None)
        assert result['quality_audit']['outcome_unknown']
    else:
        manifest=dynamic.pipeline_manifest.default_minimal_pipeline_manifest({'project_summary':'offline calculator'})
        result=dynamic.run_dynamic_pipeline(session_path=session,project_dir=project,pipeline_manifest=manifest,
            model='qwen',timeout=2,max_turns=3,fallback_to_agent_loop=True)
        assert result['audit']['outcome_unknown']
    assert result['status']=='rework_blocked'
    assert len(fake_gateway[0])==1
    ledger=json.loads((tmp_path/'budget.json').read_text())
    assert len(ledger['calls'])==1 and ledger['calls'][0]['submission_outcome_unknown']
    assert not any(e.get('kind')=='action' for e in conversation.read_session(session))

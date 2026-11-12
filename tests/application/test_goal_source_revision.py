import copy
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from cgkn.state import FileRunStore
from cgkn.state.acceptance import identity
from scripts.run_goal_driven import bind_goal_config,hash_file


def fixture(tmp_path):
    store=FileRunStore(tmp_path/'store');rd=store.run_dir('p','r')
    ledger=tmp_path/'budget.json';ledger.write_text(json.dumps({'calls':[{'status':'SUCCEEDED','input_tokens':4522}]}))
    frozen={'config':{'project_id':'p','run_id':'r','budget_ledger':str(ledger),'resource_and_effect_limits':{'max_input_tokens':1000000}},
            'sources':{'host.py':'old'},'core_sources':{'core.py':'same'},'checker':'same'}
    bind_goal_config(store,rd,frozen,'start')
    new=copy.deepcopy(frozen);new['sources']['host.py']='new'
    proof={'parent_config_identity':identity(frozen),'authority_reference':'offline-fixture-operator',
           'reason':'observed pre-materialization budget reservation defect','changes':{'host.py':{'before':'old','after':'new'}},'ledger_sha256':hash_file(ledger)}
    return store,rd,ledger,frozen,new,proof


def test_source_revision_preserves_run_cost_history_and_original_window(tmp_path):
    store,rd,ledger,old,new,proof=fixture(tmp_path)
    window=rd/'execution-window.json';window.write_text('{"deadline":123}')
    original=(rd/'goal-config.json').read_bytes();cost=ledger.read_bytes();clock=window.read_bytes()
    bind_goal_config(store,rd,new,'revise-sources',proof)
    bind_goal_config(store,rd,new,'resume')
    bind_goal_config(store,rd,new,'revise-sources',proof)
    assert (rd/'goal-config.json').read_bytes()==original
    assert ledger.read_bytes()==cost and window.read_bytes()==clock
    events=store.load_events('p','r')
    assert len(events)==1 and events[0].event_type=='GOAL_FRAMEWORK_REVISED'
    assert events[0].data['parent_identity']==identity(old)


@pytest.mark.parametrize('mutation',['budget','checker','core','hash','parent','unknown','business_nodes','ledger'])
def test_source_revision_rejects_unbound_or_unsafe_successor(tmp_path,mutation):
    store,rd,ledger,old,new,proof=fixture(tmp_path)
    if mutation=='budget':new['config']['resource_and_effect_limits']['max_input_tokens']=2000000
    elif mutation=='checker':new['checker']='changed'
    elif mutation=='core':new['core_sources']['core.py']='changed'
    elif mutation=='hash':proof['changes']={}
    elif mutation=='parent':proof['parent_config_identity']='wrong'
    elif mutation=='unknown':
        ledger.write_text('{"calls":[{"status":"UNKNOWN"}]}');proof['ledger_sha256']=hash_file(ledger)
    elif mutation=='ledger':ledger.write_text('{"calls":[]}')
    else:
        (rd/'run_state.json').write_text('{}')
        store.load_run=lambda *args:SimpleNamespace(nodes={'work':object()})
    with pytest.raises(ValueError):bind_goal_config(store,rd,new,'revise-sources',proof)
    assert not (rd/'events.jsonl').exists()


@pytest.mark.parametrize('unsafe',[None,'successful_history','unknown_history','product_bytes'])
def test_failed_unmaterialized_source_revision_preserves_history(tmp_path,unsafe):
    store,rd,ledger,old,new,proof=fixture(tmp_path)
    workspace=tmp_path/'workspace';workspace.mkdir()
    old['config']['inputs_and_workspace']={'workspace':str(workspace),'inputs':[]}
    new['config']['inputs_and_workspace']=copy.deepcopy(old['config']['inputs_and_workspace'])
    # Fixture genesis only: create a new store for this distinct initial configuration.
    store=FileRunStore(tmp_path/'failed-store');rd=store.run_dir('p','r')
    bind_goal_config(store,rd,old,'start');proof['parent_config_identity']=identity(old)
    (rd/'run_state.json').write_text('{}');store.load_run=lambda *args:SimpleNamespace(nodes={'work':SimpleNamespace(status='FAILED')})
    attempt=rd/'attempts/work/a.json';attempt.parent.mkdir(parents=True)
    record={'status':'FAILED','error':{'details':{}}}
    if unsafe=='successful_history':record['status']='SUCCEEDED'
    if unsafe=='unknown_history':record['error']['details']['outcome_unknown']=True
    if unsafe=='product_bytes':(workspace/'product.py').write_text('historical bytes')
    attempt.write_text(json.dumps(record));before=attempt.read_bytes()
    if unsafe:
        with pytest.raises(ValueError):bind_goal_config(store,rd,new,'revise-sources',proof)
    else:
        bind_goal_config(store,rd,new,'revise-sources',proof)
        bind_goal_config(store,rd,new,'resume')
    assert attempt.read_bytes()==before

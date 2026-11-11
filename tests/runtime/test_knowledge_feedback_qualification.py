import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import pytest
from cgkn.execution import BlockStatus, ExecutionError, ExecutionErrorCode
from cgkn.orchestration.capability_tree import CapabilityTree, CapabilityNode
from cgkn.state.task_feedback import FrozenKnowledge, digest
from src.cgnk_knowledge.store import (new_project_knowledge_pack, upsert_knowledge_items,
    update_project_knowledge, load_project_knowledge)
from tests.runtime.test_task_feedback import record, advisory


def lesson(ident='R5', **changes):
    return dict(dict(kind='KnowledgeItem', id=ident, title='Exposed regression', type='research_finding',
        content='Repeated start while running: success, changed=false, unchanged state bytes.',
        source_refs=['history/R5/failed-receipt'], tags=['job.start@1'], review_state='candidate',
        status='uncertain', visibility='public', retention='keep', importance='high', need_state='needed_now'), **changes)


def test_local_runtime_failure_is_visible_to_owner_not_unrelated(tmp_path):
    f, result, node, _ = record(tmp_path)
    failed = replace(result, attempt_id='attempt-0002', status=BlockStatus.FAILED,
        error=ExecutionError(ExecutionErrorCode.INVALID_OUTPUT,'controlled failure'))
    f.store.save_result(failed)
    f.terminal(failed, replace(node, parent_id='owner'))
    tree = CapabilityTree('goal', (CapabilityNode('owner'), replace(node,parent_id='owner'),
        CapabilityNode('next',parent_id='owner',capability_ref='x',depends_on=('work',)),
        CapabilityNode('unrelated',capability_ref='y')))
    assert f.localized(tree,'next')['items'][0]['status']=='FAILED'
    assert f.localized(tree,'owner')['items'][0]['attempt_id']=='attempt-0002'
    assert f.localized(tree,'unrelated')['items']==[]
    assert f.attempt(f.localized(tree,'owner')['items'][0]['identity'])['receipt_ref'].startswith('attempts/')


def test_candidate_not_promoted_same_run_and_contradictions_downgrade(tmp_path):
    path=tmp_path/'pack.json'
    first=update_project_knowledge(path,'p',[lesson()])['pack']
    frozen=FrozenKnowledge(first)
    assert frozen.retrieve(['job.start@1'])['applied_lesson_ids']==[]
    # A distinct synthetic independently checked lesson; never promote historical R5.
    checked=lesson('synthetic-verified',review_state='accepted',status='active',source_refs=['independent/verified-receipt'])
    second=update_project_knowledge(path,'p',[checked])['pack']
    assert frozen.retrieve(['job.start@1'])['applied_lesson_ids']==[]
    view=FrozenKnowledge(second).retrieve(['job.start@1'])
    assert view['applied_lesson_ids']==['synthetic-verified'] and view['context_sha256']==digest({k:v for k,v in view.items() if k!='context_sha256'})
    assert FrozenKnowledge(second).retrieve(['http.read@1'])['selected_items']==[]
    contradicted={**checked,'status':'uncertain','review_state':'conflict','source_refs':[*checked['source_refs'],'contradiction/receipt']}
    with pytest.raises(ValueError,match='expected_hash'):update_project_knowledge(path,'p',[contradicted])
    third=update_project_knowledge(path,'p',[contradicted],expected_hash=digest(second))['pack']
    assert FrozenKnowledge(third).retrieve(['job.start@1'])['selected_items']==[]
    with pytest.raises(ValueError,match='stale'):update_project_knowledge(path,'p',[checked],expected_hash=digest(second))
    assert load_project_knowledge(path)['all_items'][0]['review_state']=='candidate'


@pytest.mark.parametrize('status',['stale','superseded','retracted','archived'])
def test_inactive_lesson_never_injected(status):
    pack=upsert_knowledge_items(new_project_knowledge_pack('p'),[lesson(review_state='accepted',status=status)])
    assert FrozenKnowledge(pack).retrieve(['job.start@1'])['selected_items']==[]


def test_concurrent_lesson_updates_merge_without_lost_items(tmp_path):
    path=tmp_path/'pack.json'
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i:update_project_knowledge(path,'p',[lesson(str(i))]),range(24)))
    pack=load_project_knowledge(path)
    assert {i['id'] for i in pack['all_items']}=={str(i) for i in range(24)}


def test_tampered_feedback_fails_closed(tmp_path):
    f,_,_,fact=record(tmp_path)
    path=f.root/fact['receipt_ref'];raw=json.loads(path.read_text());raw['outputs']={'forged':True};path.write_text(json.dumps(raw))
    with pytest.raises(ValueError,match='hash mismatch'):f.context()


def test_reviewed_lesson_requires_actual_current_checker_success(tmp_path):
    from tests.fixtures.provenance import setup,check
    from src.cgnk_knowledge.store import finalize_reviewed_lesson
    f=setup(tmp_path/'checked',value=8,production=True);check(f)
    path=tmp_path/'pack.json';pack=update_project_knowledge(path,'p',[lesson('value-contract',tags=['value@1'],content='value=7 public contract',source_refs=[{'path':'history/observation','sha256':'raw-evidence-hash'}])])['pack']
    with pytest.raises(ValueError,match='verified'):
        finalize_reviewed_lesson(path,'value-contract',f['acceptance'],['g'],reviewer='qualification',expected_hash=digest(pack))
    check(f,value=7,attempt='attempt-0002')
    updated=finalize_reviewed_lesson(path,'value-contract',f['acceptance'],['g'],reviewer='qualification',expected_hash=digest(pack))['pack']
    assert FrozenKnowledge(updated).retrieve(['value@1'])['applied_lesson_ids']==['value-contract']
    assert updated['all_items'][0]['validation']['goals']['g']['receipt_hash']
    f['artifact'].write_text('{"value":8}')
    with pytest.raises(ValueError,match='verified'):
        finalize_reviewed_lesson(path,'value-contract',f['acceptance'],['g'],reviewer='qualification',expected_hash=digest(updated))

from types import SimpleNamespace
import pytest
from cgkn.protocol.repair import execution_repair_history,plain
from cgkn.state.task_feedback import digest
from cgkn.protocol.compiler import TableSnapshot
from cgkn.protocol.normalization import ContractError
from cgkn.orchestration.tree_edits import apply_tree_edits
from test_repair_path import initial, failed_snapshot, repair_packet, run


def context(tree, attempt, verdict='NO_IMPLEMENTATION_PROGRESS', status='FAILED'):
    return SimpleNamespace(tree=tree, execution_results={'n':{'attempt_id':attempt,'status':status,
        'metadata':{'leaf_contract_hash':digest(plain(tree.by_id['n'].config['leaf_contract'])),'implementation_progress':{'verdict':verdict,'evidence_refs':[{'path':'module.py','sha256':'old'}]}}}})


def test_real_compiler_carries_noop_history_to_next_worker_and_blocks_repeat():
    s,t=initial();s=failed_snapshot(s);packet=repair_packet()
    t=apply_tree_edits(t,run(packet,s,t)['edits'],known_capabilities={'code'})
    history=execution_repair_history(context(t,'attempt-1'))
    assert len(history)==1 and history[0]['business_acceptance']=='NOT_INFERRED'
    doc=s.document;doc['repair_context']['previous_repair_attempts']=history;s=TableSnapshot(doc)
    t=apply_tree_edits(t,run(packet,s,t)['edits'],known_capabilities={'code'})
    assert list(t.by_id['n'].config['previous_repair_attempts'])[0]['attempt_id']=='attempt-1'
    assert len(execution_repair_history(context(t,'attempt-1')))==1
    history=execution_repair_history(context(t,'attempt-2'))
    assert [x['attempt_id'] for x in history]==['attempt-1','attempt-2']
    doc=s.document;doc['repair_context']['previous_repair_attempts']=history;s=TableSnapshot(doc)
    with pytest.raises(ContractError,match='REPEATED_REPAIR_NO_PROGRESS'):run(packet,s,t)
    run({**packet,'goal':'A distinct explicit strategy'},s,t)


@pytest.mark.parametrize('verdict,status',[('UNKNOWN','FAILED'),('NO_IMPLEMENTATION_PROGRESS','UNKNOWN'),('NO_IMPLEMENTATION_PROGRESS','SUCCEEDED')])
def test_unknown_transport_and_unqualified_outcomes_not_business_history(verdict,status):
    s,t=initial();s=failed_snapshot(s)
    t=apply_tree_edits(t,run(repair_packet(),s,t)['edits'],known_capabilities={'code'})
    assert execution_repair_history(context(t,'attempt-1',verdict,status))==[]


def test_old_receipt_cannot_be_attributed_to_changed_contract():
    s,t=initial();s=failed_snapshot(s)
    t=apply_tree_edits(t,run(repair_packet(),s,t)['edits'],known_capabilities={'code'})
    ctx=context(t,'old-attempt');ctx.execution_results['n']['metadata']['leaf_contract_hash']='different'
    assert execution_repair_history(ctx)==[]

import pytest
from cgkn.protocol.normalization import ContractError
from cgkn.protocol.progress import admit_progress, strategy_fingerprint
from cgkn.protocol.compiler import TableSnapshot
from test_repair_path import initial, failed_snapshot, repair_packet, run


def packet():
    return {**repair_packet(), 'strategy': {'problem': 'durability', 'network_parallelism': True,
            'persistence_model': 'short_atomic_commit'},
            'hypothesis': {'previous': 'shared writes are safe', 'new': 'atomic commit is required',
                           'falsifying_evidence': ['checker.json'], 'expected_novel_delta': 'all receipts survive'}}


@pytest.mark.parametrize('action',[4,5,8])
def test_real_compiler_requires_semantics_before_worker_dispatch(action):
    s,t=initial();doc=failed_snapshot(s).document;doc['progress_policy']='SEMANTIC_STRATEGY_V1'
    s=TableSnapshot(doc)
    with pytest.raises(ContractError, match='SEMANTIC_STRATEGY_REQUIRED'):
        run({**repair_packet(),'action':action},s,t)
    result=run({**packet(),'action':action},s,t)
    config=next(e.payload['config'] for e in result['edits'] if e.operation=='update_config')
    assert config['repair_contract']['strategy_semantics']['network_parallelism'] is True
    from cgkn.protocol.context_pack import worker_contract_pack
    from cgkn.protocol.repair import plain
    worker=worker_contract_pack({'config':plain(config),'goal':'bounded repair','observations':[]})
    assert worker['strategy_semantics']==packet()['strategy']
    assert worker['hypothesis']==packet()['hypothesis']


def test_same_strategy_rewording_cannot_bypass_no_progress():
    failures=[{'acceptance_id':'a','failure_code':'lost','object_identity':'hash','actual':'missing','evidence_refs':['checker.json']}]
    p=packet();first=admit_progress(p,failures,[])
    history=[{**first,'status':'REPAIR_NO_PROGRESS'}]
    p['goal']='Completely rewritten optimistic explanation'
    p['strategy']['problem']=' DURABILITY '
    with pytest.raises(ContractError,match='REPEATED_REPAIR_NO_PROGRESS'):
        admit_progress(p,failures,history)
    p['strategy']['persistence_model']='transactional_store'
    assert admit_progress(p,failures,history)['strategy_fingerprint']!=first['strategy_fingerprint']


def test_unbound_or_unchanged_hypothesis_rejected():
    p=packet()
    with pytest.raises(ContractError,match='HYPOTHESIS_EVIDENCE_UNBOUND'):
        admit_progress(p,[],[])
    p['hypothesis']['new']=p['hypothesis']['previous']
    with pytest.raises(ContractError,match='HYPOTHESIS_UNCHANGED'):
        admit_progress(p,[],[])


def test_prompt_is_not_a_strategy_dimension():
    with pytest.raises(ContractError,match='STRATEGY_MUST_DESCRIBE_MECHANISM'):
        strategy_fingerprint({'problem':'x','prompt':'different wording','mechanism':'same'})


def test_evidence_falsified_boundary_cannot_be_renamed_to_new_family():
    from cgkn.protocol.progress import check_strategy_constraints
    rules=[{'scope_paths':['publisher.py'],'required_dimensions':['network_inside_lock','persistence_atomic'],
            'forbidden_patterns':[{'network_inside_lock':True},{'persistence_atomic':False}],
            'evidence_refs':['serialized.json','lost_receipts.json']}]
    for values in ({'network_inside_lock':True,'persistence_atomic':True},
                   {'network_inside_lock':False,'persistence_atomic':False}):
        with pytest.raises(ContractError,match='FALSIFIED_STRATEGY_FAMILY'):
            check_strategy_constraints({'problem':'new name',**values},['publisher.py'],rules)
    check_strategy_constraints({'network_inside_lock':False,'persistence_atomic':True},['publisher.py'],rules)
    rules[0]['dimension_types']={'network_inside_lock':'boolean','persistence_atomic':'boolean'}
    with pytest.raises(ContractError,match='STRATEGY_DIMENSION_TYPE'):
        check_strategy_constraints({'network_inside_lock':'false','persistence_atomic':True},['publisher.py'],rules)


def test_progress_and_regression_choose_local_next_operation_without_mutation():
    from cgkn.protocol.progress import ProgressGuidedBacktracking
    before={'verified':['upstream'],'failed':['current']}
    assert ProgressGuidedBacktracking.assess(before,before)['status']=='NO_PROGRESS'
    assert ProgressGuidedBacktracking.assess(before,{'verified':['upstream','current'],'failed':[]})['status']=='PROGRESS'
    assert ProgressGuidedBacktracking.assess(before,{'verified':[],'failed':['current']})['next_operation']=='AFFECTED_SUBGRAPH_REPLAN'
    assert before=={'verified':['upstream'],'failed':['current']}


def test_all_missing_leaf_fields_reported_together():
    s,t=initial();doc=failed_snapshot(s).document;doc['progress_policy']='SEMANTIC_STRATEGY_V1'
    p=packet();p.pop('goal');p.pop('expected');p.pop('accept')
    with pytest.raises(ContractError,match='LEAF_SEMANTIC_FIELDS_REQUIRED') as error:
        run(p,TableSnapshot(doc),t)
    assert set(error.value.fields)=={'goal','expected','accept'}


def test_unbound_evidence_feedback_returns_exact_bound_refs():
    p=packet();p['hypothesis']['falsifying_evidence']=['unrelated.json']
    failures=[{'evidence_refs':[{'path':'attempts/current.json','receipt_hash':'hash'}]}]
    with pytest.raises(ContractError,match='HYPOTHESIS_EVIDENCE_UNBOUND') as error:admit_progress(p,failures,[])
    assert error.value.details['allowed_evidence_refs']==failures[0]['evidence_refs']
    assert error.value.fields==('hypothesis',)

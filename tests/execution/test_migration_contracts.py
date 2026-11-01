"""Positive/negative controls for migration; no historical contract inference."""
import hashlib
import json
import sqlite3
from dataclasses import replace
import pytest

from cgkn.execution import BlockExecutionRequest, BlockExecutionResult, BlockStatus, TaskContext
from cgkn.execution.deliverables import SubjectDeliverableChecker, progress_record
from cgkn.orchestration.leaf_contract import build_leaf_contract, validate_leaf, LeafContractError
from cgkn.orchestration.capability_tree import CapabilityNode, CapabilityTree
from cgkn.providers.finish_reason import finish_disposition


def contract(**changes):
    args=dict(goal='Measure the current object',kind='INSPECTION',scope=['database/object'],
        acceptance=['measure'],checker='subject',output_identity='object-v1',
        effect_domains=['database'],executor='measure@1',subject='database/object',
        expected_observation='current value and version',pass_fail_rule='independent read matches expected value')
    args.update(changes)
    return build_leaf_contract(**args)


def request(c, before):
    return BlockExecutionRequest(project_id='p',run_id='r',node_id='n',attempt_id='a',
        executor_ref='deliverable.subjects@1',component_ref='deliverable.check@1',
        task_context=TaskContext('measure',{'leaf_contract':c}),input_values={'before':before})


def test_new_builder_is_explicit_and_old_deserialization_does_not_upgrade():
    c=contract()
    assert c['schema_version']=='1.0' and c['target_scope']==['database/object']
    old=CapabilityTree.from_dict({'kind':'CGKNCapabilityTree','schema_version':'1.0','goal':'old',
        'nodes':[{'id':'old','capability_ref':'measure@1','config':{'executor_ref':'measure@1'}}]}).nodes[0]
    assert 'leaf_contract' not in old.config
    with pytest.raises(LeafContractError):validate_leaf(old)


def test_nested_frozen_contract_hash_and_progress_equal_plain_contract():
    from cgkn.state.task_feedback import digest
    from types import MappingProxyType
    value = {'interfaces': {'fields': ['name', 'version']}}
    frozen = MappingProxyType({'interfaces': MappingProxyType({'fields': ('name', 'version')})})
    assert digest(frozen) == digest(value)
    c = contract(interface_config=frozen)
    node = CapabilityNode('n', capability_ref='measure@1', config={'executor_ref':'measure@1', 'leaf_contract':c})
    proof = {'verdict':'VERIFIED','observed':{'measurement':{'value':1}},'subjects':{'object':'v1'}}
    assert progress_record(node.config['leaf_contract'], proof) == progress_record(c, proof)


def test_research_artifact_requires_current_source_reference_not_claimed_completion(tmp_path):
    from cgkn.execution.deliverables import FileDeliverableChecker, verified_proof
    source=tmp_path/'source.txt';source.write_text('measured source', encoding='utf-8')
    artifact=tmp_path/'research.json'
    artifact.write_text(json.dumps({'source_ref':'source.txt','source_sha256':hashlib.sha256(source.read_bytes()).hexdigest()}))
    def check(root,c):
        doc=json.loads((root/'research.json').read_text())
        passed=(doc.get('source_ref') in c['source_refs'] and
            doc.get('source_sha256')==hashlib.sha256(source.read_bytes()).hexdigest())
        return {'passed':passed,'observed':doc}
    c=build_leaf_contract(goal='retain traceable research evidence',kind='RESEARCH',scope=['research.json'],
        acceptance=['source-reference'],checker='files',output_identity='research',effect_domains=['research'],
        executor='research@1',source_refs=['source.txt'],completion_criterion='current source hash verified')
    checker=FileDeliverableChecker(tmp_path,{'source-reference':check})
    req=request(c,checker.snapshot(c))
    req=replace(req,executor_ref='deliverable.files@1')
    assert verified_proof(checker.execute(req),req,checker,c)[0]
    source.write_text('changed source',encoding='utf-8')
    assert not verified_proof(checker.execute(req),req,checker,c)[0]


@pytest.mark.parametrize('changes',[
    {'scope':['../outside']},{'scope':[]},{'executor':''},{'kind':'UNKNOWN'},
    {'kind':'IMPLEMENTATION'},{'kind':'RESEARCH'}, {'scope':['a','a']},
])
def test_builder_does_not_relax_strict_validation(changes):
    with pytest.raises(LeafContractError):contract(**changes)


def test_real_sqlite_subject_check_and_failed_business_measurement(tmp_path):
    path=tmp_path/'state.db'
    with sqlite3.connect(path) as db:
        db.execute('create table kv (key text primary key, value text)')
        db.execute("insert into kv values ('current','v1')")
    def read():
        with sqlite3.connect(f'file:{path.as_posix()}?mode=ro',uri=True) as db:
            return db.execute("select value from kv where key='current'").fetchone()[0]
    checker=SubjectDeliverableChecker(lambda c:{'database/object':read()},
        {'measure':lambda r,c:{'passed':read()=='v1','observed':{'value':read()},
            'evidence_refs':[{'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}]}})
    c=contract();before=checker.snapshot(c)
    proof=checker.execute(request(c,before)).outputs['deliverable_check']
    assert proof['verdict']=='VERIFIED' and proof['subjects']['database/object']=='v1'
    with sqlite3.connect(path) as db:db.execute("update kv set value='v2'")
    proof=checker.execute(request(c,before)).outputs['deliverable_check']
    assert proof['verdict']=='FAILED'
    assert proof['non_file_delta']['database/object']['after']=='v2'


@pytest.mark.parametrize('observation',[
    {'passed':True}, {'passed':True,'observed':{'exit':0}},
    {'passed':'true','observed':'claimed','evidence_refs':['raw']},
])
def test_nonfile_checker_rejects_missing_observation_evidence(observation):
    checker=SubjectDeliverableChecker(lambda c:{'database/object':'v1'}, {'measure':lambda r,c:observation})
    with pytest.raises(ValueError):checker.execute(request(contract(),{'database/object':'v1'}))


def test_nonfile_wrong_object_and_mutating_checker_fail_closed():
    checker=SubjectDeliverableChecker(lambda c:{'another-object':'v1'}, {})
    with pytest.raises(ValueError,match='exact target'):checker.snapshot(contract())
    version=['v1']
    def mutate(r,c):
        version[0]='v2'
        return {'passed':True,'observed':'changed','evidence_refs':['raw']}
    checker=SubjectDeliverableChecker(lambda c:{'database/object':version[0]}, {'measure':mutate})
    with pytest.raises(ValueError,match='changed'):checker.execute(request(contract(),{'database/object':'v1'}))


def test_progress_retains_unknown_and_distinguishes_regression_and_readonly():
    c=contract(kind='IMPLEMENTATION',expected_delta='new persistent version')
    proof={'verdict':'FAILED','non_file_delta':{'database/object':{'before':'v1','after':'v2'}}}
    p=progress_record(c,proof)
    assert p['verdict']=='PARTIAL_PROGRESS' and p['test_count_delta']=='UNKNOWN'
    proof['progress_measurements']={'regressions':['R1'],'targeted_fail_delta':1}
    assert progress_record(c,proof)['verdict']=='REGRESSION'
    assert progress_record(contract(),proof)['verdict']=='NOT_APPLICABLE'
    assert progress_record(c,{'verdict':'FAILED'})['verdict']=='NO_IMPLEMENTATION_PROGRESS'


@pytest.mark.parametrize('reason,kw,expected',[
    ('length',{},'split'), ('length',{'partial_verified':True},'continue'),
    ('stop',{},'inspect'),('provider_error',{'retry_safe':True},'retry'),
    ('timeout',{},'inspect'),('timeout',{'outcome_unknown':True,'retry_safe':True},'reconcile'),
    ('unrecognized',{},'escalate'),
])
def test_finish_reason_preserves_raw_and_does_not_authorize_unknown_retry(reason,kw,expected):
    value=finish_disposition(reason,**kw)
    assert value['raw_finish_reason']==reason and value['disposition']==expected
    assert value['acceptance']=='NOT_INFERRED'


@pytest.mark.parametrize('wrong_object',[False,True])
def test_real_nonfile_delta_enters_canonical_feedback(tmp_path,wrong_object):
    from cgkn.executors import ExecutorRegistry,ExecutorDescriptor
    from cgkn.runtime import DAGRunner
    from cgkn.state import FileRunStore
    from cgkn.state.task_feedback import TaskFeedback
    from cgkn.orchestration.execution_dag import compile_tree
    dbpath=tmp_path/'objects.sqlite'
    with sqlite3.connect(dbpath) as db:
        db.execute('create table objects(id text primary key,value text)')
        db.executemany('insert into objects values (?,?)',[('a','v1'),('b','v1')])
    def value():
        with sqlite3.connect(f'file:{dbpath.as_posix()}?mode=ro',uri=True) as db:
            return db.execute("select value from objects where id='a'").fetchone()[0]
    class Update:
        descriptor=ExecutorDescriptor('db.update@1','deterministic',('*',))
        def execute(self,r):
            with sqlite3.connect(dbpath) as db:
                db.execute('update objects set value=? where id=?',('v2','b' if wrong_object else 'a'))
            return BlockExecutionResult(project_id=r.project_id,run_id=r.run_id,node_id=r.node_id,
                attempt_id=r.attempt_id,executor_ref=r.executor_ref,status=BlockStatus.SUCCEEDED,outputs={'updated':True})
    def measure(r,c):
        actual=value()
        return {'passed':actual=='v2','observed':{'id':'a','value':actual},
            'evidence_refs':[dict(r.input_values['execution_receipt_ref']),{'path':str(dbpath),'sha256':hashlib.sha256(dbpath.read_bytes()).hexdigest()}],
            'progress_measurements':{'semantic_delta':{'before':'v1','after':actual},
                'test_count_delta':0,'targeted_pass_delta':int(actual=='v2'),
                'targeted_fail_delta':-int(actual=='v2'),'api_schema_ui_delta':'NOT_APPLICABLE'}}
    checker=SubjectDeliverableChecker(lambda c:{'database/object':value()},{'measure':measure})
    c=contract(kind='IMPLEMENTATION',executor='db.update@1',expected_delta='record a moves from v1 to v2')
    n=CapabilityNode('update',capability_ref='db.update@1',config={'leaf_contract':c})
    registry=ExecutorRegistry();registry.register(Update());registry.register(checker)
    store=FileRunStore(tmp_path/'runs');runner=DAGRunner(registry,store,deliverable_checkers={'subject':'deliverable.subjects@1'})
    tree=CapabilityTree('update one record',(n,));runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree))
    fact=TaskFeedback(store,'p','r').context()['items'][0];p=fact['implementation_progress']
    assert p['verdict']==('NO_IMPLEMENTATION_PROGRESS' if wrong_object else 'MEANINGFUL_PROGRESS')
    assert p['executed_leaves']==['update'] and p['targeted_pass_delta']==int(not wrong_object)
    assert fact['business_acceptance']=='INSUFFICIENT_EVIDENCE'
    if not wrong_object:assert p['non_file_delta']['database/object']=={'before':'v1','after':'v2'}


@pytest.mark.parametrize('kind,fields',[
    ('IMPLEMENTATION',('expected_delta',)),('REPAIR',('expected_delta',)),
    ('RESEARCH',('source_refs','completion_criterion')),
    ('READ_ONLY_ANALYSIS',('source_refs','completion_criterion')),
    ('TEST',('subject','expected_observation','pass_fail_rule')),
    ('INSPECTION',('subject','expected_observation','pass_fail_rule')),
])
def test_public_schema_exposes_runtime_conditional_requirements(kind,fields):
    from jsonschema import Draft202012Validator
    from cgkn.orchestration.leaf_contract import CONTRACT_SCHEMA,build_leaf_contract,validate_leaf
    from cgkn.orchestration import CapabilityNode
    contract=build_leaf_contract(goal='bounded observation',kind=kind,scope=['artifact'],acceptance=['check'],
        checker='trusted',output_identity='artifact',effect_domains=['artifact'],executor='fixture@1',
        expected_delta='materialize artifact',source_refs=['public'],completion_criterion='verified source',
        subject='artifact',expected_observation='actual value',pass_fail_rule='value equals requirement')
    validator=Draft202012Validator(CONTRACT_SCHEMA)
    assert not list(validator.iter_errors(contract))
    for field in fields:
        invalid={k:v for k,v in contract.items() if k!=field}
        assert list(validator.iter_errors(invalid)),(kind,field)
        with pytest.raises(ValueError):
            validate_leaf(CapabilityNode('n',capability_ref='fixture',config={'executor_ref':'fixture@1','leaf_contract':invalid}))

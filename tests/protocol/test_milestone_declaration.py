import copy
import pytest

from cgkn.protocol.declaration import MilestoneContractCompiler, apply_semantic_patch
from cgkn.protocol.normalization import ContractError
from cgkn.protocol.contract_integrity import ContractIntegrityChecker


def semantic():
    return {'semantic_goal':'Store and reopen one local record',
        'public_behavior':'Invalid identifiers raise InvalidRecord; reads never mutate state.',
        'operations':[{'name':'RecordStore','kind':'class','parameters':'root: local path',
                       'returns':'record with name','behavior':'create and reopen records',
                       'failures':['InvalidRecord'],'idempotency':'opening twice preserves bytes',
                       'ordering':'names sorted lexically'}],
        'fields':{'name':{'type':'str','required':True,'consumers':['RecordStore']}},
        'failure_semantics':{'RecordError':{'behavior':'base of public record errors','base':'Exception'},
                             'InvalidRecord':{'behavior':'invalid record identifier','base':'RecordError'}},
        'persistence':'atomic local file replace', 'concurrency':'one writer per record',
        'acceptance_intent':['reopening preserves the record', 'invalid identifier is rejected']}


def compile_it(packet):
    return MilestoneContractCompiler().compile(packet, source_ref='evidence:decision',
        requirement_refs=['workspace'], namespace='project/milestone-one', checker_ref='fixture.acceptance@1')


def test_controller_owned_layout_can_produce_real_entrypoint_without_model_paths():
    packet=semantic()
    design,registry,receipt=MilestoneContractCompiler().compile(packet,source_ref='decision',
        requirement_refs=['entrypoint'],namespace='entrypoint',checker_ref='consumer@1',artifact_subject=True,
        artifact_layout={'source':'app.py','test':'tests/test_app.py'})
    assert [a['path'] for a in design['artifacts']]==['app.py','tests/test_app.py']
    assert all(b['object_ref']=='app.py' for b in receipt['test_binding_skeleton'])
    assert receipt['business_implementation_generated'] is False
    ContractIntegrityChecker.require(registry)


def test_support_documents_are_explicit_owned_artifacts_and_acceptance_subjects():
    design,registry,receipt=MilestoneContractCompiler().compile(semantic(),source_ref='decision',
        requirement_refs=['entrypoint'],namespace='entrypoint',checker_ref='consumer@1',artifact_subject=True,
        artifact_layout={'source':'app.py','test':'tests/test_app.py',
            'support':[{'path':'README.md','purpose':'Document actual startup and public operations'}]})
    assert design['artifacts'][-1]['path']=='README.md'
    assert all(b['subject_refs']==['app.py','README.md'] for b in receipt['test_binding_skeleton'])
    assert receipt['business_implementation_generated'] is False
    ContractIntegrityChecker.require(registry)


@pytest.mark.parametrize('source',['../app.py','F:/app.py','cgkn/core.py','tests/test_app.py','x\\app.py'])
def test_trusted_layout_still_cannot_escape_or_replace_framework(source):
    with pytest.raises(ValueError):
        MilestoneContractCompiler().compile(semantic(),source_ref='decision',requirement_refs=['entrypoint'],
            namespace='entrypoint',checker_ref='consumer@1',artifact_subject=True,
            artifact_layout={'source':source,'test':'tests/test_app.py'})


def test_milestone_compiler_generates_mechanical_bindings_including_base_exception():
    packet = semantic(); before = copy.deepcopy(packet)
    design, registry, receipt = compile_it(packet)
    assert packet == before
    assert compile_it(packet) == (design, registry, receipt)
    ContractIntegrityChecker.require(registry)
    bindings = registry['entries'][0]['definition']['exception_bindings']
    assert {r['name'] for r in bindings} == {'RecordError','InvalidRecord'}
    assert all(r['test_refs'] == [design['artifacts'][1]['path']] for r in bindings)
    assert receipt['operation_exception_mapping'] == {'RecordStore':['InvalidRecord']}
    assert all(r['status'] == 'UNIMPLEMENTED_NOT_VERIFIED' for r in receipt['test_binding_skeleton'])
    assert receipt['business_implementation_generated'] is False
    assert 'schema_version' not in packet and 'test_for' not in str(packet)


@pytest.mark.parametrize('needs_patch',[False,True])
def test_existing_planner_declares_one_milestone_as_proposal_only(needs_patch):
    import json
    from cgkn.agent.composer import AgentComposer, AgentDecisionContext
    from cgkn.orchestration.capability_tree import CapabilityTree
    from cgkn.providers import ModelRoleConfig
    from tests.protocol.test_declaration import RawClient
    packet = semantic()
    if needs_patch:packet['failure_semantics']['RecordError']['behavior']=''
    patch={'patches':[{'op':'replace','path':['failure_semantics','RecordError','behavior'],
                      'value':'base of public record errors'}]}
    client = RawClient([json.dumps(packet),*([json.dumps(patch)] if needs_patch else [])]); events = []
    planner = AgentComposer(client, ModelRoleConfig('agent','fixture'),
        planner_mode='MILESTONE_MODE', protocol_trace=events.append)
    context = AgentDecisionContext('p','r','whole project',1,CapabilityTree('whole project',()),(),{}, {},{},
        goal_acceptance={'requirements':{'workspace':{'must':True}},'checker_bindings':{'workspace':'fixture.acceptance@1'}},
        project_intent={'forbidden_operations':['public publishing']})
    proposal = planner.declare_milestone(context, namespace='first',
        requirement_refs=['workspace'], checker_ref='fixture.acceptance@1')
    assert proposal['admission'] == 'PROPOSAL_ONLY'
    assert proposal['acceptance'] == 'NOT_EVALUATED'
    assert json.loads(client.requests[0]['user'])['context']['project_intent']['forbidden_operations'] == ['public publishing']
    assert len(client.requests) == 1 + int(needs_patch) and events[-1]['status'] == 'COMPILED'
    if needs_patch:
        assert events[0]['error']['fields'] == ['failure_semantics/RecordError/behavior']
        assert 'previous_packet' not in json.loads(client.requests[1]['user'])


@pytest.mark.parametrize('change',[
    lambda p:p.update(checker_id='self'),
    lambda p:p['operations'][0].update(failures=['Undeclared']),
    lambda p:p['failure_semantics']['RecordError'].update(base='InvalidRecord'),
    lambda p:p['fields']['name'].pop('required'),
    lambda p:p.update(operations=p['operations']*9),
    lambda p:p['operations'][0].update(name='../escape'),
])
def test_incomplete_or_ambiguous_semantics_are_not_invented(change):
    packet = semantic(); change(packet)
    with pytest.raises(ContractError): compile_it(packet)


def test_patch_does_not_resend_or_change_goal_and_recompiles_complete_object():
    packet = semantic(); packet['failure_semantics']['RecordError']['behavior'] = ''
    path = ['failure_semantics','RecordError','behavior']
    with pytest.raises(ContractError): compile_it(packet)
    fixed, receipt = apply_semantic_patch(packet, {'patches':[{
        'op':'replace','path':path,'value':'base of public record errors'}]},
        allowed_paths=[path], immutable_paths=[['semantic_goal'],['acceptance_intent']])
    assert packet['failure_semantics']['RecordError']['behavior'] == ''
    assert fixed == semantic()
    assert receipt['committed'] is False and receipt['full_compilation_required']
    compile_it(fixed)


def test_empty_consumers_is_source_leaf_patch_not_compiler_public_interface():
    import json
    from cgkn.agent.composer import AgentComposer,AgentDecisionContext
    from cgkn.orchestration.capability_tree import CapabilityTree
    from cgkn.providers import ModelRoleConfig
    from tests.protocol.test_declaration import RawClient
    packet=semantic();packet['fields']['name']['consumers']=[];before=copy.deepcopy(packet)
    patch={'patches':[{'op':'replace','path':['fields','name','consumers'],'value':['RecordStore']}]}
    client=RawClient([json.dumps(packet),json.dumps(patch)]);events=[]
    planner=AgentComposer(client,ModelRoleConfig('agent','fixture'),planner_mode='MILESTONE_MODE',protocol_trace=events.append)
    ctx=AgentDecisionContext('p','r','whole project',1,CapabilityTree('whole project',()),(),{}, {},{},
        goal_acceptance={'requirements':{'workspace':{'must':True}},'checker_bindings':{'workspace':'fixture.acceptance@1'}})
    result=planner.declare_milestone(ctx,namespace='first',requirement_refs=['workspace'],checker_ref='fixture.acceptance@1')
    assert result['admission']=='PROPOSAL_ONLY' and len(client.requests)==2
    assert events[0]['error']['fields']==['fields/name/consumers']
    correction=json.loads(client.requests[1]['user'])
    assert correction['allowed_patches']==[{'path':['fields','name','consumers'],'exists':True,'required_op':'replace','current_value':[]}]
    assert 'public_interface' not in str(correction['allowed_patches']) and packet==before


def test_inheritance_cycle_identifies_exact_patchable_edge_without_weakening_check():
    packet=semantic()
    packet['failure_semantics']['RecordError']['base']='RecordError'
    with pytest.raises(ContractError) as caught:compile_it(packet)
    path=['failure_semantics','RecordError','base']
    assert caught.value.code=='EXCEPTION_INHERITANCE_CYCLE'
    assert caught.value.fields==('failure_semantics/RecordError/base',)
    assert caught.value.details['cycle_members']==['RecordError']
    fixed,receipt=apply_semantic_patch(packet,{'patches':[{'op':'replace','path':path,'value':'ValueError'}]},allowed_paths=[path])
    assert packet['failure_semantics']['RecordError']['base']=='RecordError'
    assert receipt['changed_paths']==[path]
    compile_it(fixed)
    with pytest.raises(ContractError):compile_it(packet)


@pytest.mark.parametrize('path,op,value',[
    (['semantic_goal'],'replace','different goal'),
    (['failure_semantics'],'replace',{}),
    (['failure_semantics','RecordError','behavior'],'add','duplicate'),
    (['operations',-1],'replace',{}),
])
def test_patch_cannot_escape_server_admitted_mutable_leaf(path, op, value):
    original = semantic(); before = copy.deepcopy(original)
    with pytest.raises(ContractError):
        apply_semantic_patch(original, {'patches':[{'op':op,'path':path,'value':value}]},
            allowed_paths=[['failure_semantics','RecordError','behavior']],
            immutable_paths=[['semantic_goal'],['acceptance_intent']])
    assert original == before


@pytest.mark.parametrize('malformed_patch',[False,True])
def test_exchange_repairs_one_semantic_leaf_without_resending_immutable_object(malformed_patch):
    import json
    from cgkn.protocol.exchange import exchange
    from cgkn.protocol.compiler import TableSnapshot
    from cgkn.providers import ModelRoleConfig
    from tests.protocol.test_declaration import RawClient
    broken = semantic()
    broken['failure_semantics']['RecordError']['behavior'] = ''
    path = ['failure_semantics','RecordError','behavior']
    patch = {'patches':[{'op':'replace','path':path,'value':'base of public record errors'}]}
    client = RawClient([json.dumps(broken),*(['{"patches":'] if malformed_patch else []),json.dumps(patch)])
    events = []
    (design, registry, compilation), _, stats = exchange(client, ModelRoleConfig('agent','fixture'),
        system='Declare only current milestone semantics', context={'goal':'fixture'},
        snapshot=TableSnapshot({'mode':'MILESTONE_MODE'}), semantic_attempt_id='one-milestone',
        compiler=lambda p,h:compile_it(p), normalization={}, trace=events.append, declaration=True,
        semantic_patch_policy=lambda p,e:{'allowed_paths':[path],
            'immutable_paths':[['semantic_goal'],['acceptance_intent']]})
    prompt = json.loads(client.requests[1]['user'])
    assert 'previous_packet' not in prompt and 'immutable_fields' not in prompt
    assert semantic()['semantic_goal'] not in client.requests[1]['user']
    assert prompt['allowed_patches'] == [{'path':path,'exists':True,'required_op':'replace','current_value':''}]
    assert stats['schema_repair_attempts'] == 1 and len(stats['calls']) == 2 + int(malformed_patch)
    assert events[0]['status'] == 'REJECTED'
    assert events[-1]['semantic_packet'] == patch
    assert events[-1]['patched_semantic_packet'] == semantic()
    assert events[-1]['semantic_patch_receipt']['full_compilation_required']
    if malformed_patch:
        assert semantic()['semantic_goal'] not in client.requests[2]['user']
        assert 'previous_packet' not in json.loads(client.requests[2]['user'])
    ContractIntegrityChecker.require(registry)

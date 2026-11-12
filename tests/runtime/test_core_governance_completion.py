from dataclasses import replace,asdict
from pathlib import Path
import json
import pytest
from tools.core_governance_e2e import setup,session,execute,accept,run,records_checker,admit_repair
from cgkn.runtime.node_authority import file_hash
from veriarbor.execution_authority import NodeExecutionResult,NodeCommitReceipt,DecisionRecord
from veriarbor.governance import InputBinding


def relation_control(decisions,context):
    value=records_checker(decisions,context)
    for relation in value['claim_relations']:relation['relation']=context['checker_policy']['relation']
    return value


@pytest.mark.parametrize('relation,warning',[('SUPPORTS',False),('CONTRADICTS',False),('INSUFFICIENT',False),('UNKNOWN',False),('UNKNOWN',True)])
def test_required_claim_relation_policy(tmp_path,relation,warning):
    from veriarbor.execution_authority import CriticalCheckRegistry
    from tools.core_governance_e2e import report_outcome
    a,c,src=setup(tmp_path)
    a.registry=CriticalCheckRegistry();a.registry.register('local.records',relation_control,policy={'relation':relation})
    a.registry.register('local.outcome',report_outcome,role='OUTCOME')
    c=replace(c,claim_unknown_policy='ALLOW_WITH_WARNING' if warning else 'BLOCK')
    n=session(a,c,'report',src)
    if relation=='SUPPORTS' or warning:
        out,r=execute(n,src)
        gates=accept(a,c,r,out)
        assert gates.semantic_status==('UNKNOWN' if warning else 'PASS')
        if warning:assert gates.utility_status!='PASS'
    else:
        with pytest.raises(ValueError,match='CLAIM_'):execute(n,src)


@pytest.mark.boundary
@pytest.mark.happy_path
def test_public_api_three_frontier_project(tmp_path):
    result=run(tmp_path)
    assert result['status']=='PASS' and result['real_provider_calls']==0 and result['tree_version']==4
    assert len(result['receipts'])==3
    for view in result['nodes'].values():
        assert view['checker_identities'] and view['claim_relations'] and view['input_manifest']
        assert view['derivation_summary']['independent_count']==2
        assert view['resource_decision']['closure_state']=='CLOSED'
        assert view['gate_status']['generalization_status']=='PASS'
        assert view['authority_integrity_state']=='VALID' and view['evaluation_scope_refs']
        assert view['effect_operations'] and view['effect_operations'][0]['event_id']


@pytest.mark.parametrize('state,code',[('not-ready','CLAIM_CONTRADICTED'),('unknown','CLAIM_SUPPORT_REQUIRED')])
def test_citation_exists_but_semantics_block(tmp_path,state,code):
    a,c,src=setup(tmp_path,records=[{'id':'a','event':'1','state':state},{'id':'b','event':'2','state':state}])
    node=session(a,c,'extract',src)
    with pytest.raises(ValueError,match=code):execute(node,src)
    view=a.node_view('extract')
    assert not view['commit_receipt_id'] and view['state']=='BLOCKED'
    assert view['resource_decision']['closure_state']=='CLOSED'
    assert src.exists() and view['claim_relations']


def test_duplicate_rows_do_not_satisfy_recurrence(tmp_path):
    a,c,src=setup(tmp_path,records=[{'id':'a','event':'same','state':'ready'},{'id':'b','event':'same','state':'ready'}])
    node=session(a,c,'aggregate',src)
    with pytest.raises(ValueError,match='INDEPENDENCE_POLICY_VIOLATION'):execute(node,src)
    assert a.node_view('aggregate')['derivation_summary']['independent_count']==1


@pytest.mark.parametrize('strategy',['TOP_K_BIASED','DIAGNOSTIC','UNKNOWN'])
def test_biased_good_outcome_cannot_generalize(tmp_path,strategy):
    a,c,src=setup(tmp_path);n=session(a,c,'report',src);out,r=execute(n,src)
    with pytest.raises(ValueError,match='EVALUATION_SCOPE_VIOLATION'):accept(a,c,r,out,strategy=strategy)
    assert a.node_view('report')['gate_status']['generalization_status']!='PASS'


@pytest.mark.parametrize('operation',['PERSISTENT_ARTIFACT_WRITE','PERSISTENT_LIBRARY_WRITE','KNOWLEDGE_PROMOTION','PROFILE_PROMOTION','PRODUCT_EXPORT'])
def test_standard_persistent_effects(tmp_path,operation):
    a,c,src=setup(tmp_path);n=session(a,c,'output',src);out,r=execute(n,src,operation=operation)
    assert a.validate_receipt(r.receipt_id,output_path=str(out),output_hash=file_hash(out))
    assert operation in [e['data'].get('operation') for e in a.events()]


def test_unauthorized_export_and_budget_stop_before_transport(tmp_path):
    a,c,src=setup(tmp_path);n=session(a,c,'remote',src,domains=('external_network',))
    a.begin_node_execution(n.permit_id);called=[]
    with pytest.raises(ValueError,match='UNAUTHORIZED_EFFECT'):
        a.perform_effect(n.permit_id,'PRODUCT_EXPORT',lambda:called.append(True))
    assert called==[] and a.assert_resources_closed(n.permit_id)['actual_outcome']=='BLOCKED'
    with pytest.raises(ValueError,match='ADMISSION_REQUIRED'):
        a.issue_permit(node_id='remote',contract=c,previous_permit_id=n.permit_id)
    admit_repair(a,c,n)
    p=a.issue_permit(node_id='remote',contract=c,previous_permit_id=n.permit_id)
    a.begin_node_execution(p.permit_id)
    with pytest.raises(ValueError,match='BUDGET'):
        a.perform_effect(p.permit_id,'PROVIDER_CALL',lambda:called.append(True),resource_usage={'calls':3})
    assert called==[] and a.assert_resources_closed(p.permit_id)['closure_state']=='CLOSED'
    assert a.assert_resources_closed(p.permit_id)['actual_usage']=={}
    assert a.node_view('remote')['repair_lineage']['failed_permit']==n.permit_id


def test_latest_frozen_and_producer_binding(tmp_path):
    a,c,src=setup(tmp_path);n=session(a,c,'one',src)
    consumed=[dict(n.permit.input_bindings['manifest'][0])];consumed[0]['context']={'dataset':'latest-v4'}
    with pytest.raises(ValueError,match='INPUT_BINDING_REJECT'):execute(n,src,consumed_inputs=consumed)
    admit_repair(a,c,n)
    p=a.issue_permit(node_id='one',contract=c,input_manifest=(InputBinding(str(src),str(src),file_hash(src),'one',
        context={'dataset':'frozen-v3'},execution_mode='IMPORTED_UNMANAGED'),),previous_permit_id=n.permit_id)
    assert p.input_bindings['imported_unmanaged_inputs']==(str(src),)
    a.revoke_permit(p.permit_id)
    with pytest.raises(ValueError,match='INPUT_BINDING_REJECT'):
        a.issue_permit(node_id='one',contract=c,input_manifest=(InputBinding('x',str(src),'bad','one',execution_mode='IMPORTED_UNMANAGED'),))
    with pytest.raises(ValueError,match='INPUT_BINDING_REJECT'):
        a.issue_permit(node_id='one',contract=c,input_manifest=(InputBinding('x',str(src),file_hash(src),'one',
            context={'dataset':'v4'},requirements={'context':{'dataset':'v3'}},execution_mode='IMPORTED_UNMANAGED'),))


def test_missing_checker_and_historical_identity_mismatch(tmp_path):
    a,c,src=setup(tmp_path);n=session(a,c,'report',src);out,r=execute(n,src)
    from veriarbor.execution_authority import CriticalCheckRegistry
    a.registry=CriticalCheckRegistry();a.registry.register('local.records',records_checker,version='2',policy={'states':['changed']})
    assert a.validate_receipt(r.receipt_id)==r
    assert a.audit_receipt(r.receipt_id)['checker_audit'][0]['status']=='HISTORICAL_CHECKER_VERSION_MISMATCH'


@pytest.mark.parametrize('mutation',['permit','check','receipt','delete','reorder','previous_hash'])
def test_authority_tamper_evidence(tmp_path,mutation):
    a,c,src=setup(tmp_path);n=session(a,c,'report',src);out,r=execute(n,src)
    path=a.root/'events.jsonl';rows=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    if mutation=='permit':next(e for e in rows if e['event_type']=='NODE_PERMIT_ISSUED')['data']['permit']['allowed_effects']=['forged']
    elif mutation=='check':next(e for e in rows if e['event_type']=='NODE_CRITICAL_CHECK_RESULT')['data']['check']['status']='FAIL'
    elif mutation=='receipt':next(e for e in rows if e['event_type']=='NODE_COMMITTED')['data']['receipt']['node_id']='forged'
    elif mutation=='delete':rows.pop(2)
    elif mutation=='reorder':rows[2],rows[3]=rows[3],rows[2]
    else:rows[-1]['previous_event_hash']='forged'
    path.write_text('\n'.join(json.dumps(e) for e in rows)+'\n',encoding='utf-8')
    with pytest.raises(ValueError,match='AUTHORITY_INTEGRITY_FAILURE'):a.validate_receipt(r.receipt_id)


@pytest.mark.boundary
@pytest.mark.negative
def test_unclosed_resource_and_legacy_no_fallback(tmp_path):
    a,c,src=setup(tmp_path);n=session(a,c,'report',src);out,r=execute(n,src)
    path=a.store.run_dir(a.project_id,a.run_id)/'capability_governance.json'
    state=json.loads(path.read_text());state['resource_decisions'][0]['closure_state']='OPEN';path.write_text(json.dumps(state))
    with pytest.raises(ValueError,match='RESOURCE_DECISION_UNCLOSED'):a.validate_receipt(r.receipt_id)
    from cgkn.runtime.acceptance import open_goal_acceptance as GoalAcceptance
    with pytest.raises(ValueError,match='LEGACY_NOT_ALLOWED'):GoalAcceptance(a.store,a.project_id,a.run_id,{}, {},execution_mode='LEGACY')


def test_gateway_transport_blocked_without_permit(monkeypatch):
    from cgkn.providers.gateway_client import GatewayCompletionClient
    from cgkn.providers import ModelRoleConfig
    called=[]
    monkeypatch.setattr('cgkn.providers.gateway_client._open_loopback',lambda *args,**kwargs:called.append(True))
    client=GatewayCompletionClient('http://127.0.0.1:1234','test')
    with pytest.raises(ValueError,match='PERMIT_REQUIRED'):
        client.complete(system='test',user='test',schema_name='test',schema={},config=ModelRoleConfig('worker','qwen'))
    assert called==[]


def test_gateway_fake_transport_authorized_and_measured(tmp_path,monkeypatch):
    from cgkn.providers.gateway_client import GatewayCompletionClient
    from cgkn.providers import ModelRoleConfig
    from cgkn.execution.node_effects import execution_scope
    from contextlib import contextmanager
    from types import SimpleNamespace
    a,c,src=setup(tmp_path);n=session(a,c,'remote',src,domains=('external_network',))
    a.begin_node_execution(n.permit_id);calls=[]
    @contextmanager
    def opener(*args,**kwargs):
        calls.append('fake');yield SimpleNamespace(status=200,headers={'Content-Type':'text/event-stream'})
    terminal={'id':'fake-request','status':'completed','model':'qwen','output_text':'{"ok":true}',
        'usage':{'input_tokens':1,'output_tokens':1},'cgkn_stream':{'completed':True},
        'cgkn_model_identity':{'provider_id':'qwen','identity_status':'MATCH','actual_model':'qwen','requested_model':'qwen'}}
    monkeypatch.setattr('cgkn.providers.application_network.settings',lambda:None)
    monkeypatch.setattr('cgkn.providers.gateway_client._open_loopback',opener)
    monkeypatch.setattr('cgkn.providers.gateway_stream.receive',lambda *args,**kwargs:terminal)
    monkeypatch.setenv('CGKN_PROVIDER_CACHE_MODE','off')
    client=GatewayCompletionClient('http://127.0.0.1:1234','test',enforce_budget=False)
    with execution_scope(a,n.permit_id):
        result=client.complete(system='local',user='local',schema_name='test',schema={'type':'object'},config=ModelRoleConfig('worker','qwen'))
    assert json.loads(result.text)=={'ok':True} and calls==['fake']
    events=a.events();assert any(e['event_type']=='NODE_EFFECT_FINISHED' for e in events)
    a.revoke_permit(n.permit_id,'TEST_TRANSPORT_ONLY')
    row=a.assert_resources_closed(n.permit_id)
    assert row['actual_duration']>=0 and row['actual_cost'] is None


def test_artifact_store_requires_permit_and_receipt(tmp_path):
    from cgkn.artifacts.store import ArtifactStore
    from cgkn.artifacts.types import ArtifactTypeRegistry
    from cgkn.artifacts.models import ArtifactInstance,Producer,Provenance
    a,c,src=setup(tmp_path)
    schema=tmp_path/'schema.json';schema.write_text('{"type":"object"}')
    registry=ArtifactTypeRegistry(tmp_path,{'artifact.test@1':{'schema_ref':'schema.json'}})
    store=ArtifactStore(tmp_path/'artifacts-run',registry)
    artifact=ArtifactInstance('a','artifact.test@1',a.run_id,Producer('report','local.worker@1'),{'ok':True},Provenance())
    with pytest.raises(ValueError,match='PERMIT_REQUIRED'):store.write_artifact(artifact)
    output=store.artifacts_dir/'a.json'
    n=session(a,c,'report',src,output_paths=(str(output),))
    with n:
        ref=store.write_artifact(artifact,authority=a,permit_id=n.permit_id)
        with pytest.raises(ValueError,match='COMMIT_RECEIPT_REQUIRED'):store.resolve_governed(ref,authority=a,receipt_id='missing')
        n.record_decision(DecisionRecord('d','records→supported claim','rule',input_refs=(str(src),),
            output_claim='all records ready',claim_ref='claim:ready',check_id='support'))
        n.submit_result((output,),claim_refs=('claim:ready',))
    assert store.resolve_governed(ref,authority=a,receipt_id=n.receipt.receipt_id).id=='a'


def test_external_subprocess_host_only_commit(tmp_path):
    import sys
    a,c,src=setup(tmp_path);n=session(a,c,'child',src,domains=('local_process',))
    child=tmp_path/'child.py'
    child.write_text('''import os,json,pathlib,hashlib
p=json.loads(pathlib.Path(os.environ['NODE_EXECUTION_PERMIT']).read_text())
out=pathlib.Path(os.environ['NODE_EXECUTION_RESULT']).parent/'child.json'
out.write_text('{"result":"local"}')
decision=dict(decision_id='d',semantic_transform='records→supported claim',strategy_id='rule',input_refs=list(p['input_hashes']),output_claim='all records ready',claim_ref='claim:ready',check_id='support')
result=dict(permit_id=p['permit_id'],output_hashes={str(out):hashlib.sha256(out.read_bytes()).hexdigest()},input_hashes=p['input_hashes'],decision_records=[decision],claim_refs=['claim:ready'],consumed_inputs=p['input_bindings']['manifest'])
pathlib.Path(os.environ['NODE_EXECUTION_RESULT']).write_text(json.dumps(result))
''',encoding='utf-8')
    a.run_subprocess(n.permit_id,[sys.executable,str(child)])
    assert not a.node_view('child')['commit_receipt_id']
    receipt=a.commit_node_execution(n.permit_id)
    assert a.validate_receipt(receipt.receipt_id)
    assert a.assert_resources_closed(n.permit_id)['actual_duration']>0


def test_skill_receipt_promotion_revalidation_and_no_bypass(tmp_path):
    from veriarbor.skills import SkillManifest,SkillMatcher,promotion_check
    from cgkn.adapters.veriarbor.skill_authority import GovernedSkillLifecycle
    authorities=[];ids=[]
    for run_id in ('one','two'):
        a,c,src=setup(tmp_path/run_id,run_id=run_id)
        m=SkillManifest('records','1','records','Supported local records','',scope='SHARED',
            strategy_steps=({'operation':'execute','node_id':'report'},),block_refs=('local.worker@1',),
            port_contract_refs=('records-port',),capability_contract_refs=(c.capability_id,),acceptance_refs=('quality',),
            dependency_versions={'local.worker@1':'1'},dependency_contract_hashes={'records-port':'1',c.capability_id:c.fingerprint},
            created_from_tree_branch='ROOT/report',source_capability=c.capability_id,
            checker_identities={'local.records':a.registry.identity('local.records').as_dict()})
        n=session(a,c,'report',src,input_bindings={'strategy_hash':m.strategy_hash})
        out,r=execute(n,src);accept(a,c,r,out);authorities.append(a);ids.append(r.receipt_id)
    lifecycle=GovernedSkillLifecycle(tmp_path/'skills',authorities)
    candidate,validations=lifecycle.candidate(m,ids)
    for missing in ('utility_status','generalization_status'):
        altered=tuple(replace(v,gates=replace(v.gates,**{missing:'NOT_TESTED'})) for v in validations)
        assert not promotion_check(candidate,altered,receipt_validator=lifecycle.validate)
    lifecycle.registry.register(candidate)
    verified=lifecycle.registry.update_status('records','1','VERIFIED',validations)
    assert verified.status=='VERIFIED'
    matcher=SkillMatcher(lifecycle.registry)
    task=dict(project_id=authorities[0].project_id,task_family='records',capability_id=c.capability_id,
        inputs=(),outputs=(),dependency_versions=m.dependency_versions,dependency_contract_hashes=m.dependency_contract_hashes)
    assert matcher.load(**task,checker_identities=m.checker_identities)
    with pytest.raises(ValueError,match='PERMIT_CONSUMED'):
        authorities[0].perform_effect(authorities[0].validate_receipt(ids[0]).permit_id,'PRODUCT_EXPORT',lambda:None)
    changed={k:{**v,'implementation_hash':'new'} for k,v in m.checker_identities.items()}
    assert matcher.load(**task,checker_identities=changed)==[]
    assert lifecycle.registry.lookup('records','1').status=='NEEDS_REVALIDATION'
    assert authorities[0].node_view('report')['skill_state']['status']=='NEEDS_REVALIDATION'


def test_old_receipt_schema_does_not_fabricate_identity(tmp_path):
    a,c,src=setup(tmp_path);n=session(a,c,'report',src);_,r=execute(n,src)
    old=r.as_dict()
    for key in ('schema_version','checker_identities','claim_relations','derivation_summary','input_manifest','resource_decision_id','authority_checkpoint'):
        old.pop(key)
    parsed=NodeCommitReceipt(**old)
    assert parsed.schema_status=='LEGACY_RECEIPT_SCHEMA' and not parsed.checker_identities


@pytest.mark.happy_path
@pytest.mark.negative
@pytest.mark.boundary
@pytest.mark.security
def test_optional_checkpoint_uses_existing_signer_and_purpose(tmp_path):
    import base64
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    from tools.sign_release_authorization import sign_document
    a,c,src=setup(tmp_path);n=session(a,c,'report',src);execute(n,src)
    key=Ed25519PrivateKey.generate()  # Ephemeral test key only, never persisted.
    signed=sign_document(a.chain_checkpoint(),key=key,key_id='test')
    anchor={'keys':{'test':{'purpose':'node_authority_checkpoint','public_key_b64':base64.b64encode(
        key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)).decode()}}}
    assert a.verify_checkpoint(signed,anchor=anchor,require_signature=True)
    signed['event_hash']='changed'
    with pytest.raises(ValueError,match='AUTHORITY_INTEGRITY_FAILURE'):a.verify_checkpoint(signed,anchor=anchor,require_signature=True)
    signed=sign_document(a.chain_checkpoint(),key=key,key_id='test')
    anchor['keys']['test']['purpose']='final_delivery_source_authorization'
    with pytest.raises(ValueError,match='AUTHORITY_INTEGRITY_FAILURE'):a.verify_checkpoint(signed,anchor=anchor,require_signature=True)


def test_repair_closes_without_overwriting_failed_attempt(tmp_path):
    from cgkn.adapters.veriarbor.capability_adapter import load
    a,c,src=setup(tmp_path);n=session(a,c,'report',src)
    wrong=[dict(n.permit.input_bindings['manifest'][0])];wrong[0]['context']={'dataset':'wrong'}
    with pytest.raises(ValueError,match='INPUT_BINDING_REJECT'):execute(n,src,consumed_inputs=wrong)
    admit_repair(a,c,n)
    p=a.issue_permit(node_id='report',contract=c,input_manifest=n.permit.input_bindings['manifest'],previous_permit_id=n.permit_id)
    a.begin_node_execution(p.permit_id)
    rows=json.loads(src.read_text())['records']
    out=a.store.publish_business_json(a,p.permit_id,'repaired.json',{'records':rows,'claim':'all records ready','independent_count':2})
    d=DecisionRecord('repair-d','records→supported claim','rule',input_refs=(str(src),),output_claim='all records ready',claim_ref='claim:ready',check_id='support')
    a.submit_node_result(NodeExecutionResult(p.permit_id,{str(out):file_hash(out)},decision_records=(d,),input_hashes=p.input_hashes,
        consumed_inputs=p.input_bindings['manifest'],claim_refs=('claim:ready',)))
    r=a.commit_node_execution(p.permit_id);accept(a,c,r,out)
    state=load(a.store,a.project_id,a.run_id)
    old=next(row for row in state['resource_decisions'] if row['permit_id']==n.permit_id)
    assert old['status']=='FAILED' and old['actual_outcome']=='BLOCKED'
    trace=state['failure_repair_traces'][0]
    assert trace['failed_permit']==n.permit_id and trace['new_permit']==p.permit_id
    assert trace['repair_proposal'].startswith('repair-') and trace['artifact_after']
    assert trace['acceptance_delta']['utility_after']=='PASS' and trace['closure_state']=='CLOSED'


def test_cross_project_skill_import_requires_current_target_receipts(tmp_path):
    from veriarbor.skills import SkillManifest,SkillMatcher
    from cgkn.adapters.veriarbor.skill_authority import GovernedSkillLifecycle
    from cgkn.runtime.node_authority import ExecutionAuthority
    authorities=[];source_ids=[]
    for run_id in ('source-one','source-two'):
        a,c,src=setup(tmp_path/run_id,run_id=run_id)
        manifest=SkillManifest('portable-records','1','records','Validate local records',a.project_id,
            strategy_steps=({'operation':'execute','node_id':'report'},),
            capability_contract_refs=(c.capability_id,),source_capability=c.capability_id,
            block_refs=('local.worker@1',),port_contract_refs=('records-port',),
            acceptance_refs=('quality',),created_from_tree_branch='ROOT/report',
            dependency_versions={'local.worker@1':'1'},
            dependency_contract_hashes={'records-port':'1',c.capability_id:c.fingerprint},
            checker_identities={'local.records':a.registry.identity('local.records').as_dict()})
        node=session(a,c,'report',src,input_bindings={'strategy_hash':manifest.strategy_hash})
        out,receipt=execute(node,src);accept(a,c,receipt,out)
        authorities.append(a);source_ids.append(receipt.receipt_id)
    source=GovernedSkillLifecycle(tmp_path/'source-skills',authorities)
    candidate,validations=source.candidate(manifest,source_ids)
    source.registry.register(candidate)
    source.registry.update_status(manifest.skill_id,'1','VERIFIED',validations)
    packet=source.export(manifest.skill_id,'1')
    target_ids=[];target_lifecycles=[]
    for run_id in ('target-one','target-two'):
        base,c,src=setup(tmp_path/run_id,run_id=run_id)
        a=ExecutionAuthority(base.store,'target-project',run_id,registry=base.registry)
        authorities.append(a)
        target=GovernedSkillLifecycle(tmp_path/run_id/'skills',authorities)
        imported=target.import_candidate(packet,project_id='target-project')
        assert imported.status=='NEEDS_REVALIDATION' and not imported.source_receipts
        task=dict(task_family='records',capability_id=c.capability_id,inputs=(),outputs=(),
            dependency_versions=imported.dependency_versions,dependency_contract_hashes=imported.dependency_contract_hashes,
            checker_identities=imported.checker_identities)
        assert SkillMatcher(target.registry).load(project_id='target-project',**task)==[]
        assert target.trial_manifest({'skill_id':manifest.skill_id,'version':'1'},project_id='target-project',task=task)==imported
        with pytest.raises(ValueError,match='applicability'):
            target.trial_manifest({'skill_id':manifest.skill_id,'version':'1'},project_id='target-project',task={**task,'outputs':('foreign',)})
        with pytest.raises(ValueError,match='source-project'):
            target.requalify(manifest.skill_id,'1',source_ids,project_id='target-project')
        node=session(a,c,'report',src,input_bindings={'strategy_hash':imported.strategy_hash})
        out,receipt=execute(node,src);accept(a,c,receipt,out);target_ids.append(receipt.receipt_id)
        target_lifecycles.append(target)
    target=target_lifecycles[-1]
    with pytest.raises(ValueError,match='PROMOTION_REJECT'):
        target.requalify(manifest.skill_id,'1',target_ids[:1],project_id='target-project')
    qualified=target.requalify(manifest.skill_id,'1',target_ids,project_id='target-project')
    assert qualified.status=='VERIFIED' and set(qualified.source_receipts)==set(target_ids)
    assert SkillMatcher(target.registry).load(project_id='target-project',**task)
    assert source.registry.lookup(manifest.skill_id,'1').source_receipts==tuple(source_ids)

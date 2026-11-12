"""Offline production-component chain, not a paid model/product witness."""
import hashlib
import json
import runpy
import pytest

from cgkn.agent import AgentComposer, ProjectSession
from cgkn.execution import BlockExecutionResult, BlockStatus
from cgkn.execution.deliverables import FileDeliverableChecker, SubjectDeliverableChecker
from cgkn.executors import ExecutorDescriptor, ExecutorRegistry, LLMExecutor
from cgkn.providers import ModelRoleConfig, ProviderCompletion
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore
from cgkn.runtime.acceptance import open_goal_acceptance as GoalAcceptance
from cgkn.state.acceptance import identity


class FakeModels:
    def __init__(self): self.calls=[];self.worker_calls=0;self.execution_decisions=0
    def complete(self, **kw):
        self.calls.append(kw);request=json.loads(kw['user'])
        if kw['config'].role=='worker':
            from tests.generation_migration_support import semantic_submission
            submitted=semantic_submission(kw)
            if submitted is not None:return submitted
            self.worker_calls+=1
            # Controlled wrong first candidate; only the fake Worker repairs.
            row=next(p for p in request['tables']['paths'] if p['writable'])
            if row['path'].startswith('tests/'):
                payload='from pathlib import Path\nimport runpy\ndef test_current_value():\n    assert runpy.run_path(str(Path(__file__).resolve().parents[1] / '+repr(self.source_path)+'))["value"]() == 7\n'
            else:
                self.source_path=row['path']
                payload='def value():\n    return '+('6' if self.worker_calls==1 else '7')+'\n'
            value={'op':2,'path':row['id'],'payload':payload}
        elif kw['schema_name']=='cgkn_next_milestone':
            value={'requirement_refs':['R-value'],'checker':'independent',
                   'reason_summary':'Implement and independently check one pure function'}
        elif request['tables'].get('mode')=='MILESTONE_MODE':
            value={'semantic_goal':'Implement value returning seven','public_behavior':'value() returns integer 7',
                   'operations':[{'name':'value','kind':'function','parameters':'no arguments','returns':'int',
                                  'behavior':'return integer 7','failures':[], 'idempotency':'same result every call','ordering':'single result'}],
                   'fields':{'result':{'type':'int','required':True,'consumers':['value']}},
                   'failure_semantics':{},'persistence':'none','concurrency':'read only',
                   'acceptance_intent':['value() returns integer 7']}
        else:
            self.execution_decisions+=1
            tables=request['tables']
            if self.execution_decisions==1:
                value={'action':1,'task_kind':2,'target':0,'scope':[0],'goal':'Implement current value function',
                       'expected':['Python module exports value'], 'accept':['valid public source'], 'deps':[]}
            elif self.execution_decisions==2:
                value={'action':1,'task_kind':2,'target':1,'scope':[1],'goal':'Materialize declared public test',
                       'expected':['test exercises current value function'],'accept':['valid public test source'],'deps':[]}
            elif self.execution_decisions==3:
                value={'action':1,'task_kind':4,'target':2,'scope':[0],'goal':'Independently measure current function',
                       'expected':['current value() measurement'],'accept':['independent measurement envelope'], 'deps':[0,1]}
            elif self.execution_decisions==4:
                assert request['context']['goal_state']['failed']==['R-value']
                from cgkn.protocol.context_pack import expand_failures
                evidence=[ref for failure in expand_failures(request['context'])
                          for ref in failure.get('evidence_refs',[])]
                value={'action':4,'task_kind':3,'target':0,'scope':[0],'goal':'Repair observed value contract failure',
                       'expected':['value returns 7'], 'accept':['valid source and retained public contract'], 'deps':[],
                       'strategy':{'problem':'wrong_scalar','return_type':'integer','return_value':7},
                       'hypothesis':{'previous':'the first scalar satisfies the contract',
                           'falsifying_evidence':evidence,'new':'the scalar must equal the contracted seven',
                           'expected_novel_delta':'independent value measurement returns seven'}}
            else: value={'action':9}
        return ProviderCompletion(json.dumps(value),'offline-'+kw['config'].role,'call-'+str(len(self.calls)),
                                  {'input_tokens':10,'output_tokens':20},raw_finish_reason='stop')


def test_offline_gateway_contract_core_to_existing_delivery(tmp_path,monkeypatch,explicit_probe=False):
    """Network is stubbed: exercises receipt protocol, never a real witness."""
    from pathlib import Path
    from cgkn.providers import GatewayCompletionClient,CGKNModelRouting
    from cgkn.application.software_project.service import SoftwareProjectGenerationService
    from scripts import production_candidate_provenance,provider_causal_trace
    workspace=tmp_path/'candidate'
    files={'main.py':'def value():\n    return 7\n\nif __name__ == "__main__":\n    print(value())\n',
           'README.md':'# Seven\nPython standard library. Run: python main.py\nTests: python -m pytest tests\n',
           'tests/test_main.py':'from main import value\ndef test_value():\n    assert value() == 7\n'}
    if explicit_probe:
        files['main.py'] += '    import sys\n    raise SystemExit(0 if len(sys.argv)==1 else 2)\n'
    model=FakeModels();steps=[];provider_calls=[]
    def complete(gateway,**kw):
        provider_calls.append(kw)
        assert len(provider_calls)<20, 'offline fixture must not hide a planner loop'
        request=json.loads(kw['user']);config=kw['config']
        if config.role=='worker':
            row=next(p for p in request['tables']['paths'] if p['writable'])
            from tests.generation_migration_support import semantic_submission
            packet={'op':5} if semantic_submission(kw) is not None else {'op':2,'path':row['id'],'payload':files[row['path']]}
        elif kw['schema_name']=='cgkn_next_milestone' or request['tables'].get('mode')=='MILESTONE_MODE':
            reply=model.complete(**kw)
            packet=json.loads(reply.text)
        else:
            tables=request['tables'];index=len(steps);steps.append(index)
            if index<3:
                name=list(files)[index]
                packet={'action':1,'task_kind':2,
                    'target':next(n['id'] for n in tables['nodes'] if n['state']=='available'),
                    'scope':[next(s['id'] for s in tables['scopes'] if s['path']==name)],
                    'goal':'Materialize declared '+name,'expected':['declared file exists'],
                    'accept':['declared public contract'],'deps':[]}
            elif index==3:
                packet={'action':1,'task_kind':4,
                    'target':next(n['id'] for n in tables['nodes'] if n['state']=='available'),
                    'scope':[s['id'] for s in tables['scopes'] if s['path'] in {'main.py','README.md'}],
                    'goal':'Independently verify current value and documentation',
                    'expected':['current independent measurement'],'accept':['measurement envelope'],
                    'deps':[n['id'] for n in tables['nodes'] if n['state']=='existing']}
            else: packet={'action':9}
        return ProviderCompletion(json.dumps(packet),config.model_id,'offline-gateway-'+str(len(provider_calls)),
            {'input_tokens':10,'output_tokens':20},raw_finish_reason='stop',routing={
                'identity_status':'MATCH','provider_id':config.model,'requested_model':config.model_id,
                'bound_model':config.model_id,'actual_model':config.model_id})
    monkeypatch.setattr(GatewayCompletionClient,'complete',complete)
    routing=CGKNModelRouting(ModelRoleConfig('agent','qwen',model_id='offline-flash'),
        ModelRoleConfig('worker','deepseek',model_id='offline-worker'),frozenset({'qwen','deepseek'}))
    from tests.session_authority_support import authorization
    service=SoftwareProjectGenerationService(Path(__file__).resolve().parents[2],tmp_path/'state',
        client=GatewayCompletionClient('http://127.0.0.1:9','offline-test-token'),routing=routing,
        config={'execution_authorization':authorization('offline-delivery',('code.implement@1','project.acceptance.external@1'),'return seven')})
    consumer=tmp_path/'consumer.py'
    consumer.write_text("import json,sys,pathlib,runpy\nr=json.loads(pathlib.Path(sys.argv[2]).read_text())\n"
        "w=pathlib.Path(r['workspace'])\n"
        "ok=runpy.run_path(str(w/'main.py'))['value']()==7 and (w/'README.md').is_file()\n"
        "print(json.dumps({'execution':'VALID','observed':{'value':ok}}))\n")
    profile=tmp_path/'profile.json'
    profile.write_text(json.dumps({'kind':'CGKNProjectSessionProfile','schema_version':'1.0',
        'project_id':'offline-delivery','run_id':'run','workspace':str(workspace),
        'intent':{'overall_goal':'return seven','user_visible_outcomes':['value() returns 7'],
            'constraints':['Python standard library'],'forbidden_operations':['external publication'],
            'delivery_expectations':['runnable local tool and tests'],'major_acceptance_categories':['value']},
        'requirements':{'R-value':{'must':True,'checker_keys':['independent'],'artifact_layout':{
            'source':'main.py','test':'tests/test_main.py','support':[{'path':'README.md','purpose':'Document local startup and tests'}]}}},
        'independent_consumer':{'path':str(consumer),'sha256':hashlib.sha256(consumer.read_bytes()).hexdigest(),
            'public_fields':['value']},'checkpoint_interval':1}))
    result=service.run_profile(profile,goal='return seven')
    finish_options={}
    if explicit_probe:
        from scripts import canonical_evidence_hash
        assert result['status']=='GOALS_VERIFIED' and result['delivery_status']=='BLOCKED'
        assert result['finalization']['runtime_result']['status']=='FAIL'
        root=Path(result['run_dir'])
        core=json.loads(next((root/'core_results').glob('*.json')).read_text())
        blocked=root/'delivery_attempts'/identity(core)/'result.json';original=blocked.read_bytes()
        proof=tmp_path/'verified-runtime-contract.json';proof.write_text('{"public_startup":"python main.py","expected_stdout":"7"}')
        finish_options={'cli_probe':{'entrypoint':'main.py','args':[],'stdout_contains':'7',
            'source_ref':str(proof),'source_sha256':canonical_evidence_hash.sha256_file(proof)},
            'verification_revision':{'revision_id':'b'*64,'reason':'Explicit no-argument public startup contract',
                'evidence_ref':str(proof),'evidence_sha256':canonical_evidence_hash.sha256_file(proof)}}
        before=len(provider_calls)
        result=service.finalize_core(json.loads(profile.read_text()),core,**finish_options)
        assert len(provider_calls)==before and blocked.read_bytes()==original
        assert list((root/'delivery_attempts').glob('*/prior_evidence_manifest.json'))
    assert result['status']=='GOALS_VERIFIED',result
    assert result['target_goal_satisfied']
    root=Path(result['run_dir'])
    assert production_candidate_provenance.inspect(root/production_candidate_provenance.FILE_NAME)['status']=='PASS'
    assert provider_causal_trace.inspect(root/provider_causal_trace.FILE_NAME)['status']=='PASS'
    assert not (workspace/'pytest.ini').exists()
    assert all((workspace/p).read_text()==content for p,content in files.items())
    assert result['finalization']['test_result']['status']=='PASS'
    assert result['finalization']['runtime_result']['status']=='PASS'
    assert result['public_delivery_allowed'],result['finalization'].get('gate')
    core=json.loads(next((root/'core_results').glob('*.json')).read_text())
    frozen_profile=json.loads(profile.read_text())
    calls_before=len(provider_calls)
    assert service.finalize_core(frozen_profile,core,**finish_options)['public_delivery_allowed']
    response=next((root/'provider_calls').glob('*/response.json'))
    original=response.read_bytes();tampered=json.loads(original)
    tampered['model']='unexpected-model'
    (tmp_path/'original-response.json').write_bytes(original)
    response.write_text(json.dumps(tampered))
    assert production_candidate_provenance.inspect(root/production_candidate_provenance.FILE_NAME)['status']=='NEEDS_REWORK'
    assert provider_causal_trace.inspect(root/provider_causal_trace.FILE_NAME)['status']=='NEEDS_REWORK'
    invalid=service.finalize_core(frozen_profile,core,**finish_options)
    assert invalid['delivery_status']=='BLOCKED' and not invalid['public_delivery_allowed']
    (tmp_path/'tamper-control.json').write_text(json.dumps(invalid))
    response.write_bytes(original)
    assert service.finalize_core(frozen_profile,core,**finish_options)['public_delivery_allowed']
    assert len(provider_calls)==calls_before


def test_offline_explicit_runtime_reverification_uses_same_delivery_gate(tmp_path,monkeypatch):
    test_offline_gateway_contract_core_to_existing_delivery(tmp_path,monkeypatch,explicit_probe=True)


@pytest.mark.parametrize('entry',['session','application_service','profile','conversation','api_job','local_cli'])
def test_milestone_compiler_worker_independent_failure_repair_and_checkpoint(tmp_path,entry,monkeypatch):
    workspace=tmp_path/'workspace';workspace.mkdir()
    store=FileRunStore(tmp_path/'state')
    acceptance=GoalAcceptance(store,'p','r',{'R-value':{'must':True,'checker_keys':['independent']}},
                              {'independent':'project.acceptance@1' if entry in {'profile','conversation','api_job','local_cli'} else 'measure@1'})
    acceptance.bind_subjects({'module':'NOT_YET_PRODUCED'})
    class Measure:
        descriptor=ExecutorDescriptor('measure@1','deterministic',('*',))
        def execute(self, request):
            goal=next(g for g in acceptance.view()['goals'] if g['id']==request.task_context.node_config['goal_id'])
            path=workspace/goal['milestone_contract']['design']['artifacts'][0]['path']
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            actual=runpy.run_path(str(path))['value']()
            subjects={p:digest for p in goal['subject_refs']}
            acceptance.bind_subjects({**acceptance.view()['subject_identities'],**subjects})
            return BlockExecutionResult(project_id=request.project_id,run_id=request.run_id,
                node_id=request.node_id,attempt_id=request.attempt_id,executor_ref='measure@1',
                status=BlockStatus.SUCCEEDED,outputs={'goal_check':{'goal_id':goal['id'],
                    'condition_hash':identity(goal['acceptance']),'subjects':subjects,
                    'execution':'VALID','evidence_refs':[str(path)],'observed':{'actual':actual,'expected':7},
                    'verdict':'VERIFIED' if actual==7 else 'FAILED'}})
    def valid_source(root,contract):
        import ast
        files=list(contract['target_scope'])
        for relative in files: ast.parse((root/relative).read_text())
        return {'passed':True,'observed':{'parsed':files},'artifacts':files}
    def snapshot(contract):
        return {p:hashlib.sha256((workspace/p).read_bytes()).hexdigest() if (workspace/p).is_file() else None
                for p in contract['target_scope']}
    def envelope(request,contract):
        measured=request.as_dict()['input_values']['execution_receipt']['outputs']['goal_check']
        return {'passed':all(acceptance.view()['subject_identities'].get(k)==v for k,v in measured['subjects'].items()),
                'observed':measured,'evidence_refs':[dict(request.input_values['execution_receipt_ref'])]}
    client=FakeModels();events=[]
    registry=ExecutorRegistry()
    registry.register(Measure())
    registry.register(FileDeliverableChecker(workspace,{'source':valid_source}))
    registry.register(SubjectDeliverableChecker(snapshot,{'envelope':envelope}))
    catalog={'code@1':{'executor_ref':'llm.cheap@1','semantic_task_kinds':[2,3],
                       'checker_ref':'source','acceptance':['source'],'effect_domains':['filesystem','external_network'],
                       'description':'Bounded pure function implementation and repair'},
             'measure@1':{'executor_ref':'measure@1','semantic_task_kinds':[4],
                          'checker_ref':'measurement','acceptance':['envelope'],'effect_domains':['measurement'],
                          'description':'Independent current-object business checker'}}
    intent={'overall_goal':'return seven','user_visible_outcomes':['value() returns 7'],'constraints':['offline'],
            'forbidden_operations':['network'],'delivery_expectations':['checked local module'],
            'major_acceptance_categories':['function result']}
    bindings={'source':'deliverable.files@1','measurement':'deliverable.subjects@1'}
    from tests.session_authority_support import authorization
    from cgkn.agent.project_agent import AdmissionPolicy
    auth=authorization('p',('code@1','measure@1','code.implement@1','project.acceptance.external@1'),'return seven')
    if entry=='session':
        registry.register(LLMExecutor(workspace,client,ModelRoleConfig('worker','offline-worker'),
                                      semantic_protocol=True,protocol_trace=events.append))
        session=ProjectSession(AgentComposer(client,ModelRoleConfig('agent','offline-flash'),
            planner_mode='MILESTONE_MODE',protocol_trace=events.append),
            DAGRunner(registry,store,deliverable_checkers=bindings),
            store,known_capabilities=set(catalog),worker_model='offline-worker',capability_catalog=catalog,
            acceptance=acceptance,continuous=True,max_decisions=1,admission_policy=AdmissionPolicy(**auth['admission_policy']),
            subject_snapshot=lambda paths:snapshot({'target_scope':paths}))
        result=session.run(project_id='p',run_id='r',goal='return seven',project_intent=intent)
    else:
        from pathlib import Path
        from cgkn.application.software_project.service import SoftwareProjectGenerationService
        service=SoftwareProjectGenerationService(Path(__file__).resolve().parents[2],store.root,client=client,config={'execution_authorization':auth})
        if entry in {'profile','conversation','api_job','local_cli'}:
            consumer=tmp_path/'consumer.py'
            consumer.write_text("import json,sys,pathlib,runpy\n"
                "r=json.loads(pathlib.Path(sys.argv[2]).read_text(encoding='utf-8'))\n"
                "p=pathlib.Path(r['workspace'])/next(iter(r['subjects']))\n"
                "v=runpy.run_path(str(p))['value']()\n"
                "print(json.dumps({'execution':'VALID','observed':{'value':v==7,'actual':v}}))\n")
            profile=tmp_path/'controller/.cgkn/project-session.json'
            profile.parent.mkdir(parents=True)
            profile.write_text(json.dumps({'kind':'CGKNProjectSessionProfile','schema_version':'1.0',
                'project_id':'p','run_id':'r','workspace':str(workspace),'intent':intent,
                'requirements':{'R-value':{'must':True,'checker_keys':['independent']}},
                'independent_consumer':{'path':str(consumer),'sha256':hashlib.sha256(consumer.read_bytes()).hexdigest(),
                    'public_fields':['value','actual']},'checkpoint_interval':1}))
            if entry in {'conversation','api_job','local_cli'}:
                from scripts import codex_conversation
                from cgkn.application.software_project import service as service_module
                monkeypatch.setattr(service_module,'SoftwareProjectGenerationService',lambda *a,**k:service)
                monkeypatch.setattr(codex_conversation,'CodexConversation',lambda:pytest.fail('legacy execution entered'))
                if entry=='conversation':
                    document=codex_conversation.run_formal_generation_once(tmp_path/'controller',goal='return seven')
                elif entry=='api_job':
                    api_session={'project_session_profile':str(profile),'whiteboard':{'project_summary':'return seven'}}
                    monkeypatch.setattr(codex_conversation,'load_session',lambda *a:api_session)
                    monkeypatch.setattr(codex_conversation,'save_session',lambda *a:None)
                    codex_conversation.start_generation_from_income(None,'api',tmp_path,tmp_path,'ignored',60,
                        api_session,reason='offline full chain',background=False)
                    assert api_session['generation']['status']=='goals_verified'
                    document=json.loads(next((store.run_dir('p','r')/'core_results').glob('*.json')).read_text())
                else:
                    from scripts import run_local_pipeline
                    from types import SimpleNamespace
                    document=run_local_pipeline.execute(SimpleNamespace(use_api=True,provider_mode='live',
                        goal='return seven',project_session_profile=str(profile),run_dir=store.root,
                        result=tmp_path/'local-result.json'))
            else:
                document=service.run_profile(profile,goal='return seven')
            assert document['status']=='GOALS_VERIFIED'
            assert document['public_delivery_allowed'] is False
            assert document['delivery_status']=='NOT_EVALUATED'
            acceptance=GoalAcceptance(store,'p','r',{'R-value':{'must':True,'checker_keys':['independent']}},
                {'independent':'project.acceptance@1'})
            assert [c['verdict'] for c in acceptance.data['checks']]==['FAILED','VERIFIED']
            assert [c['observation']['observed']['actual'] for c in acceptance.data['checks']]==[6,7]
            assert all(c['provenance']['status']=='TRUSTED' for c in acceptance.data['checks'])
            assert acceptance.view()['evidence_mode']=='production_provenance'
            from cgkn.state.provenance import ProvenanceGate,ProvenanceError
            gate=ProvenanceGate(store,'p','r')
            from scripts.canonical_evidence_hash import candidate_source_manifest
            manifest=candidate_source_manifest(workspace)
            assert '.cgkn-publication.lock' not in manifest
            origins=gate.delivery_sources(acceptance,workspace,manifest)
            assert origins['status']=='TRUSTED'
            assert not origins['real_provider_backed'] and not origins['delivery_authorized']
            assert set(origins['source_origins'])==set(manifest)
            from scripts import production_candidate_provenance as production
            delivery=production.produce_project_session(store,'p','r',candidate_dir=workspace,commit_sha='offline-fixture')
            assert delivery['schema_version']=='2.0' and delivery['status']=='NEEDS_REWORK'
            assert 'real_provider_planner_and_worker_required' in delivery['failures']
            assert production.inspect(delivery['provenance_ref'])['status']=='NEEDS_REWORK'
            from scripts import codex_conversation as delivery_adapter
            facts=delivery_adapter.delivery_fact_check(workspace,{},provider_result=document)
            assert facts['facts']['provider_success'] is False
            assert 'provider_not_successful' in facts['hard_blockers']
            assert production.produce_project_session(store,'p','r',candidate_dir=workspace,
                commit_sha='offline-fixture')['provenance_hash']==delivery['provenance_hash']
            from scripts import provider_causal_trace
            trace=provider_causal_trace.finalize_project_session(delivery['provenance_ref'])
            assert trace['status']=='NEEDS_REWORK'
            assert provider_causal_trace.inspect(trace['trace_ref'])['status']=='NEEDS_REWORK'
            assert provider_causal_trace.finalize_project_session(delivery['provenance_ref'])['trace_hash']==trace['trace_hash']
            calls_before=len(client.calls)
            blocked=service.finalize_core(json.loads(profile.read_text()),document)
            assert blocked['delivery_status']=='BLOCKED' and not blocked['public_delivery_allowed']
            assert 'real_provider_planner_and_worker_required' in blocked['delivery_failures']
            assert service.finalize_core(json.loads(profile.read_text()),document)==blocked
            assert len(client.calls)==calls_before
            with pytest.raises(ProvenanceError,match='lacks bounded Worker origin'):
                gate.delivery_sources(acceptance,workspace,{**manifest,'unowned.py':'not-produced-by-worker'})
            assert client.worker_calls==3
            assert len(store.load_run('p','r').nodes['sem-node-0000'].attempts)==2
            # Read-only reconstruction cannot mutate the authoritative record.
            acceptance_path=store.run_dir('p','r')/'goal_acceptance.json'
            before=acceptance_path.read_bytes()
            assert acceptance.view()==acceptance.view()
            assert acceptance_path.read_bytes()==before
            current=next(iter(acceptance.view()['goals'][0]['subject_refs']))
            source=(workspace/current).read_bytes()
            (workspace/current).write_text('def value():\n    return 99\n')
            assert not acceptance.view()['complete']
            assert acceptance_path.read_bytes()==before
            (workspace/current).write_bytes(source)
            assert acceptance.view()['complete']
            # The same typed raw observation must remain authentic on rebuild.
            check=acceptance.data['checks'][-1]
            receipt=json.loads((store.run_dir('p','r')/'attempts'/check['node_id']/(check['attempt_id']+'.json')).read_text())
            typed_ref=receipt['metadata']['raw_observation_refs'][0]
            typed_path=store.root/typed_ref['path']
            raw=typed_path.read_bytes()
            typed_path.write_text('{}')
            assert not acceptance.view()['complete']
            assert acceptance_path.read_bytes()==before
            typed_path.write_bytes(raw)
            assert acceptance.view()['complete']
            binding_path=next((store.run_dir('p','r')/'provenance_goals').glob('*.json'))
            binding=json.loads(binding_path.read_text())
            binding['subject_refs']=[]
            binding_path.write_text(json.dumps(binding))
            assert not acceptance.view()['complete']
            assert acceptance_path.read_bytes()==before
            return
        from cgkn.state.store import StateStoreError
        with store.exclusive_file(store.run_dir('p','r')/'project_session.lock'):
            with pytest.raises(StateStoreError,match='active coordinator'):
                service.run_project(project_id='p',run_id='r',workspace=workspace,intent=intent,
                    registry=registry,acceptance=acceptance,capability_catalog=catalog,
                    deliverable_checkers=bindings,checkpoint_interval=1)
        assert not client.calls
        result=service.run_project(project_id='p',run_id='r',workspace=workspace,intent=intent,
            registry=registry,acceptance=acceptance,capability_catalog=catalog,
            deliverable_checkers=bindings,checkpoint_interval=1)
        usage=service._provider_usage(store.run_dir('p','r'))
        assert usage['provider_call_count']==len(client.calls)==13
        assert usage['worker_calls']==6 and usage['provider_attempt_records_unknown']==0
        assert len(list((store.run_dir('p','r')/'protocol').glob('event-*.json')))>=8
    assert result.status=='GOALS_VERIFIED' and acceptance.view()['complete']
    assert client.worker_calls==3
    assert [c['verdict'] for c in acceptance.data['checks']]==['FAILED','VERIFIED']
    assert [c['observation']['observed']['actual'] for c in acceptance.data['checks']]==[6,7]
    assert result.tree.by_id['sem-node-0000'].config['repair_contract']['state']=='REPAIR_ADMITTED'
    assert len(store.load_run('p','r').nodes['sem-node-0000'].attempts)==2
    worker_prompts=[json.loads(r['user']) for r in client.calls if r['config'].role=='worker']
    assert all(p['context']['contract_integrity_status']=='PASS' for p in worker_prompts)
    assert worker_prompts[-1]['context']['failed_acceptance_ids']
    assert any(e.event_type=='AGENT_CHECKPOINT_CONTINUED' for e in store.load_events('p','r'))

"""Boundary tests only; full fake Worker/consumer chain is tested separately."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import codex_conversation
from cgkn.application.software_project.service import SoftwareProjectGenerationService


def test_configured_conversation_uses_core_and_does_not_claim_delivery(tmp_path, monkeypatch):
    root=tmp_path/'controller'
    profile=root/'.cgkn'/'project-session.json'
    profile.parent.mkdir(parents=True)
    profile.write_text('{}')
    calls=[]
    monkeypatch.setattr(SoftwareProjectGenerationService,'__init__',lambda self,*a,**k:None)
    def run(self,path,*,goal,on_started):
        calls.append((path,goal))
        return {'status':'GOALS_VERIFIED','public_delivery_allowed':False,'delivery_status':'NOT_EVALUATED'}
    monkeypatch.setattr(SoftwareProjectGenerationService,'run_profile',run)
    monkeypatch.setattr(codex_conversation,'CodexConversation',lambda:pytest.fail('legacy generator entered'))
    result=codex_conversation.run_formal_generation_once(root,goal='test goal')
    assert calls==[(profile,'test goal')]
    assert result['status']=='GOALS_VERIFIED' and not result['public_delivery_allowed']
    stored=json.loads((root/'.cgkn/agent-kit/generation_result.json').read_text())
    assert stored=={k:v for k,v in result.items() if k!='lean_report'}
    assert result['lean_report']['json'].endswith('lean-report.json')


@pytest.mark.parametrize('options',[{'provider_mode':'deterministic_replay'},
    {'observed_failure':'old.json'},{'codex_capability_brief':'old.txt'}])
def test_profile_cannot_silently_enter_legacy_execution(tmp_path,monkeypatch,options):
    (tmp_path/'.cgkn').mkdir()
    (tmp_path/'.cgkn/project-session.json').write_text('{}')
    monkeypatch.setattr(SoftwareProjectGenerationService,'__init__',lambda *a,**k:pytest.fail('provider initialized'))
    with pytest.raises(ValueError):
        codex_conversation.run_formal_generation_once(tmp_path,goal='test',**options)


def test_core_error_never_falls_back_to_legacy_generator(tmp_path,monkeypatch):
    (tmp_path/'.cgkn').mkdir()
    (tmp_path/'.cgkn/project-session.json').write_text('{}')
    monkeypatch.setattr(SoftwareProjectGenerationService,'__init__',lambda self,*a,**k:None)
    def fail(*a,**k): raise RuntimeError('retained core failure')
    monkeypatch.setattr(SoftwareProjectGenerationService,'run_profile',fail)
    monkeypatch.setattr(codex_conversation,'CodexConversation',lambda:pytest.fail('legacy fallback'))
    with pytest.raises(RuntimeError,match='retained core failure'):
        codex_conversation.run_formal_generation_once(tmp_path,goal='test')


def test_agent_kit_profile_command_preserves_canonical_cli_without_legacy_brief(tmp_path,monkeypatch):
    root=Path(__file__).resolve().parents[3]
    monkeypatch.syspath_prepend(str(root/'tools/cgkn-agent-kit/src'))
    from cgkn_agent_kit import core
    from cgkn.providers import application_network
    monkeypatch.setattr(application_network,'settings',lambda:None)
    (tmp_path/'.cgkn').mkdir()
    (tmp_path/'.cgkn/agent-kit.json').write_text(json.dumps({'kind':'CGKNAgentKitProject','schema_version':'1.0',
        'cgkn_root':str(root),'artifact_dir':'.cgkn/agent-kit'}))
    (tmp_path/'.cgkn/project-session.json').write_text(json.dumps({'intent':{'overall_goal':'test'}}))
    command=core.generation_command(tmp_path,goal='test',brief_path=tmp_path/'legacy-brief.json',provider_mode='live')
    assert command[1]==str(root/'scripts/run_codex_conversation_generation.py')
    assert '--codex-capability-brief' not in command
    assert command[command.index('--goal')+1]=='test'
    with pytest.raises(core.AgentKitError,match='GOAL_MISMATCH'):
        core.generation_command(tmp_path,goal='different',brief_path=tmp_path/'legacy-brief.json',provider_mode='live')


def test_dynamic_profile_adapter_never_enters_role_stage_executor(tmp_path,monkeypatch):
    from scripts import dynamic_pipeline_runner as dynamic
    (tmp_path/'.cgkn').mkdir()
    profile=tmp_path/'.cgkn/project-session.json';profile.write_text('{}')
    monkeypatch.setattr(SoftwareProjectGenerationService,'__init__',lambda self,*a,**k:None)
    calls=[]
    def run(self,path,*,goal):
        calls.append((path,goal))
        return {'status':'BLOCKED','public_delivery_allowed':False}
    monkeypatch.setattr(SoftwareProjectGenerationService,'run_profile',run)
    monkeypatch.setattr(dynamic.local_agent_actions,'LocalAgentActionExecutor',lambda *a:pytest.fail('legacy executor entered'))
    result=dynamic.run_dynamic_pipeline(session_path=tmp_path/'old-session.json',project_dir=tmp_path,
        pipeline_manifest={'project_goal':'test'})
    assert result=={'status':'BLOCKED','public_delivery_allowed':False}
    assert calls==[(profile,'test')]
    with pytest.raises(ValueError,match='overrides'):
        dynamic.run_dynamic_pipeline(session_path=tmp_path/'old-session.json',project_dir=tmp_path,
            pipeline_manifest={'project_goal':'test'},start_stage='build')


def test_unconfigured_public_entries_fail_before_any_legacy_execution(tmp_path,monkeypatch):
    from scripts import dynamic_pipeline_runner as dynamic
    monkeypatch.setattr(codex_conversation,'CodexConversation',lambda:pytest.fail('legacy planner entered'))
    monkeypatch.setattr(dynamic.local_agent_actions,'LocalAgentActionExecutor',lambda *a:pytest.fail('legacy executor entered'))
    monkeypatch.setattr(SoftwareProjectGenerationService,'__init__',lambda *a,**k:pytest.fail('provider initialized'))
    with pytest.raises(ValueError,match='PROJECT_SESSION_PROFILE_REQUIRED'):
        codex_conversation.run_formal_generation_once(tmp_path,goal='unconfigured')
    with pytest.raises(ValueError,match='PROJECT_SESSION_PROFILE_REQUIRED'):
        dynamic.run_dynamic_pipeline(session_path=tmp_path/'session.json',project_dir=tmp_path,
            pipeline_manifest={'project_goal':'unconfigured','steps':[{'type':'agent_turn'}]})


def test_api_job_projects_core_result_without_own_run_identity(tmp_path,monkeypatch):
    session={'project_session_profile':str(tmp_path/'profile.json'),
             'whiteboard':{'project_summary':'test'},'generation':{'historical_ref':'retained'}}
    monkeypatch.setattr(codex_conversation,'load_session',lambda *a:session)
    saved=[];started=[]
    monkeypatch.setattr(codex_conversation,'save_session',lambda *a:saved.append(json.loads(json.dumps(a[-1]))))
    monkeypatch.setattr(codex_conversation,'production_generation_identity',lambda *a:pytest.fail('second run identity'))
    monkeypatch.setattr(SoftwareProjectGenerationService,'__init__',lambda self,*a,**k:None)
    def run(self,path,*,goal,on_started):
        assert goal=='test'
        on_started({'run_id':'frozen-run','run_dir':str(tmp_path/'state'),'project_dir':str(tmp_path/'candidate')})
        return {'status':'GOALS_VERIFIED','run_id':'frozen-run','run_dir':str(tmp_path/'state'),
            'project_dir':str(tmp_path/'candidate'),'public_delivery_allowed':False,'delivery_status':'NOT_EVALUATED'}
    monkeypatch.setattr(SoftwareProjectGenerationService,'run_profile',run)
    codex_conversation.start_generation_from_income(None,'conversation',tmp_path,tmp_path,'ignored',10,
        session,reason='test',background=False,on_started=started.append)
    assert session['generation']['run_id']=='frozen-run'
    assert session['generation']['historical_ref']=='retained'
    assert session['generation']['status']=='goals_verified'
    assert not session['generation']['public_delivery_allowed']
    assert started[0]['run_id']=='frozen-run'
    session['generation']['outcome_unknown']=True
    before=json.loads(json.dumps(session))
    with pytest.raises(ValueError,match='PRIOR_OUTCOME_UNKNOWN'):
        codex_conversation.run_agent_generation_job(None,'conversation',tmp_path,tmp_path,'ignored',10)
    assert session==before


def test_api_unknown_is_retained_and_not_dispatched_again(tmp_path,monkeypatch):
    session={'project_session_profile':str(tmp_path/'profile.json'),'whiteboard':{'project_summary':'test'}}
    monkeypatch.setattr(codex_conversation,'load_session',lambda *a:session)
    monkeypatch.setattr(codex_conversation,'save_session',lambda *a:None)
    monkeypatch.setattr(SoftwareProjectGenerationService,'__init__',lambda self,*a,**k:None)
    class Unknown(RuntimeError): outcome_unknown=True
    calls=[]
    def run(*a,**k):
        calls.append(1)
        raise Unknown('receipt retained')
    monkeypatch.setattr(SoftwareProjectGenerationService,'run_profile',run)
    with pytest.raises(Unknown):
        codex_conversation.run_provider_generation_job(None,'api',tmp_path,tmp_path,'ignored',10)
    assert session['generation']['status']=='outcome_unknown'
    assert session['generation']['outcome_unknown'] is True
    with pytest.raises(ValueError,match='PRIOR_OUTCOME_UNKNOWN'):
        codex_conversation.run_provider_generation_job(None,'api',tmp_path,tmp_path,'ignored',10)
    assert calls==[1]


def test_local_cli_and_implementation_alias_share_core_service(tmp_path,monkeypatch):
    from scripts import run_local_pipeline as cli,run_local_pipeline_impl as implementation
    monkeypatch.setattr(SoftwareProjectGenerationService,'__init__',lambda self,*a,**k:None)
    calls=[]
    def run(self,path,*,goal):
        calls.append((path,goal))
        return {'status':'GOALS_VERIFIED','delivery_status':'NOT_EVALUATED','public_delivery_allowed':False}
    monkeypatch.setattr(SoftwareProjectGenerationService,'run_profile',run)
    args=SimpleNamespace(use_api=True,provider_mode='live',goal='test',run_dir=tmp_path/'state',
        project_session_profile=str(tmp_path/'profile.json'),result=tmp_path/'result.json')
    for entry in (cli.execute,implementation.execute):
        result=entry(args)
        assert result['status']=='GOALS_VERIFIED' and not result['public_delivery_allowed']
    assert calls==[(str(tmp_path/'profile.json'),'test')]*2
    args.project_session_profile=''
    with pytest.raises(ValueError,match='PROJECT_SESSION_PROFILE_REQUIRED'):
        cli.execute(args)
    assert len(calls)==2


def test_core_finalization_interruption_is_recorded_and_not_replayed(tmp_path,monkeypatch):
    from cgkn.state import FileRunStore
    from cgkn.state.acceptance import identity
    service=object.__new__(SoftwareProjectGenerationService)
    service.artifact_root=tmp_path/'state'
    profile={'project_id':'p','run_id':'r'}
    core={'kind':'CGKNProjectSessionCoreResult','status':'GOALS_VERIFIED'}
    calls=[]
    def interrupted(*args):
        calls.append(1)
        raise RuntimeError('controlled post-build interruption')
    monkeypatch.setattr(service,'_finalize_core_locked',interrupted)
    with pytest.raises(RuntimeError,match='controlled post-build'):
        service.finalize_core(profile,core)
    attempt=FileRunStore(service.artifact_root).run_dir('p','r')/'delivery_attempts'/identity(core)
    raw=(attempt/'error.json').read_bytes()
    error=json.loads(raw)
    assert error['classification']=='HARNESS_ERROR' and error['outcome_unknown']
    with pytest.raises(RuntimeError,match='reconcile before replay'):
        service.finalize_core(profile,core)
    assert calls==[1] and (attempt/'error.json').read_bytes()==raw


def test_core_finalization_uses_existing_session_lock(tmp_path,monkeypatch):
    from cgkn.state import FileRunStore
    from cgkn.state.store import StateStoreError
    service=object.__new__(SoftwareProjectGenerationService)
    service.artifact_root=tmp_path/'state'
    store=FileRunStore(service.artifact_root)
    monkeypatch.setattr(service,'_finalize_core_locked',lambda *a:pytest.fail('concurrent finalizer entered'))
    with store.exclusive_file(store.run_dir('p','r')/'project_session.lock'):
        with pytest.raises(StateStoreError,match='active coordinator'):
            service.finalize_core({'project_id':'p','run_id':'r'},{'status':'GOALS_VERIFIED'})


def test_retired_conversation_execution_paths_are_absent():
    # Replaces historical tests that required a second generation/retry lifecycle.
    for name in ('run_provider_execute_with_retries','execute_validated_provider_round',
                 'write_provider_validation_receipt','finish_supervision_recovery_stop',
                 'run_simulator_preflight','queue_generation_job_legacy_disabled'):
        assert not hasattr(codex_conversation,name),name
    from scripts import run_agent_mvp
    assert not hasattr(run_agent_mvp,'run_direct_baseline')


def test_retired_component_generation_and_retry_owners_are_absent():
    from scripts import run_local_pipeline as facade,run_local_pipeline_impl as implementation,provider_generation
    for name in ('provider_generate_project','provider_generate_project_component',
                 'provider_generate_component_file','provider_generate_component_job',
                 'provider_generate_project_component_split','provider_generate_project_by_components',
                 'execute_provider_job_patch_generation','run_provider_semantic_review_with_repair',
                 '_provider_generate_leaf_with_retry','_provider_generate_job_with_retry'):
        assert not hasattr(implementation,name),name
        assert not hasattr(facade,name),name
    assert not hasattr(provider_generation,'run')

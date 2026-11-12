from pathlib import Path

from cgkn.agent import AgentProjectLoop, ProjectSession
from cgkn.application.software_project.contracts import ProjectResultStatus
from cgkn.application.software_project.service import (
    GenerationRunResult,
    SoftwareProjectGenerationService,
)


def test_compatibility_name_has_no_second_lifecycle():
    assert AgentProjectLoop is ProjectSession
    assert AgentProjectLoop.run is ProjectSession.run


def test_service_failure_does_not_clone_workspace_or_restart_planner(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    calls = []

    def failed_session(self, case, run_id, run_dir, workspace, round_number,
                       failure_summary, *, decision_multiplier):
        calls.append((run_id, workspace, decision_multiplier))
        (workspace / "successful-sibling.txt").write_text("preserve exact identity")
        return GenerationRunResult(case.case_id, run_id, run_dir, workspace,
                                   ProjectResultStatus.NEEDS_REWORK,
                                   {"sanitized_failure_summary": "one branch failed"})

    monkeypatch.setattr(SoftwareProjectGenerationService, "_run_round", failed_session)
    service = SoftwareProjectGenerationService(root, tmp_path, client=object())
    result = service.run_case("seeded_repair", max_repair_rounds=2)
    assert result.status is ProjectResultStatus.NEEDS_REWORK
    assert len(calls) == 1 and calls[0][2] == 3
    assert list((tmp_path / "seeded_repair").iterdir()) == [result.run_dir]
    assert (result.workspace / "successful-sibling.txt").read_text() == "preserve exact identity"


def test_session_service_preserves_same_provider_concrete_routes(tmp_path):
    from cgkn.providers import CGKNModelRouting, ModelRoleConfig
    root = Path(__file__).resolve().parents[2]
    routing = CGKNModelRouting(ModelRoleConfig('agent','qwen',model_id='fixture-flash'),
        ModelRoleConfig('worker','qwen',model_id='fixture-coder'), frozenset({'qwen'}))
    service = SoftwareProjectGenerationService(root, tmp_path, client=object(), routing=routing)
    config = service._resolved_config()
    assert service._role('agent', config['high_capability_agent']) == routing.agent
    assert service._role('worker', config['cheap_worker']) == routing.worker


def test_session_service_default_does_not_select_max(tmp_path):
    root = Path(__file__).resolve().parents[2]
    service = SoftwareProjectGenerationService(root, tmp_path, client=object())
    assert 'max' not in service._resolved_config()['high_capability_agent']['model'].lower()


def test_checked_in_entry_defaults_and_same_provider_identity(tmp_path):
    import json
    from scripts.run_agent_mvp import load_config, role_config
    root = Path(__file__).resolve().parents[2]
    for name, role in [('agent_mvp.json', 'agent'),
                       ('software_project_generation.json', 'high_capability_agent')]:
        value = json.loads((root / 'config' / name).read_text())
        assert 'max' not in value[role]['model'].lower()
    config = {'kind':'CGKNAgentMVPConfig','schema_version':'1.0',
              'agent':{'model':'qwen','model_id':'fixture-planner'},
              'worker':{'model':'qwen','model_id':'fixture-worker'}}
    path = tmp_path / 'routing.json'
    path.write_text(json.dumps(config))
    loaded = load_config(path)
    assert role_config('agent', loaded['agent']).model_id == 'fixture-planner'
    assert role_config('worker', loaded['worker']).model_id == 'fixture-worker'


def test_minimal_intent_is_frozen_in_existing_store_before_planning(tmp_path):
    import pytest
    from cgkn.agent.composer import AgentDecision
    from cgkn.executors import ExecutorRegistry
    from cgkn.runtime import DAGRunner
    from cgkn.state import FileRunStore
    seen=[]
    class Planner:
        planner_mode='MILESTONE_MODE'
        def decide(self, context):
            seen.append(context.project_intent)
            return AgentDecision('d','fixture','fixture',(),False,False,True,'fixture stop',{},'',0)
    store=FileRunStore(tmp_path)
    from cgkn.agent.project_agent import AdmissionPolicy
    session=ProjectSession(Planner(),DAGRunner(ExecutorRegistry(),store),store,
        known_capabilities=set(),worker_model='fixture',admission_policy=AdmissionPolicy(project_id='p',execution_budget={'calls':0}))
    intent={'overall_goal':'goal','user_visible_outcomes':['usable record store'],
            'constraints':['local only'],'forbidden_operations':['public publishing'],
            'delivery_expectations':['local package'],'major_acceptance_categories':['persistence']}
    result=session.run(project_id='p',run_id='r',goal='goal',project_intent=intent)
    assert result.status=='BLOCKED' and seen==[intent]
    path=store.run_dir('p','r')/'minimal_project_intent.json'; before=path.read_bytes()
    with pytest.raises(ValueError,match='conflicting immutable record'):
        session.run(project_id='p',run_id='r',goal='goal',project_intent={**intent,'constraints':[]})
    assert len(seen)==1 and path.read_bytes()==before
    with pytest.raises(ValueError,match='requires minimal project intent'):
        session.run(project_id='p',run_id='other',goal='goal')


def test_application_usage_keeps_orphaned_provider_request_unknown(tmp_path):
    from cgkn.state import FileRunStore
    store=FileRunStore(tmp_path)
    root=store.run_dir('p','r')
    store.immutable_json(root/'provider_calls'/'interrupted'/'request.json',{
        'identity':'interrupted','config':{'role':'agent','model':'qwen','model_id':'fixture-flash'},
        'request':{'user':'one pending milestone'}})
    before=(root/'provider_calls'/'interrupted'/'request.json').read_bytes()
    usage=SoftwareProjectGenerationService._provider_usage(root)
    assert usage['provider_call_count']==1 and usage['agent_calls']==1
    assert usage['provider_attempt_records_unknown']==1 and usage['outcome_unknown']==1
    assert usage['provider_usage'][0]['model']=='UNKNOWN'
    assert usage['provider_usage'][0]['requested_model']=='fixture-flash'
    assert (root/'provider_calls'/'interrupted'/'request.json').read_bytes()==before


def test_explicit_route_change_retains_original_snapshot_and_rejects_silent_switch(tmp_path):
    import json, pytest
    from dataclasses import replace
    from cgkn.providers import CGKNModelRouting, ModelRoleConfig
    from cgkn.state import FileRunStore
    from cgkn.state.provenance import put_evidence, ProvenanceError
    routing=CGKNModelRouting(ModelRoleConfig('agent','qwen',model_id='fixture-planner'),
        ModelRoleConfig('worker','deepseek',model_id='fixture-worker'),frozenset({'qwen','deepseek'}))
    store=FileRunStore(tmp_path/'state')
    service=SoftwareProjectGenerationService(tmp_path,tmp_path/'state',client=object(),routing=routing)
    service._bind_routing(store,'p','r')
    original=store.run_dir('p','r')/'model_routing_snapshot.json';before=original.read_bytes()
    changed=replace(routing,worker=ModelRoleConfig('worker','qwen',model_id='fixture-coder'))
    service.routing=changed
    with pytest.raises(ValueError,match='explicit recorded decision'):service._bind_routing(store,'p','r')
    assert original.read_bytes()==before
    ref=put_evidence(store,'p','r',{'kind':'TransportObservation','outcome_unknown':True})
    decision={'decision_id':'e'*64,'from_config_hash':routing.config_hash,'to_config_hash':changed.config_hash,
              'reason_summary':'Explicit alternate cheap route after retained transport failure','evidence_refs':[ref]}
    with pytest.raises(ProvenanceError):
        service._bind_routing(store,'p','r',{**decision,'evidence_refs':[{**ref,'sha256':'0'*64}]})
    service._bind_routing(store,'p','r',decision)
    event_path=store.run_dir('p','r')/'events.jsonl';event_bytes=event_path.read_bytes()
    service._bind_routing(store,'p','r',decision)
    service._bind_routing(store,'p','r')
    assert event_path.read_bytes()==event_bytes and original.read_bytes()==before
    events=[e for e in store.load_events('p','r') if e.event_type=='MODEL_ROUTE_CHANGED']
    assert len(events)==1 and events[0].data['automatic_fallback'] is False
    assert service._role('worker',service._resolved_config()['cheap_worker']).model_id=='fixture-coder'
    path=store.root/events[0].data['snapshot_ref']['path']
    snapshot=json.loads(path.read_text());assert snapshot['actual_models']=={'agent':'','worker':''}
    path.write_text('{}')
    with pytest.raises(ProvenanceError):service._bind_routing(store,'p','r')

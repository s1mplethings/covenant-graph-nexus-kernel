from __future__ import annotations

import json

import pytest

from cgkn.agent.composer import AgentComposer, AgentDecisionContext, parse_agent_decision
from cgkn.agent.composer_contract import parse_tree_edit
from cgkn.orchestration.capability_tree import CapabilityTree
from cgkn.providers import ModelRoleConfig, ProviderCompletion


pytestmark = [pytest.mark.negative, pytest.mark.boundary, pytest.mark.security]


def completion(value=None):
    return ProviderCompletion(json.dumps(value or {}), "agent-model", "request", {"tokens": 1}, 1)


def decision(*, edits=(), run=True, finish=False, escalate=False):
    return {"schema_version": "1.0", "decision_id": "d", "summary": "s", "reason": "r", "edits": list(edits), "request_run": run, "finish": finish, "needs_escalation": escalate, "escalation_reason": "review" if escalate else ""}


def edit(operation, payload=None):
    return {"edit_id": "e", "operation": operation, "node_id": "n", "payload": payload or {}, "provenance": {"actor": "agent"}}


@pytest.mark.happy_path
@pytest.mark.roundtrip
def test_valid_decision_normalizes_root_and_deep_values() -> None:
    raw = decision(edits=[edit("add_node", {"capability_ref": "c@1", "parent_id": "root", "depends_on": [], "config": {"nested": {"x": [1]}}})])
    parsed = parse_agent_decision(raw, completion(), "context")
    value = parsed.as_dict()
    assert value["edits"][0]["payload"]["parent_id"] == ""
    assert value["edits"][0]["payload"]["config"] == {"nested": {"x": [1]}}
    assert parsed.context_chars == 7 and len(parsed.context_hash) == 64


@pytest.mark.parametrize("value,match", [
    ({"schema_version": "1.0"}, "envelope"),
    ({**decision(), "edits": "bad"}, "must be a list"),
    (decision(edits=["bad"]), "must be an object"),
    (decision(edits=[edit("request_run")]), "unauthorized"),
    (decision(edits=[edit("add_node", {"capability_ref": ""})]), "not canonical"),
    (decision(edits=[edit("update_config", {})]), "not canonical"),
    (decision(edits=[edit("retry_node", {"x": 1})]), "invalid tree edit payload"),
    (decision(run=False), "exactly one"),
    (decision(run=True, finish=True), "exactly one"),
])
@pytest.mark.fault_injection
def test_invalid_decision_matrix(value, match) -> None:
    with pytest.raises(ValueError, match=match):
        parse_agent_decision(value, completion(), "context")


def test_tree_edit_rejects_extra_fields() -> None:
    value = edit("retry_node"); value["shell"] = "no"
    with pytest.raises(ValueError, match="unknown tree edit"):
        parse_tree_edit(value)


def test_retry_payload_defense_rejects_nonempty_parsed_edit(monkeypatch) -> None:
    class Parsed:
        operation = "retry_node"
        payload = {"forbidden": True}
    monkeypatch.setattr("cgkn.agent.composer.parse_tree_edit", lambda _value: Parsed())
    with pytest.raises(ValueError, match="must be empty"):
        parse_agent_decision(decision(edits=[edit("retry_node")]), completion(), "context")


class Client:
    def __init__(self, value): self.value = value
    def complete(self, **_kwargs): return completion(self.value)


@pytest.mark.happy_path
def test_composer_decide_serializes_context_without_hidden_reasoning() -> None:
    value = decision(run=False, finish=True)
    composer = AgentComposer(Client(value), ModelRoleConfig("agent", "agent-model"))
    context = AgentDecisionContext("p", "r", "goal", 1, CapabilityTree("goal", ()), (), {"nested": {"x": [1]}}, {}, {})
    result = composer.decide(context)
    assert result.finish and "reasoning" not in json.dumps(result.as_dict()).lower()
    with pytest.raises(ValueError, match="agent model"):
        AgentComposer(Client(value), ModelRoleConfig("worker", "worker-model"))


def test_advertised_retry_schema_requires_actual_empty_payload():
    from jsonschema import Draft202012Validator
    from cgkn.agent.composer import AGENT_SCHEMA
    validator=Draft202012Validator(AGENT_SCHEMA)
    good=decision(edits=[edit('retry_node',{})])
    assert not list(validator.iter_errors(good))
    for bad in [{',':{}},{'}}],':{}},{'provenance':{'source':'misplaced'}}]:
        assert list(validator.iter_errors(decision(edits=[edit('retry_node',bad)])))
    assert not list(validator.iter_errors(decision(edits=[edit('update_config',{'config':{'goal':'bounded'}})])))


def test_completed_schema_rejection_reaches_next_project_decision(tmp_path):
    from cgkn.providers.gateway_client import GatewayCompletionError
    from cgkn.agent import AgentProjectLoop
    from cgkn.runtime import DAGRunner
    from cgkn.state import FileRunStore
    from cgkn.executors import ExecutorRegistry
    class RejectThenEscalate:
        calls=0
        def complete(self, **kwargs):
            self.calls+=1
            if self.calls==1:
                error=GatewayCompletionError('schema_validation_failed','completed output rejected',outcome_unknown=False)
                error.completed_response={'output_text':json.dumps({'edits':[{'action':'add_node'}]}),
                    'model':'actual-version','id':'original-request','usage':{'input_tokens':10,'output_tokens':5},
                    'cgkn_model_identity':{'actual_model':'actual-version'}}
                raise error
            context=json.loads(kwargs['user']);feedback=context['failure_details']['decision_validation']
            assert feedback['failure_domain']=='MODEL_OUTPUT'
            assert feedback['model']=='actual-version' and feedback['request_id']=='original-request'
            assert feedback['usage']['output_tokens']==5 and not feedback['outcome_unknown']
            assert 'required property' in feedback['error'] and 'action' in feedback['raw_response']
            return completion(decision(run=False,escalate=True))
    client=RejectThenEscalate();store=FileRunStore(tmp_path)
    from cgkn.agent.project_agent import AdmissionPolicy
    loop=AgentProjectLoop(AgentComposer(client,ModelRoleConfig('agent','fixture')),
        DAGRunner(ExecutorRegistry(),store),store,known_capabilities=set(),worker_model="fixture",max_decisions=2,
        admission_policy=AdmissionPolicy(project_id='p',execution_budget={'calls':0}))
    result=loop.run(project_id='p',run_id='r',goal='bounded')
    assert result.status=='BLOCKED' and client.calls==2
    saved=json.loads((store.run_dir('p','r')/'agent/decision-01.json').read_text())
    assert saved['rejected'] and saved['request_id']=='original-request'


@pytest.mark.parametrize('category,unknown,document',[
    ('transport_error',False,{'output_text':'{}'}),
    ('schema_validation_failed',True,{'output_text':'{}'}),
    ('schema_validation_failed',False,None),
])
def test_incomplete_or_transport_error_is_not_planner_validation(category,unknown,document):
    from cgkn.providers.gateway_client import GatewayCompletionError
    error=GatewayCompletionError(category,'retain external failure',outcome_unknown=unknown)
    error.completed_response=document
    class Broken:
        def complete(self,**kwargs):raise error
    ctx=AgentDecisionContext('p','r','goal',1,CapabilityTree('goal',()),(),{},{},{})
    with pytest.raises(GatewayCompletionError) as caught:
        AgentComposer(Broken(),ModelRoleConfig('agent','fixture')).decide(ctx)
    assert caught.value is error


def test_public_audit_needs_observable_outcome_not_multiple_alternatives():
    raw=decision(finish=True,run=False)
    raw['decision_audit']={'expected_outcome':'Independent checker verifies original requirement','facts':['current observation available']}
    assert parse_agent_decision(raw,completion(),'context').decision_audit==raw['decision_audit']
    raw['decision_audit']['expected_outcome']=''
    with pytest.raises(ValueError,match='expected_outcome'):
        parse_agent_decision(raw,completion(),'context')

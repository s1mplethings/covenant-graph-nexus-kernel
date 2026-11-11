import json
import pytest
from cgkn.agent import AgentComposer, AgentProjectLoop
from cgkn.providers import ModelRoleConfig, ProviderCompletion
from cgkn.state import FileRunStore


class Client:
    def __init__(self, rows): self.rows=iter(rows); self.contexts=[]
    def complete(self, **kwargs):
        self.contexts.append(json.loads(kwargs['user']))
        row=next(self.rows)
        if isinstance(row, Exception): raise row
        return ProviderCompletion(row,'synthetic','id',{})


class NoRun:
    def run(self, **kwargs): raise AssertionError('rejected decisions cannot execute')


def finish():
    return json.dumps(dict(schema_version='1.0',decision_id='end',summary='end',reason='end',edits=[],request_run=False,finish=True,needs_escalation=False,escalation_reason=''))


def test_raw_bad_json_feedback_and_budget(tmp_path):
    client=Client(['{invalid', finish()]); store=FileRunStore(tmp_path)
    loop=AgentProjectLoop(AgentComposer(client,ModelRoleConfig('agent','a')),NoRun(),store,known_capabilities=set(),worker_model='w',max_decisions=2)
    result=loop.run(project_id='p',run_id='r',goal='probe')
    assert result.decision_count==2 and result.status=='FAILED'
    feedback=client.contexts[1]['failure_details']['decision_validation']
    assert feedback['raw_response']=='{invalid' and feedback['error']
    assert not client.contexts[1]['tree']['nodes']


def test_transport_error_not_semantic_feedback(tmp_path):
    client=Client([ValueError('transport')])
    loop=AgentProjectLoop(AgentComposer(client,ModelRoleConfig('agent','a')),NoRun(),FileRunStore(tmp_path),known_capabilities=set(),worker_model='w')
    with pytest.raises(ValueError,match='transport'):loop.run(project_id='p',run_id='r',goal='probe')
    assert len(client.contexts)==1

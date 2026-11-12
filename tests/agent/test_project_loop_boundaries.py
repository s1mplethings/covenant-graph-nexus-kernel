from __future__ import annotations

import pytest
from dataclasses import asdict
from cgkn.agent.project_agent import AdmissionPolicy
from cgkn.runtime import DAGRunner
from cgkn.executors import ExecutorRegistry
from veriarbor.capability import CapabilityContract
from tests.qualification_support import probe_node, probe_runner

from cgkn.agent.composer import AgentDecision
from cgkn.agent.project_loop import AgentProjectLoop
from cgkn.orchestration.tree_edits import TreeEdit
from cgkn.providers import ModelRoleConfig
from cgkn.state import FileRunStore


pytestmark = [pytest.mark.negative, pytest.mark.boundary]


class Composer:
    config = ModelRoleConfig("agent", "agent")
    def __init__(self, decisions): self.decisions = list(decisions)
    def decide(self, _context): return self.decisions.pop(0)


class Runner(DAGRunner):
    def __init__(self,store):super().__init__(ExecutorRegistry(),store)
    def run(self, **_kwargs): raise AssertionError("runner must not be called")


def policy():
    return AdmissionPolicy(project_id='p',incremental_mode=False,allowed_effect_domains=frozenset({'probe/n','probe/work','probe/eval'}),
        capability_contracts={'c@1':asdict(CapabilityContract('c@1','Bounded loop calibration',critical=False,
            positive_controls=('independent probe observation',)))},execution_budget={'calls':0})


def decision(*, edits=(), run=False, finish=False, escalation=False):
    return AgentDecision("d", "summary", "reason", tuple(edits), run, finish, escalation, "review" if escalation else "", {}, "hash", 1,
        decision_audit={'capability_claim':{'target_capability_id':'c@1','strategy_capabilities':['c@1'],
            'exploration_reason':'Bounded loop calibration','exploration_budget':1,'exploration_measure':'Original loop assertions'}})


def loop(tmp_path, decisions, **kwargs):
    store=FileRunStore(tmp_path)
    return AgentProjectLoop(Composer(decisions), Runner(store), store, known_capabilities={"c@1"}, worker_model="worker", **kwargs, admission_policy=policy())


def test_constructor_rejects_same_model_and_invalid_limit(tmp_path) -> None:
    store=FileRunStore(tmp_path)
    AgentProjectLoop(Composer([]), Runner(store), store, known_capabilities=set(), worker_model="agent", admission_policy=policy())
    with pytest.raises(ValueError, match="positive"):
        loop(tmp_path, [], max_decisions=0)
    assert loop(tmp_path, [], max_decisions=80).max_decisions == 80


def test_escalation_and_finish_before_run_are_fail_closed(tmp_path) -> None:
    blocked = loop(tmp_path / "a", [decision(escalation=True)]).run(project_id="p", run_id="r", goal="g")
    assert blocked.status == "BLOCKED" and blocked.escalation_reason == "review"
    finished = loop(tmp_path / "b", [decision(finish=True)]).run(project_id="p", run_id="r", goal="g")
    assert finished.status == "FAILED" and finished.as_dict()["run_summary"] is None


def test_multiple_retry_and_empty_run_are_rejected(tmp_path) -> None:
    retries = (
        TreeEdit("e1", "retry_node", "n", {}, {"actor": "agent"}),
        TreeEdit("e2", "retry_node", "n", {}, {"actor": "agent"}),
    )
    for name, invalid, message in [('a', decision(edits=retries), 'at most one'), ('b', decision(run=True), 'no executable')]:
        candidate = loop(tmp_path / name, [invalid], max_decisions=1)
        result = candidate.run(project_id="p", run_id="r", goal="g")
        assert result.status == 'BLOCKED' and not result.tree.nodes
        events = candidate.store.load_events('p', 'r')
        assert events[-1].event_type == 'AGENT_DECISION_REJECTED'
        assert message in events[-1].data['error']


def test_decision_limit_blocks_without_false_success(tmp_path) -> None:
    result = loop(tmp_path, [decision()], max_decisions=1).run(project_id="p", run_id="r", goal="g")
    assert result.status == "BLOCKED" and result.escalation_reason == "agent decision limit reached"


def test_graph_rejection_returns_feedback_and_preserves_tree(tmp_path):
    from cgkn.runtime.dag_runner import GraphEditRejected
    edit = TreeEdit("e", "add_node", "n", {"capability_ref":"c@1", "parent_id":"", "depends_on":[], "config":probe_node("n",capability_ref="c@1").as_dict()["config"]}, {"actor":"agent"})
    contexts=[]
    class RejectingRunner(Runner):
        def validate_graph_transition(self, **kwargs):
            raise GraphEditRejected("explicit affected-subgraph retry required")
    class ObservingComposer(Composer):
        def decide(self, context):
            contexts.append(context)
            return super().decide(context)
    store=FileRunStore(tmp_path)
    candidate=AgentProjectLoop(ObservingComposer([decision(edits=[edit],run=True),decision(escalation=True)]),RejectingRunner(store),store,known_capabilities={"c@1"},worker_model="worker",admission_policy=policy())
    result=candidate.run(project_id="p",run_id="r",goal="g")
    assert result.status=="BLOCKED" and not result.tree.nodes
    assert "affected-subgraph" in contexts[-1].failure_details["decision_validation"]["error"]


def test_custom_worker_descriptor_counted_without_counting_evaluation(tmp_path):
    from cgkn.executors import ExecutorRegistry
    from cgkn.executors.protocol import ExecutorDescriptor
    from cgkn.execution import BlockExecutionResult,BlockStatus
    from cgkn.runtime import DAGRunner
    class LocalFixture:
        def __init__(self,ref):self.descriptor=ExecutorDescriptor(ref,'bounded_llm',('c@1',))
        def execute(self,r):
            return BlockExecutionResult(project_id=r.project_id,run_id=r.run_id,node_id=r.node_id,attempt_id=r.attempt_id,executor_ref=r.executor_ref,status=BlockStatus.SUCCEEDED,outputs={'node':r.node_id})
    registry=ExecutorRegistry()
    for ref in ['custom.worker@1','task.evaluate@1']:registry.register(LocalFixture(ref))
    edits=[TreeEdit('e'+str(i),'add_node',node,{'capability_ref':'c@1','parent_id':'','depends_on':[], 'config':probe_node(node,capability_ref='c@1',config={'executor_ref':ref}).as_dict()['config']},{'actor':'agent'}) for i,(node,ref) in enumerate([('work','custom.worker@1'),('eval','task.evaluate@1')])]
    store=FileRunStore(tmp_path)
    agent=AgentProjectLoop(Composer([decision(edits=edits,run=True),decision(finish=True)]),probe_runner(registry,store,execution_mode='GOVERNED'),store,known_capabilities={'c@1'},worker_model='worker',admission_policy=policy())
    result=agent.run(project_id='p',run_id='r',goal='controlled counter fixture')
    assert result.worker_calls==1 and len(result.run_summary.actual_executions)==2

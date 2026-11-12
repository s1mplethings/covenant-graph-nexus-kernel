import json
from tests.calibration_admission import run_calibration

from cgkn.agent.composer import AgentComposer, AgentDecisionContext
from cgkn.executors import ExecutorRegistry, LLMExecutor
from cgkn.orchestration.capability_tree import CapabilityTree, CapabilityNode
from cgkn.orchestration.execution_dag import compile_tree
from cgkn.providers import ModelRoleConfig, ProviderCompletion
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore
from cgkn.state.task_feedback import FrozenKnowledge, TaskFeedback
from src.cgnk_knowledge.store import new_project_knowledge_pack, upsert_knowledge_items
from cgkn.execution.deliverables import FileDeliverableChecker
from cgkn.orchestration.leaf_contract import build_leaf_contract


def test_frozen_retrieval_sent_to_actual_planner_and_worker_calls(tmp_path):
    item = dict(kind='KnowledgeItem', id='validated-rule', title='fixture rule', type='constraint',
        content='Use current object evidence', source_refs=['public-fixture'], tags=['code@1'],
        review_state='accepted', status='active', visibility='public', retention='keep',
        importance='high', need_state='needed_now')
    pack = upsert_knowledge_items(new_project_knowledge_pack('p'), [item,
        {**item, 'id': 'private', 'visibility': 'private'},
        {**item, 'id': 'candidate', 'review_state': 'candidate'},
        {**item, 'id': 'retracted', 'status': 'retracted'}])
    knowledge = FrozenKnowledge(pack)
    pack['all_items'].clear()  # in-flight snapshot must not mutate
    sent = []

    class Client:
        def complete(self, **kwargs):
            prompt = json.loads(kwargs['user'])
            sent.append((kwargs['schema_name'], prompt))
            if kwargs['schema_name'] == 'cgkn_agent_decision':
                value = dict(schema_version='1.0', decision_id='d', summary='done', reason='controlled',
                    edits=[], request_run=False, finish=True, needs_escalation=False, escalation_reason='')
            else:
                value = dict(schema_version='1.0', node_id=prompt['node_id'], summary='observed',
                    actions=[], expected_outputs=[], confidence=0.5, needs_escalation=False, escalation_reason='')
            return ProviderCompletion(json.dumps(value), 'controlled-model')

    client = Client()
    context = AgentDecisionContext('p', 'r', 'g', 1, CapabilityTree('g', ()),
        ('code@1',), {}, {}, {}, retrieved_knowledge=knowledge.retrieve(['code@1']))
    AgentComposer(client, ModelRoleConfig('agent', 'controlled')).decide(context)
    registry = ExecutorRegistry()
    registry.register(LLMExecutor(tmp_path, client, ModelRoleConfig('worker', 'controlled')))
    (tmp_path/'knowledge.txt').write_text('Use current object evidence',encoding='utf-8')
    registry.register(FileDeliverableChecker(tmp_path,{'public-rule':lambda root,c:
        {'passed':(root/'knowledge.txt').read_text()=='Use current object evidence',
         'observed':{'rule':(root/'knowledge.txt').read_text()}}}))
    tree = CapabilityTree('g', (CapabilityNode('n', capability_ref='code@1',
        config={'executor_ref': 'llm.cheap@1','leaf_contract':build_leaf_contract(
            goal='Inspect the bounded public knowledge context',kind='INSPECTION',scope=['knowledge.txt'],
            acceptance=['public-rule'],checker='knowledge',output_identity='public-rule',effect_domains=['filesystem','external_network'],
            executor='llm.cheap@1',subject='knowledge.txt',expected_observation='current public rule',
            pass_fail_rule='independent public rule read')}),))
    store = FileRunStore(tmp_path / 'state')
    run_calibration(DAGRunner(registry, store, knowledge=knowledge,deliverable_checkers={'knowledge':'deliverable.files@1'}),project_id='p', run_id='r', tree=tree, dag=compile_tree(tree),model_calls=1)
    assert len(sent) == 2
    for name, prompt in sent:
        selected = (prompt if name == 'cgkn_agent_decision' else prompt['config'])['retrieved_knowledge']
        assert [item['id'] for item in selected['selected_items']] == ['validated-rule']
        assert selected['snapshot_sha256'] == knowledge.version
    assert TaskFeedback(store, 'p', 'r').context()['items'][0]['status'] == 'SUCCEEDED'

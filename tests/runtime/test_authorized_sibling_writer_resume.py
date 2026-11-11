"""Explicit root repair plus committed version chain; never generic peer reuse."""
import json
import pytest
from cgkn.executors import ExecutorRegistry
from cgkn.executors.llm import LLMExecutor
from cgkn.execution.deliverables import FileDeliverableChecker
from cgkn.orchestration import CapabilityTree, compile_tree
from cgkn.orchestration.tree_edits import TreeEdit, apply_tree_edits
from cgkn.protocol.compiler import TableSnapshot
from cgkn.protocol.repair import plain
from cgkn.providers import ModelRoleConfig, ProviderCompletion
from cgkn.runtime import DAGRunner
from cgkn.runtime.dag_runner import GraphEditRejected
from cgkn.state import FileRunStore
from tests.protocol.test_repair_path import snapshot, packet, run
from tests.governed_measurement_support import admit_file_fixture, admit_fixture_tree

pytestmark = [pytest.mark.boundary, pytest.mark.negative]


@pytest.mark.parametrize('tamper', ['', 'root-stage', 'peer-stage', 'peer-before', 'peer-raw', 'live', 'event'])
def test_root_authorized_sibling_handoff_requires_intact_causal_evidence(tmp_path, tamper):
    work = tmp_path/'work'; work.mkdir()
    store = FileRunStore(tmp_path/'state'); calls = []
    class Client:
        def complete(self, **kw):
            prompt = json.loads(kw['user']); calls.append(prompt)
            name = prompt['context']['allowed_write_paths'][0]
            key = next(p['id'] for p in prompt['tables']['paths'] if p['path'] == name)
            return ProviderCompletion(json.dumps({'op': 2, 'path': key,
                'payload': f'value = {len(calls)}\n'}), 'fake', str(len(calls)), {})
    registry = ExecutorRegistry()
    registry.register(LLMExecutor(work, Client(), ModelRoleConfig('worker','fake'),
        semantic_protocol=True, protocol_trace=lambda e: None))
    registry.register(FileDeliverableChecker(work, {'public': lambda root, contract: {
        'passed': (root/contract['target_scope'][0]).read_text().startswith('value = '),
        'observed': {'content': (root/contract['target_scope'][0]).read_text()}}}))
    runner = DAGRunner(registry, store, deliverable_checkers={'source':'deliverable.files@1'})
    doc = snapshot().document
    doc['capabilities'] = [{'capability_ref':'code','task_kinds':[2,3],
        'executor_ref':'llm.cheap@1','checker_ref':'source',
        'acceptance_refs':['public'],'effect_domains':['source']}]
    table = TableSnapshot(doc); tree = CapabilityTree('original user goal', ())
    for proposal in [packet(), {**packet(),'target':1,'scope':[1],'deps':[0]},
                     {**packet(),'target':2,'scope':[1],'deps':[0]}]:
        tree = apply_tree_edits(tree, run(proposal,table,tree)['edits'], known_capabilities={'code'})
    tree=admit_file_fixture(store,tree)
    assert runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree)).status == 'SUCCEEDED'
    # Bare sibling writes remain rejected, as in the existing unchanged controls.
    with pytest.raises(GraphEditRejected, match='OBJECT_VERSION_MISMATCH'):
        runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree),resume=True)
    config = plain(tree.by_id['n'].config)
    config['verified_artifact_change_reason'] = 'Explicit fixture Agent root repair'
    tree = apply_tree_edits(tree, (TreeEdit('root-change','update_config','n',
        {'config':config},{'source':'Agent fixture'}),), known_capabilities={'code'})
    tree=admit_fixture_tree(store,tree,operations=({'operation':'update_config','node_id':'n','config':config},))
    repaired = runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree),
                         resume=True,accept_edits=True,retry_node='n')
    assert repaired.status == 'SUCCEEDED' and len(calls) == 6
    folder = store.run_dir('p','r')
    writers = [e.node_id for e in store.load_events('p','r') if e.event_type == 'NODE_FINISHED'
               and e.attempt_id == 'attempt-0002' and e.node_id in {'sibling','inspect'}]
    assert len(writers) == 2 and len(set(writers)) == 2
    predecessor, successor = writers
    historical = (folder/'attempts/sibling/attempt-0001.json').read_bytes()
    if tamper == 'root-stage': (folder/'candidates/n/attempt-0002/module.py').write_text('changed')
    if tamper == 'peer-stage': (folder/'candidates'/successor/'attempt-0002/tests.py').write_text('changed')
    if tamper == 'peer-raw': (folder/'execution_receipts'/successor/'attempt-0002.json').write_text('{}')
    if tamper == 'live': (work/'tests.py').write_text('external change')
    if tamper == 'peer-before':
        path = folder/'publication_intents'/successor/'attempt-0002.json'
        value = json.loads(path.read_text()); value['before']['tests.py'] = '0'*64
        path.write_text(json.dumps(value))
    if tamper == 'event':
        path = folder/'events.jsonl'
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        path.write_text(''.join(json.dumps(row)+'\n' for row in rows if not (
            row['event_type']=='NODE_FINISHED' and row.get('node_id')=='n' and row.get('attempt_id')=='attempt-0002')))
    if tamper:
        with pytest.raises(GraphEditRejected, match='OBJECT_VERSION_MISMATCH'):
            runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree),resume=True)
    else:
        again = runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree),resume=True)
        assert again.status == 'SUCCEEDED' and set(again.reused_nodes) == {'n','sibling','inspect'}
        proof = [e for e in store.load_events('p','r') if e.event_type=='HISTORICAL_WRITER_VERSION_REUSED'][-1]
        assert proof.data['business_acceptance'] == 'NOT_EVALUATED'
        assert proof.node_id == predecessor
        assert proof.data['successor_chain'][0]['node_id'] == successor
    assert len(calls) == 6
    assert (folder/'attempts/sibling/attempt-0001.json').read_bytes() == historical

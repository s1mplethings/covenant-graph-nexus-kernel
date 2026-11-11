"""Actual staged writes: history is not current-object business acceptance."""
import json
import pytest
from tests.protocol.test_repair_path import snapshot, packet, run
from cgkn.protocol.compiler import TableSnapshot
from cgkn.orchestration import CapabilityTree, compile_tree
from cgkn.orchestration.tree_edits import apply_tree_edits
from cgkn.providers import ModelRoleConfig, ProviderCompletion
from cgkn.executors import ExecutorRegistry
from cgkn.executors.llm import LLMExecutor
from cgkn.execution.deliverables import FileDeliverableChecker
from cgkn.runtime import DAGRunner
from cgkn.runtime.dag_runner import GraphEditRejected
from cgkn.state import FileRunStore
from tests.governed_measurement_support import admit_file_fixture, admit_fixture_tree

pytestmark = [pytest.mark.boundary, pytest.mark.negative]

@pytest.mark.parametrize('tamper', ['', 'live', 'stage', 'journal', 'unrelated', 'original-stage', 'original-journal', 'events', 'raw'])
def test_descendant_publication_chain_required_for_resume(tmp_path, tamper, monkeypatch):
    work=tmp_path/'work';work.mkdir();store=FileRunStore(tmp_path/'state');calls=[]
    class Client:
        def complete(self, **kw):
            prompt=json.loads(kw['user']);calls.append(prompt)
            key=next(x['id'] for x in prompt['tables']['paths'] if x['path']=='module.py')
            return ProviderCompletion(json.dumps({'op':2,'path':key,'payload':f'value = {len(calls)}\n'}), 'fake', str(len(calls)), {})
    reg=ExecutorRegistry()
    reg.register(LLMExecutor(work,Client(),ModelRoleConfig('worker','fake',model_id='fake'),semantic_protocol=True,protocol_trace=lambda event:None))
    reg.register(FileDeliverableChecker(work, {'public':lambda root,c:{'passed':(root/'module.py').read_text().startswith('value = '),'observed':{'content':(root/'module.py').read_text()}}}))
    runner=DAGRunner(reg,store,deliverable_checkers={'source':'deliverable.files@1'})
    doc=snapshot().document
    doc['capabilities']=[{'capability_ref':'code','task_kinds':[2,3],'executor_ref':'llm.cheap@1','checker_ref':'source','acceptance_refs':['public'],'effect_domains':['source']}]
    s=TableSnapshot(doc);tree=CapabilityTree('original user goal',())
    for item in [packet(),{**packet(),'target':1,'deps':[] if tamper=='unrelated' else [0]}]:
        tree=apply_tree_edits(tree,run(item,s,tree)['edits'],known_capabilities={'code'})
    tree=admit_file_fixture(store,tree)
    first=runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree))
    assert first.status=='SUCCEEDED' and len(calls)==2
    folder=store.run_dir('p','r')
    old=(folder/'node_results/n.json').read_bytes()
    if tamper=='live':(work/'module.py').write_text('value = 999\n')
    if tamper=='stage':(folder/'candidates/sibling/attempt-0001/module.py').write_text('value = 999\n')
    if tamper=='events':
        path=folder/'events.jsonl';rows=[json.loads(line) for line in path.read_text().splitlines()];path.write_text(''.join(json.dumps(row)+'\n' for row in rows if not (row['event_type']=='NODE_FINISHED' and row.get('node_id')=='sibling')))
    if tamper=='raw':(folder/'execution_receipts/sibling/attempt-0001.json').write_text('{}')
    if tamper=='original-stage':(folder/'candidates/n/attempt-0001/module.py').write_text('value = 999\n')
    if tamper=='original-journal':
        path=folder/'publication_intents/n/attempt-0001.json';row=json.loads(path.read_text());row['after']['module.py']='0'*64;path.write_text(json.dumps(row))
    if tamper=='journal':
        path=folder/'publication_intents/sibling/attempt-0001.json'
        row=json.loads(path.read_text());row['before']['module.py']='0'*64;path.write_text(json.dumps(row))
    if tamper:
        with pytest.raises(GraphEditRejected,match='OBJECT_VERSION_MISMATCH'):
            runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree),resume=True)
    else:
        again=runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree),resume=True)
        assert again.status=='SUCCEEDED' and set(again.reused_nodes)=={'n','sibling'}
        assert any(e.event_type=='HISTORICAL_WRITER_VERSION_REUSED' for e in store.load_events('p','r'))
        # Retrying only the descendant must retain the ancestor's historical
        # publication proof before invalidating the descendant's latest state.
        tree=admit_fixture_tree(store,tree,operations=({'operation':'retry_node','node_id':'sibling'},))
        retried=runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree),resume=True,retry_node='sibling')
        assert retried.actual_executions==('sibling',) and retried.reused_nodes==('n',)
        assert (work/'module.py').read_text()=='value = 3\n'
        assert runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree),resume=True).status=='SUCCEEDED'
        from cgkn.execution import BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode
        def failed_worker(self, request):
            return BlockExecutionResult(project_id=request.project_id,run_id=request.run_id,node_id=request.node_id,
                attempt_id=request.attempt_id,executor_ref=request.executor_ref,status=BlockStatus.FAILED,
                error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR,'controlled bounded work failure'))
        with monkeypatch.context() as patcher:
            patcher.setattr(LLMExecutor,'execute',failed_worker)
            tree=admit_fixture_tree(store,tree,operations=({'operation':'retry_node','node_id':'sibling'},))
            failed=runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree),resume=True,retry_node='sibling')
            assert failed.status=='FAILED' and failed.reused_nodes==('n',)
            assert (work/'module.py').read_text()=='value = 3\n'
        failed_bytes=(folder/'attempts/sibling/attempt-0003.json').read_bytes()
        tree=admit_fixture_tree(store,tree,operations=({'operation':'retry_node','node_id':'sibling'},))
        recovered=runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree),resume=True,retry_node='sibling')
        assert recovered.status=='SUCCEEDED' and recovered.actual_executions==('sibling',)
        assert (folder/'attempts/sibling/attempt-0003.json').read_bytes()==failed_bytes
        assert (work/'module.py').read_text()=='value = 4\n'
    assert len(calls)==(2 if tamper else 4) and (folder/'node_results/n.json').read_bytes()==old
    if tamper=='live':
        proposed=apply_tree_edits(tree,run({**packet(),'target':2,'scope':[1],'deps':[1]},s,tree)['edits'],known_capabilities={'code'})
        node=proposed.by_id['inspect'].as_dict()
        node['config']['leaf_contract']['effect_domains']=['filesystem','external_network']
        proposed=admit_fixture_tree(store,proposed,operations=({'operation':'add_node','node_id':node['id'],
            'capability_ref':node['capability_ref'],'parent_id':node['parent_id'],
            'depends_on':node['depends_on'],'config':node['config']},))
        before={name:(folder/name).read_bytes() for name in ['run_state.json','capability_tree.json','execution_dag.json','events.jsonl']}
        with pytest.raises(GraphEditRejected,match='OBJECT_VERSION_MISMATCH'):
            runner.run(project_id='p',run_id='r',tree=proposed,dag=compile_tree(proposed),resume=True,accept_edits=True)
        assert all((folder/name).read_bytes()==content for name,content in before.items())
        assert 'inspect' not in store.load_run('p','r').nodes
        assert len(calls)==2

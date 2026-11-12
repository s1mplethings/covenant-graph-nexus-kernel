import hashlib,json
from types import SimpleNamespace
import pytest
from cgkn.execution.materialization import stage_file_worker
from cgkn.execution.deliverables import FileDeliverableChecker
from cgkn.executors.llm import LLMExecutor,BoundedFileActions
from cgkn.executors import ExecutorRegistry
from cgkn.providers import ModelRoleConfig,ProviderCompletion
from cgkn.state import FileRunStore
from cgkn.runtime import DAGRunner
from cgkn.orchestration import CapabilityTree,compile_tree
from cgkn.orchestration.tree_edits import TreeEdit,apply_tree_edits
from cgkn.protocol.compiler import TableSnapshot
from cgkn.protocol.repair import plain
from tests.protocol.test_repair_path import snapshot,packet,run

pytestmark=[pytest.mark.boundary,pytest.mark.negative]

@pytest.mark.parametrize('current',['new dependency','validated partial',None])
@pytest.mark.boundary
@pytest.mark.negative
def test_staging_never_replaces_newer_live_input_with_older_partial(tmp_path,current):
    root=tmp_path/'live';root.mkdir();name='module.py'
    if current is not None:(root/name).write_bytes(current.encode())
    old=tmp_path/'candidates/n/attempt-0001'/name;old.parent.mkdir(parents=True);old.write_bytes(b'validated partial')
    prior={name:{'path':str(old),'sha256':hashlib.sha256(old.read_bytes()).hexdigest()}}
    executor=SimpleNamespace(actions=BoundedFileActions(root));contract={'target_scope':[name]}
    staged,_,reused=stage_file_worker(executor,FileDeliverableChecker(root,{}),contract,tmp_path/'candidates/n/attempt-0002',prior)
    assert (staged.actions.root/name).read_bytes()==(current or 'validated partial').encode()
    assert old.read_bytes()==b'validated partial'
    assert (name in reused)==(current in {None,'validated partial'})
    if current is not None:assert (root/name).read_bytes()==current.encode()


@pytest.mark.boundary
@pytest.mark.happy_path
def test_explicit_root_change_authorizes_only_affected_writers_and_preserves_live_inputs(tmp_path):
    root=tmp_path/'live';root.mkdir();store=FileRunStore(tmp_path/'state');calls={}
    class Client:
        def complete(self,**kw):
            from tests.generation_migration_support import semantic_submission
            submitted=semantic_submission(kw)
            if submitted is not None:return submitted
            prompt=json.loads(kw['user']);name=prompt['context']['allowed_write_paths'][0]
            calls[name]=calls.get(name,0)+1
            key=next(p['id'] for p in prompt['tables']['paths'] if p['path']==name)
            return ProviderCompletion(json.dumps({'op':2,'path':key,'payload':f'value = {calls[name]}\n'}),'fake','fake',{})
    registry=ExecutorRegistry();registry.register(LLMExecutor(root,Client(),ModelRoleConfig('worker','fake'),semantic_protocol=True,protocol_trace=lambda e:None))
    def check(work,c):
        name=c['target_scope'][0];value=(work/name).read_text()
        return {'passed':value.startswith('value = '),'observed':{'value':value},'artifacts':[name]}
    registry.register(FileDeliverableChecker(root,{'public':check}))
    runner=DAGRunner(registry,store,deliverable_checkers={'source':'deliverable.files@1'})
    doc=snapshot().document;doc['capabilities']=[{'capability_ref':'code','task_kinds':[2,3],'executor_ref':'llm.cheap@1','checker_ref':'source','acceptance_refs':['public'],'effect_domains':['source']}]
    table=TableSnapshot(doc);tree=CapabilityTree('original user goal',())
    for item in [packet(),{**packet(),'target':1,'scope':[1],'deps':[0]},{**packet(),'target':2,'scope':[2]}]:
        tree=apply_tree_edits(tree,run(item,table,tree)['edits'],known_capabilities={'code'})
    # Admit the tiny offline repair fixture before dispatch. It uses one fake
    # Provider and bounded file materialization as an explicitly atomic repair.
    from dataclasses import replace
    from tests.governed_measurement_support import admit_fixture_tree
    nodes=[]
    for node in tree.nodes:
        cfg=plain(node.config);leaf=cfg['leaf_contract']
        leaf.update(task_kind='REPAIR',effect_domains=['filesystem','external_network'],
            atomic_repair_justification='Bounded fake-provider repair and checked file materialization',expected_delta='updated fixture file')
        nodes.append(replace(node,config=cfg))
    tree=admit_fixture_tree(store,replace(tree,nodes=tuple(nodes)))
    assert runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree)).status=='SUCCEEDED'
    untouched=(root/'project').read_bytes();config=plain(tree.by_id['n'].config)
    config['verified_artifact_change_reason']='Explicit offline Agent repair of root contract'
    tree=apply_tree_edits(tree,(TreeEdit('authorize','update_config','n',{'config':config},{'source':'Agent fixture'}),),known_capabilities={'code'})
    tree=admit_fixture_tree(store,tree,operations=({'operation':'update_config','node_id':'n','config':config},))
    repaired=runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree),resume=True,accept_edits=True,retry_node='n')
    assert repaired.status=='SUCCEEDED' and set(repaired.actual_executions)=={'n','sibling'}
    assert (root/'project').read_bytes()==untouched and calls['project']==1
    child=store.load_result('p','r','sibling')
    assert child.metadata['inherited_change_authorization']['root_node_id']=='n'
    assert 'inherited_change_authorization' not in store.load_result('p','r','inspect').metadata
    assert 'verified_artifact_change_reason' not in tree.by_id['sibling'].config
    # Simulate a newer input version. It is protected, not declared VERIFIED.
    (root/'tests.py').write_bytes(b'value = 900\n')
    for _ in range(2):
        result=runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree),resume=True,retry_node='sibling')
        assert result.status=='FAILED'
        failed=store.load_result('p','r','sibling')
        assert failed.error.message=='current predecessor artifact requires explicit Agent change reason'
        assert failed.metadata['protected_existing_input_hashes']['tests.py']==hashlib.sha256(b'value = 900\n').hexdigest()
        assert failed.metadata.get('deliverable_verdict')!='VERIFIED'
        assert (root/'tests.py').read_bytes()==b'value = 900\n'
    assert calls['project']==1 and calls['module.py']==2

from dataclasses import replace
from pathlib import Path
import pytest

from cgkn.application.software_project.qualification import new_contract, install, MeasuredExecutor
from cgkn.application.software_project.snapshot import snapshot_project
from cgkn.execution import BlockExecutionRequest, BlockExecutionResult, BlockStatus, TaskContext
from cgkn.executors import ExecutorRegistry
from cgkn.executors.protocol import ExecutorDescriptor
from cgkn.orchestration import CapabilityNode, CapabilityTree, compile_tree
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore


def test_new_application_adapter_is_explicit_and_preserves_scope_limits():
    cfg = {'executor_ref':'llm.cheap@1', 'target_paths':['a.py'], 'goal':'one source'}
    c = new_contract('a', cfg, ['b'])
    assert c['adapter_source_schema'] == 'CGKNApplicationProposal/1.0'
    assert c['dependencies'] == ['b'] and c['target_scope'] == ['a.py']
    from cgkn.orchestration.leaf_contract import LeafContractError
    with pytest.raises(LeafContractError, match='NEEDS_DECOMPOSITION'):
        new_contract('a', {**cfg, 'target_paths':[str(i)+'.py' for i in range(9)]})


def test_success_claim_without_observation_binding_is_not_delivery(tmp_path):
    class Forged:
        descriptor = ExecutorDescriptor('local.python-test@1','fixture',('project.python.pytest@1',),())
        def execute(self, request):
            return BlockExecutionResult(project_id=request.project_id,run_id=request.run_id,node_id=request.node_id,
                attempt_id=request.attempt_id,executor_ref=request.executor_ref,status=BlockStatus.SUCCEEDED,
                outputs={'stdout':'1 passed','returncode':0})
    reg=ExecutorRegistry();reg.register(Forged())
    store=FileRunStore(tmp_path/'runs');root=tmp_path/'project';root.mkdir()
    acceptance, checkers=install(reg,store,root,'p','r','a public goal')
    # Bypass the trusted measurement wrapper, not the canonical checker. A forged
    # executor must be rejected even though its outputs resemble a pytest PASS.
    reg.unregister('local.python-test@1');reg.register(Forged())
    cfg={'executor_ref':'local.python-test@1','goal':'test current source'}
    cfg['leaf_contract']=new_contract('test',cfg)
    tree=CapabilityTree('g',(CapabilityNode('test',capability_ref='project.python.pytest@1',config=cfg),))
    result=DAGRunner(reg,store,deliverable_checkers=checkers).run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree))
    receipt=store.load_result('p','r','test')
    assert result.status=='FAILED'
    assert receipt.metadata['execution_status']=='EXECUTION_SUCCESS'
    assert receipt.metadata['deliverable_verdict']=='FAILED'
    assert not acceptance.view()['complete']


def test_oracle_side_effects_are_retained_outside_live_candidate(tmp_path):
    class Oracle:
        descriptor=ExecutorDescriptor('project.obligation-oracle@1','fixture',('project.obligation-oracle-plan@1',),())
        def __init__(self,workspace):self.workspace=workspace
        def execute(self,r):
            (self.workspace/'fixture.txt').write_text('actual test input')
            assert (self.workspace/'source.txt').read_text()=='stable'
            return BlockExecutionResult(project_id=r.project_id,run_id=r.run_id,node_id=r.node_id,
                attempt_id=r.attempt_id,executor_ref=r.executor_ref,status=BlockStatus.SUCCEEDED,
                outputs={'evidence':[{'status':'PASS','observed':'read stable source'}]})
    root=tmp_path/'project';root.mkdir();(root/'source.txt').write_text('stable')
    before=snapshot_project(root).project_tree_hash
    store=FileRunStore(tmp_path/'runs')
    wrapper=MeasuredExecutor(Oracle(root),root,store=store)
    request=BlockExecutionRequest(project_id='p',run_id='r',node_id='oracle',attempt_id='a',
        executor_ref='project.obligation-oracle@1',component_ref='project.obligation-oracle-plan@1',task_context=TaskContext('measure'))
    result=wrapper.execute(request)
    assert result.outputs['measurement_binding']['before']==before==result.outputs['measurement_binding']['after']
    assert not (root/'fixture.txt').exists()
    assert (store.run_dir('p','r')/'measurements/oracle/a/fixture.txt').read_text()=='actual test input'


def test_candidate_rebinding_never_changes_live_worker_root(tmp_path):
    from cgkn.application.software_project.scope import ScopedProjectLLMExecutor
    from cgkn.providers import ModelRoleConfig
    worker=ScopedProjectLLMExecutor(tmp_path/'live',None,ModelRoleConfig('worker','fake'))
    staged=worker.in_candidate_workspace(tmp_path/'candidate')
    assert staged.candidate_root==(tmp_path/'candidate').resolve()
    assert worker.candidate_root==(tmp_path/'live').resolve()


def test_staging_preserves_custom_action_policy(tmp_path):
    from cgkn.executors.llm import LLMExecutor, BoundedFileActions
    from cgkn.execution.materialization import stage_file_worker
    from cgkn.execution.deliverables import FileDeliverableChecker
    from cgkn.providers import ModelRoleConfig
    class Restricted(BoundedFileActions):
        def apply(self,action):
            if action['action']=='write_file':raise PermissionError('restricted write')
            return super().apply(action)
    root=tmp_path/'live';root.mkdir()
    worker=LLMExecutor(root,None,ModelRoleConfig('worker','fake'));worker.actions=Restricted(root)
    cfg={'executor_ref':'llm.cheap@1','target_paths':['a.py'],'goal':'one source'}
    contract=new_contract('a',cfg)
    staged,_,_=stage_file_worker(worker,FileDeliverableChecker(root,{}),contract,tmp_path/'candidate')
    with pytest.raises(PermissionError,match='restricted write'):
        staged.actions.apply({'action':'write_file','path':'a.py','content':'value=1'})
    assert not (root/'a.py').exists() and not (tmp_path/'candidate/a.py').exists()
    assert worker.actions.root==root.resolve()


def test_current_planner_catalog_excludes_direct_experiment(tmp_path):
    from cgkn.application.software_project.service import SoftwareProjectGenerationService
    from cgkn.application.software_project.catalog import get_case
    service=SoftwareProjectGenerationService(Path.cwd(),tmp_path,client=object())
    catalog=service._catalog(get_case('local_json_notes'))
    assert 'direct_agent_execute@1' not in catalog
    assert all(row['executor_ref']!='project.direct-agent@1' for row in catalog.values())
    assert 'project.file.generate@1' in catalog
    assert 'direct_agent_execute@1' in service.bundle.catalog  # retained experimental compatibility

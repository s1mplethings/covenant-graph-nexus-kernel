"""Bind isolated executor tests to real Host authority; never publish results.

These tests exercise an executor beneath DAGRunner. Their temporary permits
authorize only the declared local file/model effects. Assertions remain the
test oracle; no output is promoted into a formal artifact or commit receipt.
"""
from dataclasses import asdict, replace
from tempfile import TemporaryDirectory
from cgkn.agent.project_agent import AdmissionPolicy
from cgkn.execution.node_effects import execution_scope
from cgkn.orchestration import CapabilityTree, CapabilityNode
from cgkn.runtime.governed import admit_declared_tree
from cgkn.runtime.node_authority import ExecutionAuthority
from cgkn.state import FileRunStore
from veriarbor.capability import CapabilityContract


def invoke_bound_executor(executor, request):
    if request.executor_ref not in {'llm.cheap@1','task.evaluate@1','local.python-test@1','project.acceptance@1',
                                    'local.file@1','local.command@1','local.action@1'}:
        raise ValueError('This fixture only admits bounded file/model workers')
    if request.executor_ref=='task.evaluate@1':
        from cgkn.execution import BlockExecutionRequest,TaskContext
        request=BlockExecutionRequest(project_id=request.project_id,run_id=request.run_id,
            node_id=request.node_id,attempt_id=request.attempt_id,executor_ref=request.executor_ref,
            component_ref='task.evaluate@1',input_values=request.input_values,
            task_context=TaskContext('Evaluate a bound public receipt',{}))
    config=dict(request.task_context.node_config)
    if request.executor_ref=='llm.cheap@1':
        leaf=dict(config['leaf_contract']);leaf['effect_domains']=['filesystem','external_network'];calls=32
    else:
        from cgkn.orchestration.leaf_contract import build_leaf_contract
        calls=1 if request.executor_ref=='task.evaluate@1' else 0
        domains = (['external_network'] if calls else
                   (['local_process'] if config.get('action')=='run_command' else ['filesystem'])
                   if request.executor_ref=='local.action@1' else ['filesystem']
                   if request.executor_ref=='local.file@1' else ['local_process'])
        leaf=build_leaf_contract(goal=request.task_context.node_goal,kind='INSPECTION',scope=['observation'],
            acceptance=['independent-test-assertions'],checker='fixture.observation',output_identity='observation',
            effect_domains=domains,executor=request.executor_ref,
            subject='explicit fixture inputs',expected_observation='bounded executor result',
            pass_fail_rule='original independent regression assertions')
    config.update(executor_ref=request.executor_ref,leaf_contract=leaf)
    contract=CapabilityContract(request.component_ref,leaf['leaf_goal'],critical=False,
        positive_controls=('isolated executor assertions',))
    policy=AdmissionPolicy(project_id=request.project_id,
        capability_contracts={request.component_ref:asdict(contract)},
        allowed_effect_domains=frozenset(leaf['effect_domains']),allow_remote_effects=calls>0,
        execution_budget={'calls':calls})
    with TemporaryDirectory(prefix='cgkn-executor-authority-') as directory:
        authority=ExecutionAuthority(FileRunStore(directory),request.project_id,request.run_id)
        tree=CapabilityTree(leaf['leaf_goal'],(CapabilityNode(request.node_id,
            capability_ref=request.component_ref,config=config),))
        admit_declared_tree(authority,tree,policy=policy,proposal_id='isolated-executor',
            reason='Test supplies explicit bounded execution and independent assertions')
        permit=authority.issue_permit(node_id=request.node_id,contract=contract)
        authority.begin_node_execution(permit.permit_id)
        bound=replace(request,task_context=replace(request.task_context,node_config=config),
            metadata={**request.metadata,'execution_mode':'GOVERNED','node_execution_permit':asdict(permit)})
        try:
            with execution_scope(authority,permit.permit_id):
                return executor.execute(bound)
        finally:
            authority.revoke_permit(permit.permit_id,'ISOLATED_EXECUTOR_TEST_COMPLETE_NO_PUBLICATION')

from unittest.mock import Mock
from experiments.product_eval_076_v8.routes import FeedbackDAGRunner
from cgkn.execution import BlockStatus

def test_invalid_request_returns_raw_failure_without_executor_or_repair():
 registry=Mock();runner=FeedbackDAGRunner(registry,Mock());cfg={'action':'read_file','path':'/input/probe.txt'}
 result=runner._execute('p','r','a','n','workspace.file@1',cfg,{},())
 assert result.status==BlockStatus.FAILED
 assert result.error.message=='ValueError: request identity, component_ref, and executor_ref are required'
 registry.resolve.assert_not_called()
 assert 'executor_ref' not in cfg

def test_valid_request_is_dispatched_unchanged_once():
 registry=Mock();store=Mock();runner=FeedbackDAGRunner(registry,store)
 cfg={'executor_ref':'local.file@1','action':'read_file','path':'/input/probe.txt'}
 runner._execute('p','r','a','n','workspace.file@1',cfg,{},())
 registry.resolve.assert_called_once_with('local.file@1','workspace.file@1')
 request=registry.resolve.return_value.execute.call_args.args[0]
 assert dict(request.task_context.node_config)==cfg
 registry.resolve.return_value.execute.assert_called_once()

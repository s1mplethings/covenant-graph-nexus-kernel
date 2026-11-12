from tests.calibration_admission import run_calibration
import pytest
from cgkn.execution import BlockExecutionResult, BlockStatus
from cgkn.executors import ExecutorDescriptor, ExecutorRegistry
from cgkn.orchestration.capability_tree import CapabilityTree
from cgkn.orchestration.execution_dag import compile_tree
from cgkn.state import FileRunStore
from tests.qualification_support import probe_node, probe_runner

@pytest.mark.parametrize("declared,explicit,expected", [(60,None,60),(60,7,7),(30,None,30)])
def test_runner_uses_registered_default_but_preserves_explicit_node_budget(tmp_path,declared,explicit,expected):
    seen=[]
    class Probe:
        descriptor=ExecutorDescriptor("budget@1","probe",("probe@1",),default_timeout_seconds=declared)
        def execute(self,request):
            seen.append(request.timeout_seconds)
            return BlockExecutionResult(project_id=request.project_id,run_id=request.run_id,
                node_id=request.node_id,attempt_id=request.attempt_id,executor_ref=self.descriptor.executor_ref,
                status=BlockStatus.SUCCEEDED,outputs={"node":request.node_id,"timeout":request.timeout_seconds})
    config={"executor_ref":"budget@1"}
    if explicit is not None:config["timeout_seconds"]=explicit
    tree=CapabilityTree("budget qualification",(probe_node("check",capability_ref="probe@1",config=config),))
    registry=ExecutorRegistry();registry.register(Probe());store=FileRunStore(tmp_path)
    result=run_calibration(governed_probe_runner(registry,store),project_id="p",run_id="r",tree=tree,dag=compile_tree(tree))
    assert result.status=="SUCCEEDED" and seen==[expected]
    receipt=store.load_result("p","r","check")
    assert receipt.metadata["execution_timeout_seconds"]==expected
    assert receipt.metadata["execution_timeout_source"]==("node" if explicit is not None else "executor_default")

@pytest.mark.parametrize("value",[True,0,-1,float("nan"),float("inf"),"60"])
def test_invalid_registered_timeout_rejected(value):
    with pytest.raises(ValueError):ExecutorDescriptor("bad@1","probe",("probe@1",),default_timeout_seconds=value)


def governed_probe_runner(*args, **kwargs):
    return probe_runner(*args, execution_mode="GOVERNED", **kwargs)

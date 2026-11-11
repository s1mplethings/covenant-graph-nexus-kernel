"""Optional deterministic network probe through the common Block boundary."""
from __future__ import annotations

import time

from cgkn.component.spec import ComponentSpec
from cgkn.component.ports import PortSpec
from cgkn.execution import BlockExecutionResult,BlockStatus,ExecutionError,ExecutionErrorCode
from cgkn.execution.contracts import utc_now
from cgkn.providers.network_health import probe
from .protocol import ExecutorDescriptor


NETWORK_HEALTH_COMPONENT=ComponentSpec('network.health','1.0',
    input_ports=(PortSpec('probe','artifact.network_probe@1'),),
    output_ports=(PortSpec('health','artifact.network_health@1'),),
    effects={'network.probe':True})


class NetworkHealthExecutor:
    descriptor=ExecutorDescriptor('local.network-health@1','network',('network.health@1.0',),('network.probe',))

    def execute(self,request):
        started=utc_now(); clock=time.monotonic(); error=None; outputs={}
        try:
            if request.component_ref!=NETWORK_HEALTH_COMPONENT.ref or 'network.probe' not in request.declared_effects:
                raise ValueError('NETWORK_PROBE_COMPONENT_AND_EFFECT_REQUIRED')
            spec=request.input_values['probe']
            row=probe(spec['provider'],spec['route_id'],spec['proxy_url'],spec['endpoint'],min(float(spec.get('timeout',5)),request.timeout_seconds))
            outputs={'health':row}
            status=BlockStatus.SUCCEEDED if row['http_reached'] else BlockStatus.BLOCKED
            if status==BlockStatus.BLOCKED:
                error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR,'NetworkUnavailable',{'category':row['category'],'layer':row['layer']})
        except (KeyError,ValueError,TypeError):
            status=BlockStatus.FAILED;error=ExecutionError(ExecutionErrorCode.CONTRACT_ERROR,'Invalid bounded network probe')
        return BlockExecutionResult(project_id=request.project_id,run_id=request.run_id,attempt_id=request.attempt_id,
            node_id=request.node_id,executor_ref=request.executor_ref,status=status,outputs=outputs,error=error,
            started_at=started,ended_at=utc_now(),duration_ms=int((time.monotonic()-clock)*1000),retryable=False)

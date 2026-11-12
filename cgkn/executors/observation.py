"""Observation adapter at the common Executor boundary, configured by the host."""
import json
from dataclasses import replace
from cgkn.execution.observations import Observations

class ObservationExecutor:
    def __init__(self,delegate,store,declarations,subject):
        self.delegate,self.store,self.declarations,self.subject=delegate,store,tuple(declarations),dict(subject)
        self.descriptor=delegate.descriptor;self.resource_claims=getattr(delegate,'resource_claims',{})
    def execute(self,request):
        result=self.delegate.execute(request);body=result.as_dict();obs=Observations(self.store,request.project_id,request.run_id);refs=[]
        for spec in self.declarations:
            value=body['outputs'].get(spec['field'],'')
            raw=value if isinstance(value,(str,bytes)) else json.dumps(value,ensure_ascii=False)
            refs.append(obs.record(raw,observation_type=spec['type'],producer=result.executor_ref,subject=self.subject,
                node_id=request.node_id,attempt_id=request.attempt_id,created_at=result.ended_at,
                encoding=spec.get('encoding','utf-8'),media_type=spec.get('media_type','text/plain'),
                structured={k:body['outputs'][k] for k in spec.get('public_fields',()) if k in body['outputs']}))
        return replace(result,metadata={**body['metadata'],'typed_observation_refs':refs})

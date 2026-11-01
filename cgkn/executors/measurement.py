"""Bounded deterministic file measurement through the existing Block interface."""
import hashlib
import json
from pathlib import Path

from cgkn.execution import BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode
from cgkn.execution.check_evidence import predicate
from cgkn.executors.protocol import ExecutorDescriptor
from cgkn.state.acceptance import identity


class EvidenceBoundExecutor:
    """Attach actual bounded observations to immutable run evidence.

    Trusted host configures the delegate, source and subject paths. The wrapper
    never accepts candidate-supplied checker code and never grants acceptance.
    """
    def __init__(self, delegate, store, checker_source, artifacts, candidate_id, candidate_version):
        self.delegate,self.descriptor=delegate,delegate.descriptor
        self.store,self.source=store,Path(checker_source)
        self.artifacts={k:Path(v) for k,v in artifacts.items()}
        self.candidate_id,self.version=candidate_id,candidate_version

    def execute(self, request):
        from dataclasses import replace
        from cgkn.state.provenance import put_evidence,reference,ProvenanceGate
        from cgkn.execution.contracts import utc_now
        data={k:p.read_bytes() for k,p in self.artifacts.items()}
        source=self.source.read_bytes()
        result=self.delegate.execute(request)
        if any(p.read_bytes()!=data[k] for k,p in self.artifacts.items()) or self.source.read_bytes()!=source:
            return replace(result,status=BlockStatus.FAILED,error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR,'checker changed candidate or checker source'))
        if result.status!=BlockStatus.SUCCEEDED or 'goal_check' not in result.outputs:return result
        gate=ProvenanceGate(self.store,request.project_id,request.run_id);binding=gate.binding()
        check=result.as_dict()['outputs']['goal_check'];goal_id=check['goal_id'];contract=binding['goals'][goal_id]
        def blob(raw):
            h=hashlib.sha256(raw).hexdigest();path=gate.root/'evidence'/(h+'.blob')
            self.store.immutable_blob(path,raw);return reference(self.store.root,path)
        refs={k:blob(v) for k,v in data.items()};subjects={k:r['sha256'] for k,r in refs.items()}
        candidate=put_evidence(self.store,request.project_id,request.run_id,{'kind':'CandidateIdentity','candidate_id':self.candidate_id,'version':self.version,'created_at':utc_now(),'subjects':subjects,'artifacts':refs})
        raw=put_evidence(self.store,request.project_id,request.run_id,{'kind':'RawObservation','observed':check['observed'],'execution':check['execution'],'created_at':utc_now(),'subjects':subjects,'input_ref':binding['input_ref'],'checker_hash':hashlib.sha256(source).hexdigest()})
        witness={'kind':'CheckWitness','goal_id':goal_id,'logical_task_id':binding['logical_task_id'],'requirement_hashes':{k:identity(binding['requirements'][k]) for k in contract['requirement_refs']},'input_ref':binding['input_ref'],'environment_ref':binding['environment_ref'],'checker_ref':result.executor_ref,'checker_version':check['checker_version'],'checker_source_ref':blob(source),'candidate_ref':candidate,'observation_ref':raw,'attempt_id':request.attempt_id}
        check['provenance_ref']=put_evidence(self.store,request.project_id,request.run_id,witness)
        return replace(result,outputs={**result.outputs,'goal_check':check},metadata={**result.metadata,'bound_candidate':{'id':self.candidate_id,'version':self.version}})


class FileMeasurementExecutor:
    descriptor = ExecutorDescriptor('measure.file@1', 'deterministic', ('measure.file@1',))

    def __init__(self, root, contracts):
        self.root = Path(root).resolve()
        self.contracts = json.loads(json.dumps(contracts))

    def execute(self, request):
        try:
            contract = self.contracts[request.input_values['contract_id']]
            path = self.root / contract['path']
            if path.is_symlink() or not path.resolve().is_relative_to(self.root):
                raise ValueError('measurement outside trusted root')
            raw = path.read_bytes()
            if len(raw) > 1_000_000:
                raise ValueError('measurement exceeds bounded input')
            artifact = hashlib.sha256(raw).hexdigest()
            observed = json.loads(raw)
            value = observed[contract['field']]
            applicable = artifact == contract['artifact_sha256']
            verdict = ('VERIFIED' if predicate(value, contract['predicate']) else 'FAILED') if applicable else 'INSUFFICIENT_EVIDENCE'
            check = {'goal_id':contract['goal_id'], 'condition_hash':identity(contract['predicate']),
                     'subjects':{contract['subject']:artifact}, 'execution':'VALID',
                     'evidence_refs':[str(path)], 'observed':{'value':value, 'artifact_sha256':artifact},
                     'verdict':verdict, 'contract_version':contract['version'], 'checker_version':'1.0'}
            return BlockExecutionResult(project_id=request.project_id, run_id=request.run_id,
                node_id=request.node_id, attempt_id=request.attempt_id, executor_ref=request.executor_ref,
                status=BlockStatus.SUCCEEDED, outputs={'goal_check':check})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return BlockExecutionResult(project_id=request.project_id, run_id=request.run_id,
                node_id=request.node_id, attempt_id=request.attempt_id, executor_ref=request.executor_ref,
                status=BlockStatus.FAILED, error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR, str(exc)))

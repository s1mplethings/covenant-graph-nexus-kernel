from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time
import hashlib
from dataclasses import replace
from typing import Any, Mapping

from cgkn.execution import BlockExecutionRequest, BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode
from cgkn.execution.contracts import utc_now
from cgkn.executors.protocol import ExecutorDescriptor

from .contracts import AcceptanceResult, FailureClass, ProjectResultStatus


class ExternalAcceptanceExecutor:
    descriptor = ExecutorDescriptor("project.acceptance@1", "external_acceptance", ("project.acceptance.external@1",), ("process.execute", "test.observe"))

    def __init__(self, project_root: pathlib.Path | str, acceptance_root: pathlib.Path | str,
                 *, session_acceptance=None, consumer=None, qualified_revision=None):
        self.project_root = pathlib.Path(project_root).resolve()
        self.acceptance_root = pathlib.Path(acceptance_root).resolve()
        self.session_acceptance = session_acceptance
        self.consumer = dict(consumer or {})
        self.checker_version = "1"
        self.checker_revision_ref = None
        if self.consumer:
            # A full external consumer needs its own declared default budget;
            # an explicit node timeout remains authoritative in DAGRunner.
            self.descriptor = replace(self.descriptor,
                default_timeout_seconds=float(self.consumer.get("timeout_seconds", 60)))
            if session_acceptance is None: raise ValueError('consumer requires existing GoalAcceptance')
            supplied=pathlib.Path(self.consumer['path']).absolute()
            path=supplied.resolve()
            if (path.is_relative_to(self.project_root) or not path.is_file()
                    or any(p.is_symlink() for p in (supplied,*supplied.parents))):
                raise ValueError('independent consumer must be outside candidate workspace')
            raw=path.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=self.consumer['sha256']:
                raise ValueError('independent consumer source hash mismatch')
            store=session_acceptance.store
            root=store.run_dir(session_acceptance.project_id,session_acceptance.run_id)
            self.consumer_path=root/'private_checker'/(self.consumer['sha256']+'.py')
            store.immutable_blob(self.consumer_path,raw)
            store.immutable_json(root/'independent_consumer.json',self.consumer)
            if qualified_revision is not None:
                from cgkn.state.provenance import ProvenanceGate
                binding = ProvenanceGate(store, session_acceptance.project_id, session_acceptance.run_id).binding()
                accepted = binding.get('checker_revisions', {}).get(qualified_revision['checker_key'], {}).get(qualified_revision['checker_version'])
                if accepted != qualified_revision:
                    raise ValueError('unbound checker revision')
                self.consumer_path = store.root/qualified_revision['source_ref']['path']
                self.consumer['sha256'] = qualified_revision['checker_hash']
                self.checker_version = qualified_revision['checker_version']
                self.checker_revision_ref = qualified_revision['revision_ref']

    def execute(self, request: BlockExecutionRequest) -> BlockExecutionResult:
        if self.consumer:
            return self._execute_milestone(request)
        started, clock = utc_now(), time.perf_counter()
        case_id = str(request.task_context.node_config.get("case_id", ""))
        snapshot_hash = ""
        for value in request.task_context.dependency_results.values():
            if isinstance(value, Mapping) and value.get("snapshot_hash"):
                snapshot_hash = str(value["snapshot_hash"])
        test_path = self.acceptance_root / f"test_{case_id}.py"
        if not test_path.is_file():
            result = AcceptanceResult(ProjectResultStatus.FAIL, FailureClass.HARNESS_FAILURE, "acceptance harness is unavailable", snapshot_hash=snapshot_hash)
            return self._block(request, result, started, clock)
        env = os.environ.copy()
        env.update({"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "CGKN_GENERATED_PROJECT": str(self.project_root), "PYTHONPATH": str(self.project_root)})
        dependency_policy = request.task_context.node_config.get("dependency_policy", {})
        if isinstance(dependency_policy, Mapping):
            test_policy = dependency_policy.get("test", {})
            if isinstance(test_policy, Mapping):
                env["CGKN_TEST_ALLOWED_PACKAGES"] = ",".join(str(item) for item in test_policy.get("allowed_packages", ()))
        try:
            completed = subprocess.run([sys.executable, "-m", "pytest", "-q", str(test_path)], cwd=self.project_root, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=request.timeout_seconds, env=env)
            status = ProjectResultStatus.PASS if completed.returncode == 0 else ProjectResultStatus.FAIL
            failure = None if status is ProjectResultStatus.PASS else FailureClass.PROJECT_FAILURE
            summary = "all external requirements passed" if status is ProjectResultStatus.PASS else "one or more external requirements failed"
            failed_count = sum(1 for line in completed.stdout.splitlines() if line.startswith("FAILED "))
            failed = tuple(f"public-requirement-{index + 1}" for index in range(failed_count))
            stdout = self._sanitized_output(completed.stdout, status)
            stderr = self._sanitized_output(completed.stderr, status)
            result = AcceptanceResult(status, failure, summary, failed, (completed.returncode,), stdout, stderr, {"real_subprocess": True, "isolated_harness": True}, int((time.perf_counter() - clock) * 1000), snapshot_hash)
        except subprocess.TimeoutExpired:
            result = AcceptanceResult(ProjectResultStatus.FAIL, FailureClass.TIMEOUT, "external acceptance timed out", duration_ms=int((time.perf_counter() - clock) * 1000), snapshot_hash=snapshot_hash)
        return self._block(request, result, started, clock)

    def _execute_milestone(self, request):
        """Run a frozen external consumer; success is a typed observation.

        Raw process output remains protected evidence. Only explicitly public
        scalar facts enter goal feedback; exit zero alone never verifies work.
        """
        from cgkn.execution.observations import Observations, FORBIDDEN_PUBLIC
        from cgkn.state.acceptance import identity
        a=self.session_acceptance;store=a.store;started=utc_now();clock=time.perf_counter();refs=[]
        root=store.run_dir(request.project_id,request.run_id)
        try:
            if (request.project_id,request.run_id)!=(a.project_id,a.run_id):
                raise ValueError('independent consumer run mismatch')
            goal=next(g for g in a.view()['goals'] if g['id']==request.task_context.node_config['goal_id'])
            if a.checkers[goal['checker']]!=self.descriptor.executor_ref:
                raise ValueError('consumer is not the registered goal checker')
            if hashlib.sha256(self.consumer_path.read_bytes()).hexdigest()!=self.consumer['sha256']:
                raise ValueError('frozen consumer changed')
            def snapshot():
                values={}
                for name in goal['subject_refs']:
                    path=(self.project_root/name).resolve()
                    if not path.is_relative_to(self.project_root): raise ValueError('consumer subject escape')
                    values[name]=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
                return values
            subjects=snapshot()
            if not subjects or not all(subjects.values()): raise ValueError('consumer subjects are not materialized')
            document={'kind':'IndependentMilestoneRequest','project_id':request.project_id,'run_id':request.run_id,
                'goal_id':goal['id'],'requirements':{r:a.requirements[r] for r in goal['requirement_refs']},
                'acceptance':goal['acceptance'],'public_contract':goal['milestone_contract'],
                'workspace':str(self.project_root),'subjects':subjects}
            input_path=root/'consumer_requests'/request.node_id/(request.attempt_id+'.json')
            store.immutable_json(input_path,document)
            scratch=root/'consumer_scratch'/request.node_id/request.attempt_id;scratch.mkdir(parents=True,exist_ok=True)
            env=os.environ.copy()
            env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1',TEMP=str(scratch),TMP=str(scratch))
            argv=[sys.executable,'-X','utf8',str(self.consumer_path),'--request',str(input_path)]
            process=subprocess.run(argv,cwd=scratch,env=env,capture_output=True,
                timeout=min(request.timeout_seconds,int(self.consumer.get('timeout_seconds',60))))
            observations=Observations(store,request.project_id,request.run_id)
            common={'producer':self.descriptor.executor_ref,'subject':subjects,
                    'node_id':request.node_id,'attempt_id':request.attempt_id}
            refs.append(observations.record(process.stdout,observation_type='json_document',media_type='application/json',**common))
            refs.append(observations.record(process.stderr,observation_type='stderr_text',**common))
            refs.append(observations.record(json.dumps({'returncode':process.returncode}),
                observation_type='process_result',structured={'returncode':process.returncode},argv=argv,**common))
            typed=observations.resolve(refs[0])
            if process.returncode!=0 or typed['normalization_error']:
                raise ValueError('independent consumer did not produce a valid measurement')
            result=typed['structured']['document']
            if (not isinstance(result,dict) or set(result)!={'execution','observed'}
                    or result['execution']!='VALID' or not isinstance(result['observed'],dict)
                    or type(result['observed'].get('value')) is not bool):
                raise ValueError('invalid independent measurement envelope')
            public_fields=self.consumer.get('public_fields',['value'])
            if (not isinstance(public_fields,list) or 'value' not in public_fields
                    or any(not isinstance(k,str) or k in FORBIDDEN_PUBLIC or k.startswith('_') or '.' in k for k in public_fields)):
                raise ValueError('invalid public consumer field policy')
            public={k:result['observed'][k] for k in public_fields if k in result['observed']}
            if any(isinstance(v,(dict,list)) for v in public.values()):
                raise ValueError('consumer public projection requires qualified scalar fields')
            if snapshot()!=subjects or hashlib.sha256(self.consumer_path.read_bytes()).hexdigest()!=self.consumer['sha256']:
                raise ValueError('consumer mutated its candidate or checker')
            public_ref=observations.record(json.dumps(public),observation_type='checker_result',structured=public,**common)
            refs.append(public_ref)
            passed=public['value'];verdict='VERIFIED' if passed else 'FAILED'
            feedback=observations.public_feedback([public_ref],requirement_id=goal['id'],goal=goal['acceptance'],
                current_object=subjects,expected=goal['acceptance'],public_fields=public_fields,
                failure_domain='NONE' if passed else 'BUSINESS')
            provenance_fields={};candidate_metadata={}
            if (root/'provenance_contract.json').exists():
                from cgkn.state.provenance import ProvenanceGate,put_evidence,reference
                binding=ProvenanceGate(store,request.project_id,request.run_id).binding()
                artifacts={}
                for name,digest in subjects.items():
                    source=(self.project_root/name).read_bytes()
                    if hashlib.sha256(source).hexdigest()!=digest:
                        raise ValueError('candidate changed while sealing evidence')
                    target=root/'candidate_objects'/digest
                    store.immutable_blob(target,source)
                    artifacts[name]=reference(store.root,target)
                candidate_id=identity(subjects)
                candidate_ref=put_evidence(store,request.project_id,request.run_id,
                    {'kind':'CandidateIdentity','candidate_id':candidate_id,'version':candidate_id,
                     'created_at':started,'subjects':subjects,'artifacts':artifacts})
                raw_ref=put_evidence(store,request.project_id,request.run_id,
                    {'kind':'RawObservation','created_at':started,'subjects':subjects,
                     'checker_hash':self.consumer['sha256'],'input_ref':binding['input_ref'],
                     'observed':public,'execution':'VALID','typed_observation_refs':refs,
                     'consumer_request_ref':reference(store.root,input_path)})
                witness={'kind':'CheckWitness','goal_id':goal['id'],
                    'logical_task_id':binding['logical_task_id'],
                    'requirement_hashes':{r:identity(binding['requirements'][r]) for r in goal['requirement_refs']},
                    'input_ref':binding['input_ref'],'environment_ref':binding['environment_ref'],
                    'checker_ref':self.descriptor.executor_ref,'checker_version':self.checker_version,
                    'checker_source_ref':reference(store.root,self.consumer_path),
                    'attempt_id':request.attempt_id,'candidate_ref':candidate_ref,'observation_ref':raw_ref}
                if self.checker_revision_ref is not None:
                    witness['checker_revision_ref'] = self.checker_revision_ref
                if 'incremental_checker_bindings' in binding:
                    witness['goal_binding_ref']=reference(store.root,root/'provenance_goals'/(identity(goal['id'])+'.json'))
                provenance_fields={'checker_version':self.checker_version,'provenance_ref':put_evidence(store,request.project_id,request.run_id,witness)}
                candidate_metadata={'bound_candidate':{'id':candidate_id,'version':candidate_id}}
            a.bind_subjects({**a.view()['subject_identities'],**subjects})
            return BlockExecutionResult(project_id=request.project_id,run_id=request.run_id,node_id=request.node_id,
                attempt_id=request.attempt_id,executor_ref=self.descriptor.executor_ref,status=BlockStatus.SUCCEEDED,
                outputs={'goal_check':{'goal_id':goal['id'],'condition_hash':identity(goal['acceptance']),
                    'subjects':subjects,'execution':'VALID','verdict':verdict,'observed':public,'evidence_refs':[public_ref],**provenance_fields},
                         'public_feedback':feedback},started_at=started,ended_at=utc_now(),
                duration_ms=int((time.perf_counter()-clock)*1000),
                metadata={'independent_checker_hash':self.consumer['sha256'],'raw_observation_refs':refs,
                          'hidden_source_exposed':False,**candidate_metadata})
        except (OSError,ValueError,TypeError,KeyError,StopIteration,subprocess.TimeoutExpired) as exc:
            observations=Observations(store,request.project_id,request.run_id)
            failure_subject={'run_id':request.run_id,'node_id':request.node_id,'attempt_id':request.attempt_id}
            for content,kind in ((getattr(exc,'stdout',None),'stdout_text'),(getattr(exc,'stderr',None),'stderr_text')):
                if content:
                    refs.append(observations.record(content,observation_type=kind,producer=self.descriptor.executor_ref,
                        subject=failure_subject,node_id=request.node_id,attempt_id=request.attempt_id))
            refs.append(observations.record(json.dumps({'error_type':type(exc).__name__,'status':'INVALID_EVALUATOR'}),
                observation_type='checker_result',producer=self.descriptor.executor_ref,subject=failure_subject,
                node_id=request.node_id,attempt_id=request.attempt_id,structured={'failure_domain':'HARNESS'}))
            return BlockExecutionResult(project_id=request.project_id,run_id=request.run_id,node_id=request.node_id,
                attempt_id=request.attempt_id,executor_ref=self.descriptor.executor_ref,status=BlockStatus.FAILED,
                outputs={'status':'INVALID_EVALUATOR','evidence_refs':refs},
                error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR,'independent consumer measurement invalid',
                    {'failure_domain':'HARNESS','error_type':type(exc).__name__,'outcome_unknown':False}),
                started_at=started,ended_at=utc_now(),duration_ms=int((time.perf_counter()-clock)*1000),
                metadata={'hidden_source_exposed':False,'raw_observation_refs':refs})

    @staticmethod
    def _sanitized_output(value: str, status: ProjectResultStatus) -> str:
        """Keep useful PASS evidence without leaking harness paths or assertions."""
        if not value:
            return ""
        if status is ProjectResultStatus.FAIL:
            return "external acceptance diagnostics withheld"
        lines = [line for line in value.splitlines() if "passed in" in line]
        return (lines[-1] + "\n") if lines else "external acceptance completed\n"

    @staticmethod
    def _block(request: BlockExecutionRequest, result: AcceptanceResult, started: str, clock: float) -> BlockExecutionResult:
        value = result.as_dict()
        status = BlockStatus.SUCCEEDED if result.status is ProjectResultStatus.PASS else BlockStatus.FAILED
        error = None if status is BlockStatus.SUCCEEDED else ExecutionError(ExecutionErrorCode.INVALID_OUTPUT, result.sanitized_summary, {"failure_class": result.failure_class.value if result.failure_class else None, "failed_requirement_ids": list(result.failed_requirement_ids)})
        return BlockExecutionResult(project_id=request.project_id, run_id=request.run_id, attempt_id=request.attempt_id, node_id=request.node_id, executor_ref=request.executor_ref, status=status, outputs=value, error=error, started_at=started, ended_at=utc_now(), duration_ms=max(0, int((time.perf_counter() - clock) * 1000)), metadata={"hidden_source_exposed": False})


def write_acceptance_receipt(path: pathlib.Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

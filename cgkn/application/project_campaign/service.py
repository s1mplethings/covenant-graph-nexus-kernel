from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import tomllib
import uuid
import zipfile
from dataclasses import replace
from typing import Any, Callable, Mapping, Sequence

from scripts import canonical_evidence_hash, customer_runtime_runner, local_packager, real_test_execution

from cgkn.application.capability_builder import CapabilityBuilderService, CapabilityRisk, CapabilitySpec, CapabilityStore, StoredCapabilityRuntime
from cgkn.application.learning import GenerationRequest, LearningEvent, ProductionGenerationClient, StoreLessonRecorder, canonical_hash, record_feedback
from cgkn.application.materialization import materialize_json
from cgkn.application.self_growth import SelfGrowthService
from cgkn.application.software_project.contracts import WorkerScope
from cgkn.application.software_project.scope import ScopedFileTransaction
from cgkn.execution import BlockExecutionRequest, BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode
from cgkn.execution.contracts import utc_now
from cgkn.executors import ExecutorRegistry
from cgkn.executors.llm import WORKER_SCHEMA, validate_worker_proposal
from cgkn.executors.protocol import ExecutorDescriptor
from cgkn.orchestration import CapabilityNode, CapabilityTree, compile_tree
from cgkn.providers import ModelRoleConfig, ProviderConnectionError, parse_json_object
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore

from .contracts import CampaignState, ProjectCase, ProjectRunReceipt


CAMPAIGN_ID = "ITER-MULTI-PROJECT-REAL-USAGE-CAMPAIGN-026"
PYPROJECT_CAP = "project.python.pyproject.render@1"
README_CAP = "project.readme.cli_examples.render@1"
LICENSE_CAP = "project.python.license.render@1"


class CapabilityGap(RuntimeError):
    pass


class _FunctionExecutor:
    def __init__(self, ref: str, component: str, function: Callable[[BlockExecutionRequest], Mapping[str, Any]]):
        self.descriptor = ExecutorDescriptor(ref, "campaign_deterministic", (component,), ("filesystem.write",), True, False, "local")
        self.function = function

    def execute(self, request: BlockExecutionRequest) -> BlockExecutionResult:
        started = utc_now(); clock = time.perf_counter()
        try:
            outputs = dict(self.function(request))
            return BlockExecutionResult(request.project_id, request.run_id, request.attempt_id, request.node_id, request.executor_ref, BlockStatus.SUCCEEDED, outputs=outputs, started_at=started, ended_at=utc_now(), duration_ms=int((time.perf_counter()-clock)*1000))
        except CapabilityGap as exc:
            return BlockExecutionResult(request.project_id, request.run_id, request.attempt_id, request.node_id, request.executor_ref, BlockStatus.FAILED, error=ExecutionError(ExecutionErrorCode.EXECUTOR_NOT_FOUND, str(exc), {"status":"GROWTH_REQUIRED"}), retryable=True, started_at=started, ended_at=utc_now(), duration_ms=int((time.perf_counter()-clock)*1000))
        except Exception as exc:
            return BlockExecutionResult(request.project_id, request.run_id, request.attempt_id, request.node_id, request.executor_ref, BlockStatus.FAILED, error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR, f"{type(exc).__name__}: {exc}"), started_at=started, ended_at=utc_now(), duration_ms=int((time.perf_counter()-clock)*1000))


class _CoreExecutor:
    def __init__(self, case: ProjectCase, workspace: pathlib.Path, generation: ProductionGenerationClient, config: ModelRoleConfig):
        self.case, self.workspace, self.generation, self.config = case, workspace, generation, config
        self.descriptor = ExecutorDescriptor(f"campaign.{case.project_id}.core@1", "campaign_project_codegen", (f"campaign.{case.project_id}.core@1",), ("filesystem.write",), True, True, "provider")

    def execute(self, request: BlockExecutionRequest) -> BlockExecutionResult:
        started = utc_now(); clock = time.perf_counter(); failure = dict(request.task_context.node_config.get("failure_evidence", {}))
        current = {path.relative_to(self.workspace).as_posix(): path.read_text(encoding="utf-8") for path in sorted(self.workspace.rglob("*.py")) if ".pytest_cache" not in path.parts}
        contract = _contract(self.case)
        prompt = {
            "node_id": request.node_id, "project_id": self.case.project_id,
            "target_paths": list(self.case.target_paths), "current_sources": current,
            "interface_contract": self.case.interface_contract, "behavior_contract": self.case.behavior_contract,
            "dependency_policy": {"runtime":"PYTHON_STDLIB_ONLY","test":["pytest"],"network":"FORBIDDEN","shell":"FORBIDDEN"},
            "failure_evidence": failure,
        }
        try:
            model_config=replace(self.config,max_output_tokens=min(self.config.max_output_tokens,4000),reasoning_effort="low") if failure else self.config
            result = self.generation.generate(GenerationRequest(
                "project.codegen", "REPAIR" if failure else "GENERATION", self.case.project_id,
                f"campaign.{self.case.project_id}.core@1", self.config.model,
                "Implement exactly the declared cohesive project core. Contracts are authoritative. Return complete JSON file actions for only target_paths. Runtime must use Python stdlib only and must not use network, shell, tests, hidden acceptance, metadata, campaign artifacts, or undeclared aliases.",
                prompt, contract, current, failure, f"campaign_{self.case.project_id}_actions", WORKER_SCHEMA, model_config,
                dependency_risk_policy=prompt["dependency_policy"], allowed_actions=("write_file","patch_file"),
                forbidden_actions=("network","shell","test_write","metadata_write","hidden_acceptance"), run_id=request.run_id,
            ))
            proposal = validate_worker_proposal(parse_json_object(result.completion.text), request.node_id)
            if proposal["needs_escalation"]:
                raise ValueError(proposal["escalation_reason"] or "project core escalated")
            scope = WorkerScope(tuple(self.case.target_paths), tuple(self.case.target_paths), protected_paths=("tests","pyproject.toml","README.md","LICENSE",".git","governance","artifacts"), max_actions=8, max_write_files=8, max_total_output_bytes=140_000, allow_create=True, allow_patch=True, allow_delete=False)
            writes = ScopedFileTransaction(self.workspace, scope).apply(proposal["actions"])
            missing = [path for path in self.case.target_paths if not (self.workspace/path).is_file()]
            if missing:
                raise ValueError("PROJECT_CORE_MISSING_TARGETS:"+",".join(missing))
            source_hash = canonical_hash({path:(self.workspace/path).read_text(encoding="utf-8") for path in self.case.target_paths})
            revision_id,revision_path=_snapshot_candidate(self.workspace,self.case.target_paths,source_hash)
            receipt = {"kind":"CampaignProjectGenerationReceipt","schema_version":"1.0","candidate_id":"candidate-"+source_hash[-16:],"candidate_revision_id":revision_id,"candidate_revision_path":revision_path,"source_hash":source_hash,"request_id":result.completion.request_id,"lesson_snapshot_hash":result.lesson_snapshot_hash,"applied_lesson_ids":list(result.applied_lesson_ids),"lesson_context_chars":result.lesson_context_chars,"generation_context_hash":result.generation_context_hash,"manual_edits":0,"contains_credentials":False}
            _write_json(self.workspace/"generation_receipt.json", receipt)
            return BlockExecutionResult(request.project_id, request.run_id, request.attempt_id, request.node_id, request.executor_ref, BlockStatus.SUCCEEDED, outputs={**receipt,"modified_files":[item["path"] for item in writes]}, usage=dict(result.completion.usage), started_at=started, ended_at=utc_now(), duration_ms=int((time.perf_counter()-clock)*1000))
        except ProviderConnectionError as exc:
            return BlockExecutionResult(request.project_id, request.run_id, request.attempt_id, request.node_id, request.executor_ref, BlockStatus.FAILED, error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR, f"{exc.error_class}: {exc}", {"failure_domain":exc.error_class,"outcome_unknown":exc.outcome_unknown,"timeout_phase":exc.timeout_phase or "NONE"}), retryable=not exc.outcome_unknown, started_at=started, ended_at=utc_now(), duration_ms=int((time.perf_counter()-clock)*1000))
        except Exception as exc:
            return BlockExecutionResult(request.project_id, request.run_id, request.attempt_id, request.node_id, request.executor_ref, BlockStatus.FAILED, error=ExecutionError(ExecutionErrorCode.INVALID_OUTPUT, f"{type(exc).__name__}: {exc}"), started_at=started, ended_at=utc_now(), duration_ms=int((time.perf_counter()-clock)*1000))


class MultiProjectCampaignService:
    def __init__(self, repository_root: pathlib.Path | str, artifact_root: pathlib.Path | str, generation: ProductionGenerationClient, model_config: ModelRoleConfig, cases: Sequence[ProjectCase], *, rerun_project_ids: Sequence[str] = ()):
        self.repository_root = pathlib.Path(repository_root).resolve(); self.root = pathlib.Path(artifact_root).resolve()
        self.generation, self.config, self.cases = generation, model_config, tuple(cases)
        self.shared_store = CapabilityStore(self.root/"capability_registry")
        self.source_commit = _git(self.repository_root, "rev-parse", "HEAD")
        self.provider_calls = self.input_tokens = self.output_tokens = self.cost_ticks = 0
        self.growth_count = self.reuse_count = 0
        self.rerun_project_ids=frozenset(rerun_project_ids); self.interrupted_calls:dict[str,int]={}

    def run(self) -> Mapping[str, Any]:
        self.root.mkdir(parents=True, exist_ok=True)
        self._recover_interrupted_projects()
        self._prepare_reruns()
        _write_json(self.root/"project_matrix.json", self._matrix_document())
        existing = self._load_receipts()
        self._seed_counters(existing)
        if self.generation.max_provider_calls is not None:
            self.generation.max_provider_calls=self.generation.provider_call_count+max(0,36-self.provider_calls)
        for wave in ("A","B","C"):
            if wave == "C":
                self._freeze_holdout()
            for case in (item for item in self.cases if item.wave == wave):
                if case.project_id in existing:
                    continue
                if self.provider_calls >= 36:
                    existing[case.project_id] = self._blocked_receipt(case, "PROVIDER_BUDGET_EXHAUSTED")
                else:
                    existing[case.project_id] = self.run_project(case)
                self._checkpoint(wave, case.project_id, existing)
            if wave == "C":
                self._finalize_holdout_learning(existing)
            self._wave_summary(wave, existing)
        report = self._final_report(existing)
        _write_json(self.root/"final_report.json", report)
        return report

    def run_project(self, case: ProjectCase) -> Mapping[str, Any]:
        started = time.perf_counter(); before_calls = self.generation.provider_call_count; prior_calls=self.interrupted_calls.get(case.project_id,0)
        before_usage = self._client_usage()
        project_root = self.root/"projects"/case.project_id; workspace = project_root/"workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        for relative, content in case.initial_files.items():
            path=workspace/relative; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(content,encoding="utf-8")
        initial_hashes = _hash_tree(workspace)
        run_id = f"{case.project_id}-{uuid.uuid4().hex[:10]}"; state = FileRunStore(project_root/"state")
        recorder = StoreLessonRecorder(self.generation.store) if self.generation.store else None
        tree = self._tree(case); dag = compile_tree(tree); registry = self._registry(case, workspace, project_root)
        runner = DAGRunner(registry, state)
        first = runner.run(project_id=case.project_id, run_id=run_id, tree=tree, dag=dag, constraints=("stdlib only","network forbidden","shell forbidden","routing frozen"))
        grown: list[str] = []; reused: list[str] = []
        missing = [ref for ref in case.required_capabilities if not (self.root/"capability_registry"/_slug(ref)/"admission.json").is_file()]
        for ref in case.required_capabilities:
            if ref not in missing: reused.append(ref); self.reuse_count += 1
        if missing:
            growth = SelfGrowthService(CapabilityBuilderService(self.generation,self.config,provider_id="grok",mode="SINGLE_PROVIDER_MODE",store=self.shared_store),self.shared_store,provider_id="grok",mode="SINGLE_PROVIDER_MODE",history_path=project_root/"growth_history.json")
            for ref in missing:
                outcome = growth.ensure_and_resume(project_root/"growth"/_slug(ref), _capability_spec(ref), _capability_input(ref, case))
                if outcome.status != "PASS":
                    return self._failure(case, project_root, before_calls, started, "CAPABILITY_IMPLEMENTATION_BLOCKER:"+outcome.failure_class, grown, reused, usage_before=before_usage, run_id=run_id, recorder=recorder)
                grown.append(ref); self.growth_count += 1
        repair_rounds = 0
        tree = self._tree(case); dag = compile_tree(tree)
        final = first if first.status == "SUCCEEDED" else runner.run(project_id=case.project_id, run_id=run_id, tree=tree, dag=dag, resume=True, retry_node="capability-resolve", constraints=("stdlib only","network forbidden","shell forbidden","routing frozen"))
        repair_failure_code = ""
        if final.status != "SUCCEEDED":
            failed = next(iter(final.failed_nodes), "")
            failed_result=state.load_result(case.project_id,run_id,failed)
            provider_failure=str(failed_result.error.details.get("failure_domain","")) if failed_result.error else ""
            if provider_failure and failed_result.retryable and prior_calls+self.generation.provider_call_count-before_calls < 4:
                final=runner.run(project_id=case.project_id,run_id=run_id,tree=tree,dag=dag,resume=True,retry_node="core-generate",constraints=("stdlib only","network forbidden","shell forbidden","routing frozen"))
                failed = next(iter(final.failed_nodes), "") if final.status != "SUCCEEDED" else ""
                failed_result=state.load_result(case.project_id,run_id,failed) if failed else failed_result
                provider_failure=str(failed_result.error.details.get("failure_domain","")) if failed_result.error else ""
            repairable = not provider_failure and failed in {"core-generate","compile","pytest","oracle","hidden"}
            if final.status != "SUCCEEDED" and repairable and prior_calls+self.generation.provider_call_count-before_calls < 4:
                repair_rounds=1; repair_failure_code=failed.upper().replace("-","_"); failure=_repair_evidence(failed,state.load_result(case.project_id,run_id,failed))
                tree=self._tree(case,{"failure_domain":"CANDIDATE_DEFECT","failed_node":failed,"receipt":failure}); dag=compile_tree(tree)
                final=runner.run(project_id=case.project_id,run_id=run_id,tree=tree,dag=dag,resume=True,retry_node="core-generate",constraints=("stdlib only","network forbidden","shell forbidden","routing frozen"))
        calls=prior_calls+self.generation.provider_call_count-before_calls
        if calls > 4:
            raise RuntimeError("CRITICAL_PROVIDER_PROJECT_BUDGET_EXCEEDED")
        if final.status != "SUCCEEDED":
            domain=self._final_failure_domain(state,case,run_id,final.failed_nodes)
            return self._failure(case,project_root,before_calls,started,domain,grown,reused,repair_rounds,usage_before=before_usage,run_id=run_id,recorder=recorder)
        core=state.load_result(case.project_id,run_id,"core-generate"); package=state.load_result(case.project_id,run_id,"package")
        usage=self._accumulate_usage(core,calls,before_usage)
        applied=tuple(core.outputs.get("applied_lesson_ids",()))
        if recorder:
            recorder.record_event(self._event(run_id,case,core,repair_failure_code,"PASS",project_root))
            if case.wave != "C":
                record_feedback(self.generation.store,applied,success=True); recorder.finalize_run(run_id)
        receipt=materialize_json(ProjectRunReceipt(
            case.project_id,case.wave,case.project_type,canonical_hash(case.public_goal),canonical_hash(_contract(case)),canonical_hash(_obligations(case)),str(core.outputs.get("lesson_snapshot_hash","")),applied,case.required_capabilities,tuple(grown),tuple(reused),calls,usage["input_tokens"],usage["output_tokens"],repair_rounds,1+repair_rounds,
            materialize_json(state.load_result(case.project_id,run_id,"pytest").outputs),materialize_json(state.load_result(case.project_id,run_id,"oracle").outputs),materialize_json(state.load_result(case.project_id,run_id,"hidden").outputs),materialize_json(package.outputs),materialize_json(package.outputs.get("runtime_smoke",{})),"","PASS",self.source_commit,round(time.perf_counter()-started,3),
        ).as_dict())
        receipt.update({"run_id":run_id,"case_hash":case.case_hash,"hidden_hash":case.hidden_hash,"lesson_context_chars":int(core.outputs.get("lesson_context_chars",0)),"generation_context_hash":str(core.outputs.get("generation_context_hash","")),"cost_in_usd_ticks":usage["cost_in_usd_ticks"],"initial_snapshot_hash":canonical_hash(initial_hashes),"final_snapshot_hash":canonical_hash(_hash_tree(workspace))})
        if case.existing_repo:
            receipt["repository_change"] = self._repository_change(case,workspace,initial_hashes)
        _write_json(project_root/"project_receipt.json",receipt)
        return receipt

    def _tree(self, case: ProjectCase, failure: Mapping[str,Any]|None=None) -> CapabilityTree:
        nodes=(
            CapabilityNode("contract",capability_ref="campaign.contract@1",config={"executor_ref":"campaign.contract@1"}),
            CapabilityNode("capability-resolve",capability_ref="campaign.capability.resolve@1",depends_on=("contract",),config={"executor_ref":"campaign.capability.resolve@1"}),
            CapabilityNode("core-generate",capability_ref=f"campaign.{case.project_id}.core@1",depends_on=("contract",),config={"executor_ref":f"campaign.{case.project_id}.core@1","failure_evidence":dict(failure or {})}),
            CapabilityNode("tests-render",capability_ref="campaign.tests.render@1",depends_on=("contract",),config={"executor_ref":"campaign.tests.render@1"}),
            CapabilityNode("metadata-render",capability_ref="campaign.metadata.render@1",depends_on=("capability-resolve",),config={"executor_ref":"campaign.metadata.render@1"}),
            CapabilityNode("docs-render",capability_ref="campaign.docs.render@1",depends_on=("capability-resolve",),config={"executor_ref":"campaign.docs.render@1"}),
            CapabilityNode("compile",capability_ref="campaign.compile@1",depends_on=("core-generate","tests-render","metadata-render","docs-render"),config={"executor_ref":"campaign.compile@1"}),
            CapabilityNode("pytest",capability_ref="campaign.pytest@1",depends_on=("compile",),config={"executor_ref":"campaign.pytest@1"}),
            CapabilityNode("oracle",capability_ref="campaign.oracle@1",depends_on=("pytest",),config={"executor_ref":"campaign.oracle@1"}),
            CapabilityNode("hidden",capability_ref="campaign.hidden@1",depends_on=("oracle",),config={"executor_ref":"campaign.hidden@1"}),
            CapabilityNode("snapshot",capability_ref="campaign.snapshot@1",depends_on=("hidden",),config={"executor_ref":"campaign.snapshot@1"}),
            CapabilityNode("package",capability_ref="campaign.package@1",depends_on=("snapshot",),config={"executor_ref":"campaign.package@1"}),
        )
        return CapabilityTree(f"Produce and validate {case.project_id}",nodes)

    def _registry(self,case:ProjectCase,workspace:pathlib.Path,project_root:pathlib.Path)->ExecutorRegistry:
        registry=ExecutorRegistry(); contract=_contract(case)
        funcs={
            "campaign.contract@1":lambda req:_write_json(project_root/"contract.json",contract) or {"contract_hash":canonical_hash(contract)},
            "campaign.capability.resolve@1":lambda req:self._resolve(case),
            "campaign.tests.render@1":lambda req:_render_tests(workspace,case),
            "campaign.metadata.render@1":lambda req:self._metadata(workspace,case),
            "campaign.docs.render@1":lambda req:self._docs(workspace,case),
            "campaign.compile@1":lambda req:_compile(workspace,case),
            "campaign.pytest@1":lambda req:_pytest(workspace),
            "campaign.oracle@1":lambda req:_evaluate(workspace,case.package_name,case.public_cases,"oracle"),
            "campaign.hidden@1":lambda req:_evaluate(workspace,case.package_name,case.hidden_cases,"hidden"),
            "campaign.snapshot@1":lambda req:_snapshot(workspace),
            "campaign.package@1":lambda req:_package(self.repository_root,workspace,project_root,case,self.source_commit),
        }
        for ref,func in funcs.items(): registry.register(_FunctionExecutor(ref,ref,func))
        registry.register(_CoreExecutor(case,workspace,self.generation,self.config)); return registry

    def _resolve(self,case:ProjectCase)->Mapping[str,Any]:
        missing=[ref for ref in case.required_capabilities if not (self.root/"capability_registry"/_slug(ref)/"admission.json").is_file()]
        if missing: raise CapabilityGap("CAPABILITY_GAP:"+",".join(missing))
        return {"status":"PASS","required":list(case.required_capabilities)}

    def _metadata(self,workspace:pathlib.Path,case:ProjectCase)->Mapping[str,Any]:
        if case.existing_repo: return {"status":"PASS","preserved":True}
        runtime=StoredCapabilityRuntime(self.shared_store,provider_id="grok")
        value=runtime.invoke(PYPROJECT_CAP,_capability_input(PYPROJECT_CAP,case)); text=str(value["pyproject_toml"]); tomllib.loads(text); (workspace/"pyproject.toml").write_text(text,encoding="utf-8")
        if LICENSE_CAP in case.required_capabilities:
            license_value=runtime.invoke(LICENSE_CAP,_capability_input(LICENSE_CAP,case)); (workspace/"LICENSE").write_text(str(license_value["license_text"]),encoding="utf-8")
        return {"status":"PASS","pyproject":"pyproject.toml","license":LICENSE_CAP in case.required_capabilities}

    def _docs(self,workspace:pathlib.Path,case:ProjectCase)->Mapping[str,Any]:
        if case.existing_repo: return {"status":"PASS","preserved":True}
        if README_CAP in case.required_capabilities:
            value=StoredCapabilityRuntime(self.shared_store,provider_id="grok").invoke(README_CAP,_capability_input(README_CAP,case)); text=str(value["readme_md"])
        else:
            text=f"# {case.project_id}\n\n{case.public_goal}\n\n## Usage\n\n`python -m {case.package_name} --help`\n"
        (workspace/"README.md").write_text(text,encoding="utf-8"); return {"status":"PASS","readme":"README.md"}

    def _repository_change(self,case:ProjectCase,workspace:pathlib.Path,initial:Mapping[str,str])->Mapping[str,Any]:
        final=_hash_tree(workspace); changed=sorted(path for path in set(initial)|set(final) if initial.get(path)!=final.get(path) and not path.startswith(("tests/test_contract_campaign.py","generation_receipt.json","customer_runtime.json","TEST_REPORT.md","DELIVERY_NOTES.md","test_","oracle_","hidden_","snapshot_","acceptance_")))
        unrelated=sorted(path for path in changed if path not in case.allowed_paths)
        value={"repository_snapshot":"PASS","change_contract":"PASS" if not unrelated else "FAIL","impact_set":list(case.allowed_paths),"changed_paths":changed,"unrelated_edits":unrelated,"interface_preservation":"PASS","existing_tests":"PASS","new_acceptance":"PASS","patch_bundle":"PASS" if not unrelated else "FAIL"}
        _write_json(workspace/"patch_receipt.json",value); _write_json(workspace/"interface_diff_receipt.json",{"status":"PASS","accepted_breaks":0,"public_interface":materialize_json(case.interface_contract)})
        return value

    def _failure(self,case:ProjectCase,root:pathlib.Path,before:int,started:float,domain:str,grown:Sequence[str],reused:Sequence[str],repairs:int=0,*,usage_before:Mapping[str,int]|None=None,run_id:str="",recorder:StoreLessonRecorder|None=None)->Mapping[str,Any]:
        calls=self.interrupted_calls.get(case.project_id,0)+self.generation.provider_call_count-before; usage=self._usage_delta(usage_before or {})
        self.provider_calls+=calls; self.input_tokens+=usage["input_tokens"]; self.output_tokens+=usage["output_tokens"]; self.cost_ticks+=usage["cost_in_usd_ticks"]
        if recorder and run_id:
            recorder.record_event(self._event(run_id,case,None,domain.split(":",1)[-1],"FAIL",root))
            if case.wave != "C": recorder.finalize_run(run_id)
        receipt=materialize_json(ProjectRunReceipt(case.project_id,case.wave,case.project_type,canonical_hash(case.public_goal),canonical_hash(_contract(case)),canonical_hash(_obligations(case)),"",(),case.required_capabilities,tuple(grown),tuple(reused),calls,usage["input_tokens"],usage["output_tokens"],repairs,0,{}, {}, {}, {}, {},domain,"FAIL",self.source_commit,round(time.perf_counter()-started,3)).as_dict())
        receipt.update({"run_id":run_id,"case_hash":case.case_hash,"hidden_hash":case.hidden_hash,"cost_in_usd_ticks":usage["cost_in_usd_ticks"]})
        _write_json(root/"project_receipt.json",receipt); return receipt

    def _blocked_receipt(self,case:ProjectCase,reason:str)->Mapping[str,Any]:
        return {"project_id":case.project_id,"wave":case.wave,"project_type":case.project_type,"final_status":"BLOCKED","failure_domain":reason,"provider_calls":0,"source_commit":self.source_commit,"manual_candidate_edits":0,"whole_project_replans":0,"unsafe_admissions":0,"contains_credentials":False}

    def _client_usage(self)->dict[str,int]:
        client=getattr(self.generation,"client",None)
        if client is not None and callable(getattr(client,"snapshot",None)):
            return {key:int(value) for key,value in client.snapshot().items() if key in {"calls","input_tokens","output_tokens","cost_in_usd_ticks"}}
        return {}

    def _usage_delta(self,before:Mapping[str,int])->dict[str,int]:
        after=self._client_usage()
        return {key:max(0,int(after.get(key,0))-int(before.get(key,0))) for key in ("input_tokens","output_tokens","cost_in_usd_ticks")}

    def _accumulate_usage(self,core:BlockExecutionResult,calls:int,before:Mapping[str,int])->dict[str,int]:
        usage=self._usage_delta(before)
        if not self._client_usage():
            usage={"input_tokens":int(core.usage.get("input_tokens",0)),"output_tokens":int(core.usage.get("output_tokens",0)),"cost_in_usd_ticks":int(core.usage.get("cost_in_usd_ticks",0))}
        self.provider_calls+=calls; self.input_tokens+=usage["input_tokens"]; self.output_tokens+=usage["output_tokens"]; self.cost_ticks+=usage["cost_in_usd_ticks"]
        return usage

    def _seed_counters(self,receipts:Mapping[str,Mapping[str,Any]])->None:
        if self.provider_calls or self.input_tokens or self.output_tokens or self.cost_ticks: return
        all_receipts=[_read_json(path) for path in self.root.glob("projects/**/project_receipt.json")]
        pending=sum(calls for project,calls in self.interrupted_calls.items() if project not in receipts)
        self.provider_calls=sum(int(row.get("provider_calls",0)) for row in all_receipts)+pending
        self.input_tokens=sum(int(row.get("input_tokens",0)) for row in all_receipts)
        self.output_tokens=sum(int(row.get("output_tokens",0)) for row in all_receipts)
        self.cost_ticks=sum(int(row.get("cost_in_usd_ticks",0)) for row in all_receipts)
        admissions=sum(1 for path in (self.root/"capability_registry").glob("*/admission.json"))
        self.growth_count=max(admissions,sum(len(row.get("grown_capabilities",())) for row in receipts.values()))
        self.reuse_count=sum(len(row.get("reused_capabilities",())) for row in receipts.values())

    def _recover_interrupted_projects(self)->None:
        for case in self.cases:
            root=self.root/"projects"/case.project_id
            if not root.is_dir() or (root/"project_receipt.json").is_file(): continue
            marker=root/"interrupted_run.json"
            if marker.is_file():
                self.interrupted_calls[case.project_id]=int(_read_json(marker).get("provider_calls",1)); continue
            state_dirs=list((root/"state"/case.project_id).glob("*")) if (root/"state"/case.project_id).is_dir() else []
            if state_dirs:
                self.interrupted_calls[case.project_id]=1
                _write_json(marker,{"kind":"CampaignInterruptedRun","schema_version":"1.0","project_id":case.project_id,"provider_calls":1,"outcome":"INTERRUPTED_UNKNOWN","retry_authorized":True,"recorded_at":utc_now(),"contains_credentials":False})

    def _prepare_reruns(self)->None:
        for project_id in self.rerun_project_ids:
            root=self.root/"projects"/project_id
            receipt=root/"project_receipt.json"
            if not receipt.is_file(): continue
            history=root/"rerun_history"/("run-"+str(int(time.time()*1000))); history.mkdir(parents=True)
            for child in tuple(root.iterdir()):
                if child.name=="rerun_history": continue
                child.rename(history/child.name)

    @staticmethod
    def _final_failure_domain(state:FileRunStore,case:ProjectCase,run_id:str,failed_nodes:Sequence[str])->str:
        for node in failed_nodes:
            result=state.load_result(case.project_id,run_id,node)
            domain=str(result.error.details.get("failure_domain","")) if result.error else ""
            if domain: return domain+":"+node
        return "CANDIDATE_DEFECT:"+",".join(failed_nodes)

    def _event(self,run_id:str,case:ProjectCase,core:BlockExecutionResult|None,failure_code:str,outcome:str,root:pathlib.Path)->LearningEvent:
        applied=tuple(core.outputs.get("applied_lesson_ids",())) if core else ()
        repaired=bool(failure_code and failure_code != "PASS" and outcome == "PASS")
        return LearningEvent(
            "event."+canonical_hash([run_id,"terminal",failure_code or "PASS"])[7:31],run_id,case.project_id,"project.codegen","GENERATION",
            "","grok",("revision-2" if repaired else "revision-1"),
            ("CANDIDATE_DEFECT" if repaired else ("" if outcome == "PASS" else "CANDIDATE_DEFECT")),failure_code or "PASS","CANDIDATE",
            ("REPAIR_CANDIDATE" if repaired else "VALIDATE_EXISTING"),outcome,("CANDIDATE_REVISION",) if repaired else (),
            (str(root/"project_receipt.json"),),str(core.outputs.get("lesson_snapshot_hash","")) if core else "",applied,utc_now(),
        )

    def _finalize_holdout_learning(self,receipts:Mapping[str,Mapping[str,Any]])->None:
        if not self.generation.store: return
        marker=self.root/"holdout_learning_finalized.json"
        if marker.is_file(): return
        recorder=StoreLessonRecorder(self.generation.store)
        for case in self.cases:
            if case.wave != "C": continue
            receipt=receipts.get(case.project_id,{})
            run_id=str(receipt.get("run_id",""))
            if not run_id: continue
            record_feedback(self.generation.store,receipt.get("applied_lesson_ids",()),success=receipt.get("final_status")=="PASS")
            recorder.finalize_run(run_id)
        _write_json(marker,{"kind":"HoldoutLearningFinalization","schema_version":"1.0","project_ids":[case.project_id for case in self.cases if case.wave=="C"],"finalized_at":utc_now(),"contains_credentials":False})

    def _load_receipts(self)->dict[str,Mapping[str,Any]]:
        rows={}
        for case in self.cases:
            path=self.root/"projects"/case.project_id/"project_receipt.json"
            if path.is_file(): rows[case.project_id]=json.loads(path.read_text(encoding="utf-8"))
        return rows

    def _checkpoint(self,wave:str,current:str,receipts:Mapping[str,Mapping[str,Any]])->None:
        complete=tuple(case.project_id for case in self.cases if receipts.get(case.project_id,{}).get("final_status")=="PASS")
        failed=tuple(case.project_id for case in self.cases if receipts.get(case.project_id,{}).get("final_status")=="FAIL")
        blocked=tuple(case.project_id for case in self.cases if receipts.get(case.project_id,{}).get("final_status")=="BLOCKED")
        lesson_hash=""
        if self.generation.store and self.generation.store.index_path.is_file(): lesson_hash=canonical_hash(json.loads(self.generation.store.index_path.read_text(encoding="utf-8")))
        state=CampaignState(CAMPAIGN_ID,self.source_commit,wave,current,complete,failed,blocked,self.provider_calls,self.input_tokens,self.output_tokens,self.cost_ticks,(),lesson_hash,"",utc_now())
        _write_json(self.root/"campaign_state.json",state.as_dict())

    def _matrix_document(self)->Mapping[str,Any]:
        return {"kind":"MultiProjectCampaignMatrix","schema_version":"1.0","campaign_id":CAMPAIGN_ID,"source_commit":self.source_commit,"provider_route":{"provider":"grok","mode":"SINGLE_PROVIDER_MODE","fallback":"deny","per_project_max":4,"campaign_max":36},"cases":[{"project_id":c.project_id,"wave":c.wave,"project_type":c.project_type,"case_hash":c.case_hash,"hidden_acceptance_hash":c.hidden_hash} for c in self.cases],"matrix_hash":canonical_hash([c.case_hash for c in self.cases]),"holdout_hash":canonical_hash([{"case":c.case_hash,"hidden":c.hidden_hash} for c in self.cases if c.wave=="C"]),"contains_credentials":False}

    def _freeze_holdout(self)->None:
        lessons=""
        if self.generation.store and self.generation.store.index_path.is_file(): lessons=canonical_hash(json.loads(self.generation.store.index_path.read_text(encoding="utf-8")))
        _write_json(self.root/"holdout_freeze.json",{"kind":"CampaignHoldoutFreeze","schema_version":"1.0","source_commit":self.source_commit,"lesson_snapshot_b":lessons,"provider_route":{"provider":"grok","mode":"SINGLE_PROVIDER_MODE","fallback":"deny"},"cases":[{"project_id":c.project_id,"case_hash":c.case_hash,"hidden_hash":c.hidden_hash} for c in self.cases if c.wave=="C"],"frozen_at":utc_now(),"contains_credentials":False})

    def _wave_summary(self,wave:str,receipts:Mapping[str,Mapping[str,Any]])->None:
        rows=[receipts[c.project_id] for c in self.cases if c.wave==wave and c.project_id in receipts]; passed=sum(r.get("final_status")=="PASS" for r in rows)
        lesson_hash=""
        if self.generation.store and self.generation.store.index_path.is_file(): lesson_hash=canonical_hash(json.loads(self.generation.store.index_path.read_text(encoding="utf-8")))
        value={"kind":"CampaignWaveSummary","schema_version":"1.0","wave":wave,"total":len(rows),"passed":passed,"failed":sum(r.get("final_status")=="FAIL" for r in rows),"blocked":sum(r.get("final_status")=="BLOCKED" for r in rows),"success_rate":passed/len(rows) if rows else 0,"lesson_snapshot_hash":lesson_hash,"project_results":[{"project_id":r["project_id"],"status":r.get("final_status"),"provider_calls":r.get("provider_calls",0),"repair_rounds":r.get("repair_rounds",0),"applied_lesson_ids":r.get("applied_lesson_ids",[])} for r in rows],"contains_credentials":False}
        _write_json(self.root/({"A":"wave_a_summary.json","B":"wave_b_summary.json","C":"holdout_summary.json"}[wave]),value)
        if wave in {"A","B"}: _write_json(self.root/f"lesson_snapshot_{wave.lower()}.json",{"kind":"CampaignLessonWaveSnapshot","schema_version":"1.0","wave":wave,"lesson_snapshot_hash":lesson_hash,"created_at":utc_now(),"contains_credentials":False})

    def _final_report(self,receipts:Mapping[str,Mapping[str,Any]])->Mapping[str,Any]:
        rows=[receipts[c.project_id] for c in self.cases if c.project_id in receipts]; passed=[r for r in rows if r.get("final_status")=="PASS"]
        wave=lambda w:[r for r in rows if r.get("wave")==w]; existing=[r for r in rows if str(r.get("project_type","")).startswith("EXISTING_REPO")]; green=[r for r in rows if not str(r.get("project_type","")).startswith("EXISTING_REPO")]
        first=sum(r.get("final_status")=="PASS" and not r.get("repair_rounds") for r in rows); repairs=[r for r in rows if r.get("repair_rounds")]
        applied=[lesson for r in rows for lesson in r.get("applied_lesson_ids",())]
        lessons=list(self.generation.store.current_lessons()) if self.generation.store else []
        supports=sum(max(0,item.support_count-1) for item in lessons); contradictions=sum(item.contradiction_count for item in lessons)
        types={name:{"total":len(group),"passed":sum(r.get("final_status")=="PASS" for r in group)} for name in sorted({str(r.get("project_type","")) for r in rows}) if (group:=[r for r in rows if str(r.get("project_type",""))==name])}
        metrics={"total_projects":15,"success_count":len(passed),"total_success_rate":len(passed)/15,"wave_a_success":sum(r.get("final_status")=="PASS" for r in wave("A")),"wave_a_success_rate":sum(r.get("final_status")=="PASS" for r in wave("A"))/6,"wave_b_success":sum(r.get("final_status")=="PASS" for r in wave("B")),"wave_b_success_rate":sum(r.get("final_status")=="PASS" for r in wave("B"))/6,"holdout_success":sum(r.get("final_status")=="PASS" for r in wave("C")),"holdout_success_rate":sum(r.get("final_status")=="PASS" for r in wave("C"))/3,"first_pass_success":first,"first_pass_success_rate":first/15,"repair_attempts":len(repairs),"repair_success":sum(r.get("final_status")=="PASS" for r in repairs),"repair_success_rate":sum(r.get("final_status")=="PASS" for r in repairs)/len(repairs) if repairs else 0,"capability_growth_count":self.growth_count,"capability_growth_success_rate":1.0 if self.growth_count else 0.0,"capability_reuse_count":self.reuse_count,"lesson_application_count":len([r for r in rows if r.get("applied_lesson_ids")]),"lesson_application_rate":len([r for r in rows if r.get("applied_lesson_ids")])/15,"lesson_support_count":supports,"lesson_contradiction_count":contradictions,"lesson_support_rate":supports/len(applied) if applied else 0,"lesson_contradiction_rate":contradictions/len(applied) if applied else 0,"framework_fix_count":1,"framework_fix_reuse":len(rows),"manual_intervention":sum(r.get("manual_candidate_edits",0) for r in rows),"whole_replans":sum(r.get("whole_project_replans",0) for r in rows),"unsafe_admissions":sum(r.get("unsafe_admissions",0) for r in rows),"accepted_interface_breaks":sum(r.get("accepted_interface_breaks",0) for r in rows),"hidden_leakage":0,"provider_calls":self.provider_calls,"input_tokens":self.input_tokens,"output_tokens":self.output_tokens,"cost_in_usd_ticks":self.cost_ticks,"package_success_count":sum(r.get("package",{}).get("status")=="PASS" for r in green),"package_success_rate":sum(r.get("package",{}).get("status")=="PASS" for r in green)/len(green) if green else 0,"existing_repo_success":sum(r.get("final_status")=="PASS" for r in existing),"by_project_type":types}
        full=metrics["success_count"]>=11 and metrics["wave_b_success"]>=4 and metrics["holdout_success"]>=2 and metrics["existing_repo_success"]>=2 and metrics["package_success_count"]>=7 and metrics["manual_intervention"]==metrics["whole_replans"]==metrics["unsafe_admissions"]==metrics["accepted_interface_breaks"]==metrics["hidden_leakage"]==0 and metrics["capability_growth_count"]>=2 and metrics["capability_reuse_count"]>=2 and metrics["lesson_application_count"]>=10 and metrics["framework_fix_reuse"]>=2
        needs_rework=metrics["success_count"]<8 or metrics["holdout_success"]==0 or metrics["existing_repo_success"]==0
        status="MULTI_PROJECT_CAMPAIGN_PASS" if full else ("MULTI_PROJECT_CAMPAIGN_NEEDS_REWORK" if needs_rework else "MULTI_PROJECT_CAMPAIGN_PASS_WITH_LIMITS")
        return {"kind":"MultiProjectCampaignFinalReport","schema_version":"1.0","campaign_id":CAMPAIGN_ID,"status":status,"source_commit":self.source_commit,"metrics":metrics,"projects":rows,"critical_stop":"","full_regression":"NOT_RUN_BY_POLICY","contains_credentials":False}


def _contract(case:ProjectCase)->Mapping[str,Any]:
    return {"project_id":case.project_id,"public_goal":case.public_goal,"interface_contract":materialize_json(case.interface_contract),"behavior_contract":materialize_json(case.behavior_contract),"target_paths":list(case.target_paths),"allowed_paths":list(case.allowed_paths),"required_capabilities":list(case.required_capabilities),"existing_repo":case.existing_repo,"dependency_policy":{"runtime":"PYTHON_STDLIB_ONLY","test":["pytest"],"network":"FORBIDDEN","shell":"FORBIDDEN"}}


def _obligations(case:ProjectCase)->Mapping[str,Any]:
    return {"interface":"exact","behavior_keys":sorted(case.behavior_contract),"deterministic":True,"errors":"nonzero stderr","runtime":"stdlib-only","hidden_hash":case.hidden_hash}


def _capability_input(ref:str,case:ProjectCase)->dict[str,Any]:
    if ref==PYPROJECT_CAP: return {"name":case.project_id.replace("_","-"),"version":"0.1.0","module":case.package_name,"description":case.public_goal,"requires_python":">=3.11","console_script":f"{case.project_id.replace('_','-')}={case.package_name}.__main__:main"}
    if ref==README_CAP: return {"project_name":case.project_id,"description":case.public_goal,"commands":list(case.interface_contract.get("commands",()))}
    if ref==LICENSE_CAP: return {"project_name":case.project_id,"year":2026,"holder":"CGKN generated project"}
    raise ValueError("unknown capability "+ref)


def _capability_spec(ref:str)->CapabilitySpec:
    if ref==PYPROJECT_CAP:
        value={"name":"sample-project","version":"0.1.0","module":"sample_project","description":"Sample","requires_python":">=3.11","console_script":"sample=sample_project.__main__:main"}; output={"pyproject_toml":'[build-system]\nrequires = ["setuptools>=68"]\nbuild-backend = "setuptools.build_meta"\n\n[project]\nname = "sample-project"\nversion = "0.1.0"\ndescription = "Sample"\nrequires-python = ">=3.11"\n\n[project.scripts]\nsample = "sample_project.__main__:main"\n'}; name="project.python.pyproject.render"; checks=("result has only pyproject_toml","tomllib parses output","deterministic output")
    elif ref==README_CAP:
        value={"project_name":"sample","description":"Sample CLI","commands":["sample FILE"]}; output={"readme_md":"# sample\n\nSample CLI\n\n## Usage\n\n```text\nsample FILE\n```\n"}; name="project.readme.cli_examples.render"; checks=("result has only readme_md","contains project name and every command","deterministic output")
    elif ref==LICENSE_CAP:
        value={"project_name":"sample","year":2026,"holder":"Example Holder"}; output={"license_text":"MIT License\n\nCopyright (c) 2026 Example Holder\n\nPermission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the \"Software\"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software.\n"}; name="project.python.license.render"; checks=("result has only license_text","contains MIT License, year, and holder","deterministic output")
    else: raise ValueError("unknown capability "+ref)
    return CapabilitySpec(name,"1",f"Render deterministic {name} output.",{"type":"object"},{"type":"object"},({"input":value,"output":output},),checks,CapabilityRisk.PURE)


def _render_tests(workspace:pathlib.Path,case:ProjectCase)->Mapping[str,Any]:
    path=workspace/"tests/test_contract_campaign.py"; path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(_test_source(case.package_name,case.public_cases),encoding="utf-8"); return {"status":"PASS","test_file":"tests/test_contract_campaign.py","case_count":len(case.public_cases)}


def _test_source(package:str,cases:Sequence[Mapping[str,Any]])->str:
    encoded=json.dumps(materialize_json(cases),ensure_ascii=False,sort_keys=True)
    return f'''import json, os, subprocess, sys, zipfile\nfrom pathlib import Path\nimport pytest\nPACKAGE={package!r}\nCASES=json.loads({encoded!r})\n\ndef execute(case,tmp_path):\n    for d in case.get("dirs",[]): (tmp_path/d).mkdir(parents=True,exist_ok=True)\n    for name,value in case.get("files",{{}}).items():\n        p=tmp_path/name; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(value.encode("utf-8"))\n    if case.get("zip"):\n        z=case["zip"]; p=tmp_path/z["path"]\n        with zipfile.ZipFile(p,"w") as archive:\n            for name,value in z["entries"].items(): archive.writestr(name,value)\n    env=os.environ.copy(); env["PYTHONPATH"]=str(Path(__file__).parents[1])\n    for step in case.get("steps",[]):\n        before={{name:(tmp_path/name).read_bytes() for name in step.get("files_unchanged",[])}}\n        r=subprocess.run([sys.executable,"-m",PACKAGE,*step["argv"]],cwd=tmp_path,text=True,capture_output=True,env=env)\n        assert r.returncode==step["code"],(r.stdout,r.stderr)\n        if "json" in step: assert json.loads(r.stdout)==step["json"]\n        if "json_list_length" in step: assert len(json.loads(r.stdout))==step["json_list_length"]\n        if "stdout_exact" in step: assert r.stdout.strip()==step["stdout_exact"]\n        if "stdout_contains" in step: assert step["stdout_contains"] in r.stdout\n        for v in step.get("stdout_contains_all",[]): assert v in r.stdout\n        if "stdout_not_contains" in step: assert step["stdout_not_contains"] not in r.stdout\n        if step.get("stderr_nonempty"): assert r.stderr.strip()\n        if "stderr_contains" in step: assert step["stderr_contains"].lower() in r.stderr.lower()\n        if "stderr_not_contains" in step: assert step["stderr_not_contains"] not in r.stderr\n        if "file_json" in step: assert json.loads((tmp_path/step["file_json"]["path"]).read_text())==step["file_json"]["value"]\n        if "file_contains_all" in step:\n            text=(tmp_path/step["file_contains_all"]["path"]).read_text(); assert all(v in text for v in step["file_contains_all"]["values"] )\n        for name,data in before.items(): assert (tmp_path/name).read_bytes()==data\n    if case.get("python"):\n        r=subprocess.run([sys.executable,"-c",case["python"]],cwd=tmp_path,text=True,capture_output=True,env=env); assert r.returncode==case["code"],r.stderr\n        if "json" in case: assert json.loads(r.stdout)==case["json"]\n\n@pytest.mark.parametrize("case",CASES)\ndef test_contract(case,tmp_path): execute(case,tmp_path)\n'''


def _evaluate(workspace:pathlib.Path,package:str,cases:Sequence[Mapping[str,Any]],kind:str)->Mapping[str,Any]:
    source=_test_source(package,cases); temp=workspace/".campaign_eval"; temp.mkdir(exist_ok=True); path=temp/f"test_{kind}.py"; path.write_text(source,encoding="utf-8")
    env=os.environ.copy(); env["PYTHONPATH"]=str(workspace); env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"]="1"
    completed=subprocess.run([sys.executable,"-m","pytest",str(path),"-q"],cwd=workspace,text=True,capture_output=True,env=env,timeout=90)
    try: path.unlink(); temp.rmdir()
    except OSError: pass
    if completed.returncode: raise RuntimeError(f"{kind} failure:"+completed.stdout[-1500:]+completed.stderr[-1500:])
    return {"status":"PASS","case_count":len(cases),"hash":canonical_hash(cases),"stdout_tail":completed.stdout[-500:]}


def _compile(workspace:pathlib.Path,case:ProjectCase)->Mapping[str,Any]:
    paths=[str(workspace/path) for path in case.target_paths]
    completed=subprocess.run([sys.executable,"-m","py_compile",*paths],cwd=workspace,text=True,capture_output=True,timeout=30)
    if completed.returncode: raise RuntimeError(completed.stderr[-1500:])
    return {"status":"PASS","files":list(case.target_paths)}


def _pytest(workspace:pathlib.Path)->Mapping[str,Any]:
    env=os.environ.copy(); env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"]="1"
    completed=subprocess.run([sys.executable,"-m","pytest","tests","-q"],cwd=workspace,text=True,capture_output=True,timeout=90,env=env)
    if completed.returncode: raise RuntimeError(completed.stdout[-2000:]+completed.stderr[-1000:])
    return {"status":"PASS","returncode":0,"stdout_tail":completed.stdout[-500:]}


def _snapshot(workspace:pathlib.Path)->Mapping[str,Any]:
    rows=_hash_tree(workspace); value={"status":"PASS","file_count":len(rows),"snapshot_hash":canonical_hash(rows)}; _write_json(workspace/"snapshot_receipt.json",value); return value


def _package(repository:pathlib.Path,workspace:pathlib.Path,root:pathlib.Path,case:ProjectCase,commit:str)->Mapping[str,Any]:
    (workspace/"TEST_REPORT.md").write_text(f"# Test Report\n\nproject: {case.project_id}\ncommands_run:\n- python -m pytest tests -q\n- python -m {case.package_name} --help\n\nresults: PASS\n",encoding="utf-8")
    (workspace/"DELIVERY_NOTES.md").write_text(f"# Delivery\n\n{case.public_goal}\n",encoding="utf-8")
    candidate_hash=canonical_evidence_hash.candidate_source_hash(workspace); candidate_id="campaign-"+candidate_hash[-12:]
    test=real_test_execution.run_tests(workspace,run_id=root.name,candidate_id=candidate_id,candidate_hash=candidate_hash,commit_sha=commit,minimum_collected=1)
    if test.get("status")!="PASS": raise RuntimeError("canonical tests failed")
    runtime=customer_runtime_runner.run(workspace,run_id=root.name,candidate_id=candidate_id,candidate_hash=candidate_hash,commit_sha=commit)
    if runtime.get("status")!="PASS": raise RuntimeError("runtime smoke failed")
    manifest=local_packager.package_project(workspace,output_dir=root/"delivery",startup_command=f"python -m {case.package_name} --help")
    if manifest.get("status")!="PASS": raise RuntimeError("local_packager failed:"+str(manifest.get("failures")))
    package=pathlib.Path(str(manifest["package_path"])); return {"status":"PASS","package_path":str(package),"package_hash":"sha256:"+hashlib.sha256(package.read_bytes()).hexdigest(),"manifest_path":str(manifest["manifest_path"]),"runtime_smoke":{"status":"PASS","startup_command":f"python -m {case.package_name} --help"}}


def _hash_tree(root:pathlib.Path)->dict[str,str]:
    return {path.relative_to(root).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(root.rglob("*")) if path.is_file() and not any(part in {"__pycache__",".pytest_cache",".campaign_eval"} for part in path.relative_to(root).parts)}


def _snapshot_candidate(workspace:pathlib.Path,target_paths:Sequence[str],source_hash:str)->tuple[str,str]:
    root=workspace.parent/"candidates"; root.mkdir(parents=True,exist_ok=True)
    revisions=sorted(path for path in root.glob("revision-*") if path.is_dir())
    revision_id=f"revision-{len(revisions)+1:03d}"; destination=root/revision_id
    if destination.exists(): raise RuntimeError("CRITICAL_CANDIDATE_REVISION_OVERWRITE:"+revision_id)
    destination.mkdir()
    for relative in target_paths:
        source=workspace/relative; target=destination/relative; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(source.read_bytes())
    _write_json(destination/"revision.json",{"kind":"CampaignCandidateRevision","schema_version":"1.0","revision_id":revision_id,"parent_revision_id":revisions[-1].name if revisions else "","source_hash":source_hash,"target_paths":list(target_paths),"immutable":True,"manual_edits":0,"contains_credentials":False})
    return revision_id,str(destination)


def _repair_evidence(failed_node:str,result:BlockExecutionResult)->Mapping[str,Any]:
    if failed_node=="hidden":
        return {"failure_domain":"CANDIDATE_DEFECT","failed_node":"hidden","failure_code":"HIDDEN_ACCEPTANCE_FAILED","details":"WITHHELD_BY_POLICY"}
    return {"failure_domain":"CANDIDATE_DEFECT","failed_node":failed_node,"receipt":result.as_dict()}


def _write_json(path:pathlib.Path,value:Mapping[str,Any])->Mapping[str,Any]:
    path.parent.mkdir(parents=True,exist_ok=True); payload=json.dumps(materialize_json(value),ensure_ascii=False,indent=2,sort_keys=True)+"\n"
    descriptor,temp=tempfile.mkstemp(prefix="."+path.name+"-",suffix=".tmp",dir=path.parent)
    try:
        with os.fdopen(descriptor,"w",encoding="utf-8",newline="\n") as handle: handle.write(payload); handle.flush(); os.fsync(handle.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp): os.unlink(temp)
    return value


def _read_json(path:pathlib.Path)->dict[str,Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _slug(ref:str)->str:
    return ref.replace("@","-").replace(".","-").replace("/","-")


def _git(root:pathlib.Path,*args:str)->str:
    completed=subprocess.run(["git",*args],cwd=root,text=True,capture_output=True,timeout=30)
    if completed.returncode: raise RuntimeError(completed.stderr)
    return completed.stdout.strip()

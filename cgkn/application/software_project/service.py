from __future__ import annotations

from cgkn.telemetry.lean import observed

import ast
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Any, Mapping, Callable

from cgkn.agent import ProjectSession
from cgkn.agent.composer import AgentComposer, AgentDecision, AgentDecisionContext
from cgkn.executors import CommandExecutor, ExecutorRegistry, FileExecutor, PythonTestExecutor
from cgkn.providers import (
    CGKNModelRouting,
    CompletionClient,
    GatewayCompletionClient,
    ModelRoleConfig,
    completion_client_from_environment,
)
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore

from .acceptance import ExternalAcceptanceExecutor
from .bundle import SoftwareProjectBundle
from .catalog import ProjectCase, get_case
from .contracts import ProjectResultStatus, canonical_hash
from .receipt import ProjectGenerationReceipt
from .scope import ScopedProjectLLMExecutor
from .snapshot import ProjectSnapshotExecutor, snapshot_project


class SoftwareProjectAgentComposer(AgentComposer):
    """Case-specific prompt/normalization adapter to the canonical composer."""

    decision_schema_name = 'cgkn_software_project_agent_decision'
    additional_instructions = (
        "You are the CGKN high-capability software-project composition Agent. Return only one JSON AgentDecision with validated TreeEdits. "
        "You decide the project file structure and dependencies, but never output source file content, execute commands, or claim tests passed. "
        "For a new project, create one workspace.inspect node, one project.file.generate node per principal source or documentation file, a project.tests.generate node for each public test file, then compile, pytest, runtime smoke, snapshot, and external acceptance nodes. "
        "Generation or patch node config must contain executor_ref='llm.cheap@1', goal, target_paths (one path, or two tightly bound tiny files), allowed_paths (target paths plus only explicit relevant read paths), file_purpose, interfaces, acceptance, allowed_effects=['filesystem.write'], max_actions<=4, max_write_files<=2, max_total_output_bytes<=64000, allow_create, allow_patch, allow_delete=false, protected_paths. "
        "Inspect uses local.file@1 action=list_files path='.'. Compile uses local.command@1 with argv command. Pytest uses local.python-test@1 and pytest_args. Smoke uses local.command@1. Snapshot uses project.snapshot@1. Acceptance uses project.acceptance@1 and only the public case_id. "
        "Dependencies must ensure every source is generated before tests, all file nodes before compile, compile before pytest and smoke, those before snapshot, and snapshot before acceptance. "
        "On a failed run, add or update only the smallest patch node and retry the failed node/subgraph. Finish only after the external acceptance node succeeded. "
        "Diagnose from the first concrete traceback location. A NameError, missing import, syntax error, or fixture defect located in a generated public test file must repair the corresponding project.tests.generate node, never application source. Only patch application source when a valid public test demonstrates application behavior contradicting the public contract. "
        "update_config payload is exactly {config: object}; it cannot contain capability_ref. If you update a node that already succeeded, also emit exactly one retry_node edit for the earliest changed node so the canonical DAG invalidates its downstream closure. Do not update downstream nodes when their config is unchanged. "
        "Allowed operations are canonical TreeEdits only; use exact capability_ref and executor_ref names from the catalog. Never mention or request hidden test paths or values."
    )

    def decide(self, context: AgentDecisionContext) -> AgentDecision:
        decision = super().decide(context)
        worker_edits = [item for item in decision.edits if item.operation == "add_node" and item.payload.get("capability_ref") in {"project.file.generate@1", "project.file.patch@1", "project.tests.generate@1"}]
        if len(worker_edits) > 20:
            raise ValueError("Agent exceeded worker-call budget")
        for edit in worker_edits:
            config = dict(edit.payload.get("config", {}))
            if not config.get("target_paths") or config.get("allow_delete") is not False:
                raise ValueError("Agent worker node omitted mandatory scope")
        return decision

    @staticmethod
    def _normalize_decision(value: Mapping[str, Any], context: AgentDecisionContext) -> dict[str, Any]:
        """Project-adapter normalization for common Provider placement errors."""
        result = dict(value)
        edits: list[dict[str, Any]] = []
        protected = [".git", ".github", ".cgkn", "benchmarks", "artifacts", "governance", "cgkn"]
        dependency_aliases: dict[str, list[str]] = {}
        for item in value.get("edits", []):
            if isinstance(item, Mapping) and item.get("operation") == "add_dependency" and isinstance(item.get("payload"), Mapping) and isinstance(item["payload"].get("depends_on"), list):
                dependency_aliases.setdefault(str(item.get("node_id", "")), []).extend(str(dep) for dep in item["payload"]["depends_on"])
        retry_candidate = ""
        for raw_edit in value.get("edits", []):
            edit = dict(raw_edit)
            payload = dict(edit.get("payload", {}))
            if edit.get("operation") == "add_dependency" and isinstance(payload.get("depends_on"), list):
                continue
            if edit.get("operation") == "add_node":
                config = dict(payload.get("config", {}))
                if payload.get("executor_ref") and not config.get("executor_ref"):
                    config["executor_ref"] = payload["executor_ref"]
                capability_ref = str(payload.get("capability_ref", ""))
                catalog_row = context.capability_catalog.get(capability_ref, {}) if isinstance(context.capability_catalog, Mapping) else {}
                if not config.get("executor_ref") and isinstance(catalog_row, Mapping) and catalog_row.get("executor_ref"):
                    config["executor_ref"] = str(catalog_row["executor_ref"])
                if isinstance(config.get("acceptance"), str):
                    config["acceptance"] = [config["acceptance"]]
                if config.get("protected_paths") == []:
                    config["protected_paths"] = protected
                if capability_ref in {"project.file.generate@1", "project.tests.generate@1"}:
                    config["allow_patch"] = True
                if capability_ref == "project.tests.generate@1":
                    config["goal"] = str(config.get("goal", "")) + " Test only the declared public contract. Fixtures must be structurally valid unless a test explicitly expects an input error; never assert successful behavior from malformed fixtures or invent alternate CLI flags. Subprocess tests must run from the project root or set an explicit project-root PYTHONPATH."
                dependencies = list(payload.get("depends_on", [])) + dependency_aliases.get(str(edit.get("node_id", "")), [])
                from .qualification import new_contract
                if 'leaf_contract' not in config:
                    config['leaf_contract'] = new_contract(str(edit['node_id']), config, list(dict.fromkeys(dependencies)))
                payload = {"capability_ref": payload.get("capability_ref", ""), "parent_id": payload.get("parent_id", ""), "depends_on": list(dict.fromkeys(dependencies)), "config": config}
            elif edit.get("operation") == "update_config":
                config = dict(payload.get("config", {}))
                if isinstance(config.get("acceptance"), str):
                    config["acceptance"] = [config["acceptance"]]
                if config.get("target_paths") and config.get("protected_paths") == []:
                    config["protected_paths"] = protected
                payload = {"config": config}
                existing = context.tree.by_id.get(str(edit.get("node_id", "")))
                effective_executor = config.get("executor_ref") or (existing.config.get("executor_ref") if existing else "")
                if existing and 'leaf_contract' not in config:
                    from .qualification import new_contract
                    effective = {**dict(existing.config), **config}
                    config['leaf_contract'] = new_contract(existing.id, effective, existing.depends_on)
                if effective_executor == "llm.cheap@1" and not retry_candidate:
                    config["allow_patch"] = True
                    retry_candidate = str(edit.get("node_id", ""))
            edit["payload"] = payload
            edits.append(edit)
        if result.get("request_run") and retry_candidate:
            edits = [item for item in edits if item.get("operation") != "retry_node"]
            edits.append({"edit_id": f"normalized-retry-{retry_candidate}", "operation": "retry_node", "node_id": retry_candidate, "payload": {}, "provenance": {"adapter": "software_project", "reason": "updated completed worker node requires affected-subgraph retry"}})
        result["edits"] = edits
        return result


@dataclass(frozen=True)
class GenerationRunResult:
    case_id: str
    run_id: str
    run_dir: pathlib.Path
    workspace: pathlib.Path
    status: ProjectResultStatus
    receipt: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"case_id": self.case_id, "run_id": self.run_id, "run_dir": str(self.run_dir), "workspace": str(self.workspace), "status": self.status.value, "receipt": dict(self.receipt)}


class SoftwareProjectGenerationService:
    def __init__(
        self,
        repository_root: pathlib.Path | str,
        artifact_root: pathlib.Path | str,
        *,
        client: CompletionClient | None = None,
        config: Mapping[str, Any] | None = None,
        routing: CGKNModelRouting | None = None,
    ):
        self.repository_root = pathlib.Path(repository_root).resolve()
        self.artifact_root = pathlib.Path(artifact_root).resolve()
        self.client = client or completion_client_from_environment()
        self.config = dict(config or {})
        default_routing = self.repository_root / "config" / "provider_profiles" / "gateway_model_routing.json"
        from cgkn.providers.application_network import routing_path
        default_routing = routing_path(default_routing)
        self.routing = routing or (CGKNModelRouting.load(default_routing) if isinstance(self.client, GatewayCompletionClient) else None)
        self.bundle = SoftwareProjectBundle.build()
        self.acceptance_root = self.repository_root / "benchmarks" / "real_project_generation" / "acceptance"

    def run_project(self, *, project_id, run_id, workspace, intent, registry,
                    acceptance, capability_catalog, deliverable_checkers,
                    max_parallel=1, checkpoint_interval=4, continuation_feedback=None,execution_authorization=None):
        """Assemble the existing production authorities for a generic goal.

        Application adapters supply registered independent checkers and public
        requirements. They cannot inject a planner or another project loop.
        This returns core acceptance only; public delivery still requires the
        existing post-build/packager/public-delivery gate.
        """
        from cgkn.executors import LLMExecutor
        from cgkn.providers.recording import RecordedCompletionClient
        from cgkn.component.spec import _thaw
        root=pathlib.Path(workspace).resolve()
        if not root.is_dir(): raise ValueError('project workspace must already exist')
        store=acceptance.store
        policy,planning=self._execution_authorities(project_id,run_id,store,execution_authorization)
        if (acceptance.project_id,acceptance.run_id)!=(project_id,run_id) or store.root.resolve()!=self.artifact_root:
            raise ValueError('project/acceptance/run-store authority mismatch')
        if any(e.descriptor.executor_ref=='llm.cheap@1' for e in registry.list()):
            raise ValueError('application adapter cannot replace the canonical bounded Worker')
        if any(not v.get('semantic_task_kinds') for v in capability_catalog.values()):
            raise ValueError('production capabilities require semantic task kinds')
        config=self._resolved_config()
        planner=self._role('agent',config['high_capability_agent'])
        worker=self._role('worker',config['cheap_worker'])
        client=self.client.bind_run(run_id,project_id) if isinstance(self.client,GatewayCompletionClient) else self.client
        client=RecordedCompletionClient(client,store,project_id,run_id)
        run_root=store.run_dir(project_id,run_id)
        def trace(event):
            store.immutable_json(run_root/'protocol'/('event-'+uuid.uuid4().hex+'.json'),_thaw(event))
        execution_registry=ExecutorRegistry()
        for executor in registry.list(): execution_registry.register(executor)
        execution_registry.register(LLMExecutor(root,client,worker,max_rounds=4,semantic_protocol=True,protocol_trace=trace,
            patch_policy=(continuation_feedback or {}).get("bounded_patch_policy")))
        from cgkn.execution.deliverables import FileDeliverableChecker
        observer=FileDeliverableChecker(root,{})
        session=ProjectSession(AgentComposer(client,planner,planner_mode='MILESTONE_MODE',protocol_trace=trace),
            DAGRunner(execution_registry,store,max_parallel=max_parallel,deliverable_checkers=deliverable_checkers),
            store,known_capabilities=set(capability_catalog),worker_model=worker.model,
            capability_catalog=capability_catalog,acceptance=acceptance,
            continuous=True,max_decisions=checkpoint_interval,
            admission_policy=policy,
            subject_snapshot=lambda paths:observer.snapshot({'target_scope':paths}))
        # Serialize only competing planners for this exact project run. The
        # DAG coordinator has its own lock and independent ready nodes retain
        # their normal parallel execution inside this session.
        with store.exclusive_file(run_root/'project_session.lock'):
            if (continuation_feedback or {}).get('route_change') and session._unresolved_execution_nodes(project_id,run_id):
                raise ValueError('reconcile unknown execution effects before changing route')
            self._bind_routing(store,project_id,run_id,(continuation_feedback or {}).get('route_change'))
            return session.run(project_id=project_id,run_id=run_id,goal=intent['overall_goal'],project_intent=intent,
                               planning=planning,
                               continuation_feedback=continuation_feedback,
                               resume=(run_root/'agent_checkpoint.json').exists())

    def _execution_authorities(self,project_id,run_id,store,authorization=None):
        """Assemble existing owners from explicit, immutable run authorization."""
        from cgkn.agent.planning_scope import assemble_execution_authorities
        raw=authorization if authorization is not None else self.config.get('execution_authorization')
        return assemble_execution_authorities(project_id,run_id,store,raw)

    def _bind_routing(self, store, project_id, run_id, decision=None):
        """Append an explicit controller route decision; retain the initial snapshot."""
        if not self.routing:
            if decision: raise ValueError('route decision requires explicit routing config')
            return
        from cgkn.state import EventRecord
        from cgkn.state.provenance import ProvenanceGate
        root=store.run_dir(project_id,run_id)
        original=root/'model_routing_snapshot.json'
        if not original.exists():
            if decision: raise ValueError('route change requires an existing route')
            self.routing.snapshot(run_id).write_once(original)
            return
        current=json.loads(original.read_text(encoding='utf-8'))['routing_config_hash']
        changes=[e for e in store.load_events(project_id,run_id) if e.event_type=='MODEL_ROUTE_CHANGED'] if (root/'events.jsonl').exists() else []
        for event in changes:
            row=event.data
            if row['from_config_hash']!=current: raise ValueError('broken route decision lineage')
            snapshot=ProvenanceGate(store,project_id,run_id).resolve(row['snapshot_ref'])
            if json.loads(snapshot)['routing_config_hash']!=row['to_config_hash']:
                raise ValueError('route snapshot mismatch')
            current=row['to_config_hash']
        target=self.routing.config_hash
        if current==target:
            if decision and not any(e.data.get('decision')==decision for e in changes):
                raise ValueError('route decision does not describe a new route')
            return
        required={'decision_id','from_config_hash','to_config_hash','reason_summary','evidence_refs'}
        if (not isinstance(decision,dict) or set(decision)!=required
                or not re.fullmatch('[0-9a-f]{64}',str(decision.get('decision_id','')))
                or decision['from_config_hash']!=current or decision['to_config_hash']!=target
                or not isinstance(decision['reason_summary'],str) or not decision['reason_summary'].strip()
                or not isinstance(decision['evidence_refs'],list) or not decision['evidence_refs']):
            raise ValueError('route change requires an explicit recorded decision with current hashes and evidence')
        if any(e.data['decision']['decision_id']==decision['decision_id'] for e in changes):
            raise ValueError('route decision identity already consumed')
        gate=ProvenanceGate(store,project_id,run_id)
        for ref in decision['evidence_refs']: gate.resolve(ref)
        path=root/'routing_snapshots'/(decision['decision_id']+'.json')
        if not path.exists():self.routing.snapshot(run_id).write_once(path)
        saved=json.loads(path.read_text(encoding='utf-8'))
        if saved['routing_config_hash']!=target or saved['run_id']!=run_id:
            raise ValueError('conflicting retained routing snapshot')
        ref={'path':str(path.relative_to(store.root)).replace('\\','/'),
             'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        store.append_event(EventRecord('route.'+decision['decision_id'],project_id,run_id,
            'MODEL_ROUTE_CHANGED',data={'decision':decision,'from_config_hash':current,
                'to_config_hash':target,'snapshot_ref':ref,'automatic_fallback':False,
                'actual_model_authority':'Per-call provider response; snapshot does not assert actual identity'}))

    def run_profile(self, profile_path, *, goal, on_started=None, continuation_feedback=None):
        """Deserialize a controller-owned profile into the same core assembly.

        The profile supplies public intent/requirements and a frozen external
        consumer, never executable model-authored checker configuration.
        Delivery is deliberately not inferred from this core result.
        """
        from cgkn.execution.deliverables import FileDeliverableChecker,SubjectDeliverableChecker
        from cgkn.state.acceptance import GoalAcceptance,identity
        from .qualification import source_delivery
        path=pathlib.Path(profile_path).resolve()
        profile=json.loads(path.read_text(encoding='utf-8'))
        required={'kind','schema_version','project_id','run_id','workspace','intent','requirements','independent_consumer'}
        if (not isinstance(profile,dict) or not required<=profile.keys()
                or set(profile)-required-{'max_parallelism','checkpoint_interval','execution_authorization'}
                or profile['kind']!='CGKNProjectSessionProfile' or profile['schema_version']!='1.0'):
            raise ValueError('invalid canonical project profile')
        workspace=pathlib.Path(profile['workspace']).resolve()
        if path.is_relative_to(workspace) or self.artifact_root.is_relative_to(workspace):
            raise ValueError('profile and evidence store must be outside candidate workspace')
        if profile['intent']['overall_goal']!=goal:
            raise ValueError('profile goal does not match the user goal')
        store=FileRunStore(self.artifact_root)
        project_id,run_id=profile['project_id'],profile['run_id']
        run_root=store.run_dir(project_id,run_id)
        store.immutable_json(run_root/'project_profile.json',profile)
        workspace.mkdir(parents=True,exist_ok=True)
        acceptance=GoalAcceptance(store,project_id,run_id,profile['requirements'],
                                  {'independent':'project.acceptance@1'})
        from cgkn.state.checker_revision import bind_checker_revision
        qualified_revision=bind_checker_revision(store,project_id,run_id,'independent',
            profile['independent_consumer'],(continuation_feedback or {}).get('evaluator_revision'))
        registry=ExecutorRegistry()
        registry.register(ExternalAcceptanceExecutor(workspace,pathlib.Path(profile['independent_consumer']['path']).parent,
            session_acceptance=acceptance,consumer=profile['independent_consumer'],qualified_revision=qualified_revision))
        from cgkn.state.provenance import put_evidence
        input_ref=put_evidence(store,project_id,run_id,{'kind':'PublicInput',
            'intent':profile['intent'],'requirements':profile['requirements']})
        environment_ref=put_evidence(store,project_id,run_id,{'kind':'ToolEnvironment',
            'python_version':sys.version,'python_executable':sys.executable,
            'python_sha256':hashlib.sha256(pathlib.Path(sys.executable).read_bytes()).hexdigest(),
            'consumer_protocol':'IndependentMilestoneRequest/1'})
        store.immutable_json(run_root/'provenance_contract.json',{'kind':'ProvenanceContract',
            'logical_task_id':project_id+'/'+run_id,'requirements':profile['requirements'],
            'input_ref':input_ref,'environment_ref':environment_ref,'goals':{},
            'workspace_root':str(workspace),'incremental_checker_bindings':{
                'independent':{'checker_ref':'project.acceptance@1',
                    'checker_hash':profile['independent_consumer']['sha256'],'checker_version':'1',
                    'predicate':{'operator':'equal','expected':True}}}})
        file_checker=FileDeliverableChecker(workspace,{'source':source_delivery})
        registry.register(file_checker)
        def measurement(request,contract):
            output=request.as_dict()['input_values']['execution_receipt']['outputs']
            measured=output.get('goal_check',{})
            goal_row=next((g for g in acceptance.view()['goals'] if g['id']==measured.get('goal_id')),None)
            valid=bool(goal_row and measured.get('execution')=='VALID' and measured.get('evidence_refs')
                and measured.get('condition_hash')==identity(goal_row['acceptance'])
                and measured.get('subjects')=={p:acceptance.view()['subject_identities'].get(p) for p in goal_row['subject_refs']})
            return {'passed':valid,'observed':measured or {'status':output.get('status','UNKNOWN')},
                    'evidence_refs':[dict(request.input_values['execution_receipt_ref'])]}
        registry.register(SubjectDeliverableChecker(file_checker.snapshot,{'measurement':measurement}))
        catalog={
            'code.implement@1':{'executor_ref':'llm.cheap@1','semantic_task_kinds':[2,3,6],
                'checker_ref':'source','acceptance':['source'],'effect_domains':['filesystem','external_network'],
                'description':'Bounded implementation, repair or integration of current public contract'},
            'project.acceptance.external@1':{'executor_ref':'project.acceptance@1','semantic_task_kinds':[4],
                'checker_ref':'independent-measurement','acceptance':['measurement'],'effect_domains':['local_process'],
                'description':'Frozen independent consumer measures current compiled milestone objects'},
        }
        if on_started: on_started({'run_id':run_id,'run_dir':str(run_root),'project_dir':str(workspace)})
        result=self.run_project(project_id=project_id,run_id=run_id,workspace=workspace,intent=profile['intent'],
            registry=registry,acceptance=acceptance,capability_catalog=catalog,
            deliverable_checkers={'source':'deliverable.files@1','independent-measurement':'deliverable.subjects@1'},
            max_parallel=int(profile.get('max_parallelism',1)),checkpoint_interval=int(profile.get('checkpoint_interval',4)),
            continuation_feedback=continuation_feedback,execution_authorization=profile.get('execution_authorization'))
        document={'kind':'CGKNProjectSessionCoreResult','status':result.status,
            'target_goal_satisfied':acceptance.view()['complete'],
            'delivery_status':'NOT_EVALUATED','run_id':run_id,'run_dir':str(run_root),'project_dir':str(workspace),
            'goal_acceptance':acceptance.view(),'result':result.as_dict(),
            'provider_usage':self._provider_usage(run_root),'public_delivery_allowed':False}
        store.immutable_json(run_root/'core_results'/(identity(document)+'.json'),document)
        if result.status=='BLOCKED' and result.escalation_reason.startswith('BUDGET_BLOCKED:'):
            from scripts.provider_api_budget import ProviderBudgetExhausted
            raise ProviderBudgetExhausted('PROVIDER_BUDGET_EXHAUSTED: '+result.escalation_reason)
        # Fake/local qualification remains core-only. Recorded live responses
        # still must independently qualify their source and identity chain.
        requests = list((run_root/'provider_calls').glob('*/request.json'))
        live = bool(requests) and all(json.loads(p.read_text(encoding='utf-8')).get(
            'transport_kind') == 'recorded_gateway' for p in requests)
        if result.status == 'GOALS_VERIFIED' and live:
            return self.finalize_core(profile, document)
        return document

    def finalize_core(self, profile, core_result, *, cli_probe=None, verification_revision=None):
        """Adapt canonical state to the existing post-build/packager/gate route."""
        from cgkn.state.acceptance import identity
        store=FileRunStore(self.artifact_root)
        root=store.run_dir(profile['project_id'],profile['run_id'])
        with store.exclusive_file(root/'project_session.lock'):
            if (cli_probe is None) != (verification_revision is None):
                raise ValueError('revised runtime probe requires an explicit verification revision')
            if cli_probe is not None:
                from scripts import customer_runtime_runner
                customer_runtime_runner.validate_cli_probe(cli_probe,pathlib.Path(profile['workspace']))
                original=root/'delivery_attempts'/identity(core_result)/'result.json'
                if not original.is_file() or json.loads(original.read_text(encoding='utf8')).get('delivery_status')!='BLOCKED':
                    raise ValueError('only a settled blocked delivery may be explicitly reverified')
            attempt_key=core_result if verification_revision is None else {
                'core_result':core_result,'cli_probe':cli_probe,'verification_revision':verification_revision}
            attempt=root/'delivery_attempts'/identity(attempt_key)
            completed=attempt/'result.json'
            if completed.exists():
                result=json.loads(completed.read_text(encoding='utf-8'))
                # Reuse is read-only and must not preserve stale delivery PASS.
                if result.get('public_delivery_allowed'):
                    from scripts import production_candidate_provenance, codex_conversation
                    check=codex_conversation.evaluate_public_delivery_gate(
                        pathlib.Path(profile['workspace']),result['finalization']['manifest'],
                        {'goal':profile['intent']['overall_goal'],
                         'requirement':'\n'.join([profile['intent']['overall_goal'],
                             *profile['intent']['delivery_expectations']])},
                        provider_result=core_result,
                        production_provenance_ref=root/production_candidate_provenance.FILE_NAME,
                        allow_provider_review=False)
                    if not check.get('delivery_allowed'):
                        return {**result,'delivery_status':'BLOCKED','public_delivery_allowed':False,
                                'delivery_recheck':check}
                return result
            if (attempt/'started.json').exists():
                raise RuntimeError('delivery outcome unresolved; reconcile before replay')
            store.immutable_json(attempt/'started.json',{'core_result_hash':identity(core_result),
                'started_at':time.time(),'operation':'existing_post_build_finalization',
                'cli_probe':cli_probe,'verification_revision':verification_revision})
            try:
                if verification_revision is not None:
                    import shutil
                    archived={}
                    sources=[('candidate',p,pathlib.Path(profile['workspace'])) for p in pathlib.Path(profile['workspace']).rglob('*') if p.is_file()]
                    # Active OS lock handles are coordination, not evidence.
                    sources += [('run',p,root) for p in root.iterdir() if p.is_file() and p.suffix!='.lock']
                    for category,source,base in sources:
                        target=attempt/'prior_evidence'/category/source.relative_to(base)
                        target.parent.mkdir(parents=True,exist_ok=True)
                        shutil.copyfile(source,target)
                        archived[str(target.relative_to(attempt))]=hashlib.sha256(target.read_bytes()).hexdigest()
                    store.immutable_json(attempt/'prior_evidence_manifest.json',archived)
                options={} if verification_revision is None else {'cli_probe':cli_probe,'verification_revision':verification_revision}
                result=self._finalize_core_locked(profile,core_result,**options)
            except Exception as exc:
                store.immutable_json(attempt/'error.json',{'classification':'HARNESS_ERROR',
                    'error_type':type(exc).__name__,'message':str(exc),'outcome_unknown':True})
                raise
            store.immutable_json(completed,result)
            return result

    def _finalize_core_locked(self, profile, core_result, *, cli_probe=None, verification_revision=None):
        from cgkn.state.acceptance import identity
        from scripts import production_candidate_provenance, codex_conversation
        store=FileRunStore(self.artifact_root)
        project_id,run_id=profile['project_id'],profile['run_id']
        run_root=store.run_dir(project_id,run_id)
        workspace=pathlib.Path(profile['workspace']).resolve()
        provenance=production_candidate_provenance.produce_project_session(
            store,project_id,run_id,candidate_dir=workspace,
            commit_sha=self._git_identity()['source_commit'])
        if provenance['status']!='PASS':
            result={**core_result,'delivery_status':'BLOCKED',
                'delivery_failures':provenance['failures'],'public_delivery_allowed':False}
        else:
            session={'goal':profile['intent']['overall_goal'],
                     'requirement':'\n'.join([profile['intent']['overall_goal'],
                         *profile['intent']['delivery_expectations']])}
            core_ref=run_root/'core_results'/(identity(core_result)+'.json')
            store.immutable_json(core_ref,core_result)
            finalized=codex_conversation.post_build_finalize_provider_project(
                workspace,{**core_result,'goal':profile['intent']['overall_goal']},{},session,
                session_dir=run_root/'delivery_events',conversation_id=run_id,
                production_identity={k:provenance[k] for k in ('run_id','candidate_id','candidate_hash','commit_sha')},
                production_run_dir=run_root,stage_receipts={},provider_result_path=core_ref,
                provider_causal_capture={},core_provenance_ref=pathlib.Path(provenance['provenance_ref']),
                cli_probe=cli_probe,verification_revision=verification_revision)
            result=self._delivery_projection(core_result,finalized)
        store.immutable_json(run_root/'delivery_results'/(identity(result)+'.json'),result)
        return result

    @staticmethod
    def _delivery_projection(core_result,finalized):
        """Expose the existing gate verdict without conflating goal/delivery."""
        from scripts.adaptive_delivery import FINAL_VERDICTS
        gate=finalized.get('gate',{})
        verdict=gate.get('verdict')
        allowed=(finalized.get('ok') is True and gate.get('delivery_allowed') is True
                 and verdict in FINAL_VERDICTS)
        return {**core_result,'delivery_status':verdict if allowed else 'BLOCKED',
            'public_delivery_allowed':allowed,'finalization':finalized,
            'formal_evidence_status':('PASS_WITH_LIMITS' if verdict=='DELIVER_WITH_WARNINGS' else 'PASS')
                                     if allowed else 'NOT_EVALUATED'}

    def run_case(self, case_id: str, *, max_repair_rounds: int = 2) -> GenerationRunResult:
        if max_repair_rounds not in {0, 1, 2}:
            raise ValueError("application repair rounds must be between zero and two")
        case = get_case(case_id)
        # Old callers specify a resource allowance, not another repair owner.
        # A failed branch stays in the same canonical graph/workspace so that
        # successful siblings, UNKNOWN and candidate identities remain intact.
        run_id = f"{case_id}-{uuid.uuid4().hex[:12]}-r0"
        run_dir = self.artifact_root / case_id / run_id
        workspace = run_dir / "workspace"
        run_dir.mkdir(parents=True, exist_ok=False)
        if case.seeded_fixture:
            shutil.copytree(self.repository_root / case.seeded_fixture, workspace)
        else:
            workspace.mkdir()
        return self._run_round(case, run_id, run_dir, workspace, 0, "",
                               decision_multiplier=max_repair_rounds + 1)

    @observed("software_project", lambda a: a["run_dir"])
    def _run_round(self, case: ProjectCase, run_id: str, run_dir: pathlib.Path, workspace: pathlib.Path, round_number: int, failure_summary: str, *, decision_multiplier: int = 1) -> GenerationRunResult:
        started = time.perf_counter()
        config = self._resolved_config()
        high = self._role("agent", config["high_capability_agent"])
        worker = self._role("worker", config["cheap_worker"])
        # Roles have distinct authority even when the provider/model is shared.
        # Provider aliases are not concrete model identities.
        run_client: CompletionClient = self.client.bind_run(run_id, case.case_id) if isinstance(self.client, GatewayCompletionClient) else self.client
        if self.routing:
            self.routing.snapshot(run_id).write_once(run_dir / "model_routing_snapshot.json")
        store = FileRunStore(self.artifact_root)
        from cgkn.providers.recording import RecordedCompletionClient
        run_client = RecordedCompletionClient(run_client, store, case.case_id, run_id)
        registry = ExecutorRegistry()
        registry.register(FileExecutor(workspace))
        registry.register(CommandExecutor(workspace))
        registry.register(PythonTestExecutor(workspace))
        registry.register(ScopedProjectLLMExecutor(workspace, run_client, worker))
        registry.register(ProjectSnapshotExecutor(workspace))
        registry.register(ExternalAcceptanceExecutor(workspace, self.acceptance_root))
        public_case = {"case_id": case.case_id, "public_goal": case.public_goal, "public_acceptance": list(case.public_acceptance), "entrypoint": case.entrypoint, "runtime_command": list(case.runtime_command)}
        self._write(run_dir / "public_case.json", public_case)
        initial_test = self._initial_test(workspace) if case.seeded_fixture else None
        goal = self._goal(case, round_number, failure_summary, workspace)
        catalog = self._catalog(case)
        composer = SoftwareProjectAgentComposer(run_client, high)
        from .qualification import install
        acceptance, checkers = install(registry, store, workspace, case.case_id, run_id, case.public_goal)
        policy,planning=self._execution_authorities(case.case_id,run_id,store)
        loop = ProjectSession(
            composer, DAGRunner(registry, store, deliverable_checkers=checkers), store,
            known_capabilities=set(catalog), worker_model=worker.model,
            capability_catalog=catalog, max_decisions=int(config.get("max_agent_decisions", 4)) * decision_multiplier, acceptance=acceptance,
            admission_policy=policy,
        )
        try:
            result = loop.run(project_id=case.case_id, run_id=run_id, goal=goal,planning=planning, constraints=(f"public project contract: {case.public_goal}", f"public acceptance: {list(case.public_acceptance)}", "stdlib-only", "no outbound network", "no hidden acceptance access", "no absolute paths", "no placeholders", "worker writes only declared target_paths"))
            status, validation = self._validate_completion(case, run_id, workspace, store, result)
            usage = self._provider_usage(run_dir)
            if usage["worker_calls"] > 20 or usage["provider_call_count"] > 24:
                status = ProjectResultStatus.NEEDS_REWORK
                validation = dict(validation) | {"sanitized_failure_summary": "provider call budget exceeded"}
        except Exception as exc:
            result = None
            status, validation = ProjectResultStatus.BLOCKED_PROVIDER, {"sanitized_failure_summary": f"generation framework stopped: {type(exc).__name__}"}
            self._write(run_dir / "framework_error.json", {"type": type(exc).__name__, "message": str(exc)})
            if composer.last_provider_payload:
                self._write(run_dir / "agent" / "rejected-decision.json", composer.last_provider_payload)
        receipt = self._receipt(case, run_id, run_dir, workspace, round_number, result, status, validation, initial_test, high, worker, int((time.perf_counter() - started) * 1000))
        self._write(run_dir / "generation_receipt.json", receipt)
        self._write(run_dir / "provider_usage.json", self._provider_usage(run_dir))
        if (run_dir / "node_results").is_dir():
            for name, target in (("internal_test_receipt.json", "pytest"), ("runtime_receipt.json", "smoke"), ("external_acceptance_receipt.json", "accept"), ("project_snapshot.json", "snapshot")):
                match = next((p for p in (run_dir / "node_results").glob("*.json") if target in p.stem.lower()), None)
                if match:
                    shutil.copyfile(match, run_dir / name)
        return GenerationRunResult(case.case_id, run_id, run_dir, workspace, status, receipt)

    def _validate_completion(self, case: ProjectCase, run_id: str, workspace: pathlib.Path, store: FileRunStore, result: Any) -> tuple[ProjectResultStatus, dict[str, Any]]:
        if result.status != "GOALS_VERIFIED" or not result.run_summary:
            summary = "Agent/DAG run did not complete"
            if result.run_summary and result.run_summary.failed_nodes:
                failed = result.run_summary.failed_nodes[-1]
                block = store.load_result(case.case_id, run_id, failed)
                summary = block.error.message if block.error else summary
            return ProjectResultStatus.FAIL, {"sanitized_failure_summary": summary}
        snapshot_rows = []
        acceptance_rows = []
        for node in result.tree.nodes:
            if not node.executable:
                continue
            block = store.load_result(case.case_id, run_id, node.id)
            if node.capability_ref == "project.snapshot@1": snapshot_rows.append(dict(block.outputs))
            if node.capability_ref == "project.acceptance.external@1": acceptance_rows.append(dict(block.outputs))
        if len(snapshot_rows) != 1 or len(acceptance_rows) != 1:
            return ProjectResultStatus.FAIL, {"sanitized_failure_summary": "completion nodes are missing or duplicated"}
        snap, acceptance = snapshot_rows[0], acceptance_rows[0]
        if acceptance.get("status") != "PASS" or acceptance.get("snapshot_hash") != snap.get("snapshot_hash"):
            return ProjectResultStatus.FAIL, {"sanitized_failure_summary": acceptance.get("sanitized_summary", "external acceptance failed"), "snapshot": snap, "acceptance": acceptance}
        if not workspace.exists() or not snap.get("files") or not (workspace / case.entrypoint).is_file():
            return ProjectResultStatus.FAIL, {"sanitized_failure_summary": "project snapshot or entrypoint is incomplete", "snapshot": snap, "acceptance": acceptance}
        scan = self._forbidden_scan(workspace)
        if scan:
            return ProjectResultStatus.FAIL, {"sanitized_failure_summary": "generated project failed forbidden-content scan", "forbidden_findings": scan, "snapshot": snap, "acceptance": acceptance}
        return ProjectResultStatus.PASS, {"sanitized_failure_summary": "", "snapshot": snap, "acceptance": acceptance}

    def _receipt(self, case: ProjectCase, run_id: str, run_dir: pathlib.Path, workspace: pathlib.Path, round_number: int, result: Any, status: ProjectResultStatus, validation: Mapping[str, Any], initial_test: Mapping[str, Any] | None, high: ModelRoleConfig, worker: ModelRoleConfig, wall_ms: int) -> dict[str, Any]:
        usage_evidence = self._provider_usage(run_dir)
        snapshot = dict(validation.get("snapshot", {}))
        tree_doc = json.loads((run_dir / "capability_tree.json").read_text(encoding="utf-8")) if (run_dir / "capability_tree.json").is_file() else {}
        dag_doc = json.loads((run_dir / "execution_dag.json").read_text(encoding="utf-8")) if (run_dir / "execution_dag.json").is_file() else {}
        token_totals = self._token_totals(usage_evidence["provider_usage"])
        attempt_count = usage_evidence["worker_execution_attempts"] + usage_evidence["deterministic_calls"]
        source_loc = sum(
            len(path.read_text(encoding="utf-8", errors="replace").splitlines())
            for path in workspace.rglob("*.py") if "__pycache__" not in path.parts
        )
        internal_test = self._capability_status(result, "project.python.pytest@1")
        runtime_result = self._capability_status(result, "project.command.smoke@1")
        hidden_result = dict(validation.get("acceptance", {})).get("status", "NOT_EVALUATED")
        values = {
            "case_id": case.case_id, "project_id": case.case_id, "run_id": run_id, "generation_round": round_number,
            **self._git_identity(), "goal_hash": "sha256:" + hashlib.sha256(case.public_goal.encode()).hexdigest(),
            "agent_model": high.model, "worker_model": worker.model,
            "agent_request_ids": usage_evidence["agent_request_ids"],
            "worker_request_ids": usage_evidence["worker_request_ids"],
            "provider_usage": usage_evidence["provider_usage"], "provider_call_count": usage_evidence["provider_call_count"],
            "agent_calls": usage_evidence["agent_calls"], "worker_calls": usage_evidence["worker_calls"], "deterministic_calls": usage_evidence["deterministic_calls"],
            "tree_hash": canonical_hash(tree_doc) if tree_doc else "", "dag_hash": canonical_hash(dag_doc) if dag_doc else "",
            "tree_nodes": len(tree_doc.get("nodes", [])), "dag_nodes": len(dag_doc.get("nodes", [])),
            "snapshot_hash": snapshot.get("snapshot_hash", ""), "generated_file_count": snapshot.get("total_file_count", 0),
            "generated_source_loc": source_loc,
            "internal_compile_result": self._capability_status(result, "project.python.compile@1"),
            "internal_test_result": internal_test,
            "runtime_result": runtime_result,
            "hidden_acceptance_result": hidden_result,
            "functional_success": status is ProjectResultStatus.PASS,
            "tree_edit_success": bool(tree_doc.get("nodes")),
            "dag_compile_success": bool(dag_doc.get("nodes")),
            "worker_proposal_success": usage_evidence["worker_calls"] > 0,
            "file_materialization_success": any(path.is_file() for path in workspace.rglob("*.py")),
            "repair_success": bool(round_number and status is ProjectResultStatus.PASS),
            "false_pass": internal_test == "PASS" and hidden_result != "PASS",
            "false_fail": False,
            "retry_count": max(0, attempt_count - len({path.parent.name for path in (run_dir / "attempts").glob("*/attempt-*.json")})),
            **token_totals,
            "initial_test": dict(initial_test or {}), "repair_rounds": round_number,
            "manual_intervention": 0, "human_intervention": False, "wall_time_ms": wall_ms,
            "final_status": status.value, "sanitized_failure_summary": str(validation.get("sanitized_failure_summary", "")),
            "secrets_persisted": False,
        }
        routing_path = run_dir / "model_routing_snapshot.json"
        if routing_path.is_file():
            routing_doc = json.loads(routing_path.read_text(encoding="utf-8"))
            values["model_routing_snapshot_hash"] = canonical_hash(routing_doc)
            values["model_routing_roles"] = dict(routing_doc.get("roles", {}))
            values["model_routing_fallback"] = routing_doc.get("fallback", "deny")
        return ProjectGenerationReceipt(values).as_dict()

    @staticmethod
    def _provider_usage(run_dir: pathlib.Path) -> dict[str, Any]:
        # Raw request/response receipts include rejected declarations and
        # interrupted calls that never became a graph decision or task result.
        # They are the authority when present; legacy projections stay readable.
        requests = sorted((run_dir / 'provider_calls').glob('*/request.json'))
        if requests:
            rows = []
            for path in requests:
                request = json.loads(path.read_text(encoding='utf-8'))
                response_path, error_path = path.with_name('response.json'), path.with_name('error.json')
                response = json.loads(response_path.read_text(encoding='utf-8')) if response_path.exists() else {}
                error = json.loads(error_path.read_text(encoding='utf-8')) if error_path.exists() else {}
                config = request['config']
                rows.append({'role':config['role'], 'identity':request['identity'],
                    'requested_provider_or_model':config['model'], 'requested_model':config.get('model_id'),
                    'model':response.get('model','UNKNOWN'), 'routing':response.get('routing',{}),
                    'request_id':response.get('request_id'), 'usage':response.get('usage',{}),
                    'provider_attempts':response.get('attempts', 0 if error.get('provider_dispatched') is False else None),
                    'status':'RESPONSE_RECORDED' if response else 'ERROR_RECORDED' if error else 'OUTCOME_UNKNOWN',
                    'outcome_unknown':not response and error.get('outcome_unknown') is not False,
                    'error':error, 'evidence_ref':str(path.relative_to(run_dir))})
            attempts=list((run_dir / 'attempts').glob('*/attempt-*.json'))
            executions=[json.loads(p.read_text(encoding='utf-8')) for p in attempts]
            return {'agent_request_ids':[r['request_id'] for r in rows if r['role']=='agent' and r['request_id']],
                    'worker_request_ids':[r['request_id'] for r in rows if r['role']=='worker' and r['request_id']],
                    'provider_usage':rows, 'provider_call_count':len(rows),
                    'agent_calls':sum(r['role']=='agent' for r in rows),
                    'worker_calls':sum(r['role']=='worker' for r in rows),
                    'provider_attempts_known':sum(r['provider_attempts'] for r in rows if r['provider_attempts'] is not None),
                    'provider_attempt_records_unknown':sum(r['provider_attempts'] is None for r in rows),
                    'outcome_unknown':sum(r['outcome_unknown'] for r in rows),
                    'deterministic_calls':sum(d.get('executor_ref')!='llm.cheap@1' for d in executions),
                    'worker_execution_attempts':sum(d.get('executor_ref')=='llm.cheap@1' for d in executions)}
        agent_docs = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((run_dir / "agent").glob("decision-*.json"))] if (run_dir / "agent").is_dir() else []
        attempt_docs = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((run_dir / "attempts").glob("*/attempt-*.json"))] if (run_dir / "attempts").is_dir() else []
        agent_rows = [{"role": "agent", **dict(doc.get("provider", {}))} for doc in agent_docs]
        worker_rows: list[dict[str, Any]] = []
        worker_request_ids: list[str] = []
        for doc in attempt_docs:
            if doc.get("executor_ref") != "llm.cheap@1":
                continue
            usage = dict(doc.get("usage", {}))
            request_ids = [str(item) for item in usage.get("request_ids", ()) if item]
            if not request_ids and usage.get("request_id"):
                request_ids = [str(usage["request_id"])]
            worker_request_ids.extend(request_ids)
            worker_rows.append({"role": "worker", "node_id": doc.get("node_id"), "attempt_id": doc.get("attempt_id"), **usage})
        agent_request_ids = [str(row.get("request_id")) for row in agent_rows if row.get("request_id")]
        return {
            "agent_request_ids": agent_request_ids,
            "worker_request_ids": worker_request_ids,
            "provider_usage": agent_rows + worker_rows,
            "provider_call_count": len(agent_request_ids) + len(worker_request_ids),
            "agent_calls": len(agent_request_ids),
            "worker_calls": len(worker_request_ids),
            "deterministic_calls": sum(1 for doc in attempt_docs if doc.get("executor_ref") != "llm.cheap@1"),
            "worker_execution_attempts": sum(1 for doc in attempt_docs if doc.get("executor_ref") == "llm.cheap@1"),
        }

    @staticmethod
    def _token_totals(rows: list[dict[str, Any]]) -> dict[str, int | str]:
        totals: dict[str, int | str] = {"agent_input_tokens": 0, "agent_output_tokens": 0, "worker_input_tokens": 0, "worker_output_tokens": 0, "context_chars": 0}
        availability = {"agent_input_tokens": True, "agent_output_tokens": True, "worker_input_tokens": True, "worker_output_tokens": True}
        for row in rows:
            role = str(row.get("role", ""))
            usage = row.get("usage", row)
            if not isinstance(usage, Mapping):
                continue
            if role == "agent":
                for target, source in (("agent_input_tokens", "prompt_tokens"), ("agent_output_tokens", "completion_tokens")):
                    value = usage.get(source)
                    if isinstance(value, int):
                        totals[target] = int(totals[target]) + value
                    else:
                        availability[target] = False
            elif role == "worker":
                for target, source in (("worker_input_tokens", "prompt_tokens"), ("worker_output_tokens", "completion_tokens")):
                    value = usage.get(source)
                    if isinstance(value, int):
                        totals[target] = int(totals[target]) + value
                    else:
                        availability[target] = False
                totals["context_chars"] = int(totals["context_chars"]) + int(usage.get("context_chars", 0))
        for key, complete in availability.items():
            if not complete:
                totals[key] = "TOKEN_USAGE_UNAVAILABLE"
        return totals

    @staticmethod
    def _capability_status(result: Any, capability_ref: str) -> str:
        if not result or not result.run_summary:
            return "NOT_EVALUATED"
        nodes = [node.id for node in result.tree.nodes if node.capability_ref == capability_ref]
        return "PASS" if len(nodes) == 1 and nodes[0] not in result.run_summary.failed_nodes and nodes[0] not in result.run_summary.blocked_nodes else "FAIL"

    def _goal(self, case: ProjectCase, round_number: int, failure_summary: str, workspace: pathlib.Path) -> str:
        mode = "Build from an empty workspace." if round_number == 0 and not case.seeded_fixture else "Repair the existing workspace with the smallest scoped changes."
        existing = sorted(path.relative_to(workspace).as_posix() for path in workspace.rglob("*") if path.is_file())
        return f"{case.public_goal}\n{mode}\nPublic acceptance: {list(case.public_acceptance)}\nRequired entrypoint: {case.entrypoint}\nRuntime smoke argv: {list(case.runtime_command)}\nExisting public files: {existing}\nSanitized previous failure: {failure_summary or 'none'}."

    def _catalog(self, case: ProjectCase) -> dict[str, Any]:
        catalog = self.bundle.catalog
        # The Direct benchmark remains a compatibility experiment, not an Agent capability.
        catalog.pop("direct_agent_execute@1", None)
        catalog["workspace.inspect@1"] |= {"executor_ref": "local.file@1", "config": {"action": "list_files", "path": ".", "goal": "Inspect public workspace files"}}
        catalog["project.python.compile@1"] |= {"executor_ref": "local.command@1", "config": {"command": [sys.executable, "-m", "compileall", "-q", "."], "goal": "Compile all Python sources"}}
        catalog["project.python.pytest@1"] |= {"executor_ref": "local.python-test@1", "config": {"pytest_args": ["-q"], "goal": "Run public project tests"}}
        catalog["project.command.smoke@1"] |= {"executor_ref": "local.command@1", "config": {"command": [sys.executable, *case.runtime_command[1:]], "goal": "Run the declared public runtime smoke"}}
        catalog["project.snapshot@1"] |= {"executor_ref": "project.snapshot@1", "config": {"entrypoints": [case.entrypoint], "test_commands": [f"{sys.executable} -m pytest -q"], "runtime_commands": [" ".join((sys.executable, *case.runtime_command[1:]))], "goal": "Create deterministic project snapshot"}}
        catalog["project.acceptance.external@1"] |= {"executor_ref": "project.acceptance@1", "config": {"case_id": case.case_id, "goal": "Run isolated external acceptance"}}
        return catalog

    def _resolved_config(self) -> dict[str, Any]:
        resolved = {
            "high_capability_agent": {"model": "qwen3.8-flash", "timeout_seconds": 90, "max_output_tokens": 7000, "reasoning_effort": "none"},
            "cheap_worker": {"model": "qwen3.7-flash", "timeout_seconds": 90, "max_output_tokens": 6000, "temperature": 0.0, "reasoning_effort": "none"},
            "max_agent_decisions": 4,
        } | self.config
        if self.routing:
            def role(value: ModelRoleConfig) -> dict[str, Any]:
                return {
                    "model": value.model,
                    "model_id": value.model_id,
                    "timeout_seconds": value.timeout_seconds,
                    "max_output_tokens": value.max_output_tokens,
                    "temperature": value.temperature,
                    "reasoning_effort": value.reasoning_effort,
                }
            resolved["high_capability_agent"] = role(self.routing.agent)
            resolved["cheap_worker"] = role(self.routing.worker)
        return resolved

    @staticmethod
    def _role(role: str, value: Mapping[str, Any]) -> ModelRoleConfig:
        return ModelRoleConfig(role, str(value["model"]), int(value.get("timeout_seconds", 90)), int(value.get("max_output_tokens", 6000)), float(value.get("temperature", 0.0)), str(value.get("reasoning_effort", "none")), value.get("model_id"))

    @staticmethod
    def _initial_test(workspace: pathlib.Path) -> dict[str, Any]:
        env = os.environ.copy(); env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        completed = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=workspace, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=60, env=env)
        return {"returncode": completed.returncode, "stdout": completed.stdout[-2000:], "stderr": completed.stderr[-2000:]}

    @staticmethod
    def _forbidden_scan(workspace: pathlib.Path) -> list[str]:
        findings: list[str] = []
        suspicious = ("benchmarks/real_project_generation", "CGKN_GENERATED_PROJECT", "hidden_acceptance", "TODO", "FIXME")
        for path in workspace.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            relative = path.relative_to(workspace).as_posix()
            if path.name in {"generation_receipt.json", "external_acceptance_receipt.json", "project_snapshot.json"}:
                findings.append(f"forged-evidence:{relative}")
            if path.stat().st_size == 0 and path.suffix == ".py": findings.append(f"zero-byte:{relative}")
            if path.suffix.lower() in {".py", ".md", ".txt", ".json", ".html", ".js", ".css"}:
                text = path.read_text(encoding="utf-8", errors="replace")
                if any(token in text for token in suspicious): findings.append(f"suspicious-literal:{relative}")
                if re.search(r"(?i)(?:[A-Z]:\\\\(?:Users|Documents|Desktop)\\\\|/(?:home|Users)/[^/]+/)", text): findings.append(f"absolute-machine-path:{relative}")
                if re.search(r"(?i)(?:api[_-]?key|secret|token)\s*[:=]\s*['\"][^'\"]{8,}", text): findings.append(f"secret-like-literal:{relative}")
                is_test = relative.startswith("tests/") or path.name.startswith("test_")
                if not is_test and ("requests." in text or "urllib.request" in text or "http.client" in text): findings.append(f"network-usage:{relative}")
                if path.suffix.lower() == ".py":
                    try:
                        tree = ast.parse(text)
                    except SyntaxError:
                        findings.append(f"invalid-python:{relative}")
                        continue
                    for node in ast.walk(tree):
                        names: list[str] = []
                        if isinstance(node, ast.Import): names = [alias.name.split(".")[0] for alias in node.names]
                        elif isinstance(node, ast.ImportFrom) and node.level == 0: names = [str(node.module or "").split(".")[0]]
                        for name in names:
                            if name and name not in sys.stdlib_module_names and not (workspace / name).exists() and not (workspace / f"{name}.py").exists():
                                findings.append(f"undeclared-dependency:{relative}:{name}")
        return sorted(set(findings))

    def _git_identity(self) -> dict[str, str]:
        def git(*args: str) -> str:
            return subprocess.run(["git", *args], cwd=self.repository_root, text=True, encoding="utf-8", errors="replace", capture_output=True, check=True).stdout.strip()
        return {"source_commit": git("rev-parse", "HEAD"), "source_tree": git("rev-parse", "HEAD^{tree}")}

    @staticmethod
    def _write(path: pathlib.Path, value: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@observed("formal_project", lambda a: pathlib.Path(a["project_root"]) / ".cgkn" / "agent-kit", expose=True)
def run_formal_generation_once(
    project_root: str | pathlib.Path,
    *,
    goal: str,
    provider_mode: str = "live",
    model: str = "gpt-4.1",
    repair_model: str = "",
    timeout: int = 1800,
    replay_dir: str | pathlib.Path | None = None,
    result_path: str | pathlib.Path | None = None,
    codex_capability_brief: str | pathlib.Path | None = None,
    observed_failure: str | pathlib.Path | None = None,
    on_started: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run/resume one production conversation generation turn synchronously.

    This is a local interface adapter to the sole reviewed Codex conversation
    route.  It does not add a generator, verifier, packager, or delivery exit.
    """
    root = pathlib.Path(project_root).resolve()
    artifact_dir = root / ".cgkn" / "agent-kit"
    core_profile = root / '.cgkn' / 'project-session.json'
    if core_profile.exists():
        # A configured production session uses the existing core directly.
        # Never fall back to a legacy whole-project repair loop after failure.
        if provider_mode != 'live' or replay_dir is not None:
            raise ValueError('project-session profile requires its recorded provider route')
        if observed_failure is not None or codex_capability_brief is not None:
            raise ValueError('legacy repair/brief input cannot override frozen project-session context')
        service = SoftwareProjectGenerationService(pathlib.Path(__file__).resolve().parents[3],
                                                    artifact_dir / 'project_sessions')
        result = service.run_profile(core_profile, goal=goal, on_started=on_started)
        output = pathlib.Path(result_path).resolve() if result_path else artifact_dir / 'generation_result.json'
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return result
    raise ValueError('PROJECT_SESSION_PROFILE_REQUIRED: configure .cgkn/project-session.json; legacy project lifecycle is retired')


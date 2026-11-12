from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from cgkn.orchestration.capability_tree import CapabilityTree, _thaw
from cgkn.orchestration.tree_edits import TreeEdit, EDIT_PAYLOAD_KEYS
from cgkn.providers import CompletionClient, ModelRoleConfig, ProviderCompletion, parse_json_object

from .composer_contract import parse_tree_edit


AGENT_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "required": ["schema_version", "decision_id", "summary", "reason", "edits", "request_run", "finish", "needs_escalation", "escalation_reason"],
    "properties": {
        "schema_version": {"const": "1.0"}, "decision_id": {"type": "string"}, "summary": {"type": "string"}, "reason": {"type": "string"},
        "edits": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["edit_id", "operation", "node_id", "payload", "provenance"], "properties": {
            "edit_id": {"type": "string"}, "operation": {"enum": ["add_node", "remove_node", "replace_node", "move_node", "add_dependency", "remove_dependency", "replace_executor", "update_config", "retry_node"]}, "node_id": {"type": "string"},
            "payload": {"type": "object"}, "provenance": {"type": "object"}
        }}}, "request_run": {"type": "boolean"}, "finish": {"type": "boolean"},
        "needs_escalation": {"type": "boolean"}, "escalation_reason": {"type": "string"},
    },
}


# Advertise the same operation-specific payload boundary enforced by TreeEdit.
AGENT_SCHEMA['properties']['edits']['items']['allOf']=[
    {'if':{'properties':{'operation':{'const':operation}}},
     'then':{'properties':{'payload':{'type':'object','properties':{key:{} for key in sorted(keys)},
                                    'additionalProperties':False}}}}
    for operation,keys in sorted(EDIT_PAYLOAD_KEYS.items()) if operation in AGENT_SCHEMA['properties']['edits']['items']['properties']['operation']['enum']
]


@dataclass(frozen=True)
class AgentDecisionContext:
    project_id: str
    run_id: str
    goal: str
    decision_number: int
    tree: CapabilityTree
    known_capabilities: tuple[str, ...]
    capability_catalog: Mapping[str, Any]
    run_summary: Mapping[str, Any]
    failure_details: Mapping[str, Any]
    execution_results: Mapping[str, Any] = field(default_factory=dict)
    goal_acceptance: Mapping[str, Any] = field(default_factory=dict)
    task_feedback: Mapping[str, Any] = field(default_factory=dict)
    retrieved_knowledge: Mapping[str, Any] = field(default_factory=dict)
    project_intent: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"project_id": self.project_id, "run_id": self.run_id, "goal": self.goal, "decision_number": self.decision_number, "tree": self.tree.as_dict(), "known_capabilities": list(self.known_capabilities), "capability_catalog": _thaw(self.capability_catalog), "run_summary": _thaw(self.run_summary), "failure_details": _thaw(self.failure_details), "execution_results": _thaw(self.execution_results), "goal_acceptance": _thaw(self.goal_acceptance), "task_feedback": _thaw(self.task_feedback), "retrieved_knowledge": _thaw(self.retrieved_knowledge), "project_intent":_thaw(self.project_intent)}


@dataclass(frozen=True)
class AgentDecision:
    decision_id: str
    summary: str
    reason: str
    edits: tuple[TreeEdit, ...]
    request_run: bool
    finish: bool
    needs_escalation: bool
    escalation_reason: str
    provider: Mapping[str, Any]
    context_hash: str
    context_chars: int
    goal_plan: Mapping[str, Any] | None = None
    decision_audit: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"decision_audit": _thaw(self.decision_audit), "schema_version": "1.0", "decision_id": self.decision_id, "summary": self.summary, "reason": self.reason, "edits": [{"edit_id": item.edit_id, "operation": item.operation, "node_id": item.node_id, "payload": _thaw(item.payload), "provenance": _thaw(item.provenance)} for item in self.edits], "request_run": self.request_run, "finish": self.finish, "needs_escalation": self.needs_escalation, "escalation_reason": self.escalation_reason, "provider": _thaw(self.provider), "context_hash": self.context_hash, "context_chars": self.context_chars, "goal_plan": _thaw(self.goal_plan) if self.goal_plan else None}


def parse_agent_decision(value: Mapping[str, Any], completion: ProviderCompletion, raw_context: str) -> AgentDecision:
    required = set(AGENT_SCHEMA["required"])
    if set(value) - {"goal_plan", "decision_audit"} != required or value.get("schema_version") != "1.0":
        raise ValueError("agent decision has invalid envelope")
    edits_raw = value.get("edits")
    if not isinstance(edits_raw, list):
        raise ValueError("agent edits must be a list")
    normalized_edits: list[dict[str, Any]] = []
    for raw in edits_raw:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        payload = dict(item.get("payload", {}))
        if item.get("operation") == "add_node" and payload.get("parent_id") in {None, "root"}:
            payload["parent_id"] = ""
        item["payload"] = payload
        normalized_edits.append(item)
    edits = tuple(parse_tree_edit(item) for item in normalized_edits)
    if len(edits) != len(edits_raw):
        raise ValueError("agent edit must be an object")
    if any(item.operation not in {"add_node", "remove_node", "replace_node", "move_node", "add_dependency", "remove_dependency", "replace_executor", "update_config", "retry_node"} for item in edits):
        raise ValueError("agent proposed an unauthorized operation")
    for item in edits:
        if item.operation == "add_node":
            if set(item.payload) != {"capability_ref", "parent_id", "depends_on", "config"}:
                raise ValueError("agent add_node payload is not canonical")
        elif item.operation == "update_config" and set(item.payload) != {"config"}:
            raise ValueError("agent update_config payload is not canonical")
        elif item.operation == "retry_node" and item.payload:
            raise ValueError("agent retry_node payload must be empty")
    controls = sum(bool(value[name]) for name in ("request_run", "finish", "needs_escalation"))
    if controls != 1 and not (controls == 0 and value.get("goal_plan")):
        raise ValueError("agent decision must choose exactly one control outcome")
    audit=value.get('decision_audit',{})
    if audit and (set(audit)!={'alternatives_considered','expected_outcome'} or not isinstance(audit['alternatives_considered'],list) or any(not isinstance(x,str) for x in audit['alternatives_considered']) or not isinstance(audit['expected_outcome'],str)):
        raise ValueError('invalid public decision audit')
    return AgentDecision(str(value["decision_id"]), str(value["summary"]), str(value["reason"]), edits, bool(value["request_run"]), bool(value["finish"]), bool(value["needs_escalation"]), str(value["escalation_reason"]), {"model": completion.model, "routing": dict(completion.routing), "request_id": completion.request_id, "usage": dict(completion.usage), "attempts": completion.attempts}, hashlib.sha256(raw_context.encode()).hexdigest(), len(raw_context), value.get("goal_plan"),audit)


class AgentDecisionValidationError(ValueError):
    """Rejected model text, preserved verbatim for the next bounded decision."""

    def __init__(self, error: Exception, completion: ProviderCompletion):
        super().__init__(str(error))
        self.feedback = {"error_type": type(error).__name__, "error": str(error),
                         "raw_response": completion.text, "model": completion.model,
                         "request_id": completion.request_id}


class AgentComposer:
    additional_instructions = ''
    decision_schema_name = 'cgkn_agent_decision'

    def __init__(self, client: CompletionClient, config: ModelRoleConfig, *, require_decision_audit=False, allow_goal_plan=True, semantic_tables=None, protocol_trace=None, context_resolver=None, context_policy=None, planner_mode='EXECUTION_MODE'):
        if config.role != "agent":
            raise ValueError("AgentComposer requires agent model config")
        self.client, self.config = client, config
        self.last_provider_payload = {}
        if planner_mode not in {'EXECUTION_MODE','MILESTONE_MODE'}:
            raise ValueError('unsupported planner mode')
        self.planner_mode = planner_mode
        self.semantic_tables=semantic_tables or (self._milestone_snapshot if planner_mode=='MILESTONE_MODE' else None)
        self.protocol_trace=protocol_trace
        self.context_resolver,self.context_policy=context_resolver,context_policy
        if self.semantic_tables is not None and not callable(protocol_trace):raise ValueError("semantic protocol requires an audit sink")
        self.require_decision_audit,self.allow_goal_plan=require_decision_audit,allow_goal_plan

    def declare_milestone(self, context, *, namespace, requirement_refs, checker_ref, subject_ref=None, artifact_subject=False):
        """Declare one current milestone through this same Planner/client.

        Returns a proposal, never committed state or an acceptance verdict.
        The ProjectSession application adapter owns admission into its existing
        GoalAcceptance plan and registry; no second lifecycle is introduced.
        """
        if self.planner_mode != 'MILESTONE_MODE' or not callable(self.protocol_trace):
            raise ValueError('MILESTONE_MODE and durable protocol trace required')
        from cgkn.protocol.declaration import MilestoneContractCompiler
        from cgkn.protocol.compiler import TableSnapshot
        from cgkn.protocol.exchange import exchange
        from cgkn.protocol.normalization import ContractError
        acceptance = _thaw(context.goal_acceptance)
        if not set(requirement_refs) <= acceptance.get('requirements',{}).keys():
            raise ValueError('milestone requirement bindings are not registered')
        if checker_ref not in acceptance.get('checker_bindings',{}).values():
            raise ValueError('milestone independent checker is not registered')
        if subject_ref is not None and subject_ref not in acceptance.get('subject_identities',{}):
            raise ValueError('milestone subject is not registered')
        public = {'goal':context.goal, 'project_intent':_thaw(context.project_intent),
            'verified_state':[{'acceptance':g['acceptance'],'verdict':g['verdict']}
                              for g in acceptance.get('goals',()) if g.get('verdict') == 'VERIFIED'],
            'unresolved_acceptance':[{'acceptance':g['acceptance'],'verdict':g.get('verdict')}
                                     for g in acceptance.get('goals',()) if g.get('verdict') != 'VERIFIED'],
            'current_requirements':{r:acceptance.get('requirements',{}).get(r) for r in requirement_refs},
            'dependency_contracts':self._milestone_dependencies(acceptance,requirement_refs),
            'failure_details':_thaw(context.failure_details),
            'task_feedback':_thaw(context.task_feedback),
            'relevant_knowledge':_thaw(context.retrieved_knowledge)}
        source = f'{context.project_id}:{context.run_id}:milestone-decision:{context.decision_number}'
        compiler = MilestoneContractCompiler()
        layouts=[acceptance['requirements'][r]['artifact_layout'] for r in requirement_refs
                 if 'artifact_layout' in acceptance['requirements'][r]]
        if layouts and any(layout!=layouts[0] for layout in layouts):
            raise ValueError('selected requirements need separate artifact ownership milestones')
        artifact_layout=layouts[0] if layouts else None
        if artifact_layout:
            owned={a['path'] for g in acceptance.get('goals',())
                   for a in g.get('milestone_contract',{}).get('design',{}).get('artifacts',[])}
            proposed=[artifact_layout.get('source'),artifact_layout.get('test'),
                      *[a['path'] for a in artifact_layout.get('support',[])]]
            if {p.casefold() for p in owned}.intersection(p.casefold() for p in proposed if isinstance(p,str)):
                raise ValueError('new milestone cannot replace an existing artifact owner; repair the existing node')

        def patches(packet, error):
            paths=[]
            for field in error.fields:
                parts=field.split('/')
                if parts[0] in {'semantic_goal','public_behavior','acceptance_intent'}:
                    continue
                # The compiler must identify a semantic leaf before local
                # correction can touch an already populated container.
                path=[int(p) if p.isdigit() else p for p in parts]
                node=packet
                try:
                    for part in path:node=node[part]
                except (KeyError,IndexError,TypeError):node=None
                metadata_list=bool(path[0]=='fields' and len(path)>=3 and path[-1]=='consumers')
                if not isinstance(node,(dict,list)) or (metadata_list and isinstance(node,list)):paths.append(path)
            if not paths:raise ContractError('MILESTONE_REDECISION_REQUIRED', details={
                'original_proposal_retained':True,'original_error':error.as_dict()})
            return {'allowed_paths':paths,'immutable_paths':[['semantic_goal'],['public_behavior'],['acceptance_intent']]}

        compiled, completion, stats = exchange(self.client, self.config,
            system='You are the existing project Planner in MILESTONE_MODE. Declare ONLY the current bounded milestone, not the whole project. Return exactly eight fields: semantic_goal, public_behavior, operations (array of 1..8 objects), fields (object mapping field names to definitions, NOT an array), failure_semantics (object mapping exception names to policies, NOT an array), persistence, concurrency, acceptance_intent. semantic_goal, public_behavior, persistence and concurrency are nonempty strings. Each operation has exactly name (Python symbol), kind (function or class), parameters, returns, behavior, failures (array of declared exception names), idempotency, ordering. parameters, returns, behavior, idempotency and ordering must be nonempty; describe absence explicitly in words, not false/null/empty containers. Each field definition has type, required boolean, consumers (array of public operation names). Each failure_semantics policy has exactly behavior (nonempty string) and base (declared public exception or standard exception; never itself; empty string for an existing built-in exception). acceptance_intent is a nonempty array of observable conditions. Follow the granularity explicitly required by current_requirements: when it requests one aggregate acceptance intent, return EXACTLY ONE array item expressing a conjunction of all public behaviors and negative cases for this milestone. Keep every requirement in that item and the full public_behavior/operations; do not omit conditions to shorten it. Do not fragment a requested aggregate into one array item per operation or error case, as each item becomes a separate goal binding. This applies only to the new declaration; never merge or remove previously admitted goals or evidence. Never generate IDs, paths, hashes, checker/test bindings, schema versions, implementation or self-verification. The compiler generates mechanical bindings. Preserve the entire selected public requirement, including its CLI or other interfaces; do not silently narrow it. Give public semantics only, no hidden reasoning.',
            context=public, snapshot=TableSnapshot({'mode':'MILESTONE_MODE'}), semantic_attempt_id=source,
            compiler=lambda packet,bound:compiler.compile(packet, source_ref=source,
                namespace=namespace, requirement_refs=requirement_refs, checker_ref=checker_ref, subject_ref=subject_ref,
                artifact_subject=artifact_subject,artifact_layout=artifact_layout),
            normalization={}, trace=self.protocol_trace, declaration=True,
            context_resolver=self.context_resolver, context_policy=self.context_policy,
            semantic_patch_policy=patches)
        return {'design':compiled[0], 'registry':compiled[1], 'compilation':compiled[2],
                'provider':{'model':completion.model,'request_id':completion.request_id,
                            'routing':dict(completion.routing)}, 'exchange':stats,
                'admission':'PROPOSAL_ONLY', 'acceptance':'NOT_EVALUATED'}

    def decide(self, context: AgentDecisionContext) -> AgentDecision:
        if self.planner_mode == 'MILESTONE_MODE':
            if not context.project_intent or not context.goal_acceptance:
                raise ValueError('MILESTONE_MODE requires frozen intent and independent acceptance')
            view = context.goal_acceptance
            if view.get('uncovered_must') and all(g['verdict']=='VERIFIED' for g in view.get('goals',())):
                return self._next_milestone(context)
        if self.semantic_tables is not None:
            from cgkn.protocol.adapters import semantic_decide
            return semantic_decide(self,context)
        from cgkn.orchestration.leaf_contract import CONTRACT_SCHEMA
        raw_context = json.dumps({**context.as_dict(),'execution_leaf_contract_schema':CONTRACT_SCHEMA}, ensure_ascii=False, sort_keys=True)
        schema=json.loads(json.dumps(AGENT_SCHEMA))
        if context.goal_acceptance and self.allow_goal_plan and self.planner_mode != 'MILESTONE_MODE':
            schema["properties"]["goal_plan"]={"type":"object"}
        if self.require_decision_audit:
            schema['required'].append('decision_audit')
            schema['properties']['decision_audit']={'type':'object','additionalProperties':False,'required':['alternatives_considered','expected_outcome'],'properties':{'alternatives_considered':{'type':'array','items':{'type':'string'}},'expected_outcome':{'type':'string'}}}
        from cgkn.providers.gateway_client import GatewayCompletionError
        try:
            completion = self.client.complete(system="""You are the CGKN composition Agent. Decide only validated CapabilityTree edits and whether to run, finish, or escalate. Never write files, execute shell/network, change the project goal, package, deliver, or reveal hidden reasoning. Return concise JSON only.
    Exactly one of request_run, finish, needs_escalation must be true. Repair edits require request_run=true, finish=false, needs_escalation=false. Rejected decisions have not applied their edits; use validation feedback for a new decision.
    Canonical edit syntax is exact: add_node payload is {\"capability_ref\": str, \"parent_id\": str, \"depends_on\": [str], \"config\": object}; update_config payload is {\"config\": object}; retry_node payload is {}. Executor selection belongs in config.executor_ref. Copy config keys and values exactly from capability_catalog; do not invent aliases or absolute paths. Use capability_ref, depends_on, and executor_ref exactly; never substitute capability, dependencies, tool, runner, model, command, instruction, target_file, or file_path. Composite nodes have empty capability_ref and cannot execute. Every executable leaf requires config.leaf_contract with schema_version=1.0, leaf_goal, task_kind, target_scope (bounded relative artifact paths), expected_delta for writes, acceptance (registered checker condition names), checker_ref, output_identity, effect_domains (one primary), executor_ref and dependencies matching the node. Research requires source_refs and completion_criterion; tests require subject, expected_observation and pass_fail_rule. Choose independently verifiable deliverables, not whole products. NEEDS_DECOMPOSITION requires Agent revision; framework never splits business work. Execution success is not deliverable or goal acceptance. A request_run decision must create or retain at least one executable node.""" + "\n" + self.additional_instructions, user=raw_context, schema_name=self.decision_schema_name, schema=schema, config=self.config)
        except GatewayCompletionError as exc:
            document = getattr(exc, 'completed_response', None)
            if exc.category != 'schema_validation_failed' or exc.outcome_unknown or not isinstance(document, dict):
                raise
            text = document.get('output_text')
            if not isinstance(text, str):
                raise
            completion = ProviderCompletion(text, str(document.get('model') or 'UNKNOWN'),
                str(document.get('id') or ''), dict(document.get('usage') or {}),
                routing=dict(document.get('cgkn_model_identity') or {}))
            try:
                from jsonschema import Draft202012Validator
                value = parse_json_object(text)
                errors = [{'path': list(e.path), 'message': e.message}
                          for e in Draft202012Validator(schema).iter_errors(value)]
                reason = json.dumps(errors, ensure_ascii=False) if errors else str(exc)
            except ValueError as parse_error:
                reason = str(parse_error)
            rejection = AgentDecisionValidationError(ValueError(reason), completion)
            rejection.feedback.update(category=exc.category, failure_domain='MODEL_OUTPUT',
                outcome_unknown=False, usage=dict(completion.usage), routing=dict(completion.routing))
            raise rejection from exc

        try:
            self.last_provider_payload=parse_json_object(completion.text)
            value=self._normalize_decision(self.last_provider_payload,context)
            if (not self.allow_goal_plan or self.planner_mode == 'MILESTONE_MODE') and value.get('goal_plan'):raise ValueError('goal_plan is frozen; omit goal_plan, retain current acceptance contract')
            if self.require_decision_audit and not value.get('decision_audit'):raise ValueError('public decision_audit required: brief alternatives_considered and expected_outcome, no hidden reasoning')
            return parse_agent_decision(value, completion, raw_context)
        except (ValueError, TypeError, KeyError) as exc:
            # Transport errors remain outside this handler. No response repair.
            raise AgentDecisionValidationError(exc, completion) from exc

    @staticmethod
    def _normalize_decision(value, context):
        return value

    def _next_milestone(self, context):
        """A bounded planning decision of this same Agent, not another loop.

        Only previously registered public requirements/checkers/subjects may
        be selected. The resulting plan still goes through ProjectSession and
        GoalAcceptance.propose/commit. Compilation never attests acceptance.
        """
        if not callable(self.protocol_trace):
            raise ValueError('milestone planning requires durable protocol trace')
        view = _thaw(context.goal_acceptance)
        available = [r for r in view['uncovered_must'] if all(
            view['obligations'].get(d,{}).get('verdict')=='VERIFIED'
            for d in view['requirements'][r].get('depends_on',[]))]
        checkers = list(view['checker_bindings'])
        if not available or not checkers:
            raise ValueError('milestone planning lacks registered public bindings')
        public = {'goal':context.goal, 'project_intent':_thaw(context.project_intent),
                  'uncovered_requirements':{r:view['requirements'][r] for r in available},
                  'checker_keys':checkers,
                  'verified_milestones':[{'id':g['id'],'acceptance':g['acceptance']}
                                         for g in view['goals']],
                  'failure_details':_thaw(context.failure_details),
                  'progress':_thaw(context.task_feedback.get('progress_receipt',{}))}
        schema = {'type':'object','additionalProperties':False,
                  'required':['requirement_refs','checker','reason_summary'],
                  'properties':{'requirement_refs':{'type':'array','minItems':1,'uniqueItems':True,'items':{'enum':available}},
                                'checker':{'enum':checkers},
                                'reason_summary':{'type':'string','minLength':1}}}
        raw=json.dumps(public,ensure_ascii=False,sort_keys=True)
        completion=self.client.complete(system='Select only the next small, independently verifiable milestone from registered uncovered public requirements. Do not plan the whole product, implement business code, invent checker bindings or assert success. Return the selected bindings and a brief public reason; no hidden reasoning.',
            user=raw,schema_name='cgkn_next_milestone',schema=schema,config=self.config)
        trace={'kind':'MILESTONE_SELECTION','decision_number':context.decision_number,
               'context':public,'raw_response':completion.text,'model':completion.model,
               'request_id':completion.request_id,'usage':dict(completion.usage),
               'routing':dict(completion.routing),'provider_attempts':completion.attempts}
        try:
            from jsonschema import Draft202012Validator
            selection=parse_json_object(completion.text)
            errors=list(Draft202012Validator(schema).iter_errors(selection))
            if errors: raise ValueError('; '.join(e.message for e in errors))
            for requirement in selection['requirement_refs']:
                allowed=view['requirements'][requirement].get('checker_keys')
                if allowed is not None and selection['checker'] not in allowed:
                    raise ValueError('requirement is not bound to the selected independent checker')
        except (ValueError,TypeError) as exc:
            self.protocol_trace({**trace,'status':'REJECTED','error':str(exc)})
            raise AgentDecisionValidationError(exc,completion) from exc
        self.protocol_trace({**trace,'status':'ADMITTED_BINDINGS_ONLY','selection':selection})
        namespace=f'{context.project_id}/{context.run_id}/milestone/{context.decision_number}'
        proposal=self.declare_milestone(context,namespace=namespace,
            requirement_refs=selection['requirement_refs'],checker_ref=view['checker_bindings'][selection['checker']],
            artifact_subject=True)
        compilation=proposal['compilation']
        dependency_goals=self._milestone_dependencies(view,selection['requirement_refs'])
        dependency_artifacts=sorted({p for g in dependency_goals for p in g['subject_refs']})
        milestone_id=compilation['milestone_id']
        prior_goals=[{k:v for k,v in g.items() if k not in {'verdict','evidence','must'}} for g in view['goals']]
        prior_phases=[{k:v for k,v in p.items() if k!='acceptance'} for p in view['phases']]
        plan={'phases':prior_phases+[{'id':milestone_id,'outcome':proposal['design']['reason_summary'],
                                      'depends_on':[p['id'] for p in prior_phases]}],
              'goals':prior_goals+[{'id':binding['acceptance_id'],'phase_id':milestone_id,
                  'requirement_refs':selection['requirement_refs'],'acceptance':binding['intent'],
                  'subject_refs':list(dict.fromkeys([*binding.get('subject_refs',[binding['object_ref']]),*dependency_artifacts])),
                  'checker':selection['checker'],'task_refs':[],
                  'milestone_contract':{'design':proposal['design'],'registry':proposal['registry'],
                                        'compilation':compilation,'dependency_artifacts':dependency_artifacts,
                                        'dependency_goal_ids':[g['goal_id'] for g in dependency_goals]}}
                                  for binding in compilation['test_binding_skeleton']]}
        calls=[{'model':completion.model,'request_id':completion.request_id,'usage':dict(completion.usage),
                'routing':dict(completion.routing),'attempts':completion.attempts},*proposal['exchange']['calls']]
        return AgentDecision('declare-'+milestone_id,'Declare next bounded milestone',selection['reason_summary'],
            (),False,False,False,'',{'calls':calls},hashlib.sha256(raw.encode()).hexdigest(),len(raw),plan,
            {'alternatives_considered':[],'expected_outcome':'Admit public contract; independent acceptance remains pending'})

    @staticmethod
    def _milestone_dependencies(view, requirement_refs):
        needed=set()
        def collect(requirement):
            for dependency in view['requirements'][requirement].get('depends_on',[]):
                if dependency not in needed:
                    needed.add(dependency);collect(dependency)
        for requirement in requirement_refs: collect(requirement)
        return [{'goal_id':g['id'],'subject_refs':g['subject_refs'],
                 'public_contract':g['milestone_contract']['registry'],
                 'artifact_design':g['milestone_contract']['design']}
                for g in view.get('goals',[]) if g['verdict']=='VERIFIED' and g.get('milestone_contract')
                and needed.intersection(g['requirement_refs'])]

    @staticmethod
    def _milestone_snapshot(context):
        """Compile numeric views from already admitted milestone contracts."""
        from cgkn.protocol.tables import planner_snapshot
        from cgkn.protocol.normalization import digest, ContractError
        from cgkn.protocol.compiler import TableSnapshot
        goals = _thaw(context.goal_acceptance.get('goals',()))
        pending = [g for g in goals if g['verdict']!='VERIFIED']
        # Retain the final contract for the terminal FINISH decision.
        from cgkn.protocol.context_pack import dependency_ready_goals,unresolved_effect_paths,task_readiness_projection
        unknown_paths=unresolved_effect_paths(context)
        selected = dependency_ready_goals(goals,unknown_paths) if pending else goals[-1:]
        if unknown_paths and not selected:
            raise ContractError('OUTCOME_UNKNOWN_REQUIRES_RECONCILE')
        contracts = {g['milestone_contract']['compilation']['milestone_id']:g['milestone_contract']
                     for g in selected if g.get('milestone_contract')}
        if not contracts:
            if any(g.get('milestone_contract',{}).get('dependency_goal_ids') for g in pending):
                raise ContractError('MILESTONE_DEPENDENCY_NOT_READY')
            raise ContractError('ADMITTED_MILESTONE_CONTRACT_REQUIRED')
        # A failed integration may implicate a verified dependency. Expose its
        # original owner contract, never a fresh implementation or a rewritten
        # acceptance predicate. Only authenticated, current tested subjects qualify.
        identities=context.goal_acceptance.get('subject_identities',{})
        repair_paths={};repair_owners={};owner_rows=[]
        if context.goal_acceptance.get('evidence_mode')=='production_provenance':
            for failed in selected:
                evidence=failed.get('evidence') or {}
                if (failed.get('verdict')!='FAILED' or not evidence.get('receipt_hash')
                        or not evidence.get('node_id') or not evidence.get('attempt_id')
                        or evidence.get('provenance',{}).get('status')!='TRUSTED'):
                    continue
                failed_contract=failed.get('milestone_contract',{})
                subjects=evidence.get('subjects',{})
                bound={p for p in failed_contract.get('dependency_artifacts',[])
                       if p in failed.get('subject_refs',[]) and subjects.get(p)
                       and subjects[p]==identities.get(p)}
                for owner in goals:
                    if (owner['id'] not in failed_contract.get('dependency_goal_ids',[])
                            or owner.get('verdict')!='VERIFIED' or not owner.get('milestone_contract')):
                        continue
                    contract=owner['milestone_contract']
                    artifacts=[a for a in contract['design']['artifacts'] if a['path'] in bound]
                    if not artifacts:continue
                    key=contract['compilation']['milestone_id']
                    repair_owners[key]=contract
                    for artifact in artifacts:
                        path=artifact['path']
                        repair_paths.setdefault(failed['id'],set()).add(path)
                        owner_rows.append({'owner_goal_id':owner['id'],'path':path,
                            'subject_identity':subjects[path],'failed_goal_id':failed['id'],
                            'failure_receipt_hash':evidence['receipt_hash']})
        all_contracts={**repair_owners,**contracts}
        declarations = [a for c in contracts.values() for a in c['design']['artifacts']]
        repair_scope={p for paths in repair_paths.values() for p in paths}
        seen={a['path'] for a in declarations}
        for contract in repair_owners.values():
            for artifact in contract['design']['artifacts']:
                if artifact['path'] in repair_scope and artifact['path'] not in seen:
                    declarations.append(artifact);seen.add(artifact['path'])
        documents = [c['registry'] for c in all_contracts.values()]
        registry = {**documents[0], 'entries':[e for d in documents for e in d['entries']]}
        failures=[]
        for goal in selected:
            evidence=goal.get('evidence')
            if goal['verdict']!='FAILED' or not evidence: continue
            paths=[a['path'] for a in goal['milestone_contract']['design']['artifacts']]
            paths=sorted(set(paths)|repair_paths.get(goal['id'],set()))
            targets=[n.id for n in context.tree.nodes
                     if n.config.get('leaf_contract',{}).get('task_kind') in {'IMPLEMENTATION','REPAIR'}
                     and set(n.config['leaf_contract']['target_scope']).intersection(paths)]
            failures.append({'acceptance_id':goal['id'],'failure_domain':'business',
                'artifact_paths':paths,'target_leaf_refs':targets,'expected':goal['acceptance'],
                'actual':{'verdict':'FAILED','root_cause':'UNRESOLVED',
                          **({'public_reason':evidence['reason']} if evidence.get('reason') else {})},
                'failure_code':'INDEPENDENT_ACCEPTANCE_FAILED',
                'object_identity':evidence.get('subjects'),
                'evidence_refs':[{'path':f"attempts/{evidence['node_id']}/{evidence['attempt_id']}.json",
                                  'receipt_hash':evidence['receipt_hash']}],
                'authority':'current independent GoalAcceptance verdict; no inferred business cause'})
        from cgkn.protocol.repair import execution_repair_history
        snapshot = planner_snapshot(context,declarations,action_version=2,
            public_contract_registry=registry,
            public_contract_registry_ref='goal_acceptance.json:milestone_contract:'+digest(registry),
            context_raw_ref=f'agent/context-{context.decision_number:02d}.json',
            repair_context={'failures':failures,'previous_repair_attempts':execution_repair_history(context)})
        document = snapshot.document
        document['dependency_owner_repairs']=owner_rows
        document['dependency_owner_repair_policy']='Only current authenticated failed-integration subjects are exposed. Repair the existing owner with explicit evidence and its original contract; do not bypass it with a new writer or runtime monkeypatch. Unrelated subjects and owner tests remain read-only unless independently covered. This changes no acceptance verdict. Successful integration-source producers may be selected as bounded read dependencies where needed; preserve the original owner public contract.'
        document['verified_frontier']=[g['id'] for g in goals if g.get('verdict')=='VERIFIED']
        document['task_readiness']=task_readiness_projection(goals,context.goal_acceptance.get('subject_identities',{}),unknown_paths)
        document['progress_policy']='SEMANTIC_STRATEGY_V1'
        document['strategy_constraints']=_thaw(context.failure_details.get('continuation_requirements',{}).get('strategy_constraints',[]))
        document['repair_strategy_instruction']='Before repair or strategy switch, strategy must contain a problem field PLUS at least TWO distinct named implementation-mechanism dimensions at the TOP LEVEL (at least THREE keys total). A two-key problem/mechanism object is invalid. Choose meaningful dimensions such as data_ownership and update_boundary; do not use prompt/code/rationale/timestamp padding. Supply hypothesis={previous, falsifying_evidence:[exact current bound failure-ref objects], new, expected_novel_delta}. Same mechanism and unchanged evidence cannot authorize a repeated failed attempt.'
        bound_capabilities=[]
        bindings=context.goal_acceptance.get('checker_bindings',{})
        identities=context.goal_acceptance.get('subject_identities',{})
        document['artifact_readiness']=[{'path':a['path'],
            'materialized':bool(identities.get(a['path'])),
            'current_identity':identities.get(a['path']),
            'new_writer_allowed':not bool(identities.get(a['path'])),
            'purpose':a['purpose']} for a in declarations]
        # Existing admitted milestone dependency bindings grant bounded reads,
        # not writes or a second execution/dependency authority.
        all_goals={g['id']:g for g in goals}
        document['milestone_dependency_inputs']={}
        for contract in all_contracts.values():
            dependency_paths=contract.get('dependency_artifacts',[])
            dependency_ids=contract.get('dependency_goal_ids',[])
            unresolved=[gid for gid in dependency_ids if all_goals.get(gid,{}).get('verdict')!='VERIFIED']
            covered={p for gid in dependency_ids for p in all_goals.get(gid,{}).get('subject_refs',[])}
            unavailable=sorted(p for p in dependency_paths if p not in covered or not identities.get(p))
            for artifact in contract['design']['artifacts']:
                document['milestone_dependency_inputs'][artifact['path']]={
                    'subjects':{p:identities.get(p) for p in dependency_paths},
                    'unresolved_goal_ids':unresolved,'unavailable_paths':unavailable}
        document['acceptance_readiness']=[]
        ready_goals=set()
        for goal_index,goal in enumerate(selected):
            contract=goal.get('milestone_contract',{})
            required={a['path'] for a in contract.get('design',{}).get('artifacts',[])}
            required.update(goal['subject_refs'])
            missing=sorted(p for p in required if not identities.get(p))
            document['acceptance_readiness'].append({'goal_index':goal_index,'missing_artifacts':missing,
                'ready':not missing,'instruction':'Materialize missing declared artifacts before independent acceptance; existence is not business verification.'})
            if not missing:ready_goals.add(goal['id'])
        for capability in document['capabilities']:
            if capability['executor_ref'] not in bindings.values():
                bound_capabilities.append(capability)
                continue
            for goal in selected:
                if goal['id'] in ready_goals and bindings.get(goal['checker']) == capability['executor_ref']:
                    bound_capabilities.append({**capability,
                        'config':{**capability.get('config',{}),'goal_id':goal['id']},
                        'description':capability.get('description','')+' Independent acceptance: '+str(goal['acceptance'])})
        document['capabilities']=bound_capabilities
        # Current checker nodes get their exact registered goal binding from
        # the compiler. Never ask the model to invent IDs/config envelopes.
        document['goals'] = [g for g in document['goals'] if g['goal_id'] in {x['id'] for x in selected}]
        return TableSnapshot(document)

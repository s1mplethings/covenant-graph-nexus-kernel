"""Deterministic compact interface for the canonical composition Agent.

One selected capability becomes one normal tree edit; no planner or scheduler.
"""
import hashlib
import json
from dataclasses import replace
from .composer import AgentComposer, AgentDecision, AgentDecisionValidationError
from cgkn.providers import parse_json_object
from cgkn.orchestration.tree_edits import TreeEdit

ACTION_SCHEMA = {"type": "object", "additionalProperties": False,
    "required": ["summary", "operation", "capability", "config", "depends_on", "node_id"],
    "properties": {"summary": {"type": "string"}, "operation": {"enum": ["execute", "retry", "finish"]},
        "capability": {"type": "string"}, "config": {"type": "object"},
        "depends_on": {"type": "array", "items": {"type": "string"}}, "node_id": {"type": "string"}}}

class ActionComposer(AgentComposer):
    def set_runtime_context(self, supplier, models=()):
        """Mechanical state supplier; the Agent retains all composition decisions."""
        self.runtime_context = supplier
        self.allowed_models = tuple(models)

    def decide(self, context):
        payload = context.as_dict()
        schema = json.loads(json.dumps(ACTION_SCHEMA))
        if hasattr(self, 'runtime_context'):
            payload['durable_state'] = self.runtime_context()
            if 'goal_acceptance' in payload['durable_state']:
                payload['goal_acceptance']=payload['durable_state'].pop('goal_acceptance')
            try:
                artifact_hash=json.loads(payload['durable_state'].get('raw_state',{}).get('stdout','{}')).get('artifact_hash')
            except (ValueError,TypeError):artifact_hash=None
            if artifact_hash and artifact_hash != getattr(self,'_artifact_hash',None):
                self._blocked_action=None
                self._observation_repeats={}
                self._alternative_used=False
                self._stagnation_count=0
            self._artifact_hash=artifact_hash
            payload['model_selection'] = {'current': self.config.model, 'allowed': self.allowed_models,
                'instruction': 'switch_model: config={"model": allowed_alias}, capability/node_id empty, depends_on empty. Keeps tree, state, results and shared budget. Worker provider is separately selectable in config.'}
            schema = json.loads(json.dumps(ACTION_SCHEMA))
            schema['properties']['operation']['enum'].append('switch_model')
        if context.goal_acceptance:
            schema['properties']['operation']['enum'].extend(['plan','blocked'])
            payload['plan_contract']={'operation':'plan','config':{'phases':[{'id':'stable id','outcome':'required outcome','depends_on':[]}], 'goals':[{'id':'stable id','phase_id':'phase id','requirement_refs':['public requirement id'],'acceptance':'observable condition','subject_refs':['current input/artifact identity key'],'checker':'registered checker','task_refs':[]}]}, 'blocked_contract':'Only when every remaining critical branch has a concrete non-quota blocker: operation=blocked, config={reason,affected_goals,attempted_strategies,evidence_refs,recovery}, capability/node_id empty, depends_on empty. Do not use for ordinary errors or missing checks.', 'rules':'Generate project-specific milestones. Preserve MUST and existing goal identities/conditions. No task DONE implies verification. Use registered checks; finish requires valid goal evidence. Delegate candidate implementation and self tests to workspace.code@1.'}
        goals=payload.get('goal_acceptance') or {}
        if goals.get('goals'):
            # Mechanical progress observation, not a business diagnosis. Distinct
            # read commands cannot hide an unchanged artifact/acceptance frontier.
            frontier=json.dumps([getattr(self,'_artifact_hash',None),[(g['id'],g.get('verdict'),g.get('acceptance'),g.get('subject_refs')) for g in goals['goals']]],sort_keys=True)
            fingerprint=hashlib.sha256(frontier.encode()).hexdigest()
            if fingerprint != getattr(self,'_frontier_fingerprint',None):
                self._frontier_fingerprint=fingerprint;self._frontier_rounds=0;self._frontier_models=[]
            self._frontier_rounds=getattr(self,'_frontier_rounds',0)+1
            if self._frontier_rounds>=8:
                payload['progress_observation']={'unchanged_frontier_rounds':self._frontier_rounds,'switched_main_role_to':None,'reason':'No change in candidate identity or recorded goal acceptance frontier. Reads can inform understanding but are not verified goal progress. Use existing observations to choose a different strategy, a meaningful check or another branch. This is a diagnostic checkpoint, not a quota, model escalation authorization or completion verdict.'}
        if payload.get('durable_state',{}).get('public_feedback'):
            payload['feedback_scope_rule']='Public feedback is historical evidence for its referenced run/candidate only. Preserve it. It is not a fresh observation of later code and does not by itself prove either continued failure or a successful repair. Current claims require current-object checks.'
        if context.execution_results and hasattr(self, '_previous_action'):
            latest = set(context.run_summary.get('actual_executions', ()))
            failures = [v for k, v in context.execution_results.items() if k in latest and v['status'] != 'SUCCEEDED']
            if failures:
                signature = json.dumps([self._previous_action, [(v.get('error'), v.get('outputs', {}).get('stderr'), v.get('outputs', {}).get('stdout')) for v in failures]], sort_keys=True)
                self._stagnation_count = getattr(self, '_stagnation_count', 0) + 1 if signature == getattr(self, '_stagnation_signature', None) else 1
                self._stagnation_signature = signature
                if self._stagnation_count >= 3:
                    self._blocked_action = self._previous_action
                    payload['stagnation_feedback'] = 'Unchanged failure after alternative strategy opportunity. This exact branch action is blocked. Continue unrelated work or obtain new evidence; do not pay to repeat it.'
                elif self._stagnation_count == 2:
                    payload['stagnation_feedback'] = 'Two unchanged action/failure rounds. Change strategy: obtain independent evidence or select a different worker. Same goal, raw failure and durable state retained. A further unchanged branch will be blocked.'
            else:
                self._stagnation_count = 0
        if context.execution_results and hasattr(self,'_previous_action'):
            latest=set(context.run_summary.get('actual_executions',()))
            for key,result in context.execution_results.items():
                if key not in latest or result['status']!='SUCCEEDED':continue
                action=json.loads(json.dumps(self._previous_action))
                action.get('config',{}).pop('timeout_seconds',None)
                out=result.get('outputs',{})
                if out.get('stdout_hash'):
                    fingerprint=hashlib.sha256(json.dumps([getattr(self,'_artifact_hash',None),action,out['stdout_hash']],sort_keys=True).encode()).hexdigest()
                    seen=getattr(self,'_observation_repeats',{})
                    seen[fingerprint]=seen.get(fingerprint,0)+1
                    self._observation_repeats=seen
                    if seen[fingerprint]>=3:self._blocked_action=self._previous_action
                    if seen[fingerprint]>=2:
                        payload['repeated_observation']={'action':action,'count':seen[fingerprint],'raw_result':'/workspace/.cgkn-results/'+key+'.json','instruction':'Same action returned identical bytes again. Reuse the retained result; change observation conditions or continue with your own decision. Do not repeat unchanged reads.'}
        from cgkn.orchestration.leaf_contract import CONTRACT_SCHEMA
        payload['execution_leaf_contract_schema'] = CONTRACT_SCHEMA
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        from cgkn.protocol.adaptive_context import public_context_view
        from cgkn.protocol.exchange import complete_with_context
        public,resolver=public_context_view(payload)
        completion = complete_with_context(self.client,resolver=self._explicit_context_resolver or resolver,system='''You are the CGKN project Agent, responsible for the entire public goal. Select a registered capability and its config, dependencies, or finish. Framework binds executor and generates node IDs. execute appends a node; retry uses an existing node_id and replacement config (empty preserves it), invalidates its downstream closure. Only explicitly retry after checking side effects. Do not replay failed actions blindly. Successful nodes are reused. All execution uses the canonical DAG and isolated tools. workspace.code@1 delegates bounded implementation/test work to a separate worker; it can read files and then write its own contribution. Decide task decomposition yourself. Each execute config requires leaf_contract schema_version=1.0, leaf_goal, task_kind, target_scope (bounded relative artifact paths), expected_delta, acceptance (registered condition names), checker_ref, output_identity, effect_domains (one primary), executor_ref and dependencies. Research also needs source_refs/completion_criterion; tests need subject/expected_observation/pass_fail_rule. Reject broad cross-layer tasks by splitting into bounded leaves. NO_IMPLEMENTATION_PROGRESS and REPEATED_NO_PROGRESS_STRATEGY require a changed decision grounded in evidence. Candidate business implementation, self tests and project documentation must be written by delegated workspace.code@1 workers, not directly through planner shell/file writes. Use dependencies to supply needed prior outputs, not all history. Results include raw outputs and worker modified files. Tool errors are feedback, not a reason to abandon the entire goal. Maintain your own project notes in the workspace if useful. Finish only when all public responsibilities are completed and tested, or honestly document remaining gaps. No hidden reasoning; concise JSON only. For execute node_id is empty; for finish capability/node_id are empty, config={}, depends_on=[].''', user=json.dumps(public,ensure_ascii=False,sort_keys=True), schema_name='cgkn_capability_action', schema=schema, config=self.config)
        try:
            value = parse_json_object(completion.text)
            if set(value) != set(ACTION_SCHEMA['required']): raise ValueError('Invalid action envelope')
            op = value['operation']; cfg = value['config']; deps = value['depends_on']
            proposed_action = {k: value[k] for k in ('operation', 'capability', 'config')}
            if proposed_action == getattr(self, '_blocked_action', None):
                raise ValueError('STAGNATION_BRANCH_BLOCKED: obtain new evidence or continue unrelated work')
            self._previous_action = proposed_action
            if not isinstance(cfg, dict) or not isinstance(deps, list) or any(not isinstance(d, str) for d in deps): raise ValueError('Invalid config/dependencies')
            identifier = f"decision-{context.decision_number:04d}"
            provenance = {'actor': 'agent', 'request_id': completion.request_id}
            edits = []
            if op == 'execute':
                if value['node_id']: raise ValueError('execute node_id must be empty; framework generates identity')
                cap = value['capability']; entry = context.capability_catalog.get(cap, {})
                ref = entry.get('executor_ref')
                if not isinstance(ref, str) or not ref: raise ValueError('Capability has no unique registered executor')
                if 'executor_ref' in cfg and cfg['executor_ref'] != ref: raise ValueError('Executor conflicts with catalog')
                cfg = {**cfg, 'executor_ref': ref, '_agent_summary': value['summary']}
                edits.append(TreeEdit(identifier, 'add_node', f'n{context.decision_number:04d}', {'capability_ref': cap, 'parent_id': '', 'depends_on': deps, 'config': cfg}, provenance))
            elif op == 'retry':
                node = context.tree.by_id.get(value['node_id'])
                if node is None: raise ValueError('Unknown retry node')
                if deps or value['capability'] not in {'', node.capability_ref}: raise ValueError('Retry cannot change capability/dependencies')
                if cfg:
                    ref = context.capability_catalog[node.capability_ref]['executor_ref']
                    if cfg.get('executor_ref', ref) != ref: raise ValueError('Executor conflicts with catalog')
                    edits.append(TreeEdit(identifier+'-config','update_config',node.id,{'config': {**cfg,'executor_ref':ref}},provenance))
                edits.append(TreeEdit(identifier,'retry_node',node.id,{},provenance))
            elif op == 'switch_model':
                if not hasattr(self, 'allowed_models') or set(cfg) != {'model'} or cfg['model'] not in self.allowed_models or deps or value['capability'] or value['node_id']:
                    raise ValueError('Invalid model switch; state unchanged')
                self.config = replace(self.config, model=cfg['model'])
            elif op == 'blocked':
                if not context.goal_acceptance or not all(cfg.get(k) for k in ('reason','affected_goals','attempted_strategies','evidence_refs','recovery')):raise ValueError('blocking requires concrete evidence and recovery')
            elif op == 'plan':
                if not context.goal_acceptance or deps or value['capability'] or value['node_id']:raise ValueError('invalid plan action')
            elif op == 'finish':
                if cfg or deps or value['capability'] or value['node_id']: raise ValueError('finish must not contain an action')
            else: raise ValueError('Unknown operation')
            return AgentDecision(identifier, value['summary'], '', tuple(edits), op not in {'finish','switch_model','plan','blocked'}, op=='finish', op=='blocked', json.dumps(cfg) if op=='blocked' else '', {'model':completion.model,'request_id':completion.request_id,'usage':dict(completion.usage)}, hashlib.sha256(raw.encode()).hexdigest(), len(raw), cfg if op=='plan' else None)
        except (ValueError, TypeError, KeyError) as exc:
            raise AgentDecisionValidationError(exc, completion) from exc

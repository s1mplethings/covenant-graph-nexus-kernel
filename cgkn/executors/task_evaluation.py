"""Advisory evaluation Component; it cannot change goals or business outputs."""
import json
import time
from jsonschema import Draft202012Validator

from cgkn.execution import BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode
from cgkn.executors.protocol import ExecutorDescriptor
from cgkn.providers import parse_json_object
from cgkn.state.task_feedback import TaskFeedback


class TaskEvaluationExecutor:
    descriptor = ExecutorDescriptor('task.evaluate@1', 'bounded_llm', ('task.evaluate@1',))

    def __init__(self, store, client, config, *, allowed_models=(), acceptance=None):
        self.store, self.client, self.config = store, client, config
        self.allowed_models = tuple(allowed_models)
        self.acceptance = acceptance

    def execute(self, request):
        target = str(request.input_values.get('feedback_identity', ''))
        self.store._validate_segment(target)
        path = self.store.run_dir(request.project_id, request.run_id) / 'evaluation_locks' / (target + '.lock')
        with self.store.exclusive_file(path):
            return self._execute(request)

    def _execute(self, request):
        try:
            target = request.input_values['feedback_identity']
            feedback = TaskFeedback(self.store, request.project_id, request.run_id)
            facts = feedback.attempt(target)
            if facts['evaluation_state'] == 'NOT_REQUIRED_META':
                raise ValueError('recursive evaluation forbidden')
            revision = request.input_values.get('evaluation_revision', 1)
            if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
                raise ValueError('explicit positive evaluation revision required')
            existing = feedback.root / 'evaluations' / target / f'{revision:06d}.json'
            if existing.exists():
                row = json.loads(existing.read_text(encoding='utf-8'))
                publication = feedback.publish_candidate(target, revision)
                if request.input_values.get('evaluation_contract')=='2':
                    from cgkn.state.capability_ledger import CapabilityLedger
                    CapabilityLedger(self.store,request.project_id).capture(feedback,target,self.acceptance)
                return BlockExecutionResult(project_id=request.project_id, run_id=request.run_id,
                    node_id=request.node_id, attempt_id=request.attempt_id, executor_ref=request.executor_ref,
                    status=BlockStatus.SUCCEEDED,
                    outputs={'evaluation': row, 'candidate_publication': publication, 'reused': True})
            from cgkn.state.capability_ledger import deterministic_facts, CapabilityLedger
            receipt = deterministic_facts(feedback,target,self.acceptance)
            fields = ['observations', 'evidence_refs', 'hypothesis', 'uncertainty',
                      'required_capabilities', 'candidate_lesson', 'recommendation']
            schema = {'type': 'object', 'additionalProperties': False, 'required': fields,
                'properties': {k: ({'type': 'array', 'items': {'type': 'string'}}
                    if k in ('evidence_refs', 'required_capabilities') else {'type': 'string'}) for k in fields}}
            v2=request.input_values.get('evaluation_contract')=='2'
            if v2:
                additional={'evaluation_id':{'type':'string','const':target+':'+str(revision)},
                    'source_attempt_id':{'type':'string','const':facts['attempt_id']},
                    'capability_tags':{'type':'array','items':{'type':'string'}},
                    'outcome_interpretation':{'type':'string'},
                    'failure_domain':{'type':'string','const':receipt['failure_domain']},
                    'failure_reason_summary':{'type':'string'},'confidence':{'type':'number','minimum':0,'maximum':1},
                    'informative_for_routing':({'type':'boolean','const':False} if receipt['failure_domain'] in {'UNKNOWN','HARNESS','TRANSPORT'} else {'type':'boolean'}),'why_this_recommendation':{'type':'string'},
                    'unresolved_questions':{'type':'array','items':{'type':'string'}}}
                fields=fields+list(additional);schema['required']=fields;schema['properties'].update(additional)
            public_facts={k:facts[k] for k in ('identity','node_id','attempt_id','goal','receipt_ref','receipt_sha256','status','capability_ref','evaluation_state')}
            prompt = dict(facts=public_facts, receipt=receipt, allowed_models=self.allowed_models,
                          instruction='Cite only receipt_ref. Causes are hypotheses. No business acceptance authority. Recommendation is empty or one allowed model configuration ID.')
            intent = feedback.root / 'evaluation_intents' / target / f'{revision:06d}.json'
            response_path = intent.with_name(f'{revision:06d}.response.json')
            recovered = False
            if intent.exists():
                saved_intent = json.loads(intent.read_text(encoding='utf-8'))
                if saved_intent.get('target') != target or saved_intent.get('revision') != revision or saved_intent.get('prompt') != json.loads(json.dumps(prompt)):
                    raise RuntimeError('EVALUATION_RECOVERY_CONTEXT_MISMATCH')
                if not response_path.exists():
                    raise RuntimeError('EVALUATION_OUTCOME_UNKNOWN: no retained complete response; no automatic resubmission')
                response = json.loads(response_path.read_text(encoding='utf-8'))
                recovered = True
            else:
                from cgkn.execution.node_effects import guard_effect
                guard_effect(request,'PROVIDER_CALL',resource_usage={'calls':1})
                self.store.atomic_json(intent, {'state': 'DISPATCHED', 'target': target, 'revision': revision, 'prompt': prompt})
                from cgkn.protocol.adaptive_context import public_role_resolver
                from cgkn.protocol.exchange import complete_with_context
                completion = complete_with_context(self.client,resolver=public_role_resolver(prompt),system='Evaluate this bounded task attempt using only supplied public evidence. Return advisory JSON; never claim independent acceptance.',
                    user=json.dumps(prompt, ensure_ascii=False), schema_name='cgkn_task_evaluation', schema=schema, config=self.config)
                response = {'text': completion.text, 'model': completion.model, 'request_id': completion.request_id, 'usage': dict(completion.usage)}
                self.store.immutable_json(response_path, response)
            if not isinstance(response.get('model'), str) or not response['model'] or not isinstance(response.get('usage'), dict):
                raise ValueError('invalid retained evaluation response')
            value = parse_json_object(response['text'])
            Draft202012Validator(schema).validate(value)
            if set(value) != set(fields) or value['recommendation'] not in ('', *self.allowed_models):
                raise ValueError('invalid evaluation fields or model recommendation')
            value['model'] = response['model']
            row = feedback.revise(target, revision, value, supersedes=revision-1 if revision > 1 else None)
            publication = feedback.publish_candidate(target, revision)
            if v2:
                CapabilityLedger(self.store,request.project_id).capture(feedback,target,self.acceptance)
            return BlockExecutionResult(project_id=request.project_id, run_id=request.run_id,
                node_id=request.node_id, attempt_id=request.attempt_id, executor_ref=request.executor_ref,
                status=BlockStatus.SUCCEEDED, outputs={'evaluation': row, 'candidate_publication': publication, 'recovered_response': recovered},
                usage=({'model': response['model'], 'request_id': response.get('request_id'), 'cached_response_recovery': True} if recovered else
                       dict(response['usage']) | {'model': response['model'], 'request_id': response.get('request_id')}))
        except Exception as exc:
            return BlockExecutionResult(project_id=request.project_id, run_id=request.run_id,
                node_id=request.node_id, attempt_id=request.attempt_id, executor_ref=request.executor_ref,
                status=BlockStatus.FAILED, error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR,
                    type(exc).__name__ + ': ' + str(exc)))

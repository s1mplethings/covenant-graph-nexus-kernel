"""Application-visible request/response receipts; never credentials or hidden thought."""
import dataclasses
import time
import uuid
import json

from .gateway_client import GatewayCompletionClient,GatewayCompletionError


class RecordedCompletionClient:
    def __init__(self, client, store, project_id, run_id):
        self.client, self.store = client, store
        self.root = store.run_dir(project_id, run_id) / 'provider_calls'

    def complete(self, **kwargs):
        public = {k:v for k,v in kwargs.items() if k != 'config'}
        config=dataclasses.asdict(kwargs['config'])
        # Reopening a controller must not evade the budget latch by minting a
        # new cgkn_attempt_id for the same unresolved logical request.
        for path in self.root.glob('*/request.json'):
            prior=json.loads(path.read_text(encoding='utf-8'))
            if prior.get('config',{}).get('role')!=config['role'] or prior.get('request')!=public:continue
            error_path=path.with_name('error.json');response_path=path.with_name('response.json')
            failure=json.loads(error_path.read_text(encoding='utf-8')) if error_path.exists() else None
            if (failure and failure.get('outcome_unknown')) or (failure is None and not response_path.exists()):
                raise GatewayCompletionError('prior_submission_unknown',
                    'Original recorded request '+str(prior.get('identity'))+' requires read-only reconciliation; no new attempt created',outcome_unknown=True)
        identity = uuid.uuid4().hex
        directory = self.root / identity
        self.store.atomic_json(directory / 'request.json', {
            'identity': identity, 'started_at': time.time(), 'config': dataclasses.asdict(kwargs['config']),
            'request': public})
        try:
            if isinstance(self.client, GatewayCompletionClient):
                kwargs = {**kwargs, 'call_identity': identity}
            result = self.client.complete(**kwargs)
            self.store.atomic_json(directory / 'response.json', {
                'identity': identity, 'ended_at': time.time(), 'text': result.text, 'model': result.model,
                'request_id': result.request_id, 'usage': dict(result.usage),
                'attempts': result.attempts, 'routing': dict(result.routing),
                'raw_finish_reason':result.raw_finish_reason})
            return result
        except Exception as exc:
            self.store.atomic_json(directory / 'error.json', {
                'identity': identity, 'ended_at': time.time(), 'error_type': type(exc).__name__,
                'category': getattr(exc, 'category', None),
                'completed_response': getattr(exc, 'completed_response', None),
                'outcome_unknown': getattr(exc, 'outcome_unknown', None), 'error': str(exc)[:1500]})
            raise

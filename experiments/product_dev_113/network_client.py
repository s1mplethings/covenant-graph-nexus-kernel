"""Network-route injection on the existing API Lab / canonical budget entry.

Two attempts per logical pure-generation request, no semantic retries or tool replay.
"""
import dataclasses
import contextvars
import json
import threading
import time
import uuid
import random
from pathlib import Path

from cgkn.providers.network_transport import NetworkClients
from .budget_policy import BoundedClient
from .live_provider import LiveClient

_attempt = contextvars.ContextVar('cgnk_network_attempt',default=None)
_opener = contextvars.ContextVar('cgnk_network_opener', default=None)


class NetworkClient(BoundedClient):
    def __init__(self, *args, transport_config=None, **kwargs):
        super().__init__(*args, **kwargs)
        transport_config=transport_config or Path(__file__).resolve().parents[2]/'config/network_routes.json'
        self.transport_config = Path(transport_config)
        self.network = NetworkClients.load(transport_config, log=self._trace)
        self.slots = threading.BoundedSemaphore(2)
        self._late_settled=set()

    @property
    def urlopen(self):
        value = _opener.get()
        if value is None:
            raise RuntimeError('NETWORK_REQUEST_CONTEXT_REQUIRED')
        return value

    def _trace(self, row):
        with (self.root/'network-trace.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps(row)+'\n')

    def complete(self, *, cancel=None, **kwargs):
        config=kwargs['config']
        allowed=self.authorization.get('agent_models',[]) if config.role=='agent' else []
        aliases=[m for m in [config.model]+[m for m in allowed if m!=config.model] if m not in self.network.disabled_providers]
        errors=[]
        for alias in aliases:
            try:
                result=self._complete_transport(cancel=cancel,**{**kwargs,'config':dataclasses.replace(config,model=alias)})
                self._trace({'phase':'role_result','role':config.role,'requested_alias':config.model,'effective_alias':alias,'actual_model':result.model,'request_id':result.request_id,'prior_failures':errors})
                return result
            except RuntimeError as exc:
                if getattr(exc, 'network_outcome', {}).get('submitted', True): raise
                # Schema/semantic/context errors belong to the Agent, not fallback.
                if not str(exc).startswith(('PROVIDER_TRANSPORT_FAILED:', 'CANCELLED_OR_DEADLINE', 'LATE_RESULT_NOT_COMMITTED')):raise
                errors.append({'alias':alias,'reason':str(exc)})
                self._trace({'phase':'role_route_unavailable','role':config.role,'alias':alias,'reason':str(exc),'tool_replay':False})
        raise RuntimeError('NO_SUITABLE_ROLE_ROUTE: '+json.dumps(errors))

    def _complete_transport(self, *, cancel=None, **kwargs):
        alias = kwargs['config'].model
        route_id = self.network.bindings[alias]
        route = self.network.routes[route_id]
        logical_id = uuid.uuid4().hex
        deadline = time.monotonic()+min(route.deadline,kwargs["config"].timeout_seconds)
        if not getattr(self,"accounting_only",False):deadline=min(deadline,self.started+3600)
        if not self.slots.acquire(timeout=max(0,deadline-time.monotonic())):
            raise RuntimeError('LOCAL_POOL_DEADLINE')
        try:
            for attempt in range(2):
                if time.monotonic()>=deadline or (cancel is not None and cancel.is_set()):
                    raise RuntimeError('CANCELLED_OR_DEADLINE')
                outcome = {}
                context_token=_attempt.set((outcome,logical_id,attempt))
                token = _opener.set(self.network.opener(alias, logical_id=logical_id,
                    attempt_id=f'{logical_id}-{attempt}', deadline=deadline,
                    cancel=cancel, route_id=route_id, outcome=outcome))
                try:
                    result = LiveClient.complete(self, **kwargs)
                    if time.monotonic()>=deadline or (cancel is not None and cancel.is_set()):
                        raise RuntimeError('LATE_RESULT_NOT_COMMITTED')
                    return dataclasses.replace(result,attempts=attempt+1)
                except RuntimeError as exc:
                    exc.network_outcome = {k:v for k,v in outcome.items() if not callable(v)}
                    self._trace({'logical_id':logical_id,'attempt':attempt,'route_id':route_id,
                                 'outcome':{k:v for k,v in outcome.items() if not callable(v)},'fee_policy':'unknown retained'})
                    if attempt or not outcome.get('retryable') or outcome.get('submitted') or outcome.get('partial') or time.monotonic()>=deadline:
                        raise
                    delay = min(random.uniform(.15,.35), max(0,deadline-time.monotonic()))
                    if cancel is not None:
                        if cancel.wait(delay): raise RuntimeError('CANCELLED_OR_DEADLINE')
                    else: time.sleep(delay)
                    # Exactly one declared alternative/new attempt. Never change Provider.
                    effective = outcome.get('route_id',route_id)
                    route_id = self.network.routes[effective].fallback or effective
                finally:
                    _opener.reset(token)
                    _attempt.reset(context_token)
            raise RuntimeError('ATTEMPTS_EXHAUSTED')
        finally:
            self.slots.release()

    def bind_attempt(self,reservation,input_upper,output_upper):
        from scripts import provider_api_budget as budget
        outcome,logical_id,attempt=_attempt.get()
        self._trace({'logical_id':logical_id,'attempt':attempt,'call_id':reservation['call_id'],'phase':'reserved'})
        def late_usage(usage):
            if not isinstance(usage,dict):return
            inp=usage.get('prompt_tokens');out=usage.get('completion_tokens')
            if not isinstance(inp,int) or not isinstance(out,int) or min(inp,out)<0:return
            if isinstance(usage.get('total_tokens'),int):out=max(out,usage['total_tokens']-inp)
            with self._admission_lock:
                if reservation['call_id'] in self._late_settled:return
                budget.finalize_call(reservation,usage={'prompt_tokens':inp,'completion_tokens':out},http_status=200,status='FAILED')
                self._late_settled.add(reservation['call_id'])
                self.tokens+=inp+out-input_upper-output_upper
                self.run_cost+=(inp*20+out*60-input_upper*20-output_upper*60)/1e6
                self._trace({'logical_id':logical_id,'attempt':attempt,'call_id':reservation['call_id'],'phase':'late_usage_settled_no_result_commit'})
        outcome['late_usage_callback']=late_usage

    def close(self):
        self.network.close()

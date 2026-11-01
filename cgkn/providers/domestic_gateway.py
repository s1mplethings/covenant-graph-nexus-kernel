"""Existing Gateway server with bound upstream SSE and downstream progress.

The API Lab service/result boundary is retained; the buffered adapter is replaced.
"""
from __future__ import annotations
import contextvars
import dataclasses
from pathlib import Path
import sys
import uuid
import time
import hashlib
import json
import threading
from contextlib import contextmanager
from urllib.error import HTTPError
from urllib.request import Request

from .network_transport import NetworkClients,REQUEST_CONTEXT


class DomesticGateway:
    def __init__(self,lab_root,transport_config,*,log=None,secret_manager=None,network=None,request_transform=None,provider_parallelism=1,response_dir=None):
        sys.path.insert(0,str(Path(lab_root)/'src'))
        from cgkn_provider_lab.storage import ProviderConfigStore
        from cgkn_provider_lab.service import ProviderComparisonService
        from cgkn_provider_lab.gateway import GatewayApplication,GatewayServer,GatewayError
        if provider_parallelism not in (1,2): raise ValueError("provider parallelism must be 1 or 2")
        self.network=network or NetworkClients.load(transport_config,log=log,provider_parallelism=provider_parallelism)
        self.providers=[p for p in ProviderConfigStore().load() if p.provider_id in self.network.bindings and p.provider_id not in self.network.disabled_providers]
        self.provider_slots={p.provider_id:threading.BoundedSemaphore(provider_parallelism) for p in self.providers}
        self.available_models={p.provider_id:{p.model} for p in self.providers}
        returned_identity=contextvars.ContextVar("cgkn_returned_identity",default=None)
        requested_model=contextvars.ContextVar("cgkn_concrete_model",default=None)
        last_outcome=contextvars.ContextVar('domestic_gateway_outcome',default=None)
        owner=self
        self.stream_session_id=uuid.uuid4().hex
        class RoutedAdapter:
            def invoke(self,provider,credential,prompt,options):
                from .streaming_bound_adapter import BoundProviderRoute,invoke_stream_via_bound_opener
                from .streaming_sse import StreamLimits,StreamError,MeaningfulProgressWatchdog
                from cgkn_provider_lab.models import ProviderResult
                if requested_model.get():provider=dataclasses.replace(provider,model=requested_model.get())
                identity=uuid.uuid4().hex;outcome={};last_outcome.set(outcome)
                route=owner.network.routes[owner.network.bindings[provider.provider_id]]
                watchdog=MeaningfulProgressWatchdog(initial_timeout=route.first_response, idle_timeout=route.progress)
                system=options.system_prompt;response_format=dict(options.response_format)
                if provider.provider_id=='deepseek' and response_format.get('type')=='json_schema':
                    schema=response_format['json_schema']['schema']
                    system+='\nReturn one JSON object matching this JSON Schema exactly: '+json.dumps(schema,ensure_ascii=False)
                    response_format={'type':'json_object'}
                payload=dict(model=provider.model,messages=[dict(role='system',content=system),dict(role='user',content=prompt)],
                    temperature=options.temperature,max_tokens=options.max_tokens,reasoning_effort="none")
                if provider.provider_id=='qwen' and provider.model.startswith('qwen3.8-max'):
                    payload['max_completion_tokens']=payload.pop('max_tokens')
                if provider.provider_id=='qwen' and provider.model=='qwen3.8-flash':
                    # Official non-thinking structured-text contract. No reasoning
                    # transcript is requested or forwarded to subsequent calls.
                    payload.pop('reasoning_effort',None)
                    payload['enable_thinking']=False
                    payload['max_completion_tokens']=payload.pop('max_tokens')
                if response_format:payload['response_format']=response_format
                if request_transform:payload=json.loads(request_transform(provider,json.dumps(payload).encode()))
                context=dict(REQUEST_CONTEXT.get());progress=context.get('stream_progress')

                def on_progress(row):
                    advanced=watchdog.progress(row['meaningful_events'])
                    row={**row,'connection_alive':True,'model_making_progress':advanced,'requested_model':provider.model}
                    owner.network.emit({**row,'phase':'model_progress','provider':provider.provider_id,'logical_id':identity})
                    if progress:progress(row)
                def consume(req,parser):
                    ceiling=context.get('input_token_ceiling')
                    if ceiling is not None:
                        # Final serialized text-only request, including schema and
                        # stream options. Additional allowance covers chat framing.
                        upper=len(req.data)+1024
                        try:valid=0<int(ceiling)<=1_000_000 and upper<=int(ceiling)
                        except (ValueError,TypeError):valid=False
                        if not valid:
                            outcome.update(kind='INPUT_TOKEN_CEILING_EXCEEDED',submitted=False,retryable=False)
                            raise StreamError('input_token_ceiling_exceeded',outcome_unknown=False)
                        owner.network.emit(dict(phase='input_budget_admitted',input_upper_tokens=upper,input_token_ceiling=int(ceiling)))
                    outcome['network_entered']=True
                    return owner.network.opener(provider.provider_id,logical_id=identity,attempt_id=identity+'-1',
                        watchdog=watchdog,cancel=context.get('request_cancel'),outcome=outcome,consume=parser)(req)
                try:
                    result=invoke_stream_via_bound_opener(route=BoundProviderRoute(provider.provider_id,provider.base_url,provider.model,
                        provider.auth_header,provider.auth_prefix),token=credential,upstream_chat_payload=payload,bound_consume=consume,
                        limits=StreamLimits(max_text_bytes=2_097_152),on_progress=on_progress)
                    if not result.request_id:raise StreamError('stream_missing_request_identity')
                    if any(not isinstance(result.usage.get(k),int) or isinstance(result.usage.get(k),bool) for k in ('prompt_tokens','completion_tokens')):
                        raise StreamError('stream_usage_unknown')
                    observed=dict(requested_model=provider.model,actual_model=result.model,upstream_request_id=result.request_id,
                        usage=dict(result.usage),finish_reason=result.finish_reason)
                    owner.network.emit(dict(phase='provider_stream_completed',provider=provider.provider_id,logical_id=identity,
                        capability_mode='structured_text' if response_format else 'text',
                        upstream_request_id_sha256=hashlib.sha256(result.request_id.encode()).hexdigest(),
                        text_sha256=hashlib.sha256(result.text.encode()).hexdigest(),requested_model=provider.model,
                        actual_model=result.model,usage=dict(result.usage),finish_reason=result.finish_reason))
                    returned_identity.set(observed)
                    return ProviderResult(provider_id=provider.provider_id,display_name=provider.display_name,model=result.model,
                        status='ok',text=result.text,reasoning='',request_id=result.request_id,
                        prompt_tokens=result.usage.get('prompt_tokens'),completion_tokens=result.usage.get('completion_tokens'),
                        total_tokens=result.usage.get('total_tokens'),metadata=dict(finish_reason=result.finish_reason,
                        response_headers_received=True,stream_completed=True))
                except Exception as exc:
                    import traceback
                    if not outcome.get('kind'):outcome.update(kind=getattr(exc,'code','stream_invalid_response'),submitted=bool(outcome.get('network_entered')),retryable=False)
                    owner.network.emit(dict(phase='stream_failed',provider=provider.provider_id,error_type=outcome['kind'],submitted=outcome.get('submitted'),
                        exception_type=type(exc).__name__,exception_frames=[dict(file=Path(f.filename).name,line=f.lineno,function=f.name) for f in traceback.extract_tb(exc.__traceback__)[-5:]]))
                    raise
        class BoundApplication(GatewayApplication):
            def invoke(self,payload,mode):
                if payload.get('reasoning'):
                    raise GatewayError(400,'unsupported_reasoning_contract','Reasoning parameter mapping has not been validated for this text adapter')
                if payload.get('tools') or payload.get('tool_choice'):
                    raise GatewayError(400,'unsupported_tool_contract','This text-only controller has no tool execution contract')
                provider=payload.get('model')
                if provider not in owner.provider_slots:return super().invoke(payload,mode)
                concrete=payload.get("cgkn_model_id")
                if concrete is not None and concrete not in owner.available_models.get(provider,set()):
                    raise GatewayError(400,"concrete_model_not_admitted","Model was not present in the authenticated model inventory")
                request_hash=hashlib.sha256(json.dumps(dict(payload),ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
                attempt=payload.get('cgkn_attempt_id')
                context=dict(client_request_identity='sha256:'+request_hash,
                    client_call_key=attempt if isinstance(attempt,str) and len(attempt)<=128 and all(c.isalnum() or c in '-_' for c in attempt) else None)
                token=requested_model.set(concrete)
                inbound=REQUEST_CONTEXT.get()
                if inbound.get('inbound_http'):inbound.update(context)
                context_token=REQUEST_CONTEXT.set({**inbound,**context})
                queue_timeout=owner.network.routes[owner.network.bindings[provider]].queue
                owner.network.emit(dict(phase='gateway_request_start',provider=provider,provider_queue_timeout=queue_timeout,generation_total_limit=None))
                try:
                    progress = REQUEST_CONTEXT.get().get('stream_progress')
                    if progress:progress({'phase':'queued'})
                    with owner.provider_slot(provider,timeout=queue_timeout):
                        owner.network.emit(dict(phase='provider_slot_acquired',provider=provider))
                        if progress:progress({'phase':'connecting'})
                        return self._invoke_bound({k:v for k,v in payload.items() if k not in {"cgkn_model_id","cgkn_attempt_id","stream"}},mode)
                finally:
                    owner.network.emit(dict(phase='gateway_request_end',provider=provider))
                    REQUEST_CONTEXT.reset(context_token);requested_model.reset(token)

            def _invoke_bound(self,payload,mode):
                last_outcome.set(None)
                returned_identity.set(None)
                try:
                    status,body=super().invoke(payload,mode)
                    observed=returned_identity.get() or {}
                    body["model"]=observed.get("actual_model") or "UNKNOWN"
                    from .model_binding import confirm_model
                    body["cgkn_model_identity"]=confirm_model({"provider_id":payload.get("model"),"requested_model":observed.get("requested_model"),"bound_model":observed.get("requested_model")},body["model"])
                    body['cgkn_stream']={'completed':True,'protocol':'chat_sse','usage_status':'KNOWN'}
                    if len(json.dumps(body,ensure_ascii=False).encode())>2_097_152:
                        raise GatewayError(502,'response_too_large','Completed response exceeds admission bound')
                    from jsonschema import Draft202012Validator
                    fmt=payload.get('response_format') or (payload.get('text') or {}).get('format') or {}
                    contract=fmt.get('json_schema',fmt)
                    if 'schema' in contract:
                        text=body.get('output_text') if mode!='chat' else body['choices'][0]['message']['content']
                        try:Draft202012Validator(contract['schema']).validate(json.loads(text))
                        except Exception:
                            failure=GatewayError(422,'schema_validation_failed','Completed model text failed the requested JSON contract')
                            failure.completed_response=body
                            raise failure from None
                    if response_dir:
                        # Private evidence before returning to a possibly disconnected client.
                        # This does not settle a ledger or accept an Agent decision.
                        from .streaming_sse import save_immutable_json
                        key=REQUEST_CONTEXT.get()['client_request_identity'].removeprefix('sha256:')
                        save_immutable_json(Path(response_dir)/key[:2]/(key+'.json'),dict(
                            kind='CGKNGatewayRecoveryResponse',request_identity=key,call_mode='CACHE_REPLAY',
                            recorded_at=time.time(),response=body))
                        owner.network.emit(dict(phase='gateway_response_persisted',provider=payload.get('model')))
                    owner.network.emit(dict(phase='gateway_response_ready',gateway_http_status=status,
                        upstream_request_id=observed.get('upstream_request_id'),usage=observed.get('usage')))
                    return status,body
                except GatewayError as exc:
                    outcome=last_outcome.get() or {}
                    kind=outcome.get('kind','')
                    owner.network.emit(dict(phase='application_error',application_http_status=exc.status,
                        error_type=exc.code,outcome={k:v for k,v in outcome.items() if isinstance(v,(str,bool,int,float))}))
                    if outcome.get('submitted') is False and (outcome.get('retryable') or kind=='NetworkUnavailable'):
                        owner.network.emit(dict(phase='gateway_error',gateway_http_status=503,error_type='network_unavailable_before_send'))
                        raise GatewayError(503,'network_unavailable_before_send','Provider network unavailable before submission') from None
                    if outcome.get('submitted') is False and kind:
                        raise GatewayError(400,'provider_request_rejected_before_send','Provider request rejected before transport') from None
                    if outcome.get('submitted') and kind and not kind.startswith('HTTP_'):
                        owner.network.emit(dict(phase='gateway_error',gateway_http_status=502,error_type='provider_outcome_unknown'))
                        raise GatewayError(502,'provider_outcome_unknown','Provider submission outcome unknown; do not retry') from None
                    owner.network.emit(dict(phase='gateway_error',gateway_http_status=exc.status,error_type=exc.code))
                    raise
        service=ProviderComparisonService(secret_manager=secret_manager,adapters={p.adapter:RoutedAdapter() for p in self.providers})
        self.application=BoundApplication(self.providers,service=service,secrets=service.secret_manager)
        self.server=GatewayServer(self.application)
        # Direct construction in workers/tests uses the same formal streaming POST.
        from .route_diagnostics import install
        install(self,read_only=False)

    def start(self):return self.server.start()
    def close(self):self.network.close();self.server.stop()

    @contextmanager
    def provider_slot(self,provider,timeout=1):
        from cgkn_provider_lab.gateway import GatewayError
        cancel=REQUEST_CONTEXT.get().get('request_cancel')
        queue_until=time.monotonic()+timeout
        def check_queue():
            reason='GATEWAY_SHUTDOWN' if self.network.shutdown_event.is_set() else 'USER_CANCELLED' if cancel is not None and cancel.is_set() else None
            if reason:
                self.network.emit(dict(phase='provider_queue_cancelled',provider=provider,reason=reason,submitted=False))
                raise GatewayError(400,'provider_request_rejected_before_send',reason)
        while True:
            check_queue()
            remaining=queue_until-time.monotonic()
            if remaining<=0:
                raise GatewayError(503,'provider_queue_deadline','Provider concurrency slot unavailable')
            if self.provider_slots[provider].acquire(timeout=min(.025,remaining)):
                try:check_queue()
                except BaseException:
                    self.provider_slots[provider].release()
                    raise
                break
        try:yield
        finally:self.provider_slots[provider].release()

    def probe(self,provider):
        """Same pool/opener as the generation adapter; no credentials or generation."""
        entry=next(p for p in self.providers if p.provider_id==provider)
        outcome={};identity=uuid.uuid4().hex
        try:
            response=self.network.opener(provider,logical_id=identity,attempt_id=identity+'-probe',outcome=outcome)(Request(entry.base_url.rstrip('/')+'/models'))
            status=response.status;response.close()
        except HTTPError as exc:status=exc.code;exc.close()
        return dict(provider=provider,http_status=status,authentication='NOT_TESTED',model_calls=0)
